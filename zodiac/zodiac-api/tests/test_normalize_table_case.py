"""_normalize_table_case must not alter already double-quoted SAP identifiers."""

from __future__ import annotations

import re

from app.services.langgraph_orchestrator import _finalize_sap_sql, _normalize_table_case


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


def test_finalize_sap_sql_fixes_vbrk_qualifier_when_vbrk_missing_from_schema():
    """
    LLM often emits JOIN "VBRK" ... vbrk.col — PG error if vbrk is not fixed.
    Schema dict may omit VBRK (live introspection); mapping-based pass must fix.
    """
    sql = (
        'SELECT kna1.kunnr, SUM(COALESCE(vbrp.netwr,0)) AS TotalSales FROM vbrp '
        'INNER JOIN "VBRK" ON vbrp.vbeln = vbrk.vbeln '
        'INNER JOIN "KNA1" ON kna1.kunnr = vbrk.kunnr WHERE 1=1'
    )
    out = _finalize_sap_sql(sql, schema={})
    assert not re.search(r'(?<!["\w])vbrk\.', out, re.IGNORECASE)
    assert 'INNER JOIN "VBRK" ON' in out
    assert '"VBRK".vbeln' in out or '"VBRK"."vbeln"' in out
