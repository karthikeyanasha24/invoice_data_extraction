"""
Four-stage AI database intelligence pipeline.

User Question
  → Pipeline 1: Table Selection (lightweight catalog from cached registry)
  → Pipeline 2: Column Selection (columns for selected tables only)
  → Pipeline 3: SQL Generation (verified context only)
  → SQL Validation → Execution
  → Pipeline 4: Result Analysis & Presentation

Schema is loaded once from files via schema_intelligence_registry — never
re-introspected from the database per question.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..data_catalog.physical import has_column, has_table, resolve_table_name
from ..services.adaptive_analyst.llm_provider import analyze_json, complete_text
from ..services.adaptive_nl_sql_hardening import repair_generated_sql
from ..services.adaptive_structured_sql import (
    build_structured_query_plan,
    classify_sql_execution_error,
    detect_expression_as_column_errors,
    render_sql_from_plan,
    repair_quoted_expressions_as_columns,
    sanitize_generated_sql,
    validate_query_plan,
)
from ..services.ai_native_pipeline import _schema_violations, extract_sql
from ..services.sap_sql_precision_validator import validate_sql_precision
from ..services.schema_intelligence_registry import get_schema_registry
from ..services.sql_grain_guard import sql_has_unsafe_monetary_fanout

logger = logging.getLogger("zodiac-api.four_stage_pipeline")

ExecuteSql = Callable[[Session, str, str], List[Dict[str, Any]]]

_FOLLOWUP_LIMIT = re.compile(
    r"\b(top|limit|only)\s+(\d+|one|two|three|four|five|ten|twenty)\b", re.I
)
_FOLLOWUP_YEAR = re.compile(r"\b(20\d{2}|19\d{2})\b")


@dataclass
class VerifiedDbContext:
    question: str
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)  # TABLE.col
    joins: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    semantic_requirements: Dict[str, Any] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    query_plan: Dict[str, Any] = field(default_factory=dict)
    pipeline_log: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _log_stage(ctx: VerifiedDbContext, stage: str, payload: Dict[str, Any]) -> None:
    ctx.pipeline_log[stage] = payload
    logger.info("[four_stage] %s %s", stage, json.dumps(payload, default=str)[:1200])


def _question_needs_operational_tables(question: str) -> bool:
    q = (question or "").lower()
    return any(
        k in q
        for k in (
            "sat", "edi", "zodiac", "supplier token", "cfdi", "invoice pipeline",
            "failed invoice", "conversion rate",
        )
    )


def _apply_followup_to_context(
    question: str,
    prior: Optional[Dict[str, Any]],
) -> Optional[VerifiedDbContext]:
    if not isinstance(prior, dict):
        return None
    prev_ctx = prior.get("verified_db_context")
    if not isinstance(prev_ctx, dict):
        prev_ctx = prior.get("investigation_state", {}).get("verified_db_context")
    if not isinstance(prev_ctx, dict) or not prev_ctx.get("tables"):
        return None
    q = (question or "").lower()
    is_followup = (
        len(q.split()) <= 8
        and (
            bool(_FOLLOWUP_LIMIT.search(q))
            or bool(_FOLLOWUP_YEAR.search(q))
            or q.startswith("show only")
            or q.startswith("same for")
            or q.startswith("show the same")
        )
    )
    if not is_followup:
        from .result_first_followup import is_result_scoped_followup

        if is_result_scoped_followup(question, has_prior_rows=True) and prev_ctx.get("tables"):
            is_followup = True
    if not is_followup:
        return None
    ctx = VerifiedDbContext(
        question=question,
        tables=list(prev_ctx.get("tables") or []),
        columns=list(prev_ctx.get("columns") or []),
        joins=list(prev_ctx.get("joins") or []),
        relationships=list(prev_ctx.get("relationships") or []),
        pipeline_log={"followup_reuse": True},
    )
    _log_stage(ctx, "PIPELINE_1_TABLE_SELECTION", {"reused": True, "tables": ctx.tables})
    _log_stage(ctx, "PIPELINE_2_COLUMN_SELECTION", {"reused": True, "columns": ctx.columns})
    return ctx


def extract_semantic_requirements(question: str) -> Dict[str, Any]:
    """Parse dimensions, measure, conditions, time filters, and ranking before table discovery."""
    from .analytical_operations import merge_semantic_requirements
    from .investigation_budget import checkpoint, current_budget
    from .semantic_requirements import enrich_semantic_with_requirements

    budget = current_budget()
    if budget is not None:
        budget.checkpoint("intent_analysis")
    req: Dict[str, Any] = {}
    provider = "local"
    if budget is None or budget.allow_llm():
        req, provider = analyze_json(
            "You extract semantic requirements from business questions. JSON only.",
            (
                f"Question: {question}\n\n"
                "Return JSON: {\n"
                '  "dimensions": ["country","customer","month",...],\n'
                '  "group_by": ["month"],\n'
                '  "measure": {"concept":"sales|revenue|quantity|count|sales_order|...","aggregation":"SUM|COUNT|none|..."},\n'
                '  "condition": {"measure_operator":"<|>|=|<=|>=","measure_value":0},\n'
                '  "time_filter": {"concept":"year|month|date","value":"2000","relative":"last_month"},\n'
                '  "ranking": {"direction":"DESC|ASC","limit":1},\n'
                '  "period_compare": {"type":"period_change","base_period":{"year":"2004"},"comparison_period":{"year":"2005"},"condition":"increased"},\n'
                '  "negation": {"required":"purchase_order","forbidden":"invoice"},\n'
                '  "filters": []\n'
                "}\n"
                "Interpret 'by month/year/country/customer' as group_by dimensions — the result MUST be one row per group, never a single grand total. "
                "Interpret 'top N' / 'highest' as ranking with ORDER BY measure DESC and LIMIT. "
                "Interpret 'top N per/in each X' as ranking.partition_by = [X], NOT a global LIMIT. "
                "Interpret 'between YEAR1 and YEAR2' growth/decline as period_compare with both periods and a change condition. "
                "For growth/decline WITHOUT explicit years: do NOT invent years; leave period_compare null. "
                "Interpret 'without / no / but not' as negation (required exists AND forbidden absent). "
                "Interpret 'last month/week/year' as time_filter.relative string (e.g. last_month) — do NOT invent absolute start/end dates. "
                "Interpret 'count' / 'how many' as aggregation COUNT, not SUM of amounts. "
                "Interpret 'revenue' as a transactional monetary measure — customer master tables do not contain revenue. "
                "Interpret 'negative sales', 'sales below zero', 'loss-making sales' as measure_operator '<' measure_value 0. "
                "Interpret 'for the year 2000', 'in 2000', 'FY2000' as time_filter concept year value 2000. "
                "Unqualified 'sales' means billed invoice amounts when schema supports billing tables. "
                "For show/list invoices (no ranking): measure.aggregation = none. "
                "List every dimension explicitly mentioned or implied."
            ),
        )
    req = merge_semantic_requirements(question, req if isinstance(req, dict) else {})
    req = enrich_semantic_with_requirements(question, req)
    req["_provider"] = provider
    logger.info("[four_stage] SEMANTIC_REQUIREMENTS %s", json.dumps(req, default=str)[:800])
    checkpoint("intent_analysis_done")
    return req


def _normalize_table_name(table: str) -> str:
    return resolve_table_name(table) or table


def _tables_in_verified_set(tables: List[str]) -> set[str]:
    return {_normalize_table_name(t).upper() for t in tables}


def _tables_referenced_in_sql(sql: str) -> List[str]:
    refs: List[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'\b(?:FROM|JOIN)\s+"([A-Za-z0-9_]+)"',
        sql or "",
        re.I,
    ):
        tbl = _normalize_table_name(m.group(1))
        key = tbl.upper()
        if key not in seen and has_table(tbl):
            seen.add(key)
            refs.append(tbl)
    return refs


def _missing_tables_from_sql(sql: str, ctx: VerifiedDbContext) -> List[str]:
    allowed = _tables_in_verified_set(ctx.tables)
    missing = []
    for tbl in _tables_referenced_in_sql(sql):
        if tbl.upper() not in allowed:
            missing.append(tbl)
    return missing


def _dedupe_tables(tables: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for t in tables:
        key = _normalize_table_name(t)
        u = key.upper()
        if u in seen:
            continue
        seen.add(u)
        out.append(key)
    return out


def verify_and_expand_table_coverage(
    question: str,
    ctx: VerifiedDbContext,
    *,
    include_operational: bool,
) -> None:
    """Ensure selected tables cover ALL semantic requirements; AI adds missing tables."""
    reg = get_schema_registry()
    reqs = ctx.semantic_requirements or {}
    catalog = reg.lightweight_table_catalog(include_operational=include_operational)

    coverage, provider = analyze_json(
        "You verify table-set coverage for a business question. JSON only. "
        "Do NOT generate SQL. Select additional tables ONLY from the catalog if needed.",
        (
            f"Question: {question}\n"
            f"Semantic requirements: {json.dumps(reqs)}\n"
            f"Currently selected tables: {ctx.tables}\n\n"
            f"Full table catalog ({len(catalog)} tables, descriptions only):\n"
            f"{reg.compact_catalog_text(include_operational=include_operational)}\n\n"
            "Return JSON: {\"coverage\":{\"country\":true,\"customer\":true,\"industry\":true,\"sales\":true}, "
            "\"missing_concepts\":[], "
            "\"additional_tables\":[{\"table\":\"\",\"reason\":\"\"}], "
            "\"complete\": true}. "
            "If the question needs billed sales amounts, include the billing ITEM table (often vbrp/VBRP) "
            "not only the billing header (VBRK) or sales order header (VBAK). "
            "Every dimension AND the measure must be covered before complete=true."
        ),
    )

    ctx.coverage = coverage.get("coverage") if isinstance(coverage.get("coverage"), dict) else {}
    for item in coverage.get("additional_tables") or []:
        if not isinstance(item, dict):
            continue
        tbl = str(item.get("table") or "").strip()
        if tbl and has_table(tbl):
            ctx.tables.append(_normalize_table_name(tbl))

    ctx.tables = _dedupe_tables(ctx.tables)

    # Expand join neighbors from schema relationships (metadata-driven, not question keywords)
    ctx.tables = reg.expand_join_neighbors(ctx.tables)
    try:
        from .join_cardinality import ensure_connected_tables

        expanded, _ons = ensure_connected_tables(ctx.tables)
        ctx.tables = _dedupe_tables(expanded)
    except Exception:
        pass

    _log_stage(
        ctx,
        "TABLE_COVERAGE_CHECK",
        {
            "provider": provider,
            "coverage": ctx.coverage,
            "tables_after_expansion": ctx.tables,
            "complete": coverage.get("complete"),
            "missing_concepts": coverage.get("missing_concepts"),
        },
    )


def expand_coverage_from_metadata(
    question: str,
    ctx: VerifiedDbContext,
    *,
    include_operational: bool,
) -> None:
    """Metadata-driven fallback: add tables for uncovered semantic requirements."""
    reg = get_schema_registry()
    reqs = ctx.semantic_requirements or {}
    concepts: List[str] = []
    for d in reqs.get("dimensions") or []:
        if isinstance(d, str) and d.strip():
            concepts.append(d.strip())
    measure = reqs.get("measure")
    if isinstance(measure, dict) and measure.get("concept"):
        concepts.append(str(measure["concept"]))

    coverage = dict(ctx.coverage or {})
    added: List[str] = []

    for concept in concepts:
        if coverage.get(concept) is True or coverage.get(concept.lower()) is True:
            continue
        if any(reg.table_covers_concept(t, concept) for t in ctx.tables):
            coverage[concept] = True
            continue

        for tbl, _, reason in reg.find_tables_for_concept(
            concept, include_operational=include_operational, limit=3
        ):
            norm = _normalize_table_name(tbl)
            if has_table(norm):
                ctx.tables.append(norm)
                added.append(norm)
                coverage[concept] = True
                break

    ctx.tables = _dedupe_tables(reg.expand_join_neighbors(ctx.tables))
    ctx.coverage = coverage
    if added:
        _log_stage(
            ctx,
            "METADATA_COVERAGE_EXPANSION",
            {"added": added, "coverage": coverage, "question": question[:200]},
        )


def uncovered_semantic_concepts(ctx: VerifiedDbContext) -> List[str]:
    reqs = ctx.semantic_requirements or {}
    concepts: List[str] = []
    for d in reqs.get("dimensions") or []:
        if isinstance(d, str) and d.strip():
            concepts.append(d.strip())
    measure = reqs.get("measure")
    if isinstance(measure, dict) and measure.get("concept"):
        concepts.append(str(measure["concept"]))

    reg = get_schema_registry()
    coverage = ctx.coverage or {}
    missing: List[str] = []
    for concept in concepts:
        if coverage.get(concept) is True or coverage.get(concept.lower()) is True:
            continue
        if any(reg.table_covers_concept(t, concept) for t in ctx.tables):
            continue
        missing.append(concept)
    return missing


def ensure_complete_table_coverage(
    question: str,
    ctx: VerifiedDbContext,
    *,
    include_operational: bool,
) -> Optional[str]:
    """Run coverage verification + metadata expansion until complete or unsatisfiable."""
    reg = get_schema_registry()
    for attempt in range(2):
        verify_and_expand_table_coverage(question, ctx, include_operational=include_operational)
        expand_coverage_from_metadata(question, ctx, include_operational=include_operational)
        missing = uncovered_semantic_concepts(ctx)
        if not missing:
            return None
        _log_stage(ctx, "COVERAGE_GAP", {"attempt": attempt + 1, "missing_concepts": missing})

    still_missing = uncovered_semantic_concepts(ctx)
    if still_missing:
        for concept in still_missing:
            if not reg.find_tables_for_concept(concept, include_operational=include_operational):
                return (
                    f"Data limitation: the indexed schema has no table that clearly represents "
                    f"'{concept}' for this question."
                )
    return None


def _ensure_measure_source_tables(ctx: VerifiedDbContext) -> None:
    """If the plan needs a transactional measure, do not stop at master-data tables."""
    from .analytical_operations import find_measure_table, table_has_measure_columns, table_is_master

    reqs = ctx.semantic_requirements or {}
    measure = reqs.get("measure") if isinstance(reqs.get("measure"), dict) else {}
    concept = str(measure.get("concept") or "").lower()
    agg = str(measure.get("aggregation") or "").upper()
    ranking = reqs.get("ranking")
    monetary = any(k in concept for k in ("sales", "revenue", "amount", "billing", "quantity"))
    if not (monetary or ranking) and agg not in {"SUM", "COUNT", "AVG"}:
        return
    if find_measure_table(ctx.tables, concept or "sales"):
        return
    if ctx.tables and all(table_is_master(t) for t in ctx.tables if has_table(t)):
        pass
    elif any(table_has_measure_columns(t, concept or "sales") for t in ctx.tables if has_table(t)):
        return

    reg = get_schema_registry()
    include_ops = _question_needs_operational_tables(ctx.question)
    search_concepts = []
    if any(k in concept for k in ("sales", "revenue", "amount", "billing")):
        search_concepts.extend(["billing", "invoice", "sales"])
    elif "quant" in concept:
        search_concepts.extend(["billing item", "sales item"])
    elif agg == "COUNT" or "order" in concept:
        search_concepts.extend(["sales document", "sales order", "billing"])
    else:
        search_concepts.append(concept or "sales")

    added: List[str] = []
    for concept_name in search_concepts:
        for tbl, _, _reason in reg.find_tables_for_concept(
            concept_name, include_operational=include_ops, limit=4
        ):
            norm = _normalize_table_name(tbl)
            if has_table(norm) and table_has_measure_columns(norm, concept or "sales"):
                ctx.tables.append(norm)
                added.append(norm)
                break
        if added:
            break
    if added:
        ctx.tables = _dedupe_tables(reg.expand_join_neighbors(ctx.tables))
        _log_stage(ctx, "MEASURE_TABLE_EXPANSION", {"added": added, "tables": ctx.tables})


def pipeline1_table_selection(question: str, ctx: VerifiedDbContext) -> None:
    from .investigation_budget import current_budget

    budget = current_budget()
    if budget is not None:
        budget.checkpoint("SELECTING_TABLES")
    reg = get_schema_registry()
    include_ops = _question_needs_operational_tables(question)

    ctx.semantic_requirements = extract_semantic_requirements(question)

    catalog = reg.lightweight_table_catalog(include_operational=include_ops)
    catalog_text = reg.compact_catalog_text(include_operational=include_ops)

    pick, provider = analyze_json(
        "You are Pipeline 1 — dynamic TABLE DISCOVERY. Return JSON only. "
        "Independently decide which tables are required to answer EVERY part of the question. "
        "Do NOT generate SQL. Do NOT select columns. "
        "Select as many tables as needed (1 to N). Tables must exist in the catalog.",
        (
            f"Question: {question}\n"
            f"Semantic requirements: {json.dumps(ctx.semantic_requirements)}\n\n"
            f"Available tables ({len(catalog)} total — descriptions only, no columns):\n"
            f"{catalog_text}\n\n"
            "Return JSON: {\"selected_tables\":[{\"table\":\"\",\"confidence\":0.0,\"reason\":\"\"}], "
            "\"reasoning\": {\"TABLE\": \"why this table is required\"}, "
            "\"data_limitation\": null}. "
            "Map each dimension AND the measure to at least one table. "
            "Master-data tables (customer/material/vendor attributes) do NOT contain revenue, "
            "sales amounts, or billed quantity — also select the transactional table that holds the measure. "
            "For billed sales/revenue amounts prefer billing header/item tables when present in catalog. "
            "Never invent table names not in the catalog."
        ),
    )

    selected: List[str] = []
    for item in pick.get("selected_tables") or []:
        if isinstance(item, dict):
            tbl = str(item.get("table") or "").strip()
            if tbl and has_table(tbl):
                selected.append(_normalize_table_name(tbl))
        elif isinstance(item, str) and has_table(item):
            selected.append(_normalize_table_name(item))

    ctx.tables = _dedupe_tables(selected)
    _ensure_measure_source_tables(ctx)
    coverage_limitation = ensure_complete_table_coverage(
        question, ctx, include_operational=include_ops
    )

    limitation = pick.get("data_limitation") or coverage_limitation or reg.resolve_data_limitation(question, ctx.tables)
    _log_stage(
        ctx,
        "PIPELINE_1_TABLE_SELECTION",
        {
            "provider": provider,
            "selected_tables": ctx.tables,
            "reasoning": pick.get("reasoning"),
            "data_limitation": limitation,
        },
    )
    if limitation and not ctx.tables:
        ctx.pipeline_log["data_limitation"] = limitation


def pipeline2_column_selection(question: str, ctx: VerifiedDbContext) -> None:
    from .investigation_budget import current_budget

    budget = current_budget()
    if budget is not None:
        budget.checkpoint("column_selection")
    reg = get_schema_registry()
    col_meta = reg.columns_for_tables(ctx.tables)
    column_text = reg.column_detail_for_selection(ctx.tables)
    suggested_joins = reg.suggested_joins(ctx.tables)

    pick, provider = analyze_json(
        "You are Pipeline 2 — COLUMN SELECTION ONLY. Return JSON only. "
        "Select columns from the provided tables. Do NOT generate SQL.",
        (
            f"Question: {question}\n"
            f"Selected tables: {ctx.tables}\n"
            f"Column metadata:\n{json.dumps(col_meta)}\n\n"
            f"{column_text}\n\n"
            f"Suggested joins from registry: {json.dumps(suggested_joins)}\n\n"
            "Return JSON: {\"selected_columns\":[{\"table\":\"\",\"column\":\"\",\"purpose\":\"\"}], "
            "\"joins\":[{\"left_table\":\"\",\"left_column\":\"\",\"right_table\":\"\",\"right_column\":\"\",\"reason\":\"\"}]}. "
            "Select columns for every dimension and the measure in the semantic requirements."
        ),
    )

    columns: List[str] = []
    for item in pick.get("selected_columns") or []:
        if not isinstance(item, dict):
            continue
        tbl = str(item.get("table") or "").strip()
        col = str(item.get("column") or "").strip()
        if tbl and col and has_column(tbl, col):
            columns.append(f"{resolve_table_name(tbl) or tbl}.{col}")

    if not columns:
        for tbl in ctx.tables:
            meta = reg.get_table(tbl)
            if not meta:
                continue
            for col in (meta.important_columns or [])[:8]:
                if has_column(tbl, col):
                    columns.append(f"{tbl}.{col}")

    joins = pick.get("joins") if isinstance(pick.get("joins"), list) else suggested_joins
    relationships: List[str] = []
    for j in joins or []:
        if not isinstance(j, dict):
            continue
        lt = str(j.get("left_table") or "")
        lc = str(j.get("left_column") or j.get("join_key") or "")
        rt = str(j.get("right_table") or "")
        rc = str(j.get("right_column") or lc or "")
        if lt and rt and lc:
            relationships.append(f"{lt}.{lc} = {rt}.{rc}")
            ctx.joins.append(j)

    # Multi-hop: insert intermediate tables + ON clauses from approved join graph.
    try:
        from .join_cardinality import ensure_connected_tables

        expanded, path_ons = ensure_connected_tables(ctx.tables)
        if len(expanded) > len(ctx.tables):
            ctx.tables = _dedupe_tables(expanded)
        for on in path_ons:
            if on and on not in relationships:
                relationships.append(on)
    except Exception:
        pass

    ctx.columns = columns
    ctx.relationships = relationships
    _log_stage(
        ctx,
        "PIPELINE_2_COLUMN_SELECTION",
        {"provider": provider, "columns": columns, "joins": ctx.joins, "relationships": relationships},
    )


def pipeline25_query_plan(question: str, ctx: VerifiedDbContext, db: Optional[Session] = None) -> None:
    """Build and validate structured query plan (columns vs expressions) before SQL."""
    from .investigation_budget import current_budget
    from .semantic_requirements import plan_missing_requirements, required_semantics

    budget = current_budget()
    if budget is not None:
        budget.checkpoint("query_planning")

    # Resolve relative YoY years from data when the plan requires two periods without literals.
    _resolve_relative_period_years(question, ctx, db)

    plan = build_structured_query_plan(
        question,
        tables=ctx.tables,
        columns=ctx.columns,
        joins=ctx.joins,
        relationships=ctx.relationships,
        semantic_requirements=ctx.semantic_requirements,
    )

    from .adaptive_query_repair import prune_plan_for_aggregation

    currency_strategy = None
    if db is not None:
        from .adaptive_currency_strategy import enrich_plan_with_currency_strategy

        currency_strategy = enrich_plan_with_currency_strategy(
            db, plan, question, ctx.tables, ctx.semantic_requirements
        )
        if currency_strategy:
            _log_stage(ctx, "CURRENCY_STRATEGY", currency_strategy.to_dict())
    prune_plan_for_aggregation(plan)

    errors = validate_query_plan(plan)
    req = required_semantics(question, ctx.semantic_requirements)
    missing = plan_missing_requirements(plan.to_dict(), req)
    if missing:
        # Attempt one plan enrichment pass before blocking SQL generation.
        _enrich_plan_for_missing_semantics(plan, req, question, ctx)
        missing = plan_missing_requirements(plan.to_dict(), req)
        if missing:
            errors = list(errors) + [f"incomplete plan: {m}" for m in missing]
            _log_stage(ctx, "PLAN_INCOMPLETE", {"missing": missing})

    if not plan.joins and ctx.joins:
        plan.joins = list(ctx.joins)
    ctx.query_plan = plan.to_dict()
    _log_stage(
        ctx,
        "QUERY_PLAN",
        {"valid": not errors, "errors": errors, "select_count": len(plan.select), "filter_count": len(plan.filters)},
    )
    if errors:
        ctx.pipeline_log["query_plan_errors"] = errors


def _resolve_relative_period_years(
    question: str, ctx: VerifiedDbContext, db: Optional[Session]
) -> None:
    """When growth/YoY is required without explicit years, bind the two latest years from the date column."""
    sem = ctx.semantic_requirements if isinstance(ctx.semantic_requirements, dict) else {}
    period = sem.get("period_compare") if isinstance(sem.get("period_compare"), dict) else None
    ops = sem.get("analytical_operations") if isinstance(sem.get("analytical_operations"), dict) else {}
    needs_resolve = bool(
        (period and period.get("requires_two_periods"))
        or (
            not _period_has_concrete_years(period or {})
            and period
            and re.search(r"\b(year[- ]over[- ]year|yoy)\b", (question or ""), re.I)
        )
    )
    if not needs_resolve:
        return
    if period and _period_has_concrete_years(period):
        return
    if db is None:
        return
    if not period:
        period = {
            "type": "period_change",
            "requires_two_periods": True,
            "op": "decline" if re.search(r"\b(decline|decrease|drop)\b", (question or ""), re.I) else "growth",
            "condition": "decreased"
            if re.search(r"\b(decline|decrease|drop)\b", (question or ""), re.I)
            else "increased",
        }
    # Anchor year from "why … in 2025" — pair with prior year when present in data.
    anchor = None
    if isinstance(period, dict):
        anchor = period.get("anchor_year")
        cp = period.get("comparison_period")
        if not anchor and isinstance(cp, dict) and cp.get("year") and not period.get("base_period"):
            anchor = str(cp.get("year"))
    date_tbl = date_col = None
    for tbl in ctx.tables:
        if not has_table(tbl):
            continue
        for c in ("fkdat", "audat", "bedat", "budat", "erdat"):
            from ..data_catalog.physical import has_column

            if has_column(tbl, c):
                date_tbl, date_col = tbl, c
                break
        if date_tbl:
            break
    if not date_tbl or not date_col:
        return
    try:
        sql = (
            f'SELECT DISTINCT SUBSTRING(TRIM(CAST("{date_tbl}"."{date_col}" AS TEXT)), 1, 4) AS y '
            f'FROM "{date_tbl}" '
            f"WHERE NULLIF(TRIM(CAST(\"{date_tbl}\".\"{date_col}\" AS TEXT)), '') IS NOT NULL "
            f"AND SUBSTRING(TRIM(CAST(\"{date_tbl}\".\"{date_col}\" AS TEXT)), 1, 4) ~ '^[12][0-9]{{3}}$' "
            f"ORDER BY y DESC LIMIT 8"
        )
        rows = db.execute(__import__("sqlalchemy").text(sql)).fetchall()
        years = [str(r[0]) for r in rows if r and r[0]]
        y_a = y_b = None
        if anchor and re.fullmatch(r"\d{4}", str(anchor)):
            y_b = str(anchor)
            prior = [y for y in years if y < y_b]
            if prior:
                y_a = prior[0]  # years sorted DESC → first prior is nearest earlier year
            else:
                y_a = str(int(y_b) - 1)
        if not y_a or not y_b:
            if len(years) >= 2:
                y_b, y_a = years[0], years[1]
            else:
                return
        period = {
            **period,
            "base_period": {"year": y_a, "start": y_a, "end": y_a},
            "comparison_period": {"year": y_b, "start": y_b, "end": y_b},
            "requires_two_periods": False,
            "resolved_from": "anchor_prior_year" if anchor else "latest_two_years",
        }
        sem["period_compare"] = period
        # Clear clarification once years are resolved from data.
        if isinstance(sem.get("clarification"), dict) and sem["clarification"].get("type") == "comparison_period":
            sem.pop("clarification", None)
        ctx.semantic_requirements = sem
        _log_stage(ctx, "PERIOD_YEARS_RESOLVED", {"base": y_a, "comparison": y_b})
    except Exception as exc:
        logger.warning("[four_stage] period year resolve failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def _period_has_concrete_years(period: Dict[str, Any]) -> bool:
    for key in ("base_period", "comparison_period"):
        val = period.get(key)
        if isinstance(val, dict) and val.get("year"):
            continue
        if isinstance(val, dict) and val.get("relative"):
            return False
        if val is None:
            return False
    y0 = period.get("base_period")
    y1 = period.get("comparison_period")
    def _y(v):
        if isinstance(v, dict):
            return str(v.get("year") or "")
        return str(v or "")
    return bool(re.fullmatch(r"\d{4}", _y(y0)) and re.fullmatch(r"\d{4}", _y(y1)))


def _enrich_plan_for_missing_semantics(plan, req: Dict[str, Any], question: str, ctx: VerifiedDbContext) -> None:
    """Mutate plan when completeness check finds missing comparison/partition/negation/date."""
    if req.get("period_compare") and not plan.period_compare:
        plan.period_compare = dict(req["period_compare"])
        plan.semantic_requirements["period_compare"] = dict(req["period_compare"])
        from .adaptive_structured_sql import _apply_period_compare_fields

        _apply_period_compare_fields(plan, plan.semantic_requirements)
    if req.get("partition_by") or (isinstance(req.get("ranking"), dict) and req["ranking"].get("partition_by")):
        ranking = dict(plan.ranking or req.get("ranking") or {})
        ranking["partition_by"] = list(
            req.get("partition_by")
            or (req.get("ranking") or {}).get("partition_by")
            or ranking.get("partition_by")
            or []
        )
        ranking.setdefault("limit", (req.get("ranking") or {}).get("limit") or 5)
        ranking.setdefault("direction", (req.get("ranking") or {}).get("direction") or "DESC")
        plan.ranking = ranking
        plan.semantic_requirements["ranking"] = ranking
    if req.get("negation") and not plan.negation:
        plan.negation = dict(req["negation"])
        plan.semantic_requirements["negation"] = dict(req["negation"])
    if req.get("date_filter"):
        tf = plan.semantic_requirements.get("time_filter") if isinstance(plan.semantic_requirements.get("time_filter"), dict) else {}
        # Always overwrite LLM-invented calendar bounds with deterministic resolution.
        tf.update({
            "relative": req["date_filter"].get("period"),
            "type": "relative_period",
            "start": req["date_filter"].get("start"),
            "end": req["date_filter"].get("end"),
            "start_yyyymmdd": req["date_filter"].get("start_yyyymmdd"),
            "end_yyyymmdd": req["date_filter"].get("end_yyyymmdd"),
            "value": req["date_filter"].get("period"),
            "concept": "relative_period",
        })
        plan.semantic_requirements["time_filter"] = tf
        # Invoice/list relative-date questions must not force SUM aggregation.
        measure = plan.semantic_requirements.get("measure") if isinstance(plan.semantic_requirements.get("measure"), dict) else {}
        if str(measure.get("aggregation") or "").upper() in {"SUM", "AVG"} and re.search(
            r"\b(show|list|display|from last|from this)\b", question or "", re.I
        ):
            if not re.search(r"\b(top|highest|total|sum|rank)\b", question or "", re.I):
                measure["aggregation"] = "none"
                plan.semantic_requirements["measure"] = measure
                plan.limit = plan.limit or 200
                # Drop measure aggregates from select for row lists
                plan.select = [
                    pf for pf in plan.select
                    if not (
                        pf.purpose == "measure"
                        or (pf.type == "expression" and re.search(r"\b(SUM|AVG)\s*\(", pf.expression or "", re.I))
                    )
                ]
    for dim in req.get("group_by") or []:
        if dim in {"month", "year", "quarter"}:
            continue
        gb = [str(g).lower() for g in (plan.semantic_requirements.get("group_by") or [])]
        if dim not in gb:
            gb.append(dim)
            plan.semantic_requirements["group_by"] = gb
        dims = [str(d).lower() for d in (plan.semantic_requirements.get("dimensions") or [])]
        if dim not in dims:
            dims.append(dim)
            plan.semantic_requirements["dimensions"] = dims
    ctx.semantic_requirements = plan.semantic_requirements
    ctx.query_plan = plan.to_dict()


def _validate_sql_against_context(sql: str, ctx: VerifiedDbContext, db: Session) -> List[str]:
    from .investigation_budget import current_budget

    budget = current_budget()
    if budget is not None:
        budget.checkpoint("VALIDATING_SQL")
    errors = list(_schema_violations(sql) or [])
    errors.extend(detect_expression_as_column_errors(sql))
    if errors:
        return errors
    allowed = _tables_in_verified_set(ctx.tables)
    for tbl in _tables_referenced_in_sql(sql):
        if tbl.upper() not in allowed:
            errors.append(f"table {tbl} not in verified selection {ctx.tables}")
    # Prefer file/registry schema — never block investigations on slow DB introspection.
    try:
        from .sap_sql_precision_validator import validate_sql_precision
        from .schema_loader import load_schema_from_mapping_file

        schema = load_schema_from_mapping_file()
        prec = validate_sql_precision(sql, schema, question=ctx.question)
        if prec and getattr(prec, "errors", None):
            prec_errors = [str(e) for e in prec.errors[:5]]
            if has_table("sat_processing_logs") and re.search(r"\bsat_processing_logs\b", sql, re.I):
                prec_errors = [
                    e for e in prec_errors if "sat_processing" not in e.lower()
                ]
            errors.extend(prec_errors)
    except Exception:
        pass
    return errors


def _repair_currency_and_regenerate(
    question: str,
    sql: str,
    ctx: VerifiedDbContext,
    db: Session,
) -> tuple[str, List[str]]:
    """Auto-resolve currency handling and regenerate SQL."""
    from .adaptive_currency_strategy import (
        apply_currency_strategy_to_sql,
        is_currency_validation_error,
        resolve_currency_strategy,
    )

    strategy = resolve_currency_strategy(
        db, tables=ctx.tables, question=question, semantic=ctx.semantic_requirements
    )
    if not strategy:
        return sql, ["currency repair: no currency column found in schema"]

    _log_stage(ctx, "CURRENCY_REPAIR", strategy.to_dict())

    from .adaptive_currency_strategy import repair_table_qualifier_mismatch

    patched = apply_currency_strategy_to_sql(sql, strategy)
    patched = repair_table_qualifier_mismatch(patched, strategy.currency_table)
    if patched != sql:
        viol = _validate_sql_against_context(patched, ctx, db)
        if not viol or not is_currency_validation_error(viol):
            ctx.pipeline_log["currency_note"] = strategy.note
            return patched, viol

    pipeline25_query_plan(question, ctx, db)
    new_sql = pipeline3_sql_generation(question, ctx)
    new_sql = sanitize_generated_sql(new_sql, question)
    viol = _validate_sql_against_context(new_sql, ctx, db)
    if viol and is_currency_validation_error(viol):
        new_sql = apply_currency_strategy_to_sql(new_sql, strategy)
        new_sql = repair_table_qualifier_mismatch(new_sql, strategy.currency_table)
        new_sql = sanitize_generated_sql(new_sql, question)
        viol = _validate_sql_against_context(new_sql, ctx, db)
    ctx.pipeline_log["currency_note"] = strategy.note
    return new_sql, viol


def _recover_missing_tables_and_regenerate(
    question: str,
    sql: str,
    ctx: VerifiedDbContext,
    db: Session,
    *,
    max_rounds: int = 2,
) -> tuple[str, List[str]]:
    """If SQL references tables outside verified set, add them and re-run P2+P3."""
    current_sql = sql
    viol: List[str] = []

    for _round in range(max_rounds):
        missing = _missing_tables_from_sql(current_sql, ctx)
        if not missing:
            return current_sql, viol

        for tbl in missing:
            if has_table(tbl):
                ctx.tables.append(_normalize_table_name(tbl))
        ctx.tables = _dedupe_tables(get_schema_registry().expand_join_neighbors(ctx.tables))

        _log_stage(
            ctx,
            "TABLE_RECOVERY",
            {"missing_tables": missing, "expanded_tables": ctx.tables, "round": _round + 1},
        )
        pipeline2_column_selection(question, ctx)
        pipeline25_query_plan(question, ctx, db)
        current_sql = pipeline3_sql_generation(question, ctx)
        viol = _validate_sql_against_context(current_sql, ctx, db)
        if not any("not in verified selection" in e for e in viol):
            return current_sql, viol

    return current_sql, viol


def _deterministic_sql_if_known(question: str, ctx: VerifiedDbContext) -> Optional[str]:
    """LEGACY: question-shaped SQL is no longer a runtime authority.

    Table/column choices must come from schema retrieval + the structured plan.
    Kept as a no-op so callers and tests can assert it never answers.
    """
    return None


def _execution_fallback_sql(question: str, ctx: VerifiedDbContext) -> Optional[str]:
    """Deterministic SQL templates when LLM/execution path fails."""
    from .adaptive_query_repair import build_measure_ranking_sql
    from .adaptive_structured_sql import (
        build_country_customer_list_sql,
        build_customer_industry_revenue_sql,
        build_dimension_ranking_sql,
        build_filter_list_sql,
        build_master_list_sql,
        build_multidim_ranking_sql,
        build_partitioned_topn_sql,
        build_period_compare_sql,
        build_period_sales_sql,
        build_relative_document_list_sql,
        build_sat_logs_sql,
        build_total_measure_sql,
    )

    for builder in (
        lambda: build_relative_document_list_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_period_compare_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_partitioned_topn_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_filter_list_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_multidim_ranking_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_dimension_ranking_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_period_sales_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_customer_industry_revenue_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_country_customer_list_sql(question, ctx.tables),
        lambda: build_sat_logs_sql(question, ctx.tables),
        lambda: build_total_measure_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_measure_ranking_sql(question, ctx.tables, ctx.semantic_requirements),
        lambda: build_master_list_sql(question, ctx.tables),
    ):
        sql = builder()
        if sql:
            from .plan_satisfaction import sql_satisfies_analytical_intent

            if not sql_satisfies_analytical_intent(sql, question, ctx.semantic_requirements):
                continue
            _register_template_tables(ctx, sql)
            return sql
    return None


def _apply_currency_if_needed(question: str, sql: str, ctx: VerifiedDbContext, db: Session) -> str:
    from .adaptive_currency_strategy import (
        apply_currency_strategy_to_sql,
        is_monetary_aggregation_question,
        repair_table_qualifier_mismatch,
        resolve_currency_strategy,
        sql_aggregates_monetary_values,
        sql_has_currency_handling,
    )

    if sql_has_currency_handling(sql) and re.search(r"\bwaerk\s*=|\bwaers\s*=", sql, re.I):
        return repair_table_qualifier_mismatch(sql, "VBRK")
    if not is_monetary_aggregation_question(question, ctx.semantic_requirements):
        return sql
    if not sql_aggregates_monetary_values(sql):
        return sql
    strategy = resolve_currency_strategy(
        db, tables=ctx.tables, question=question, semantic=ctx.semantic_requirements
    )
    if not strategy:
        return sql
    patched = apply_currency_strategy_to_sql(sql, strategy)
    patched = repair_table_qualifier_mismatch(patched, strategy.currency_table)
    for tbl in ctx.tables:
        patched = repair_table_qualifier_mismatch(patched, tbl)
    ctx.pipeline_log["currency_note"] = strategy.note
    return patched


def _register_template_tables(ctx: VerifiedDbContext, sql: str) -> None:
    """Templates pick their own joins — keep the verified set in sync so validation passes."""
    for tbl in _tables_referenced_in_sql(sql):
        if not any(_normalize_table_name(t).upper() == tbl.upper() for t in ctx.tables):
            ctx.tables.append(tbl)


def _template_sql(ctx: VerifiedDbContext, question: str, source: str, sql: str) -> str:
    out = sanitize_generated_sql(sql, question)
    _register_template_tables(ctx, out)
    _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"source": source, "sql": out[:2000]})
    return out


def pipeline3_sql_generation(question: str, ctx: VerifiedDbContext) -> str:
    from .investigation_budget import current_budget
    from .plan_satisfaction import sql_satisfies_analytical_intent
    from .adaptive_structured_sql import (
        build_country_customer_list_sql,
        build_customer_industry_revenue_sql,
        build_dimension_ranking_sql,
        build_document_count_by_period_sql,
        build_above_average_sql,
        build_filter_list_sql,
        build_master_list_sql,
        build_multi_entity_having_sql,
        build_multidim_ranking_sql,
        build_negation_anti_join_sql,
        build_partitioned_topn_sql,
        build_period_compare_sql,
        build_period_sales_sql,
        build_relative_document_list_sql,
        build_sat_logs_sql,
        build_total_measure_sql,
        detect_filter_list_intent,
    )

    budget = current_budget()
    if budget is not None:
        budget.checkpoint("sql_generation")

    def _accept(source: str, sql: Optional[str]) -> Optional[str]:
        if not sql:
            return None
        out = sanitize_generated_sql(sql, question)
        # Reject invalid grain: window + GROUP BY aggregate in the same SELECT level.
        if (
            re.search(r"\bROW_NUMBER\s*\(", out, re.I)
            and re.search(r"\bGROUP\s+BY\b", out, re.I)
            and not re.search(r"\)\s*(?:AS\s+\w+\s*)?(?:ranked|q\b)", out, re.I)
            and out.upper().find("ROW_NUMBER") < out.upper().find("FROM")
        ):
            # Window appears in outermost select alongside grouping — invalid PG grain.
            if not re.search(r"SELECT\s+\*\s+FROM\s*\(", out, re.I):
                _log_stage(
                    ctx,
                    "PIPELINE_3_SQL_REJECTED",
                    {"source": source, "reason": "window_and_group_same_level", "sql": out[:500]},
                )
                return None
        # First-class templates: validate against question-derived semantics only.
        # LLM semantic pollution (spurious currency/group_by dims) must not reject
        # correct deterministic templates in favor of broken free-form SQL.
        sem_for_check = (
            None
            if source.endswith("_template")
            else ctx.semantic_requirements
        )
        if not sql_satisfies_analytical_intent(out, question, sem_for_check):
            _log_stage(
                ctx,
                "PIPELINE_3_SQL_REJECTED",
                {"source": source, "reason": "does_not_satisfy_analytical_plan", "sql": out[:500]},
            )
            return None
        return _template_sql(ctx, question, source, out)

    # Prefer semantic templates for first-class ops before free-form plan/LLM SQL.
    # Ranking templates must beat structured/LLM paths so CAST-safe SUM wins over bare SUM(text).
    for source, builder in (
        ("relative_document_list_template", lambda: build_relative_document_list_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("period_compare_template", lambda: build_period_compare_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("negation_anti_join_template", lambda: build_negation_anti_join_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("multi_entity_having_template", lambda: build_multi_entity_having_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("partitioned_topn_template", lambda: build_partitioned_topn_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("above_average_template", lambda: build_above_average_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("filter_list_template", lambda: build_filter_list_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("document_count_period_template", lambda: build_document_count_by_period_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("multidim_ranking_template", lambda: build_multidim_ranking_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("dimension_ranking_template", lambda: build_dimension_ranking_sql(question, ctx.tables, ctx.semantic_requirements)),
    ):
        accepted = _accept(source, builder())
        if accepted:
            return accepted

    # Primary path: render from the validated structured query plan
    if ctx.query_plan:
        from .adaptive_structured_sql import StructuredQueryPlan

        plan_obj = StructuredQueryPlan.from_dict({**ctx.query_plan, "semantic_requirements": ctx.semantic_requirements})
        if not plan_obj.tables:
            plan_obj.tables = list(ctx.tables)
        rendered = render_sql_from_plan(plan_obj)
        if rendered:
            rendered = sanitize_generated_sql(repair_generated_sql(rendered, question))
            plan_viol = validate_query_plan(plan_obj)
            schema_viol = list(_schema_violations(rendered) or [])
            schema_viol.extend(detect_expression_as_column_errors(rendered))
            if not plan_viol and not schema_viol:
                accepted = _accept("structured_plan_renderer", rendered)
                if accepted:
                    return accepted
            _log_stage(
                ctx,
                "PIPELINE_3_SQL_GENERATION",
                {"source": "structured_plan_renderer_skipped", "plan_viol": plan_viol, "schema_viol": schema_viol},
            )

    filter_sql = build_filter_list_sql(question, ctx.tables, ctx.semantic_requirements)
    accepted = _accept("filter_list_template", filter_sql)
    if accepted:
        return accepted

    if detect_filter_list_intent(question, ctx.semantic_requirements):
        expanded = list(dict.fromkeys(ctx.tables))
        if has_table("VBRK") and not any((resolve_table_name(t) or t).upper() == "VBRK" for t in expanded):
            expanded.insert(0, resolve_table_name("VBRK") or "VBRK")
        filter_sql = build_filter_list_sql(question, expanded, ctx.semantic_requirements)
        accepted = _accept("filter_list_template_expanded", filter_sql)
        if accepted:
            return accepted

    for source, builder in (
        ("relative_document_list_template", lambda: build_relative_document_list_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("period_compare_template", lambda: build_period_compare_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("negation_anti_join_template", lambda: build_negation_anti_join_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("multi_entity_having_template", lambda: build_multi_entity_having_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("partitioned_topn_template", lambda: build_partitioned_topn_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("above_average_template", lambda: build_above_average_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("document_count_period_template", lambda: build_document_count_by_period_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("country_customer_list_template", lambda: build_country_customer_list_sql(question, ctx.tables)),
        ("master_list_template", lambda: build_master_list_sql(question, ctx.tables)),
        ("multidim_ranking_template", lambda: build_multidim_ranking_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("dimension_ranking_template", lambda: build_dimension_ranking_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("period_sales_template", lambda: build_period_sales_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("customer_industry_revenue_template", lambda: build_customer_industry_revenue_sql(question, ctx.tables, ctx.semantic_requirements)),
        ("sat_logs_template", lambda: build_sat_logs_sql(question, ctx.tables)),
        ("total_measure_template", lambda: build_total_measure_sql(question, ctx.tables, ctx.semantic_requirements)),
    ):
        accepted = _accept(source, builder())
        if accepted:
            return accepted

    from .adaptive_query_repair import build_measure_ranking_sql

    accepted = _accept(
        "measure_ranking_template",
        build_measure_ranking_sql(question, ctx.tables, ctx.semantic_requirements),
    )
    if accepted:
        return accepted

    if accepted:
        return accepted

    if budget is not None and not budget.allow_llm():
        _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"source": "llm_skipped_budget"})
        return ""

    reg = get_schema_registry()
    detail = reg.column_detail_for_selection(ctx.tables)
    sql_text, provider = complete_text(
        "You are Pipeline 3 — SQL GENERATION ONLY. PostgreSQL SELECT. ```sql block only. "
        "Use ONLY the verified tables, columns, and relationships provided. "
        "CRITICAL: Physical columns use \"TABLE\".\"column\" syntax. "
        "SQL expressions (SUBSTRING, EXTRACT, TRIM, CAST, SUM) must NEVER be quoted as column names. "
        "WRONG: \"VBRK\".\"SUBSTRING(TRIM(fkdat),1,4)\" "
        "RIGHT: SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4) "
        "Do NOT reference any table not listed under Verified tables. "
        "Quote identifiers. CAST text numerics with NULLIF(TRIM(...),''). "
        "Do not invent tables. Do not add restrictive date filters unless the question asks for a period. "
        "For show/list/filter questions (e.g. negative sales in a year): return ROW-LEVEL rows — NO SUM(), NO GROUP BY. "
        "If the plan has group_by (month/year/customer/...): SELECT the group expression AND the measure, GROUP BY the group expression. Never return a single grand total. "
        "Ranking questions: GROUP BY dimensions, ORDER BY metric DESC, LIMIT from question (default 10).",
        (
            f"Question: {question}\n\n"
            f"Semantic requirements: {json.dumps(ctx.semantic_requirements)}\n"
            f"Query plan: {json.dumps(ctx.query_plan)[:3000]}\n"
            f"Verified tables: {ctx.tables}\n"
            f"Verified columns: {ctx.columns}\n"
            f"Relationships: {ctx.relationships}\n\n"
            f"{detail}\n\nGenerate SQL."
        ),
    )
    sql = extract_sql(sql_text) or sql_text.strip()
    sql = repair_generated_sql(sql, question)
    sql = sanitize_generated_sql(sql)
    _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"provider": provider, "source": "llm_fallback", "sql": sql[:2000]})
    return sql


def pipeline4_result_analysis(
    question: str,
    sql: str,
    rows: List[Dict[str, Any]],
    ctx: VerifiedDbContext,
    *,
    exec_ms: int = 0,
) -> Dict[str, Any]:
    from .investigation_budget import current_budget

    budget = current_budget()
    if budget is not None:
        try:
            budget.checkpoint("result_analysis")
        except Exception:
            return {
                "answer": f"Query returned {len(rows)} row(s).",
                "summary": f"Query returned {len(rows)} row(s).",
                "findings": [],
                "presentation_type": "table" if rows else "none",
            }
        if not budget.allow_llm() or budget.prefer_simple_strategy():
            _log_stage(ctx, "PIPELINE_4_RESULT_ANALYSIS", {"provider": "skipped_budget", "row_count": len(rows), "exec_ms": exec_ms})
            return {
                "answer": f"Query returned {len(rows)} row(s).",
                "summary": f"Query returned {len(rows)} row(s).",
                "findings": [],
                "presentation_type": "table" if rows else "none",
            }
    narrative, provider = analyze_json(
        "You are Pipeline 4 — RESULT ANALYSIS. JSON only. Use ONLY numbers in the rows. Never invent.",
        (
            f"Question: {question}\nSQL:\n{sql[:1500]}\n"
            f"Tables: {ctx.tables}\nColumns: {ctx.columns}\n"
            f"Row count: {len(rows)}\nSample: {json.dumps(rows[:12], default=str)[:4000]}\n\n"
            "Return JSON: {\"answer\":\"\",\"summary\":\"\",\"findings\":[], "
            "\"presentation_type\":\"table|bar|line|pie|none\", "
            "\"calculation_explanation\":\"\", \"follow_up_suggestions\":[]}. "
            "If 0 rows: say query succeeded but no matching records — do NOT claim data does not exist globally."
        ),
    )
    _log_stage(
        ctx,
        "PIPELINE_4_RESULT_ANALYSIS",
        {"provider": provider, "row_count": len(rows), "exec_ms": exec_ms},
    )
    return narrative


def run_four_stage_database_query(
    question: str,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_sql: str = "",
) -> Dict[str, Any]:
    """
    Run P1→P4. Returns orchestrator-compatible dict with sql, rows, tables, error, narrative.
    """
    from .investigation_budget import InvestigationTimeout, current_budget
    from .investigation_budget import user_safe_pipeline_message
    from .plan_satisfaction import result_matches_analytical_intent

    t0 = time.perf_counter()
    budget = current_budget()
    try:
        return _run_four_stage_body(
            question, db, execute_sql, prior_plan=prior_plan, prior_sql=prior_sql, t0=t0
        )
    except InvestigationTimeout as te:
        ctx_log = {"timeout_stage": te.stage, "elapsed_s": te.elapsed_s}
        logger.warning("[four_stage] TIMEOUT %s", ctx_log)
        return {
            "error": "timeout",
            "error_kind": "timeout",
            "error_class": "Timeout",
            "detail": [user_safe_pipeline_message("timeout")],
            "tables": [],
            "sql": "",
            "rows": [],
            "pipeline_log": ctx_log,
            "timeout": True,
        }


def _run_four_stage_body(
    question: str,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_sql: str = "",
    t0: float = 0.0,
) -> Dict[str, Any]:
    from .investigation_budget import current_budget
    from .plan_satisfaction import result_matches_analytical_intent

    budget = current_budget()
    ctx = _apply_followup_to_context(question, prior_plan)
    if ctx is None:
        ctx = VerifiedDbContext(question=question)
        pipeline1_table_selection(question, ctx)
        # Ambiguous semantics (growth periods, qualitative thresholds, …) → clarification
        clar = (ctx.semantic_requirements or {}).get("clarification")
        if isinstance(clar, dict) and clar.get("type"):
            msg = str(clar.get("message") or "Please clarify the missing analytical parameters.")
            return {
                "error": "clarification_required",
                "error_kind": "clarification",
                "error_class": "CLARIFICATION",
                "detail": [msg],
                "tables": ctx.tables,
                "sql": "",
                "rows": [],
                "verified_context": ctx.to_dict(),
                "pipeline_log": ctx.pipeline_log,
                "clarification": clar,
                "user_message": msg,
                "narrative": {"answer": msg, "summary": msg, "findings": []},
            }
        if ctx.pipeline_log.get("data_limitation") and not ctx.tables:
            msg = str(ctx.pipeline_log["data_limitation"])
            return {
                "error": "data_limitation",
                "detail": [msg],
                "tables": [],
                "missing": [],
                "sql": "",
                "rows": [],
                "verified_context": ctx.to_dict(),
                "pipeline_log": ctx.pipeline_log,
                "data_limitation": msg,
            }
        pipeline2_column_selection(question, ctx)
        pipeline25_query_plan(question, ctx, db)

    if ctx.tables and ctx.columns and not ctx.query_plan:
        pipeline25_query_plan(question, ctx, db)

    if prior_sql and ctx.pipeline_log.get("followup_reuse"):
        sql = pipeline3_sql_generation(
            question + f"\nModify the previous SQL (do not rediscover tables):\n{prior_sql[:3000]}",
            ctx,
        )
        _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"followup_modified": True})
    else:
        sql = pipeline3_sql_generation(question, ctx)

    sql = sanitize_generated_sql(sql, question)
    sql = _apply_currency_if_needed(question, sql, ctx, db)

    from .adaptive_currency_strategy import is_currency_validation_error

    viol = _validate_sql_against_context(sql, ctx, db)
    _log_stage(ctx, "SQL_VALIDATION", {"pass": not viol, "errors": viol})

    if viol and is_currency_validation_error(viol):
        sql, viol = _repair_currency_and_regenerate(question, sql, ctx, db)
        _log_stage(ctx, "SQL_VALIDATION_AFTER_CURRENCY_REPAIR", {"pass": not viol, "errors": viol})

    if viol and any("not in verified selection" in e for e in viol):
        sql, viol = _recover_missing_tables_and_regenerate(question, sql, ctx, db)
        _log_stage(ctx, "SQL_VALIDATION_AFTER_RECOVERY", {"pass": not viol, "errors": viol})

    if viol:
        sql = sanitize_generated_sql(
            pipeline3_sql_generation(
                question + f" Fix these validation errors using ONLY verified tables {ctx.tables}: {'; '.join(viol[:5])}",
                ctx,
            )
        )
        viol = _validate_sql_against_context(sql, ctx, db)
        if viol and is_currency_validation_error(viol):
            sql, viol = _repair_currency_and_regenerate(question, sql, ctx, db)
        if viol and any("not in verified selection" in e for e in viol):
            sql, viol = _recover_missing_tables_and_regenerate(question, sql, ctx, db)
        _log_stage(ctx, "SQL_VALIDATION_RETRY", {"pass": not viol, "errors": viol})

    if not sql or viol:
        err_kind = "pipeline_error"
        if any("data limitation" in str(v).lower() for v in viol):
            err_kind = "data_limitation"
        return {
            "error": "sql_validation_failed",
            "error_kind": err_kind,
            "detail": viol or ["empty sql"],
            "tables": ctx.tables,
            "missing": [],
            "sql": sql,
            "rows": [],
            "verified_context": ctx.to_dict(),
            "pipeline_log": ctx.pipeline_log,
        }

    if sql_has_unsafe_monetary_fanout(sql):
        return {
            "error": "unsafe_grain",
            "error_kind": "pipeline_error",
            "detail": ["mixed monetary grains"],
            "tables": ctx.tables,
            "sql": sql,
            "rows": [],
            "verified_context": ctx.to_dict(),
            "pipeline_log": ctx.pipeline_log,
        }

    if budget is not None:
        budget.checkpoint("database_execution")

    t_exec = time.perf_counter()
    rows: List[Dict[str, Any]] = []
    exec_error: Optional[str] = None
    for exec_attempt in range(3):
        if budget is not None and not budget.allow_repair(exec_attempt):
            break
        try:
            rows = execute_sql(db, sql, question) or []
            exec_error = None
            break
        except Exception as exc:
            exec_error = str(exc)
            try:
                db.rollback()
            except Exception:
                pass
            err_class = classify_sql_execution_error(exec_error)
            _log_stage(ctx, "SQL_EXECUTION_ERROR", {"attempt": exec_attempt + 1, "class": err_class, "error": exec_error[:500]})
            if err_class == "timeout":
                break
            repaired_plan_sql = _repair_plan_and_rerender(question, ctx, db, err_class, exec_error)
            if repaired_plan_sql and repaired_plan_sql != sql:
                sql = sanitize_generated_sql(repaired_plan_sql, question)
                _log_stage(ctx, "PLAN_REPAIR", {"class": err_class, "sql": sql[:500]})
                continue
            if err_class == "expression_as_column":
                repaired = repair_quoted_expressions_as_columns(sql)
                if repaired != sql:
                    sql = sanitize_generated_sql(repaired)
                    continue
            if err_class == "invalid_date_extract":
                from .adaptive_structured_sql import repair_extract_on_text_dates

                repaired = repair_extract_on_text_dates(sql)
                if repaired != sql:
                    sql = sanitize_generated_sql(repaired)
                    continue
            if err_class == "grouping_error":
                from .adaptive_query_repair import build_measure_ranking_sql, repair_grouping_error_sql
                from .adaptive_structured_sql import build_filter_list_sql

                repaired = repair_grouping_error_sql(
                    sql, question, exec_error, ctx.semantic_requirements
                )
                if repaired and repaired != sql:
                    sql = sanitize_generated_sql(repaired, question)
                    _log_stage(ctx, "SQL_GROUPING_REPAIR", {"method": "remove_or_group_column", "sql": sql[:500]})
                    continue
                rebuilt = build_measure_ranking_sql(question, ctx.tables, ctx.semantic_requirements)
                if not rebuilt:
                    rebuilt = build_filter_list_sql(question, ctx.tables, ctx.semantic_requirements)
                if rebuilt:
                    sql = sanitize_generated_sql(_apply_currency_if_needed(question, rebuilt, ctx, db), question)
                    _log_stage(ctx, "SQL_GROUPING_REPAIR", {"method": "measure_ranking_fallback", "sql": sql[:500]})
                    continue
            if err_class == "alias_mismatch":
                from .adaptive_currency_strategy import repair_table_qualifier_mismatch

                repaired = sql
                for tbl in ctx.tables:
                    repaired = repair_table_qualifier_mismatch(repaired, tbl)
                if repaired != sql:
                    sql = sanitize_generated_sql(repaired, question)
                    _log_stage(ctx, "SQL_ALIAS_REPAIR", {"sql": sql[:500]})
                    continue
                fallback = _execution_fallback_sql(question, ctx)
                if fallback:
                    sql = sanitize_generated_sql(_apply_currency_if_needed(question, fallback, ctx, db), question)
                    _log_stage(ctx, "SQL_EXECUTION_FALLBACK", {"source": "deterministic_template", "sql": sql[:500]})
                    continue
            if err_class in {"undefined_column", "syntax_error", "expression_as_column", "generic_sql_error", "duplicate_alias"}:
                fallback = _execution_fallback_sql(question, ctx)
                if fallback and exec_attempt == 0:
                    sql = sanitize_generated_sql(_apply_currency_if_needed(question, fallback, ctx, db), question)
                    _log_stage(ctx, "SQL_EXECUTION_FALLBACK", {"source": "deterministic_template", "sql": sql[:500]})
                    continue
                sql = sanitize_generated_sql(
                    pipeline3_sql_generation(
                        question + f"\nPrevious SQL failed ({err_class}): {exec_error[:400]}\n"
                        f"Regenerate using verified tables {ctx.tables}. "
                        "Never quote SQL functions as column names.",
                        ctx,
                    ),
                    question,
                )
                viol = _validate_sql_against_context(sql, ctx, db)
                if viol:
                    break
                continue
            if err_class == "undefined_table":
                sql, viol = _recover_missing_tables_and_regenerate(question, sql, ctx, db)
                if viol:
                    break
                continue
            break

    exec_ms = int((time.perf_counter() - t_exec) * 1000)

    if exec_error:
        err_class = classify_sql_execution_error(exec_error)
        if err_class == "timeout":
            return {
                "error": "timeout",
                "error_kind": "timeout",
                "error_class": "Timeout",
                "detail": ["database statement exceeded remaining investigation budget"],
                "tables": ctx.tables,
                "sql": sql,
                "rows": [],
                "verified_context": ctx.to_dict(),
                "pipeline_log": ctx.pipeline_log,
                "timeout": True,
            }
        fallback = _execution_fallback_sql(question, ctx)
        if fallback:
            try:
                sql = sanitize_generated_sql(_apply_currency_if_needed(question, fallback, ctx, db), question)
                rows = execute_sql(db, sql, question) or []
                exec_error = None
                _log_stage(ctx, "SQL_EXECUTION_FINAL_FALLBACK", {"sql": sql[:500], "row_count": len(rows)})
            except Exception:
                pass
    if exec_error:
        err_class = classify_sql_execution_error(exec_error)
        err_kind = "data_limitation" if err_class == "undefined_table" and not ctx.tables else "pipeline_error"
        return {
            "error": "sql_execution_failed",
            "error_kind": err_kind,
            "detail": [exec_error[:800]],
            "error_class": err_class,
            "tables": ctx.tables,
            "sql": sql,
            "rows": [],
            "verified_context": ctx.to_dict(),
            "pipeline_log": ctx.pipeline_log,
        }

    _log_stage(ctx, "SQL_EXECUTION", {"row_count": len(rows), "exec_ms": exec_ms})

    from .adaptive_query_repair import validate_monetary_result
    from .investigation_budget import user_safe_pipeline_message

    result_warnings = validate_monetary_result(rows, question)
    plan_warnings = result_matches_analytical_intent(
        rows, question, ctx.semantic_requirements, sql=sql
    )
    semantic_attempt = 0
    while plan_warnings and semantic_attempt < 2:
        if budget is not None and not budget.allow_repair(semantic_attempt):
            break
        semantic_attempt += 1
        _log_stage(
            ctx,
            "RESULT_VALIDATION",
            {"attempt": semantic_attempt, "warnings": plan_warnings},
        )
        if budget is not None:
            budget.record_sql_attempt(
                attempt_number=semantic_attempt,
                failure_type="semantic_mismatch",
                diagnosis="; ".join(plan_warnings),
                sql=sql,
                changed_plan=True,
            )
            budget.repairs.append({"type": "semantic_mismatch", "warnings": plan_warnings})
        # Repair must change the plan when comparison/partition/negation/date is missing
        from .semantic_requirements import required_semantics
        from .adaptive_structured_sql import (
            StructuredQueryPlan,
            build_above_average_sql,
            build_dimension_ranking_sql,
            build_document_count_by_period_sql,
            build_multi_entity_having_sql,
            build_negation_anti_join_sql,
            build_partitioned_topn_sql,
            build_period_compare_sql,
            build_filter_list_sql,
            detect_filter_list_intent,
        )

        req = required_semantics(question, ctx.semantic_requirements)
        if ctx.query_plan:
            plan_obj = StructuredQueryPlan.from_dict(
                {**ctx.query_plan, "semantic_requirements": ctx.semantic_requirements}
            )
            _enrich_plan_for_missing_semantics(plan_obj, req, question, ctx)
            ctx.query_plan = plan_obj.to_dict()
        _ensure_measure_source_tables(ctx)
        pipeline2_column_selection(question, ctx)
        pipeline25_query_plan(question, ctx, db)
        retry_sql = pipeline3_sql_generation(question, ctx)

        # Targeted recovery for classic missing-dimension / partition failures
        warn_blob = " ".join(plan_warnings).lower()
        if any(tok in warn_blob for tok in ("dimension country", "ungrouped total", "country missing", "vendor")):
            rebuilt = build_dimension_ranking_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if "partition" in warn_blob or (req.get("partition_by") and "partition" in warn_blob):
            rebuilt = build_partitioned_topn_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if "period comparison" in warn_blob or "multi-period" in warn_blob or "decrease" in warn_blob:
            rebuilt = build_period_compare_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if "negation" in warn_blob or "anti" in warn_blob:
            rebuilt = build_negation_anti_join_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if "average" in warn_blob:
            rebuilt = build_above_average_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if "distinct" in warn_blob or ("country" in warn_blob and "having" in warn_blob):
            rebuilt = build_multi_entity_having_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if req.get("having_distinct"):
            rebuilt = build_multi_entity_having_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        if req.get("comparison") or detect_filter_list_intent(question, ctx.semantic_requirements):
            rebuilt = build_filter_list_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt
        elif "year" in warn_blob or "month" in warn_blob or "yearly grouping" in warn_blob:
            rebuilt = build_document_count_by_period_sql(question, ctx.tables, ctx.semantic_requirements)
            if rebuilt:
                retry_sql = rebuilt

        retry_sql = sanitize_generated_sql(_apply_currency_if_needed(question, retry_sql, ctx, db), question)
        if not retry_sql or retry_sql == sql:
            break
        viol_retry = _validate_sql_against_context(retry_sql, ctx, db)
        if viol_retry:
            break
        try:
            retry_rows = execute_sql(db, retry_sql, question) or []
            retry_warn = result_matches_analytical_intent(
                retry_rows, question, ctx.semantic_requirements, sql=retry_sql
            )
            sql, rows = retry_sql, retry_rows
            plan_warnings = retry_warn
            _log_stage(ctx, "RESULT_PLAN_REPAIR", {"sql": sql[:400], "row_count": len(rows), "remaining_warnings": retry_warn})
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            break

    if result_warnings:
        ctx.pipeline_log["result_warnings"] = result_warnings
    if plan_warnings:
        ctx.pipeline_log["result_plan_warnings"] = plan_warnings
        _log_stage(ctx, "RESULT_VALIDATION_FAILED", {"warnings": plan_warnings})
        return {
            "error": "semantic_mismatch",
            "error_kind": "pipeline_error",
            "error_class": "RESULT_VALIDATION_FAILED",
            "failure_class": "RESULT_VALIDATION_FAILED",
            "detail": plan_warnings,
            "tables": ctx.tables,
            "sql": sql,
            "rows": [],
            "verified_context": ctx.to_dict(),
            "pipeline_log": ctx.pipeline_log,
            "user_message": user_safe_pipeline_message("semantic_mismatch"),
        }

    # Adaptive investigation: confirm period direction, then try schema-supported driver grains.
    try:
        from .adaptive_analyst.investigation import (
            MAX_INVESTIGATION_QUERIES,
            evaluate_direction_gate,
            evidence_based_summary,
            is_investigation_request,
            plan_investigation_steps,
            result_has_driver_grain,
            sufficiency_for_investigation,
        )
        from .adaptive_structured_sql import build_period_compare_sql as _build_pc

        if is_investigation_request(question, ctx.semantic_requirements):
            steps = plan_investigation_steps(
                question, ctx.semantic_requirements, tables=ctx.tables
            )
            confirm_meta: Dict[str, Any] = {}
            inv_queries = 0
            gate = next((s for s in steps if s.get("kind") == "confirm_direction"), None)
            if gate and budget is not None and not budget.allow_repair(0):
                gate = None
            if gate:
                confirm_sql = _build_pc(
                    question, ctx.tables, ctx.semantic_requirements, aggregate_only=True
                )
                if confirm_sql:
                    try:
                        confirm_rows = execute_sql(db, confirm_sql, question) or []
                        inv_queries += 1
                        verdict, evidence = evaluate_direction_gate(
                            confirm_rows,
                            expected_direction=str(gate.get("expected_direction") or "decline"),
                        )
                        confirm_meta = {"verdict": verdict, **evidence, "sql": confirm_sql[:400]}
                        ctx.pipeline_log["investigation_confirm"] = confirm_meta
                        _log_stage(ctx, "INVESTIGATION_CONFIRM", confirm_meta)
                        if verdict in {"opposite", "no_change"}:
                            rows = confirm_rows
                            sql = confirm_sql
                            ctx.pipeline_log["investigation_answer_mode"] = "direction_only"
                        elif verdict == "proceed":
                            driver_steps = [s for s in steps if s.get("kind") == "drivers"]
                            best: Optional[Tuple[str, str, List[Dict[str, Any]]]] = None
                            if result_has_driver_grain(rows):
                                best = ("prior", sql, rows)
                            for dstep in driver_steps:
                                if inv_queries >= MAX_INVESTIGATION_QUERIES:
                                    break
                                if budget is not None and not budget.allow_repair(inv_queries):
                                    break
                                grain = (dstep.get("group_by") or ["customer"])[0]
                                # Mutate semantic group_by for this grain attempt.
                                sem = dict(ctx.semantic_requirements or {})
                                sem["group_by"] = [grain]
                                sem["dimensions"] = [grain]
                                if isinstance(sem.get("period_compare"), dict):
                                    sem["period_compare"] = {
                                        **sem["period_compare"],
                                        "contribution": True,
                                    }
                                driver_sql = _build_pc(
                                    question,
                                    ctx.tables,
                                    sem,
                                    aggregate_only=False,
                                    force_dims=[grain],
                                )
                                if not driver_sql:
                                    continue
                                try:
                                    driver_rows = execute_sql(db, driver_sql, question) or []
                                    inv_queries += 1
                                    _log_stage(
                                        ctx,
                                        "INVESTIGATION_DRIVERS",
                                        {
                                            "grain": grain,
                                            "row_count": len(driver_rows),
                                            "sql": driver_sql[:400],
                                        },
                                    )
                                    if driver_rows and result_has_driver_grain(driver_rows):
                                        best = (grain, driver_sql, driver_rows)
                                        # Prefer first grain with clear contribution_pct.
                                        if any(
                                            r.get("contribution_pct") is not None for r in driver_rows[:3]
                                        ):
                                            break
                                except Exception:
                                    try:
                                        db.rollback()
                                    except Exception:
                                        pass
                            if best:
                                grain, sql, rows = best
                                ctx.pipeline_log["investigation_answer_mode"] = "drivers"
                                ctx.pipeline_log["investigation_grain"] = grain
                                ctx.pipeline_log["investigation_queries"] = inv_queries
                    except Exception as inv_exc:
                        ctx.pipeline_log["investigation_confirm_error"] = str(inv_exc)[:300]
                        try:
                            db.rollback()
                        except Exception:
                            pass
            suff = sufficiency_for_investigation(
                question,
                rows,
                semantic=ctx.semantic_requirements,
                confirm_evidence=confirm_meta or None,
            )
            ctx.pipeline_log["investigation_sufficiency"] = suff
            if confirm_meta or result_has_driver_grain(rows):
                ctx.pipeline_log["investigation_evidence_summary"] = evidence_based_summary(
                    confirm=confirm_meta or None,
                    driver_rows=rows if result_has_driver_grain(rows) else [],
                    grain=str(ctx.pipeline_log.get("investigation_grain") or "customer"),
                )
    except Exception as inv_outer:
        ctx.pipeline_log["investigation_error"] = str(inv_outer)[:300]

    narrative = pipeline4_result_analysis(question, sql, rows, ctx, exec_ms=exec_ms)
    if ctx.pipeline_log.get("investigation_evidence_summary") and isinstance(narrative, dict):
        evid = str(ctx.pipeline_log["investigation_evidence_summary"])
        if evid:
            narrative["summary"] = evid
            narrative["answer"] = evid
            findings = narrative.get("findings") if isinstance(narrative.get("findings"), list) else []
            findings = [evid] + [f for f in findings if f != evid]
            narrative["findings"] = findings[:8]
    if ctx.pipeline_log.get("investigation_answer_mode") == "direction_only":
        conf = ctx.pipeline_log.get("investigation_confirm") or {}
        verdict = conf.get("verdict")
        change = conf.get("change")
        if isinstance(narrative, dict):
            if verdict == "opposite":
                narrative["summary"] = (
                    f"Revenue did not decrease over the compared periods "
                    f"(change={change}). Driver contribution analysis was not applicable."
                )
                narrative["answer"] = narrative["summary"]
            elif verdict == "no_change":
                narrative["summary"] = (
                    f"Revenue was essentially unchanged over the compared periods "
                    f"(change={change}). There is no decline to attribute to drivers."
                )
                narrative["answer"] = narrative["summary"]
    if ctx.pipeline_log.get("currency_note"):
        note = str(ctx.pipeline_log["currency_note"])
        if isinstance(narrative, dict):
            narrative.setdefault("calculation_explanation", "")
            narrative["calculation_explanation"] = (
                (narrative.get("calculation_explanation") or "") + " " + note
            ).strip()
    total_ms = int((time.perf_counter() - t0) * 1000)
    ctx.pipeline_log["total_ms"] = total_ms
    _log_stage(ctx, "FINAL_ANSWER", {"row_count": len(rows), "total_ms": total_ms})

    return {
        "sql": sql,
        "rows": rows,
        "tables": ctx.tables,
        "verified_context": ctx.to_dict(),
        "pipeline_log": ctx.pipeline_log,
        "narrative": narrative,
        "pick": {"tables": ctx.tables, "columns": ctx.columns, "joins": ctx.joins},
    }


def _repair_plan_and_rerender(
    question: str,
    ctx: VerifiedDbContext,
    db: Session,
    err_class: str,
    exec_error: str,
) -> Optional[str]:
    """Modify the structured plan from a classified error, then re-render SQL."""
    if not ctx.query_plan:
        return None
    from .adaptive_query_repair import prune_plan_for_aggregation
    from .adaptive_structured_sql import StructuredQueryPlan
    from .adaptive_query_repair import extract_grouping_error_column, column_required_for_question

    plan = StructuredQueryPlan.from_dict({**ctx.query_plan, "semantic_requirements": ctx.semantic_requirements})
    changed = False
    if err_class == "grouping_error":
        parsed = extract_grouping_error_column(exec_error)
        if parsed:
            tbl, col = parsed
            required = column_required_for_question(tbl, col, question, ctx.semantic_requirements)
            if required:
                from .adaptive_structured_sql import PlanField

                plan.group_by.append(PlanField(type="column", table=tbl, column=col, purpose="group"))
                changed = True
            else:
                plan.select = [
                    pf for pf in plan.select
                    if not (
                        pf.type == "column"
                        and (pf.table or "").upper() == tbl.upper()
                        and pf.column.lower() == col.lower()
                    )
                ]
                changed = True
        prune_plan_for_aggregation(plan)
        changed = True
    elif err_class in {"undefined_column", "expression_as_column"}:
        prune_plan_for_aggregation(plan)
        changed = True
    if not changed:
        return None
    ctx.query_plan = plan.to_dict()
    rendered = render_sql_from_plan(plan)
    if rendered:
        return _apply_currency_if_needed(question, sanitize_generated_sql(rendered, question), ctx, db)
    return None
