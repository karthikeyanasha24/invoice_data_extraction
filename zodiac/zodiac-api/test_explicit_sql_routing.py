"""
Unit checks for explicit table extraction and SQL coverage (no DB, no OpenAI).
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.inspect = lambda *a, **k: None  # type: ignore
    sqlalchemy_stub.text = lambda s: s  # type: ignore
    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_stub.Session = object  # type: ignore
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_stub

from app.services.explicit_table_sql import (  # noqa: E402
    extract_explicit_table_identifiers,
    stored_sql_covers_explicit_tables,
)
from app.services.sql_generation_sanitizers import sanitize_generated_sap_sql  # noqa: E402


def test_extract_ai_analysis_memory():
    q = "last 5 rows from ai_analysis_memory for my user"
    ids = extract_explicit_table_identifiers(q)
    assert "ai_analysis_memory" in [x.lower() for x in ids]


def test_stored_sql_must_reference_explicit_tables():
    assert not stored_sql_covers_explicit_tables(
        'SELECT * FROM "LFA1"', ["ai_analysis_memory"]
    )
    assert stored_sql_covers_explicit_tables(
        "SELECT * FROM ai_analysis_memory WHERE user_id = 3", ["ai_analysis_memory"]
    )


def test_fkdat_auto_inject():
    sql = """
SELECT r."kunag" AS c, SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS t
FROM vbrp v JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
GROUP BY r."kunag"
"""
    out = sanitize_generated_sap_sql(sql, "top customers in 1999")
    assert "SUBSTRING(TRIM(r." in out and "1999" in out


if __name__ == "__main__":
    test_extract_ai_analysis_memory()
    test_stored_sql_must_reference_explicit_tables()
    test_fkdat_auto_inject()
    print("OK: test_explicit_sql_routing")
