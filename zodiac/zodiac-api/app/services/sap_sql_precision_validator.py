from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session
from .join_graph import allowed_join_column_pairs, allowed_table_edges

logger = logging.getLogger(__name__)

SAP_DATE_COLUMNS = {
    "FKDAT",
    "BUDAT",
    "AUDAT",
    "BEDAT",
    "KDATU",
    "AUGDT",
    "ERDAT",
    "BLDAT",
    "LFDAT",
    "DATUV",
}
RISKY_AGGREGATES = {"SUM", "AVG"}


@dataclass
class SapSqlValidationResult:
    is_valid: bool
    sql: str
    normalized_sql: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    aggregate_functions: List[str] = field(default_factory=list)
    date_normalizations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SapSqlExecutionResult:
    sql: str
    rows: List[Dict[str, Any]]
    validation: SapSqlValidationResult
    warnings: List[str] = field(default_factory=list)
    should_refine: bool = False
    no_data_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "rows": self.rows,
            "warnings": self.warnings,
            "should_refine": self.should_refine,
            "no_data_reason": self.no_data_reason,
            "validation": self.validation.to_dict(),
        }


def _service_root() -> Path:
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _load_schema_ai_config() -> Dict[str, Any]:
    path = _service_root() / "schema_ai_config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load schema_ai_config.json: %s", exc)
        return {}


@lru_cache(maxsize=1)
def _load_semantic_dictionary() -> Dict[str, Any]:
    path = _service_root() / "sap_semantic_dictionary.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load sap_semantic_dictionary.json: %s", exc)
        return {}


def _clean_identifier(value: str) -> str:
    return (value or "").strip().strip('"')


def _extract_alias_map(sql: str) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+(?:(?:[A-Za-z_][A-Za-z0-9_]*\.)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?)"
        r"(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?"
        r"(?=\s+(?:ON|WHERE|GROUP|ORDER|JOIN|LEFT|RIGHT|INNER|FULL|CROSS|LIMIT)\b|\s*$)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(sql or ""):
        table_name = _clean_identifier(match.group(1))
        alias = _clean_identifier(match.group(2) or table_name)
        if not table_name:
            continue
        alias_map[alias.upper()] = table_name
        alias_map[table_name.upper()] = table_name
    return alias_map


def _extract_column_refs(sql: str) -> List[Tuple[str, str]]:
    refs: List[Tuple[str, str]] = []
    pattern = re.compile(
        r'(?:"?([A-Za-z_][A-Za-z0-9_]*)"?)[.]("?([A-Za-z_][A-Za-z0-9_]*)"?)'
    )
    for match in pattern.finditer(sql or ""):
        qualifier = _clean_identifier(match.group(1))
        column = _clean_identifier(match.group(3))
        if qualifier and column:
            refs.append((qualifier, column))
    return refs


def _extract_expression_column_refs(expr: str) -> List[Tuple[str, str]]:
    return _extract_column_refs(expr or "")


def _extract_join_column_pairs(sql: str, alias_map: Dict[str, str]) -> Dict[frozenset[str], Set[frozenset[str]]]:
    pairs: Dict[frozenset[str], Set[frozenset[str]]] = {}
    eq_pattern = re.compile(
        r'(?P<left>(?:[A-Za-z_][A-Za-z0-9_]*\s*\(\s*)*(?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?[A-Za-z_][A-Za-z0-9_]*"?(?:\s*\))*)'
        r'\s*=\s*'
        r'(?P<right>(?:[A-Za-z_][A-Za-z0-9_]*\s*\(\s*)*(?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?[A-Za-z_][A-Za-z0-9_]*"?(?:\s*\))*)',
        re.IGNORECASE,
    )
    for match in eq_pattern.finditer(sql or ""):
        left_refs = _extract_expression_column_refs(match.group("left"))
        right_refs = _extract_expression_column_refs(match.group("right"))
        if not left_refs or not right_refs:
            continue
        for left_alias, left_col in left_refs:
            for right_alias, right_col in right_refs:
                left_table = alias_map.get(left_alias.upper())
                right_table = alias_map.get(right_alias.upper())
                if not left_table or not right_table or left_table.upper() == right_table.upper():
                    continue
                pair_key = frozenset({left_table.upper(), right_table.upper()})
                col_key = frozenset({left_col.upper(), right_col.upper()})
                pairs.setdefault(pair_key, set()).add(col_key)
    return pairs


def _extract_join_table_pairs_from_clauses(sql: str, alias_map: Dict[str, str]) -> Set[frozenset[str]]:
    """
    Fallback connectivity extraction from JOIN ... ON clauses.
    Helps when ON expressions are wrapped in functions and column parser is conservative.
    """
    pairs: Set[frozenset[str]] = set()
    if not sql:
        return pairs
    join_pat = re.compile(
        r"\bJOIN\s+(?:(?:[A-Za-z_][A-Za-z0-9_]*\.)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?)"
        r"(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?\s+ON\s+"
        r"(?P<on>.*?)(?=\b(?:JOIN|WHERE|GROUP|ORDER|LIMIT|HAVING)\b|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for m in join_pat.finditer(sql):
        table_name = _clean_identifier(m.group(1))
        alias = _clean_identifier(m.group(2) or table_name)
        joined_table = alias_map.get(alias.upper()) or table_name
        on_clause = m.group("on") or ""
        aliases_in_on = {
            _clean_identifier(a).upper()
            for a in re.findall(r'("?([A-Za-z_][A-Za-z0-9_]*)"?\.)', on_clause)
            for a in [a[1]]
        }
        for aup in aliases_in_on:
            other = alias_map.get(aup)
            if not other or not joined_table:
                continue
            if other.upper() == joined_table.upper():
                continue
            pairs.add(frozenset({other.upper(), joined_table.upper()}))
    return pairs


def _parse_join_rule_pairs(rule_sql: str) -> Set[frozenset[str]]:
    pairs: Set[frozenset[str]] = set()
    eq_pattern = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)',
        re.IGNORECASE,
    )
    for match in eq_pattern.finditer(rule_sql or ""):
        left_col = _clean_identifier(match.group(2)).upper()
        right_col = _clean_identifier(match.group(4)).upper()
        if left_col and right_col:
            pairs.add(frozenset({left_col, right_col}))
    return pairs


@lru_cache(maxsize=1)
def _allowed_join_pairs() -> Dict[frozenset[str], Set[frozenset[str]]]:
    return allowed_join_column_pairs()


def _normalize_sap_date_filters(sql: str) -> Tuple[str, List[str]]:
    if not sql:
        return sql, []

    notes: List[str] = []
    normalized = sql

    year_eq_pattern = re.compile(
        r'((?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?(' + "|".join(sorted(SAP_DATE_COLUMNS)) + r')"?)(\s*=\s*)(?:\'?(\d{4})\'?)',
        re.IGNORECASE,
    )

    def _replace_year_eq(match: re.Match[str]) -> str:
        expr = match.group(1)
        year = match.group(4)
        notes.append(f"Normalized {expr} = {year} to SAP YYYYMMDD range.")
        return f"{expr} BETWEEN '{year}0101' AND '{year}1231'"

    normalized = year_eq_pattern.sub(_replace_year_eq, normalized)

    between_pattern = re.compile(
        r'((?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?(' + "|".join(sorted(SAP_DATE_COLUMNS)) + r')"?\s+BETWEEN\s+)'
        r"'(\d{4})-(\d{2})-(\d{2})'\s+AND\s+'(\d{4})-(\d{2})-(\d{2})'",
        re.IGNORECASE,
    )

    def _replace_between(match: re.Match[str]) -> str:
        prefix = match.group(1)
        start = f"{match.group(3)}{match.group(4)}{match.group(5)}"
        end = f"{match.group(6)}{match.group(7)}{match.group(8)}"
        notes.append(f"Normalized SAP date BETWEEN filter to YYYYMMDD for {prefix.strip()}.")
        return f"{prefix}'{start}' AND '{end}'"

    normalized = between_pattern.sub(_replace_between, normalized)

    compare_pattern = re.compile(
        r'((?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?(' + "|".join(sorted(SAP_DATE_COLUMNS)) + r')"?\s*(?:>=|<=|>|<)\s*)'
        r"'(\d{4})-(\d{2})-(\d{2})'",
        re.IGNORECASE,
    )

    def _replace_compare(match: re.Match[str]) -> str:
        prefix = match.group(1)
        compact = f"{match.group(3)}{match.group(4)}{match.group(5)}"
        notes.append(f"Normalized SAP date comparison to YYYYMMDD for {prefix.strip()}.")
        return f"{prefix}'{compact}'"

    normalized = compare_pattern.sub(_replace_compare, normalized)
    return normalized, notes


def _normalize_numeric_text_casts(sql: str) -> str:
    """Rewrite mixed-type numeric casts into a text-safe numeric conversion."""
    if not sql:
        return sql

    pattern = re.compile(
        r'CAST\(\s*COALESCE\(\s*(?P<expr>(?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?[A-Za-z_][A-Za-z0-9_]*"?)\s*,\s*0\s*\)\s*AS\s+NUMERIC\s*\)',
        re.IGNORECASE,
    )

    def _replace(match: re.Match[str]) -> str:
        expr = match.group("expr")
        return f"CAST(COALESCE(NULLIF(TRIM(CAST({expr} AS TEXT)), ''), '0') AS NUMERIC)"

    return pattern.sub(_replace, sql)


def _extract_aggregate_functions(sql: str) -> List[str]:
    return sorted({m.upper() for m in re.findall(r"\b(SUM|AVG|COUNT|MIN|MAX)\s*\(", sql or "", re.IGNORECASE)})


def validate_sql_precision(
    sql: str,
    schema: Dict[str, List[str]],
    question: Optional[str] = None,
) -> SapSqlValidationResult:
    normalized_sql, date_normalizations = _normalize_sap_date_filters(sql)
    normalized_sql = _normalize_numeric_text_casts(normalized_sql)
    errors: List[str] = []
    warnings: List[str] = []

    if not sql or not sql.strip():
        return SapSqlValidationResult(
            is_valid=False,
            sql=sql,
            normalized_sql=normalized_sql,
            errors=["Empty SQL"],
        )

    schema_upper = {table.upper(): {col.upper() for col in cols} for table, cols in (schema or {}).items()}
    alias_map = _extract_alias_map(normalized_sql)
    tables = sorted({table.upper() for table in alias_map.values()})

    for table_name in tables:
        if table_name not in schema_upper:
            errors.append(f"Table '{table_name}' is not available in the SAP schema.")

    for qualifier, column in _extract_column_refs(normalized_sql):
        table_name = alias_map.get(qualifier.upper())
        if not table_name:
            continue
        columns = schema_upper.get(table_name.upper())
        if columns is not None and column.upper() not in columns:
            errors.append(f"Column '{table_name}.{column}' is not available in the SAP schema.")

    used_join_pairs = _extract_join_column_pairs(normalized_sql, alias_map)
    join_pairs_from_clauses = _extract_join_table_pairs_from_clauses(normalized_sql, alias_map)
    allowed_join_pairs = _allowed_join_pairs()
    allowed_edges = allowed_table_edges()
    for table_pair, used_columns in used_join_pairs.items():
        if table_pair not in allowed_edges:
            pair_name = " <-> ".join(sorted(table_pair))
            errors.append(f"Join edge {pair_name} is not in the approved join graph.")
            continue
        allowed_columns = allowed_join_pairs.get(table_pair)
        if not allowed_columns:
            pair_name = " <-> ".join(sorted(table_pair))
            errors.append(f"Join edge {pair_name} has no approved predicate template in join graph.")
            continue
        if not used_columns & allowed_columns:
            pair_name = " <-> ".join(sorted(table_pair))
            expected = ", ".join(sorted("/".join(sorted(pair)) for pair in allowed_columns))
            actual = ", ".join(sorted("/".join(sorted(pair)) for pair in used_columns))
            errors.append(
                f"Join keys for {pair_name} do not match configured SAP join rules. "
                f"Expected one of [{expected}] but SQL uses [{actual}]."
            )

    # Ensure multi-table queries are connected by approved join edges (no accidental cross joins).
    if len(tables) > 1:
        neighbor: Dict[str, Set[str]] = {t: set() for t in tables}
        all_pairs_for_connectivity = set(used_join_pairs.keys()) | set(join_pairs_from_clauses)
        for pair in all_pairs_for_connectivity:
            tlist = sorted(pair)
            if len(tlist) == 2 and tlist[0] in neighbor and tlist[1] in neighbor:
                neighbor[tlist[0]].add(tlist[1])
                neighbor[tlist[1]].add(tlist[0])
        seen: Set[str] = set()
        stack: List[str] = [tables[0]]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(list(neighbor.get(node, set()) - seen))
        if len(seen) != len(tables):
            missing = [t for t in tables if t not in seen]
            errors.append(
                f"Query tables are not fully connected by approved joins. Unconnected tables: {', '.join(missing)}."
            )

    aggregate_functions = _extract_aggregate_functions(normalized_sql)
    if any(func in RISKY_AGGREGATES for func in aggregate_functions) and "COUNT" not in aggregate_functions:
        warnings.append("Risky aggregate query: consider COUNT(*) alongside SUM/AVG to detect zero-row totals.")

    if question:
        year_match = re.search(r"\b((?:19|20)\d{2})\b", question)
        question_l = (question or "").lower()
        sql_l = (normalized_sql or "").lower()

        has_any_sap_date_ref = any(col in normalized_sql.upper() for col in SAP_DATE_COLUMNS)
        if year_match and not has_any_sap_date_ref and not re.search(r"\b(?:GJAHR|RYEAR)\b", normalized_sql, re.IGNORECASE):
            warnings.append(
                "Question mentions a year but SQL has no SAP date/fiscal-year filter. Review date precision."
            )

        # Production guard: revenue/aggregate question with explicit calendar year over VBRP/VBRK
        # MUST include FKDAT-based year predicate (warning is insufficient for this class).
        revenue_intent = bool(
            re.search(r"\b(revenue|sales|billing|invoice value|invoice amount|total)\b", question_l)
        )
        touches_billing_tables = ("VBRP" in tables) or ("VBRK" in tables)
        needs_fkdat_year_enforcement = bool(year_match and revenue_intent and touches_billing_tables)
        if needs_fkdat_year_enforcement:
            year = year_match.group(1)
            fkdat_year_ok = bool(
                re.search(r"fkdat[^;]{0,260}(?:19|20)\d{2}", sql_l, re.IGNORECASE)
                or re.search(r"substring\s*\([^)]*fkdat[^)]*1\s*,\s*4[^)]*\)\s*=\s*'" + re.escape(year) + r"'", sql_l, re.IGNORECASE)
                or re.search(r"fkdat\s+between\s*'" + re.escape(year) + r"\d{4}'\s+and\s*'" + re.escape(year) + r"\d{4}'", sql_l, re.IGNORECASE)
            )
            if not fkdat_year_ok:
                errors.append(
                    f"Year-scoped revenue query must include FKDAT year predicate for {year} (e.g. SUBSTRING(TRIM(fkdat),1,4) = '{year}')."
                )

        # Month intent guard: "by month/monthly/per month" requires month bucket aggregation.
        month_intent = bool(re.search(r"\b(month|monthly|per month|by month)\b", question_l))
        if month_intent and touches_billing_tables:
            has_month_bucket_expr = bool(
                re.search(r"to_char\s*\([^)]*fkdat[^)]*'yyyy[-]?mm'\)", sql_l, re.IGNORECASE)
                or ("substring" in sql_l and "fkdat" in sql_l and ",1,6" in sql_l.replace(" ", ""))
                or re.search(r"date_trunc\s*\(\s*'month'[^)]*fkdat", sql_l, re.IGNORECASE)
            )
            grouped_by_bucket = bool(
                re.search(
                    r"group\s+by[^;]{0,260}(to_char|date_trunc|month|substring\s*\([^)]*fkdat[^)]*,\s*1\s*,\s*6\))",
                    sql_l,
                    re.IGNORECASE,
                )
            )
            if not (has_month_bucket_expr and grouped_by_bucket):
                errors.append(
                    "Month-intent query must aggregate by month bucket derived from FKDAT (do not plot raw line/date rows as 'by month')."
                )

    return SapSqlValidationResult(
        is_valid=not errors,
        sql=sql,
        normalized_sql=normalized_sql,
        errors=errors,
        warnings=warnings,
        tables=tables,
        columns=sorted({f"{qualifier.upper()}.{column.upper()}" for qualifier, column in _extract_column_refs(normalized_sql)}),
        aggregate_functions=aggregate_functions,
        date_normalizations=date_normalizations,
    )


def validate_sql_precision_for_db(
    db: Session,
    sql: str,
    question: Optional[str] = None,
) -> SapSqlValidationResult:
    from .schema_loader import get_schema_dict

    return validate_sql_precision(sql=sql, schema=get_schema_dict(db), question=question)


def execute_sql_with_precision_checks(
    db: Session,
    sql: str,
    question: Optional[str] = None,
) -> SapSqlExecutionResult:
    from .sap_sql_agent import _quote_catalog_sql_tables, _run_sql
    from .sql_generation_sanitizers import sanitize_generated_sap_sql

    # Same rewrites as the main orchestrator (memory / manual approve bypassed the agent)
    sql = sanitize_generated_sap_sql(sql)

    validation = validate_sql_precision_for_db(db, sql, question=question)
    if not validation.is_valid:
        return SapSqlExecutionResult(
            sql=validation.normalized_sql,
            rows=[],
            validation=validation,
            warnings=list(validation.warnings),
            should_refine=False,
            no_data_reason="validation_failed",
        )

    executable_sql = _quote_catalog_sql_tables(validation.normalized_sql)
    rows = _run_sql(db, executable_sql)
    warnings = list(validation.warnings)
    should_refine = False
    no_data_reason: Optional[str] = None

    if not rows:
        no_data_reason = "no_rows"
        if any(func in RISKY_AGGREGATES for func in validation.aggregate_functions):
            warnings.append("Aggregate query returned no rows after SAP precision checks. This can be valid when the filters are very specific.")
    elif any(func in RISKY_AGGREGATES for func in validation.aggregate_functions):
        first_row = rows[0] if isinstance(rows[0], dict) else {}
        if first_row and all(value is None for value in first_row.values()):
            warnings.append("Aggregate query returned NULL totals; likely a date/join mismatch rather than real data.")
            should_refine = True
            no_data_reason = "null_aggregate"

    return SapSqlExecutionResult(
        sql=executable_sql,
        rows=rows,
        validation=validation,
        warnings=warnings,
        should_refine=should_refine,
        no_data_reason=no_data_reason,
    )
