"""
Regression: explicit table names in the user question must not be replaced by
generic keyword routing (e.g. "last 5 rows" must not yield unrelated SAP SQL
such as LFA1 when the user asked for ai_analysis_memory).
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.inspect = lambda *a, **k: None  # type: ignore
    sqlalchemy_stub.text = lambda s: s  # type: ignore
    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_stub.Session = object  # type: ignore
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_stub

from app.services.explicit_table_sql import (
    extract_explicit_table_identifiers,
    resolve_tables_for_explicit_intent,
    stored_sql_covers_explicit_tables,
)


def main() -> int:
    q = "List the last 5 rows from ai_analysis_memory for my user"
    ids = extract_explicit_table_identifiers(q)
    assert "ai_analysis_memory" in [x.lower() for x in ids], f"expected ai_analysis_memory in {ids}"

    app, sap, unk = resolve_tables_for_explicit_intent(ids, {"VBRK", "LFA1", "VBRP"})
    assert app and "ai_analysis_memory" in [a.lower() for a in app], app
    assert not sap, "app-only question should not resolve to SAP tables"
    assert not unk

    bad_lfa1_sql = 'SELECT "LFA1".name1 FROM "LFA1" LIMIT 5'
    assert not stored_sql_covers_explicit_tables(bad_lfa1_sql, ["ai_analysis_memory"])

    good_sql = 'SELECT * FROM ai_analysis_memory WHERE user_id = 1 ORDER BY updated_at DESC LIMIT 5'
    assert stored_sql_covers_explicit_tables(good_sql, ["ai_analysis_memory"])

    # Explicit SAP table names
    q2 = 'Show rows from "VBRK" last 10'
    ids2 = extract_explicit_table_identifiers(q2)
    assert any(t.upper() == "VBRK" for t in ids2), ids2

    print("OK: explicit table precedence guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
