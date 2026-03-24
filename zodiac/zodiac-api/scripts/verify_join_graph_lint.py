"""
Regression checks for join graph linting in SQL precision validator.
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lightweight stubs for environments without SQLAlchemy installed.
if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_stub.Session = object  # type: ignore
    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_stub

from app.services.sap_sql_precision_validator import validate_sql_precision  # noqa: E402


def main() -> int:
    schema = {
        "VBRP": ["vbeln", "netwr", "matnr", "posnr"],
        "VBRK": ["vbeln", "fkdat", "waerk", "kunag"],
        "KNA1": ["kunnr", "name1", "brsch"],
        "MAKT": ["matnr", "maktx", "spras"],
    }

    good_sql = """
    SELECT k."name1" AS customer_name, SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue
    FROM vbrp v
    JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    LEFT JOIN KNA1 k ON r."kunag" = k."kunnr"
    WHERE SUBSTRING(TRIM(r."fkdat"),1,4) = '1999'
    GROUP BY k."name1"
    """
    vr_good = validate_sql_precision(good_sql, schema, question="revenue by customer in 1999")
    assert vr_good.is_valid, vr_good.errors

    bad_edge_sql = """
    SELECT SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue
    FROM vbrp v
    JOIN MAKT m ON v."vbeln" = m."matnr"
    """
    vr_bad_edge = validate_sql_precision(bad_edge_sql, schema, question="revenue by product")
    assert not vr_bad_edge.is_valid
    assert any(("not in the approved join graph" in e) or ("do not match configured SAP join rules" in e) for e in vr_bad_edge.errors), vr_bad_edge.errors

    disconnected_sql = """
    SELECT *
    FROM vbrp v
    JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    JOIN MAKT m ON v."matnr" = m."matnr"
    JOIN KNA1 k ON k."kunnr" = k."kunnr"
    """
    vr_disconnected = validate_sql_precision(disconnected_sql, schema, question="show data")
    assert not vr_disconnected.is_valid
    assert any("not fully connected" in e for e in vr_disconnected.errors), vr_disconnected.errors

    print("OK: join graph lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

