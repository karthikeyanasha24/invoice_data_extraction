"""Gemini can supply terminology to Basic, but never SQL authority."""
import json

from app.services.basic_sap_field_lookup import lookup_sap_field, unresolved_field
from app.services.basic_sql_answer import run_basic_sql_answer
from app.services.investigation_budget import begin_investigation, end_investigation


SCHEMA = {
    "VBRK": [{"col": "kunag", "type": "text"}],
    "KNA1": [{"col": "kunnr", "type": "text"}, {"col": "name1", "type": "text"}],
}


def test_known_customer_fields_do_not_use_gemini(monkeypatch):
    monkeypatch.setenv("BASIC_GEMINI_FIELD_LOOKUP", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    assert unresolved_field("Show KUNAG customer number and customer name") == ""
    known = lookup_sap_field("Show KUNAG customer number and customer name", SCHEMA)
    assert known["called"] is False and known["status"] == "local_glossary"
    assert known["columns"] == [
        {"table": "VBRK", "column": "kunag"}, {"table": "KNA1", "column": "kunnr"},
        {"table": "KNA1", "column": "name1"},
    ]
    assert unresolved_field("Show KUNAG and payer name") == "payer name"


def test_unknown_field_uses_gemini_and_validates_live_columns(monkeypatch):
    monkeypatch.setenv("BASIC_GEMINI_FIELD_LOOKUP", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("BASIC_GEMINI_MODEL", "gemini-2.5-flash-lite")
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            answer = {"meaning": "Customer's sales-region label", "columns": [
                {"table": "KNA1", "column": "NAME1"},
                {"table": "KNA1", "column": "invented_column"},
            ]}
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}],
                    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 9, "totalTokenCount": 21}}

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, url, *, json, headers):
            sent.append((url, json, headers))
            return Response()

    monkeypatch.setattr("app.services.basic_sap_field_lookup.httpx.Client", Client)
    begin_investigation("private customer question")
    try:
        result = lookup_sap_field("Show sales by sales-region name in 2001 for customer 12345", SCHEMA)
        from app.services.analyst_usage import usage_summary
        assert usage_summary()["total_tokens"] == 21
    finally:
        end_investigation()
    assert result["called"] is True and result["status"] == "validated"
    assert result["columns"] == [{"table": "KNA1", "column": "name1"}]
    assert "12345" not in json.dumps(sent)
    assert "2001" not in json.dumps(sent)
    assert "sales-region name" in json.dumps(sent)


def test_snapshot_and_disabled_lookup_do_not_call_gemini(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("BASIC_GEMINI_FIELD_LOOKUP", raising=False)
    assert lookup_sap_field("What is SAP field ZCUST?", SCHEMA)["called"] is False
    monkeypatch.setenv("BASIC_GEMINI_FIELD_LOOKUP", "true")
    assert lookup_sap_field("What is SAP field ZCUST?", SCHEMA, schema_source="schema_snapshot")["called"] is False


def test_basic_calls_lookup_only_after_reuse_and_patterns_fail(monkeypatch):
    monkeypatch.setattr("app.services.four_stage_db_pipeline.pipeline3_sql_generation", lambda *a, **k: "")
    monkeypatch.setattr("app.services.basic_rag.retrieve_examples", lambda *a, **k: [])
    hints = []

    def local_agent(examples, hint):
        hints.append(hint)
        return {"answer_status": "CANNOT_ANSWER", "answer": "No verified data", "summary": "No verified data",
                "llm_calls": 1, "meta": {}}

    result = run_basic_sql_answer("Show sales by sales-region name in 2001",
                                  execute=lambda *_: (_ for _ in ()).throw(AssertionError("no SQL")),
                                  local_agent=local_agent,
                                  field_lookup=lambda q: {"called": True, "status": "validated", "field": "sales-region name",
                                                          "columns": [{"table": "KNA1", "column": "name1"}]})
    assert len(hints) == 1
    assert result["llm_calls"] == 2
    assert result["meta"]["credits_used"] is True
    assert result["meta"]["gemini_field_lookup"]["status"] == "validated"


def test_supported_pattern_never_calls_field_lookup():
    result = run_basic_sql_answer(
        "total billed sales in 2001",
        execute=lambda sql: {"ok": True, "sql": sql, "rows": [{"currency": "DEM", "total_sales": "1"}]},
        local_agent=lambda *_: (_ for _ in ()).throw(AssertionError("model should not run")),
        field_lookup=lambda *_: (_ for _ in ()).throw(AssertionError("Gemini should not run")),
    )
    assert result["llm_calls"] == 0
