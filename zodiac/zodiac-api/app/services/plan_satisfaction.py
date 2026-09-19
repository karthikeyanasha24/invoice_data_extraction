"""Generic check: does generated SQL satisfy the structured analytical plan?
Used to reject shortcuts that answer the wrong question (e.g. customer master
instead of revenue ranking, or a grand total instead of month × count).
CRITICAL INVARIANT:
  SQL SUCCESS ≠ Investigation SUCCESS
  Wrong results must FAIL → REPAIR, never SUCCESS.
"""
from __future__ import annotations
import re
from collections import Counter
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from .analytical_operations import extract_analytical_operations, merge_semantic_requirements, table_is_master
from .semantic_requirements import (
    parse_result_date,
    required_semantics,
    result_has_dimension,
)
_MEASURE_TOKENS = ("netwr", "dmbtr", "wrbtr", "rmwwr", "fkimg", "menge", "kwert", "amount", "revenue", "sales")
_MASTER_TABLES = frozenset({
    "KNA1", "KNVV", "KNVP", "KNBK", "LFA1", "LFB1", "LFM1", "MARA", "MAKT", "MARC", "MVKE", "T016T",
})
_PERIOD_ALIASES = ("period_a", "period_b", "sales_a", "sales_b", "base", "compare", "prior", "current", "change", "growth", "diff", "delta")
def _tables_in_sql(sql: str) -> List[str]:
    found: List[str] = []
    seen = set()
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+"?([A-Za-z0-9_]+)"?', sql or "", re.I):
        name = m.group(1).upper()
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found
def sql_has_group_by(sql: str) -> bool:
    return bool(re.search(r"\bGROUP\s+BY\b", sql or "", re.I))
def sql_has_aggregation(sql: str) -> bool:
    return bool(re.search(r"\b(SUM|COUNT|AVG|MAX|MIN)\s*\(", sql or "", re.I))
def sql_has_month_bucket(sql: str) -> bool:
    s = sql or ""
    if re.search(r"SUBSTRING\s*\([\s\S]*?,\s*1\s*,\s*6\s*\)", s, re.I):
        return True
    if re.search(r"\b(TO_CHAR|DATE_TRUNC)\s*\([\s\S]*?(month|YYYY-MM|YYYYMM)", s, re.I):
        return True
    if re.search(r'\bAS\s+"?month(?:_?[a-z0-9]+)?"?\b', s, re.I):
        return True
    return False
def sql_has_year_bucket(sql: str) -> bool:
    s = sql or ""
    if re.search(r"SUBSTRING\s*\([\s\S]*?,\s*1\s*,\s*4\s*\)", s, re.I):
        return True
    if re.search(r"EXTRACT\s*\(\s*YEAR", s, re.I):
        return True
    if re.search(r'\bAS\s+"?year(?:_?[a-z0-9]+)?"?\b', s, re.I):
        return True
    return False
def sql_has_period_comparison(sql: str, years: Optional[List[str]] = None) -> bool:
    """True when SQL computes two period measures and a difference/ratio."""
    s = sql or ""
    su = s.upper()
    case_years = re.findall(r"CASE\s+WHEN[\s\S]{0,120}?(\d{4})", s, re.I)
    filter_years = re.findall(r"(?:SUBSTRING|YEAR)[\s\S]{0,80}?(?:19|20)\d{2}", s, re.I)
    has_case_pair = len(set(case_years)) >= 2 or su.count("CASE WHEN") >= 2
    has_change = bool(
        re.search(r"\b(period_b|sales_b|comparison)\b[\s\S]{0,40}-\s*\b(period_a|sales_a|base)\b", s, re.I)
        or re.search(r"\bAS\s+\"?(change|growth|diff|delta|pct_change)", s, re.I)
        or re.search(r"\)\s*-\s*(SUM|CASE)", su)
    )
    if years and len(years) >= 2:
        y0, y1 = str(years[0]), str(years[-1])
        if y0 in s and y1 in s and (has_case_pair or has_change or "FILTER" in su):
            return True
        if y0 in s and y1 in s and has_case_pair:
            return True
    if has_case_pair and has_change:
        return True
    if has_case_pair and any(a in s.lower() for a in _PERIOD_ALIASES):
        return True
    # Pivot-style: two year columns as aliases
    if years and len(years) >= 2 and all(y in s for y in years[:2]) and sql_has_aggregation(sql):
        if re.search(rf'AS\s+"?{re.escape(years[0])}', s, re.I) and re.search(
            rf'AS\s+"?{re.escape(years[-1])}', s, re.I
        ):
            return True
    return False
def sql_has_negation(sql: str) -> bool:
    s = sql or ""
    if re.search(r"\bNOT\s+EXISTS\b", s, re.I):
        return True
    if re.search(r"\bIS\s+NULL\b", s, re.I) and re.search(r"\bLEFT\s+JOIN\b", s, re.I):
        return True
    if re.search(r"\bEXCEPT\b", s, re.I):
        return True
    return False
def sql_has_calendar_year(sql: str, year: str) -> bool:
    """True when SQL constrains a calendar year (literal, EXTRACT, or YYYY text prefix)."""
    y = str(year or "").strip()
    if not y or not re.fullmatch(r"\d{4}", y):
        return False
    s = sql or ""
    if re.search(rf"['\"]{re.escape(y)}['\"]", s):
        return True
    if y in s and re.search(r"SUBSTRING\s*\([\s\S]{0,80}?,\s*1\s*,\s*4\s*\)", s, re.I):
        return True
    if y in s and re.search(r"EXTRACT\s*\(\s*YEAR", s, re.I):
        return True
    return False


def sql_has_measure_predicate(sql: str, comparison: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(comparison, dict) or comparison.get("operator") is None:
        return True
    op = str(comparison.get("operator") or "").strip()
    raw = comparison.get("value", 0)
    try:
        num = float(raw)
        val = str(int(num)) if num == int(num) else str(num)
    except (TypeError, ValueError):
        val = str(raw)
    s = sql or ""
    if re.search(rf"{re.escape(op)}\s*{re.escape(val)}\b", s):
        return True
    if op in {"<", "<=", ">", ">=", "=", "!="} and re.search(rf"{re.escape(op)}\s*{re.escape(val)}(?:\.0+)?\b", s):
        return True
    return False


def sql_has_relative_date_bound(sql: str, start_yyyymmdd: str = "", end_yyyymmdd: str = "") -> bool:
    s = sql or ""
    if start_yyyymmdd and start_yyyymmdd in s:
        return True
    if end_yyyymmdd and end_yyyymmdd in s:
        return True
    if re.search(r"DATE_TRUNC\s*\(\s*'(month|week|quarter|year)'", s, re.I):
        return True
    if re.search(r"CURRENT_DATE|INTERVAL\s+'1\s+month'", s, re.I):
        return True
    return False
def _normalize_ranking(ranking: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(ranking, dict):
        return ranking if ranking else None
    if not ranking:
        return None
    if not (ranking.get("limit") or ranking.get("direction") or ranking.get("partition_by")):
        return None
    return ranking
def sql_has_aggregation_fn(sql: str, agg: str) -> bool:
    a = (agg or "").upper()
    if not a or a in {"NONE", "NULL"}:
        return True
    return bool(re.search(rf"\b{re.escape(a)}\s*\(", sql or "", re.I))
def sql_has_measure_expression(sql: str) -> bool:
    s = (sql or "").lower()
    if sql_has_aggregation(sql):
        return True
    return any(tok in s for tok in _MEASURE_TOKENS)
def sql_is_master_only(sql: str) -> bool:
    tables = _tables_in_sql(sql)
    if not tables:
        return False
    tx = [t for t in tables if t not in _MASTER_TABLES]
    if not tx:
        return True
    try:
        return all(table_is_master(t) for t in tx)
    except Exception:
        return False
def _period_years(period: Dict[str, Any], ops: Dict[str, Any]) -> List[str]:
    years: List[str] = []
    for key in ("base_period", "comparison_period"):
        val = period.get(key)
        if isinstance(val, dict):
            if val.get("year"):
                years.append(str(val["year"]))
            elif isinstance(val.get("start"), str) and re.fullmatch(r"\d{4}", val["start"][:4] or ""):
                years.append(val["start"][:4])
        elif val is not None and re.fullmatch(r"\d{4}", str(val)):
            years.append(str(val))
    if not years:
        years = [str(y) for y in (ops.get("years") or [])]
    return years
def sql_satisfies_analytical_intent(
    sql: str,
    question: str,
    semantic: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when SQL is compatible with the analytical plan. Fail closed for rankings/groupings."""
    if not (sql or "").strip():
        return False
    req = required_semantics(question, semantic)
    sem = merge_semantic_requirements(question, semantic or {})
    ops = sem.get("analytical_operations") or extract_analytical_operations(question)
    sql_u = sql.upper()
    group_by = [str(g).lower() for g in (req.get("group_by") or sem.get("group_by") or ops.get("group_by") or [])]
    measure = req.get("measure") if isinstance(req.get("measure"), dict) else {}
    if not measure.get("aggregation"):
        measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or ops.get("aggregation") or "").upper()
    concept = str(measure.get("concept") or ops.get("measure_concept") or "").lower()
    ranking = _normalize_ranking(req.get("ranking") or sem.get("ranking") or ops.get("ranking"))
    period = req.get("period_compare")
    if not isinstance(period, dict) or not (
        period.get("base_period")
        or period.get("comparison_period")
        or period.get("requires_two_periods")
    ):
        period = None
    negation = req.get("negation")
    if not isinstance(negation, dict) or not (
        negation.get("required") or negation.get("forbidden") or negation.get("type")
    ):
        negation = None
    date_filter = req.get("date_filter")
    if isinstance(date_filter, dict):
        df_type = str(date_filter.get("type") or "")
        if df_type == "calendar_year":
            pass
        elif not (date_filter.get("start_yyyymmdd") or date_filter.get("period")):
            date_filter = None
    else:
        date_filter = None
    comparison = req.get("comparison") if isinstance(req.get("comparison"), dict) else ops.get("comparison")
    if isinstance(comparison, dict) and comparison.get("operator") is None:
        comparison = None
    monetary = (
        agg != "COUNT"
        and (
            concept in {"sales", "revenue", "amount", "billing", "turnover"}
            or any(k in concept for k in ("revenue", "amount", "billing", "billed"))
        )
    )
    quantity = any(k in concept for k in ("quant", "qty", "volume"))
    if ranking and (monetary or quantity):
        if sql_is_master_only(sql):
            return False
        if not sql_has_measure_expression(sql):
            return False
        if not sql_has_aggregation(sql) and agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"}:
            return False
    if agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"} and not sql_has_aggregation_fn(sql, agg):
        return False
    if agg == "COUNT" and group_by:
        if not sql_has_group_by(sql):
            return False
        if "month" in group_by and not sql_has_month_bucket(sql):
            return False
        if "year" in group_by and not sql_has_year_bucket(sql) and "month" not in group_by:
            return False
        if re.search(r"\bCOUNT\s*\(\s*\*\s*\)", sql, re.I) and not sql_has_group_by(sql):
            return False
    if group_by and agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"}:
        if not sql_has_group_by(sql) and not (period and sql_has_period_comparison(sql)):
            return False
        if "month" in group_by and not sql_has_month_bucket(sql):
            return False
    if agg == "SUM" and monetary and sql_is_master_only(sql):
        return False
    if ranking and isinstance(ranking, dict) and ranking.get("partition_by"):
        if "PARTITION BY" not in sql_u and "ROW_NUMBER" not in sql_u:
            return False
    elif ranking and isinstance(ranking, dict) and ranking.get("limit"):
        if "ORDER BY" not in sql_u:
            return False
    if period:
        years = _period_years(period if isinstance(period, dict) else {}, ops)
        if not sql_has_period_comparison(sql, years):
            return False
    if negation:
        if not sql_has_negation(sql):
            return False
        # Inner join to the forbidden entity without null/not-exists contradicts absence.
        forbidden = str((negation or {}).get("forbidden") or "").lower()
        if forbidden in {"invoice", "billing"} and re.search(r"\bINNER\s+JOIN\s+\"?VBRK\"?", sql, re.I):
            if not re.search(r"\bIS\s+NULL\b|\bNOT\s+EXISTS\b", sql, re.I):
                return False
    if date_filter:
        if str(date_filter.get("type") or "") == "calendar_year":
            year = str(date_filter.get("value") or (date_filter.get("years") or [""])[0] or "")
            if year and not sql_has_calendar_year(sql, year):
                return False
        elif not sql_has_relative_date_bound(
            sql,
            str(date_filter.get("start_yyyymmdd") or ""),
            str(date_filter.get("end_yyyymmdd") or ""),
        ):
            return False
    if comparison and not sql_has_measure_predicate(sql, comparison):
        return False
    having_distinct = (
        req.get("having_distinct")
        or sem.get("having_distinct")
        or ops.get("having_distinct")
    )
    if isinstance(having_distinct, dict) and having_distinct.get("dimension"):
        if not re.search(r"\bCOUNT\s*\(\s*DISTINCT\b", sql, re.I):
            return False
        if not re.search(r"\bHAVING\b", sql, re.I):
            return False
        # Prefer transactional geo when grain requires it — reject master-only land1
        # for activity questions when a fact geo column is referenced incorrectly.
        dim = str(having_distinct.get("dimension") or "").lower()
        if dim == "country" and having_distinct.get("grain") == "transaction":
            # Must reference a fact-side country expression, not only KNA1.land1.
            if re.search(r'\bKNA1\b[\s\S]{0,80}?"?land1"?', sql, re.I) and not re.search(
                r'\bVBRK\b[\s\S]{0,120}?"?land1"?|\bk\."?land1"?', sql, re.I
            ):
                # Allow alias k for fact table with land1
                if not re.search(r'\bk\."land1"|VBRK\."?land1"?', sql, re.I):
                    return False
    ql = (question or "").lower()
    ranking_not_credit = bool(
        ranking
        and re.search(r"\b(top|highest|lowest|best|worst|rank|most|bottom)\b", ql)
        and not re.search(r"\b(negative|credit memo|below zero|less than zero)\b", ql)
    )
    if ops.get("negative_measure") and not ranking_not_credit and not re.search(r"[<>]\s*0", sql):
        return False
    return True
def result_matches_analytical_intent(
    rows: List[Dict[str, Any]],
    question: str,
    semantic: Optional[Dict[str, Any]] = None,
    sql: str = "",
) -> List[str]:
    """Result-level validation. A successful query can still be the wrong answer."""
    warnings: List[str] = []
    req = required_semantics(question, semantic)
    sem = merge_semantic_requirements(question, semantic or {})
    ops = sem.get("analytical_operations") or extract_analytical_operations(question)
    group_by = [str(g).lower() for g in (req.get("group_by") or sem.get("group_by") or ops.get("group_by") or [])]
    dims = [str(d).lower() for d in (req.get("dimensions") or sem.get("dimensions") or [])]
    ranking = _normalize_ranking(req.get("ranking") or sem.get("ranking") or ops.get("ranking"))
    measure = req.get("measure") if isinstance(req.get("measure"), dict) else {}
    concept = str(measure.get("concept") or "").lower()
    agg = str(measure.get("aggregation") or ops.get("aggregation") or "").upper()
    partition_by = [
        str(p).lower()
        for p in (
            (ranking or {}).get("partition_by")
            if isinstance(ranking, dict)
            else []
        ) or req.get("partition_by") or sem.get("partition_by") or ops.get("partition_by") or []
    ]
    period = req.get("period_compare") or (
        sem.get("period_compare") if isinstance(sem.get("period_compare"), dict) else ops.get("period_compare")
    )
    negation = req.get("negation") or (
        sem.get("negation") if isinstance(sem.get("negation"), dict) else ops.get("negation")
    )
    date_filter = req.get("date_filter")
    if sql and not sql_satisfies_analytical_intent(sql, question, sem):
        warnings.append("executed SQL does not satisfy the analytical plan")
    if not rows:
        return warnings
    keys = [str(k).lower() for k in rows[0].keys()]
    if "month" in group_by:
        if not any("month" in k or re.fullmatch(r"(yyyymm|period|ym)", k) for k in keys):
            warnings.append("monthly grouping missing from result columns")
        if len(rows) == 1 and not any("month" in k for k in keys):
            warnings.append("expected month series, received a single total")
    if "year" in group_by and "month" not in group_by:
        if not any("year" in k or re.fullmatch(r"(yyyy|gjahr|fiscal_year)", k) for k in keys):
            if not period:
                warnings.append("yearly grouping missing from result columns")
    # Dimensions required by ranking / which-X / explicit group_by must appear.
    # Do NOT require every LLM-listed "available" dimension on a plain SUM total
    # (e.g. "sales for year 2000" must not fail for missing customer/country).
    _entity_dims = {
        "country",
        "customer",
        "material",
        "product",
        "vendor",
        "industry",
        "currency",
        "supplier",
    }
    check_dims = set(g for g in group_by if g in _entity_dims or g in {"month", "year", "quarter"})
    if ranking or period:
        check_dims |= {d for d in dims if d in _entity_dims}
    # Normalize supplier → vendor for result column checks.
    if "supplier" in check_dims:
        check_dims.discard("supplier")
        check_dims.add("vendor")
    for dim in check_dims:
        if dim in {"month", "year", "quarter"}:
            continue
        if not result_has_dimension(keys, dim):
            warnings.append(f"requested dimension {dim} missing from result columns")
    monetary = (
        agg != "COUNT"
        and (
            concept in {"sales", "revenue", "amount", "billing", "turnover"}
            or any(k in concept for k in ("revenue", "amount", "billing", "billed", "invoice"))
        )
    )
    if ranking and monetary:
        if sql and sql_is_master_only(sql):
            warnings.append("revenue ranking used master-only tables")
        numeric_keys = []
        for k, v in rows[0].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric_keys.append(str(k).lower())
            elif isinstance(v, str):
                try:
                    float(v.replace(",", ""))
                    numeric_keys.append(str(k).lower())
                except Exception:
                    pass
        measure_like = [
            k for k in numeric_keys
            if any(
                tok in k
                for tok in (
                    "sales", "revenue", "netwr", "amount", "total", "qty", "quantity",
                    "billed", "change", "growth", "period", "value", "purchase", "invoice",
                    "rmwwr", "dmbtr", "wrbtr",
                )
            )
        ]
        if not measure_like and not any(
            tok in " ".join(keys)
            for tok in ("netwr", "sales", "revenue", "total", "fkimg", "change", "growth", "value", "amount", "invoice")
        ):
            warnings.append("ranking result has no revenue/measure column (looks like a master listing)")
    if ranking and isinstance(ranking, dict) and ranking.get("limit"):
        try:
            lim = int(ranking["limit"])
            sql_lim_m = re.search(r"\bLIMIT\s+(\d+)\b", sql or "", re.I)
            # When SQL has an explicit LIMIT and the result respects it, do not fail
            # on an understated plan limit (e.g. plural list with LLM top-1 pollution).
            if sql_lim_m and len(rows) <= int(sql_lim_m.group(1)):
                pass
            elif not partition_by and len(rows) > lim * 5:
                warnings.append("ranking limit was not applied")
        except (TypeError, ValueError):
            pass
    if partition_by:
        part_key = None
        for p in partition_by:
            for k in keys:
                if p in k or (p == "country" and k in {"land1", "country"}) or (p == "plant" and k in {"plant", "werks"}):
                    part_key = k
                    break
            if part_key:
                break
        if not part_key:
            warnings.append("partition dimension missing from partitioned ranking result")
        else:
            lim = 5
            try:
                lim = int((ranking or {}).get("limit") or 5)
            except (TypeError, ValueError):
                lim = 5
            counts = Counter(str(r.get(part_key) if isinstance(r, dict) else "") for r in rows)
            over = {k: c for k, c in counts.items() if k and c > lim}
            if over:
                warnings.append(f"partitioned top-n exceeded limit {lim} within partition(s)")
            # If only 5 total rows but many partitions expected from SQL PARTITION BY — heuristic:
            # when SQL lacks PARTITION BY already flagged; here check overall vs per-partition.
            if len(rows) <= lim and len(counts) <= 1 and sql and "PARTITION BY" in sql.upper():
                # Could be sparse data; only fail when a single partition key dominates total = limit
                # and question asked for "each" partitions — soft check via row scarcity with multi-country claim
                pass
            if (
                len(rows) == lim
                and len(counts) == 1
                and "each" in (question or "").lower()
                and sql
                and "PARTITION BY" not in sql.upper()
            ):
                warnings.append("partitioned top-n collapsed to a single overall top-n result")
    if agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"} and group_by:
        if len(rows) == 1 and not any(
            result_has_dimension(keys, g) or (g == "month" and any("month" in k for k in keys)) for g in group_by
        ):
            warnings.append("grouped aggregation collapsed to a single ungrouped total")
    if period:
        blob = " ".join(keys)
        has_two_periods = (
            sum(1 for a in ("period_a", "period_b", "sales_200", "base", "compare", "prior", "current") if a in blob) >= 2
            or ("period_a" in blob and "period_b" in blob)
            or ("change" in blob or "growth" in blob or "diff" in blob or "delta" in blob)
        )
        years = _period_years(period if isinstance(period, dict) else {}, ops)
        year_cols = [k for k in keys if any(y in k for y in years)] if years else []
        if not has_two_periods and len(year_cols) < 2:
            # single total_sales with no change is a critical wrong-success case
            if any(k in keys for k in ("total_sales", "netwr_total", "revenue", "sales")) and not (
                "change" in blob or "growth" in blob
            ):
                warnings.append("period comparison missing: result has totals without period A/B/change")
            else:
                warnings.append("multi-period comparison columns missing from result")
        # If change present, verify condition when claimable
        condition = str((period or {}).get("condition") or (period or {}).get("op") or "").lower()
        change_key = next((k for k in keys if any(t in k for t in ("change", "growth", "diff", "delta"))), None)
        if change_key and condition in {"increased", "growth", "increase"}:
            bad = 0
            for r in rows[:50]:
                try:
                    v = float(str(r.get(change_key)).replace(",", ""))
                    if v <= 0:
                        bad += 1
                except Exception:
                    pass
            if bad and bad == min(len(rows), 50):
                warnings.append("period comparison condition 'increased' not met by change values")
        if change_key and condition in {"decreased", "decline", "decrease"}:
            bad = 0
            for r in rows[:50]:
                try:
                    v = float(str(r.get(change_key)).replace(",", ""))
                    if v >= 0:
                        bad += 1
                except Exception:
                    pass
            if bad and bad == min(len(rows), 50):
                warnings.append("period comparison condition 'decreased' not met by change values")
    if negation and sql:
        if re.search(r"\bINNER\s+JOIN\s+\"?VBRK\"?", sql, re.I) and not sql_has_negation(sql):
            warnings.append("negation contradicted by INNER JOIN to invoices without absence predicate")
    if date_filter:
        start_s = str(date_filter.get("start") or "")
        end_s = str(date_filter.get("end") or "")
        try:
            start_d = datetime.fromisoformat(start_s).date() if start_s else None
            end_d = datetime.fromisoformat(end_s).date() if end_s else None
        except Exception:
            start_d = end_d = None
        date_keys = [k for k in keys if any(t in k for t in ("date", "fkdat", "audat", "bedat", "budat", "erdat"))]
        if date_keys and start_d and end_d:
            outs = 0
            checked = 0
            for r in rows[:200]:
                for dk in date_keys:
                    d = parse_result_date(r.get(dk))
                    if d is None:
                        continue
                    checked += 1
                    if d < start_d or d >= end_d:
                        outs += 1
            if checked and outs:
                warnings.append(
                    f"relative date filter violated: {outs}/{checked} dates outside "
                    f"{date_filter.get('start_yyyymmdd')}–{date_filter.get('end_yyyymmdd')}"
                )
    return warnings
def answer_consistent_with_rows(
    answer: str,
    rows: List[Dict[str, Any]],
    question: str = "",
) -> List[str]:
    """Final NL answer must not contradict validated result rows."""
    issues: List[str] = []
    if not answer or not rows:
        return issues
    al = answer.lower()
    keys = [str(k).lower() for k in rows[0].keys()]
    change_key = next((k for k in keys if any(t in k for t in ("change", "growth", "diff", "delta"))), None)
    if change_key and re.search(r"\bincreas", al):
        try:
            vals = [float(str(r.get(change_key)).replace(",", "")) for r in rows[:20]]
            if vals and all(v <= 0 for v in vals):
                issues.append("answer claims increase but result changes are non-positive")
        except Exception:
            pass
    if change_key and re.search(r"\bdecreas|\bdeclin", al):
        try:
            vals = [float(str(r.get(change_key)).replace(",", "")) for r in rows[:20]]
            # Allow mixed signs when ranking "largest decline" — only fail if none declined.
            if vals and all(v >= 0 for v in vals):
                issues.append("answer claims decrease but result changes are non-negative")
        except Exception:
            pass
    return issues
