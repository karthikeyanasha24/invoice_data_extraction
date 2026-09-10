"""
Adaptive currency handling for monetary rankings and aggregations.

When NETWR (or similar) is summed, the pipeline probes actual currency
distribution and chooses a strategy automatically — never blocks the user
with a raw currency validation error.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..data_catalog.physical import column_names, has_column, has_table, resolve_table_name

logger = logging.getLogger("zodiac-api.currency_strategy")

MONETARY_COLUMNS = frozenset(
    {"netwr", "dmbtr", "wrbtr", "rmwwr", "wsl", "hsl", "fkimg", "menge", "wavwr"}
)
CURRENCY_COLUMNS = frozenset({"waerk", "waers", "rtcur", "hwaer", "curr", "currency"})

_RANKING_CUES = re.compile(
    r"\b(top|highest|lowest|best|worst|bottom|largest|smallest|rank|most|least)\b",
    re.I,
)


@dataclass
class CurrencyStrategy:
    mode: str  # filter | group_by
    currency_table: str
    currency_column: str
    filter_currency: Optional[str] = None
    multi_currency: bool = False
    distribution: List[Dict[str, Any]] = None  # type: ignore[assignment]
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def find_currency_column(table: str) -> Optional[str]:
    tbl = resolve_table_name(table) or table
    for col in column_names(tbl):
        if col.lower() in CURRENCY_COLUMNS:
            return col
    return None


def find_currency_context(tables: List[str]) -> Optional[Tuple[str, str]]:
    """Locate a currency column from selected tables or known billing/purchase headers."""
    seen: set[str] = set()
    candidates: List[str] = list(tables)
    for extra in ("VBRK", "vbrp", "EKKO", "RBKP", "FAGLFLEXA"):
        if extra not in candidates:
            candidates.append(extra)
    for tbl in candidates:
        key = resolve_table_name(tbl) or tbl
        if key.upper() in seen or not has_table(key):
            continue
        seen.add(key.upper())
        col = find_currency_column(key)
        if col:
            return key, col
    return None


def extract_currency_from_question(question: str) -> Optional[str]:
    q = (question or "").upper()
    for code in ("EUR", "USD", "GBP", "CAD", "INR", "JPY", "CHF", "AUD", "MXN", "BRL"):
        if re.search(rf"\b{code}\b", q):
            return code
    if re.search(r"\beuro|\beur\b|€", question or "", re.I):
        return "EUR"
    if re.search(r"\bdollar|\busd\b|\$", question or "", re.I):
        return "USD"
    return None


def probe_currency_distribution(
    db: Session,
    table: str,
    currency_col: str,
    *,
    limit: int = 15,
) -> List[Dict[str, Any]]:
    tbl = resolve_table_name(table) or table
    if not has_table(tbl) or not has_column(tbl, currency_col):
        return []
    sql = (
        f'SELECT TRIM(CAST("{tbl}"."{currency_col}" AS TEXT)) AS currency, '
        f"COUNT(*)::bigint AS row_count "
        f'FROM "{tbl}" '
        f'WHERE NULLIF(TRIM(CAST("{tbl}"."{currency_col}" AS TEXT)), \'\') IS NOT NULL '
        f"GROUP BY 1 ORDER BY row_count DESC LIMIT {int(limit)}"
    )
    try:
        rows = db.execute(text(sql)).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("[currency_strategy] probe failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return []


def resolve_currency_strategy(
    db: Session,
    *,
    tables: List[str],
    question: str,
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[CurrencyStrategy]:
    ctx = find_currency_context(tables)
    if not ctx:
        return None
    table, col = ctx
    dist = probe_currency_distribution(db, table, col)
    explicit = extract_currency_from_question(question)

    if explicit:
        return CurrencyStrategy(
            mode="filter",
            currency_table=table,
            currency_column=col,
            filter_currency=explicit,
            multi_currency=len(dist) > 1,
            distribution=dist,
            note=f"Filtered to currency {explicit} from question.",
        )

    if not dist:
        return CurrencyStrategy(
            mode="group_by",
            currency_table=table,
            currency_column=col,
            multi_currency=True,
            distribution=[],
            note="Currency column included in GROUP BY (distribution unknown).",
        )

    codes = [str(r.get("currency") or "").strip() for r in dist if r.get("currency")]
    if len(codes) == 1:
        return CurrencyStrategy(
            mode="filter",
            currency_table=table,
            currency_column=col,
            filter_currency=codes[0],
            multi_currency=False,
            distribution=dist,
            note=f"Single currency in data ({codes[0]}); auto-filtered.",
        )

    total = sum(int(r.get("row_count") or 0) for r in dist)
    top = dist[0]
    top_code = str(top.get("currency") or "").strip()
    top_pct = (int(top.get("row_count") or 0) / total) if total else 0.0

    q = (question or "").lower()
    if "by currency" in q or "per currency" in q or "each currency" in q:
        return CurrencyStrategy(
            mode="group_by",
            currency_table=table,
            currency_column=col,
            multi_currency=True,
            distribution=dist,
            note="Ranking grouped by currency as requested.",
        )

    # Dominant currency — safe to filter for ranking questions
    if top_pct >= 0.70 and top_code:
        return CurrencyStrategy(
            mode="filter",
            currency_table=table,
            currency_column=col,
            filter_currency=top_code,
            multi_currency=True,
            distribution=dist,
            note=(
                f"Multiple currencies exist; auto-filtered to dominant currency {top_code} "
                f"({top_pct:.0%} of records). Amounts are not mixed across currencies."
            ),
        )

    # Ranking / Top-N must not GROUP BY currency — that multiplies rows past the limit
    # and can collapse ranking dimensions into a currency-only aggregate.
    if is_monetary_ranking_question(question, semantic):
        code = top_code or (codes[0] if codes else None)
        if code:
            return CurrencyStrategy(
                mode="filter",
                currency_table=table,
                currency_column=col,
                filter_currency=code,
                multi_currency=True,
                distribution=dist,
                note=(
                    f"Ranking filtered to leading currency {code} to avoid mixed-currency "
                    f"comparison. Ask 'by currency' for a per-currency breakdown."
                ),
            )

    return CurrencyStrategy(
        mode="group_by",
        currency_table=table,
        currency_column=col,
        multi_currency=True,
        distribution=dist,
        note="Multiple currencies detected; results include currency column and GROUP BY currency.",
    )


def is_currency_validation_error(errors: List[str]) -> bool:
    blob = " ".join(errors).lower()
    return "currency" in blob and ("netwr" in blob or "waerk" in blob or "mixed currencies" in blob)


def is_monetary_ranking_question(question: str, semantic: Optional[Dict[str, Any]] = None) -> bool:
    if _RANKING_CUES.search(question or ""):
        return True
    sem = semantic or {}
    if isinstance(sem.get("ranking"), dict):
        return True
    measure = sem.get("measure")
    if isinstance(measure, dict):
        concept = str(measure.get("concept") or "").lower()
        agg = str(measure.get("aggregation") or "").upper()
        if concept in {"sales", "revenue", "amount", "billing"} and agg in {"SUM", "AVG", "MAX", ""}:
            return _RANKING_CUES.search(question or "") is not None
    return False


def is_monetary_aggregation_question(question: str, semantic: Optional[Dict[str, Any]] = None) -> bool:
    """True when SQL will SUM/AVG monetary columns — not row-level list/filter queries."""
    sem = semantic or {}
    if _is_filter_list_semantic(sem):
        return False
    q = (question or "").lower()
    if any(w in q for w in ("quantity", "qty", "units", " billed quantity", "billing quantity", "fkimg")):
        if not any(w in q for w in ("sales", "revenue", "netwr", "amount", "value", "billing revenue")):
            return False
    if is_monetary_ranking_question(question, sem):
        return True
    measure = sem.get("measure")
    if isinstance(measure, dict):
        agg = str(measure.get("aggregation") or "").upper()
        if agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"}:
            return True
    q = (question or "").lower()
    return any(w in q for w in ("total", "sum of", "how much", "aggregate", "combined"))


def _is_filter_list_semantic(semantic: Dict[str, Any]) -> bool:
    condition = semantic.get("condition") if isinstance(semantic.get("condition"), dict) else {}
    ranking = semantic.get("ranking")
    measure = semantic.get("measure") if isinstance(semantic.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or "").lower()
    return (
        isinstance(condition, dict)
        and condition.get("measure_operator") is not None
        and not isinstance(ranking, dict)
        and agg in {"", "none", "null"}
    )


def sql_has_currency_handling(sql: str) -> bool:
    s = (sql or "").lower()
    return any(c in s for c in ("waerk", "waers", "rtcur", "hwaer"))


def resolve_table_qualifier_in_sql(sql: str, table: str) -> str:
    """
    Return the qualifier used in SQL for a table — alias if present, else quoted table name.
    Fixes currency injection breaking queries like FROM "VBRK" k ... WHERE "VBRK".waerk.
    """
    if not sql or not table:
        return f'"{table}"'
    tbl = resolve_table_name(table) or table
    reserved = frozenset(
        {"ON", "LEFT", "RIGHT", "INNER", "OUTER", "JOIN", "WHERE", "GROUP", "ORDER", "LIMIT", "AS", "AND", "OR"}
    )
    patterns = (
        rf'(?:FROM|JOIN)\s+"{re.escape(tbl)}"\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)',
        rf'(?:FROM|JOIN)\s+{re.escape(tbl)}\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)',
        rf'(?:FROM|JOIN)\s+"{re.escape(tbl.lower())}"\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)',
    )
    for pat in patterns:
        m = re.search(pat, sql, re.I)
        if m:
            alias = m.group("alias")
            if alias.upper() not in reserved:
                return alias
    return f'"{tbl}"'


def repair_table_qualifier_mismatch(sql: str, table: str) -> str:
    """Replace bare quoted table refs with alias when SQL uses table aliases."""
    if not sql or not table:
        return sql
    qual = resolve_table_qualifier_in_sql(sql, table)
    tbl = resolve_table_name(table) or table
    if qual == f'"{tbl}"':
        return sql
    out = re.sub(rf'"{re.escape(tbl)}"\.', f'{qual}.', sql, flags=re.I)
    out = re.sub(rf'"{re.escape(tbl.lower())}"\.', f'{qual}.', out, flags=re.I)
    return out


def inject_currency_filter_sql(sql: str, table: str, column: str, currency_code: str) -> str:
    """Inject WHERE currency = code at the same nesting level as the currency table FROM."""
    if not sql or not currency_code:
        return sql
    tbl = resolve_table_name(table) or table
    if re.search(rf"{re.escape(column)}\s*=", sql, re.I):
        return sql

    def _depth_at(pos: int) -> int:
        depth = 0
        i = 0
        while i < pos and i < len(sql):
            ch = sql[i]
            if ch == "'":
                i += 1
                while i < len(sql) and sql[i] != "'":
                    i += 1
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            i += 1
        return depth

    from_m = re.search(
        rf'(?:FROM|JOIN)\s+"{re.escape(tbl)}"\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)?'
        rf'|(?:FROM|JOIN)\s+{re.escape(tbl)}\s+(?:AS\s+)?(?P<alias2>[A-Za-z_][A-Za-z0-9_]*)?',
        sql,
        re.I,
    )
    if not from_m:
        from_m = re.search(rf'(?:FROM|JOIN)\s+"{re.escape(tbl)}"', sql, re.I)
    if not from_m:
        return sql

    reserved = frozenset(
        {"ON", "LEFT", "RIGHT", "INNER", "OUTER", "JOIN", "WHERE", "GROUP", "ORDER", "LIMIT", "AS", "AND", "OR"}
    )
    alias = (from_m.groupdict().get("alias") or from_m.groupdict().get("alias2") or "").strip()
    if alias and alias.upper() not in reserved:
        qual = alias
    else:
        qual = f'"{tbl}"'
    qual_expr = f'{qual}."{column}"'
    cond = f"TRIM(CAST({qual_expr} AS TEXT)) = '{currency_code}'"
    target_depth = _depth_at(from_m.start())
    search_from = from_m.end()

    for m in re.finditer(r"\bWHERE\b", sql, re.I):
        if m.start() < search_from:
            continue
        if _depth_at(m.start()) == target_depth:
            return sql[: m.end()] + f" {cond} AND" + sql[m.end() :]

    for m in re.finditer(r"\s+(GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b", sql, re.I):
        if m.start() < search_from:
            continue
        if _depth_at(m.start()) == target_depth:
            return sql[: m.start()] + f" WHERE {cond}" + sql[m.start() :]

    # Fallback: outermost injection (legacy)
    for m in re.finditer(r"\bWHERE\b", sql, re.I):
        if _depth_at(m.start()) == 0:
            # Do not reference an inner alias at outer level
            if qual != f'"{tbl}"' and qual not in sql[: m.start()].split("FROM")[-1]:
                outer_qual = f'"{tbl}"'
                cond = f"TRIM(CAST({outer_qual}.\"{column}\" AS TEXT)) = '{currency_code}'"
            return sql[: m.end()] + f" {cond} AND" + sql[m.end() :]
    return sql.rstrip().rstrip(";") + f" WHERE {cond}"


def inject_currency_group_by_sql(sql: str, table: str, column: str) -> str:
    """Ensure currency column appears in SELECT and GROUP BY at the outermost level."""
    if not sql:
        return sql
    qual = resolve_table_qualifier_in_sql(sql, table)
    qual_expr = f'{qual}."{column}"'
    out = sql
    if column.lower() not in sql.lower():
        out = re.sub(
            r"(SELECT\s+)",
            rf'\1{qual_expr} AS currency, ',
            out,
            count=1,
            flags=re.I,
        )

    def _depth_at(pos: int) -> int:
        depth = 0
        i = 0
        while i < pos and i < len(out):
            ch = out[i]
            if ch == "'" :
                i += 1
                while i < len(out) and out[i] != "'":
                    i += 1
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            i += 1
        return depth

    gb = None
    for m in re.finditer(r"\bGROUP\s+BY\b", out, re.I):
        if _depth_at(m.start()) == 0:
            gb = m
            break
    if gb:
        tail = out[gb.end() :]
        if column.lower() not in tail.lower().split("order by")[0]:
            out = re.sub(
                r"(\bGROUP\s+BY\b[^;]+?)(\s+HAVING|\s+ORDER\s+BY|\s+LIMIT|$)",
                rf"\1, {qual_expr}\2",
                out,
                count=1,
                flags=re.I,
            )
    else:
        for m in re.finditer(r"\s+(ORDER\s+BY|LIMIT)\b", out, re.I):
            if _depth_at(m.start()) == 0:
                return out[: m.start()] + f" GROUP BY {qual_expr}" + out[m.start() :]
        out = out.rstrip().rstrip(";") + f" GROUP BY {qual_expr}"
    return out


def sql_aggregates_monetary_values(sql: str) -> bool:
    s = (sql or "").lower()
    return any(c in s for c in ("netwr", "dmbtr", "wrbtr", "rmwwr", "wavwr"))


def apply_currency_strategy_to_sql(sql: str, strategy: CurrencyStrategy) -> str:
    if strategy.mode == "filter" and strategy.filter_currency:
        return inject_currency_filter_sql(
            sql, strategy.currency_table, strategy.currency_column, strategy.filter_currency
        )
    # Never collapse a ranking query to currency-only via GROUP BY injection.
    if re.search(
        r"\b(vendor_id|customer_id|material_id|country|industry|supplier|lifnr|kunnr|matnr)\b",
        sql or "",
        re.I,
    ) and re.search(r"\b(ORDER\s+BY|LIMIT\s+\d+)\b", sql or "", re.I):
        if strategy.filter_currency or (strategy.distribution and strategy.distribution[0].get("currency")):
            code = strategy.filter_currency or str(strategy.distribution[0].get("currency") or "").strip()
            if code:
                return inject_currency_filter_sql(
                    sql, strategy.currency_table, strategy.currency_column, code
                )
    return inject_currency_group_by_sql(sql, strategy.currency_table, strategy.currency_column)


def enrich_plan_with_currency_strategy(
    db: Session,
    plan: Any,
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[CurrencyStrategy]:
    """Add currency field/filter/group-by to structured query plan when needed."""
    from .adaptive_structured_sql import PlanField, PlanFilter, StructuredQueryPlan

    if not isinstance(plan, StructuredQueryPlan):
        return None

    has_monetary = (
        any(pf.type == "column" and pf.column.lower() in MONETARY_COLUMNS for pf in plan.select)
        and is_monetary_aggregation_question(question, semantic)
    )

    if not has_monetary:
        return None

    has_currency = any(
        pf.type == "column" and pf.column.lower() in CURRENCY_COLUMNS
        for pf in plan.select + plan.group_by
    )
    has_currency_filter = any(
        (f.type == "column" and f.column.lower() in CURRENCY_COLUMNS)
        or (f.type == "expression" and "waerk" in f.expression.lower())
        for f in plan.filters
    )
    if has_currency or has_currency_filter:
        return None

    strategy = resolve_currency_strategy(db, tables=tables or plan.tables, question=question, semantic=semantic)
    if not strategy:
        return None

    tbl, col = strategy.currency_table, strategy.currency_column
    plan.select.append(PlanField(type="column", table=tbl, column=col, alias="currency", purpose="currency"))

    if strategy.mode == "filter" and strategy.filter_currency:
        plan.filters.append(
            PlanFilter(
                type="column",
                table=tbl,
                column=col,
                operator="=",
                value=strategy.filter_currency,
            )
        )
    else:
        plan.group_by.append(PlanField(type="column", table=tbl, column=col))

    # Ensure dimension columns are in GROUP BY when aggregating
    for pf in list(plan.select):
        if pf.type != "column" or pf.column.lower() in MONETARY_COLUMNS:
            continue
        if pf.column.lower() in CURRENCY_COLUMNS:
            continue
        if not any(g.type == "column" and g.table == pf.table and g.column == pf.column for g in plan.group_by):
            plan.group_by.append(PlanField(type="column", table=pf.table, column=pf.column))

    if not plan.limit and _RANKING_CUES.search(question or ""):
        m = re.search(r"\btop\s+(\d+)\b", question, re.I)
        if m:
            plan.limit = int(m.group(1))
        elif re.search(r"\b(highest|lowest|most|best|worst|largest|biggest|smallest)\b", question or "", re.I):
            plan.limit = 1
        else:
            plan.limit = 10

    plan.semantic_requirements["_currency_strategy"] = strategy.to_dict()
    return strategy
