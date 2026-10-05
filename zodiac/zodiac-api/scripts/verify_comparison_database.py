"""Read-only PostgreSQL acceptance for the generic comparison compiler.

No model APIs are called. No credentials, plans, or business rows are printed.
This verifies compiler/database compatibility, not end-to-end model planning.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-year", required=True)
    parser.add_argument("--comparison-year", required=True)
    args = parser.parse_args()
    if not all(value.isdigit() and len(value) == 4 for value in (args.base_year, args.comparison_year)):
        parser.error("Years must contain four digits")
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    from app.services.adaptive_structured_sql import (
        PlanField, PlanFilter, StructuredQueryPlan, _apply_period_compare_fields,
        _normalize_plan_expressions, render_sql_from_plan, year_filter_expression,
    )
    from app.services.sql_structure import sql_structure_errors

    load_dotenv(ROOT / ".env", encoding="utf-8-sig")
    base, comparison = args.base_year, args.comparison_year
    semantic = {
        "group_by": ["customer", "currency"], "dimensions": ["customer", "currency"],
        "measure": {"concept": "sales", "aggregation": "none"},
        "period_compare": {"base_period": {"year": base}, "comparison_period": {"year": comparison}},
    }
    plan = StructuredQueryPlan(
        question=f"Compare negative billed sales by customer and currency in {base} versus {comparison}",
        tables=["VBRK"], semantic_requirements=semantic,
        select=[PlanField(type="column", table="VBRK", column=c, purpose="dimension") for c in ("kunag", "waerk")],
        filters=[
            PlanFilter(type="expression", expression=f"{year_filter_expression('VBRK', 'fkdat')} = '{base}'"),
            PlanFilter(type="column", table="VBRK", column="netwr", operator="<", value=0),
        ],
    )
    _normalize_plan_expressions(plan)
    _apply_period_compare_fields(plan, semantic)
    sql = render_sql_from_plan(plan)
    assert not sql_structure_errors(sql)
    url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not url:
        raise RuntimeError("Database connection is not configured")
    engine = create_engine(url.replace("postgresql+asyncpg://", "postgresql://"), connect_args={
        "connect_timeout": 5,
        "options": "-c default_transaction_read_only=on -c statement_timeout=20000",
    })
    report = {"base_year": base, "comparison_year": comparison, "structural_validation": True}
    try:
        with engine.connect() as connection:
            connection.execute(text("EXPLAIN " + sql)).fetchall()
            report["postgresql_compilation"] = True
            rows = connection.execute(text(sql)).mappings().all()
            report["postgresql_execution"] = True
            report["result_row_count"] = len(rows)
            report["comparison_columns_present"] = all(
                {"period_a", "period_b", "change"} <= set(row) for row in rows
            )
            connection.rollback()
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        original = getattr(exc, "orig", exc)
        report["database_error_code"] = getattr(original, "pgcode", None)
        diagnostic = str(original).lower()
        report["failure_category"] = next((category for term, category in (
            ("timeout", "connection_timeout"), ("timed out", "connection_timeout"),
            ("refused", "connection_refused"), ("password authentication", "authentication"),
            ("could not translate host", "hostname_resolution"),
        ) if term in diagnostic), "database_error")
        report["postgresql_execution"] = False
    finally:
        engine.dispose()
    print(json.dumps(report))
    (ROOT / "scripts" / "comparison_database_verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report.get("postgresql_execution") else 1


if __name__ == "__main__":
    raise SystemExit(main())
