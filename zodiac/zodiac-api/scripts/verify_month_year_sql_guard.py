"""
Regression checks for month-bucket and year-filter SQL precision guards.
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lightweight stubs for environments without SQLAlchemy installed.
if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.case = lambda *args, **kwargs: None  # type: ignore
    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_stub.Session = object  # type: ignore
    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_stub

from app.services.ai_intent_classifier import classify_intent  # noqa: E402
from app.services.sap_sql_precision_validator import validate_sql_precision  # noqa: E402


def main() -> int:
    schema = {
        "VBRP": ["vbeln", "netwr", "matnr", "posnr"],
        "VBRK": ["vbeln", "fkdat", "waerk", "kunag"],
    }

    # 1) Month intent must be tagged in classifier.
    c = classify_intent("show monthly revenue by customer for 1999")
    assert "time_bucket_month" in c.tags, "Classifier should emit time_bucket_month tag"

    # 2) Year-scoped revenue must include FKDAT year predicate.
    bad_year_sql = """
    SELECT r."kunag" AS customer, SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue
    FROM vbrp v JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    GROUP BY r."kunag"
    """
    vr1 = validate_sql_precision(bad_year_sql, schema, question="revenue by customer in 1999")
    assert not vr1.is_valid and any("FKDAT year predicate" in e for e in vr1.errors), vr1.errors

    good_year_sql = """
    SELECT r."kunag" AS customer, SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue
    FROM vbrp v JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    WHERE SUBSTRING(TRIM(r."fkdat"),1,4) = '1999'
    GROUP BY r."kunag"
    """
    vr2 = validate_sql_precision(good_year_sql, schema, question="revenue by customer in 1999")
    assert vr2.is_valid, vr2.errors

    # 3) Month intent must be grouped by month bucket.
    bad_month_sql = """
    SELECT r."fkdat" AS billing_date, MIN(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS lowest_amount
    FROM vbrp v JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    WHERE SUBSTRING(TRIM(r."fkdat"),1,4) = '1999'
    GROUP BY r."fkdat"
    """
    vr3 = validate_sql_precision(bad_month_sql, schema, question="lowest revenue by month in 1999")
    assert not vr3.is_valid and any("aggregate by month bucket" in e for e in vr3.errors), vr3.errors

    good_month_sql = """
    SELECT SUBSTRING(TRIM(r."fkdat"),1,6) AS year_month,
           MIN(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS lowest_amount
    FROM vbrp v JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    WHERE SUBSTRING(TRIM(r."fkdat"),1,4) = '1999'
    GROUP BY SUBSTRING(TRIM(r."fkdat"),1,6)
    ORDER BY year_month
    """
    vr4 = validate_sql_precision(good_month_sql, schema, question="lowest revenue by month in 1999")
    assert vr4.is_valid, vr4.errors

    print("OK: month/year SQL precision guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

