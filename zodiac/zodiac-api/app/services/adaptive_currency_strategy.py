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

_UNFILTERED_CURRENCY_CUES = re.compile(
    r"\b(?:all\s+currencies|all\s+currency(?:\s+codes)?|"
    r"currency\s+pairs?|by\s+currency|per\s+currency|each\s+currency|"
    r"every\s+currency|without\s+(?:a\s+)?currency\s+filter|"
    r"no\s+currency\s+filter|do\s+not\s+(?:apply|use|add)\s+(?:a\s+)?currency\s+filter|"
    r"don['’]?t\s+(?:apply|use|add)\s+(?:a\s+)?currency\s+filter|"
    r"remove\s+(?:the\s+)?currency\s+filter|clear\s+(?:the\s+)?currency\s+filter)\b",
    re.I,
)


def requests_unfiltered_currency_scope(question: str) -> bool:
    """Whether the user explicitly requests a multi-currency breakdown."""
    return bool(_UNFILTERED_CURRENCY_CUES.search(question or ""))


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
    raw = question or ""
    # Accept any syntactically explicit three-letter ISO-style code instead
    # of limiting explicit user requests to a hand-maintained code list.
    explicit = re.search(
        r"\b(?:currency(?:\s+code)?|denominated\s+in)\s+([A-Za-z]{3})\b",
        raw,
        re.I,
    )
    if explicit:
        return explicit.group(1).upper()
    # A code following "in" is unambiguous when the user types it in its
    # conventional uppercase form (this avoids mistaking "in the" for THE).
    explicit = re.search(r"\bin\s+([A-Z]{3})\b", raw)
    if explicit:
        return explicit.group(1).upper()

    q = raw.upper()
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

    if requests_unfiltered_currency_scope(question):
        return CurrencyStrategy(
            mode="group_by",
            currency_table=table,
            currency_column=col,
            multi_currency=len(dist) > 1,
            distribution=dist,
            note="Currency restrictions removed; include currency as a result dimension.",
        )

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

    # Never choose a currency based on frequency for a monetary comparison.
    # Currency is part of the result grain so amounts remain comparable.
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
    return any(c in s for c in CURRENCY_COLUMNS)


_CURRENCY_COLUMN_REF = (
    r"(?:(?:\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s*\.\s*)?"
    r"\"?(?:waerk|waers|rtcur|hwaer|curr|currency)\"?"
)
_CURRENCY_LITERAL = r"'(?:''|[^'])*'"


def _sql_depth(sql: str, end: int) -> int:
    depth = 0
    quote: Optional[str] = None
    i = 0
    while i < end:
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < end and sql[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        i += 1
    return depth


def _split_and_terms(condition: str) -> List[str]:
    """Split an SQL condition at AND operators outside quotes/parentheses."""
    terms: List[str] = []
    start = 0
    depth = 0
    quote: Optional[str] = None
    i = 0
    while i < len(condition):
        ch = condition[i]
        if quote:
            if ch == quote:
                if i + 1 < len(condition) and condition[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and condition[i:i + 3].upper() == "AND":
            before = condition[i - 1] if i else " "
            after = condition[i + 3] if i + 3 < len(condition) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                terms.append(condition[start:i].strip())
                start = i + 3
                i += 2
        i += 1
    terms.append(condition[start:].strip())
    return [term for term in terms if term]


def _is_currency_filter_term(term: str) -> bool:
    candidate = term.strip()
    while candidate.startswith("(") and candidate.endswith(")"):
        # Remove a wrapper only when it encloses the entire term.
        if _sql_depth(candidate, len(candidate)) != 0:
            break
        candidate = candidate[1:-1].strip()
    column = _CURRENCY_COLUMN_REF
    values = rf"(?:{_CURRENCY_LITERAL}(?:\s*,\s*{_CURRENCY_LITERAL})*)"
    comparison = rf"(?:=|<>|!=)\s*{_CURRENCY_LITERAL}"
    simple = re.compile(rf"^\s*(?:{column})\s*(?:{comparison}|IN\s*\(\s*{values}\s*\))\s*$", re.I)
    cast = re.compile(
        rf"^\s*TRIM\s*\(\s*CAST\s*\(\s*{column}\s+AS\s+(?:TEXT|VARCHAR(?:\s*\(\s*\d+\s*\))?)\s*\)\s*\)\s*(?:{comparison}|IN\s*\(\s*{values}\s*\))\s*$",
        re.I,
    )
    return bool(simple.fullmatch(candidate) or cast.fullmatch(candidate))


def strip_currency_filter_predicates(sql: str) -> str:
    """Remove simple currency equality/IN predicates while preserving other WHERE scope.

    Only top-level AND terms that consist solely of a currency comparison are
    removed. Predicates mixed with OR or other expressions are left untouched
    because rewriting them could broaden the query incorrectly.
    """
    if not sql:
        return sql

    # Work from right to left so edits to a nested WHERE never shift an earlier one.
    where_positions: List[Tuple[int, int, int]] = []
    quote: Optional[str] = None
    depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch.isalpha() or ch == "_":
            start = i
            while i + 1 < len(sql) and (sql[i + 1].isalnum() or sql[i + 1] == "_"):
                i += 1
            word = sql[start:i + 1].upper()
            if word == "WHERE":
                where_positions.append((start, i + 1, depth))
        i += 1

    replacements: List[Tuple[int, int, str]] = []
    for where_start, where_end, where_depth in where_positions:
        # Find the end of this WHERE expression at its own query nesting level.
        quote = None
        depth = where_depth
        i = where_end
        clause_start: Optional[int] = None
        while i < len(sql):
            ch = sql[i]
            if quote:
                if ch == quote:
                    if i + 1 < len(sql) and sql[i + 1] == quote:
                        i += 1
                    else:
                        quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                if depth == where_depth:
                    clause_start = i
                    break
                depth = max(0, depth - 1)
            elif depth == where_depth and (ch.isalpha() or ch == "_"):
                start = i
                while i + 1 < len(sql) and (sql[i + 1].isalnum() or sql[i + 1] == "_"):
                    i += 1
                word = sql[start:i + 1].upper()
                if word in {"GROUP", "HAVING", "ORDER", "LIMIT", "UNION", "RETURNING"}:
                    clause_start = start
                    break
            i += 1
        if clause_start is None:
            clause_start = len(sql)

        condition = sql[where_end:clause_start]
        terms = _split_and_terms(condition)
        remaining = [term for term in terms if not _is_currency_filter_term(term)]
        if len(remaining) == len(terms):
            continue
        if remaining:
            replacement = " WHERE " + " AND ".join(remaining) + " "
            replacements.append((where_start, clause_start, replacement))
        else:
            replacements.append((where_start, clause_start, " "))

    out = sql
    for start, end, replacement in reversed(replacements):
        out = out[:start] + replacement + out[end:]
    return out


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
    # Match quoted/unquoted column refs: waerk =, "waerk" =, ."waerk"=
    if re.search(rf'(?:^|[.\s"]){re.escape(column)}"?\s*=', sql, re.I):
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

    reserved = frozenset(
        {"ON", "LEFT", "RIGHT", "INNER", "OUTER", "JOIN", "WHERE", "GROUP", "ORDER", "LIMIT", "AS", "AND", "OR"}
    )
    # Alias is only consumed when it is a real identifier, never WHERE/GROUP/etc.
    # (consuming WHERE previously pushed search_from past the clause → second WHERE).
    from_pat = (
        rf'(?:FROM|JOIN)\s+"(?:{re.escape(tbl)})"'
        rf'(?:\s+(?:AS\s+)?(?!(?:{"|".join(sorted(reserved))})\b)(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?'
        rf'|(?:FROM|JOIN)\s+(?:{re.escape(tbl)})'
        rf'(?:\s+(?:AS\s+)?(?!(?:{"|".join(sorted(reserved))})\b)(?P<alias2>[A-Za-z_][A-Za-z0-9_]*))?'
    )
    from_m = re.search(from_pat, sql, re.I)
    if not from_m:
        from_m = re.search(rf'(?:FROM|JOIN)\s+"{re.escape(tbl)}"', sql, re.I)
    if not from_m:
        return sql

    groups = from_m.groupdict()
    alias = (groups.get("alias") or groups.get("alias2") or "").strip()
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
    if requests_unfiltered_currency_scope(question):
        strategy = resolve_currency_strategy(
            db, tables=tables or plan.tables, question=question, semantic=semantic
        )
        if not strategy:
            return None
        plan.filters = [
            f for f in plan.filters
            if not (
                (f.type == "column" and f.column.lower() in CURRENCY_COLUMNS)
                or (f.type == "expression" and re.search(r"\b(?:waerk|waers|rtcur|hwaer|curr|currency)\b", f.expression, re.I))
            )
        ]
        tbl, col = strategy.currency_table, strategy.currency_column
        if not any(
            pf.type == "column" and pf.column.lower() == col.lower()
            for pf in plan.select
        ):
            plan.select.append(PlanField(type="column", table=tbl, column=col, alias="currency", purpose="currency"))
        if not any(
            pf.type == "column" and pf.column.lower() == col.lower()
            for pf in plan.group_by
        ):
            plan.group_by.append(PlanField(type="column", table=tbl, column=col))
        plan.semantic_requirements = dict(plan.semantic_requirements or {})
        plan.semantic_requirements["_currency_strategy"] = strategy.to_dict()
        return strategy
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
