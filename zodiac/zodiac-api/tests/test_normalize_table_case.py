"""_normalize_table_case must not alter already double-quoted SAP identifiers."""

from __future__ import annotations

from app.services.langgraph_orchestrator import _normalize_table_case


def test_normalize_table_case_preserves_quoted_vbrk_kna1():
    schema = {"VBRK": ["vbeln"], "KNA1": ["kunnr"]}
    sql = 'SELECT * FROM "VBRK" INNER JOIN "KNA1" ON "KNA1".kunnr = "VBRK".kunnr'
    out = _normalize_table_case(sql, schema)
    assert out == sql
    assert out.count('"VBRK"') == sql.count('"VBRK"')
    assert out.count('"KNA1"') == sql.count('"KNA1"')


def test_normalize_table_case_quotes_unquoted_uppercase():
    schema = {"VBRK": ["vbeln"]}
    sql = "SELECT * FROM VBRK WHERE vbeln = '1'"
    out = _normalize_table_case(sql, schema)
    assert '"VBRK"' in out
    assert " FROM VBRK" not in out
