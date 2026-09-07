from __future__ import annotations

from app.services.ai_native_pipeline import (
    catalog_guide_text,
    extract_sql,
    parse_json_object,
    _safe_select,
)


def test_parse_json_object_from_fence():
    raw = 'Here\n```json\n{"kind": "data_question", "needs_sql": true}\n```\n'
    assert parse_json_object(raw)["kind"] == "data_question"


def test_extract_sql_from_fence():
    raw = "```sql\nSELECT COUNT(*) AS n FROM \"VBAK\"\n```"
    assert "VBAK" in extract_sql(raw)


def test_safe_select_rejects_write():
    assert _safe_select("DELETE FROM VBAK") is None
    assert _safe_select('SELECT 1 FROM "VBAK"') is not None


def test_catalog_guide_is_guide_not_empty():
    text = catalog_guide_text()
    assert "VBAK" in text
    assert "VBAP" in text
    assert "guide only" in text.lower() or "GUIDE" in text or "guide" in text
    assert "VBED is NOT" in text
