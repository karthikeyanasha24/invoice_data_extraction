"""Basic opens the original aggregate instead of regenerating an invoice query."""
from unittest.mock import MagicMock

import pytest

from app.services.investigation_budget import end_investigation


@pytest.fixture(autouse=True)
def cleanup():
    yield
    end_investigation()


@pytest.mark.parametrize("method", ["basic", "agent"])
def test_document_followup_uses_saved_reference_without_any_model(monkeypatch, method):
    from app.api import adaptive_query as api
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent", lambda *_a, **_k: pytest.fail("No model needed"))
    monkeypatch.setattr("app.services.basic_sql_answer.run_basic_sql_answer", lambda *_a, **_k: pytest.fail("No new SQL needed"))
    artifact = {"rows": [{"year": "2001", "currency": "USD", "billed_sales": "4630639.01"}], "measures": ["billed_sales"]}
    monkeypatch.setattr("app.services.analyst_drilldown.load_artifact", lambda *_: artifact)
    calls = []
    def documents(db, user, identifier, selection):
        calls.append((identifier, selection))
        return {"totalCount": 2, "answer_status": "SUCCESS", "llm_calls": 0,
            "data": [{"billing_document": "B1", "billed_sales": "4630639.02"},
                     {"billing_document": "B2", "billed_sales": "-0.01"}],
            "reconciliation": {"original_total": "4630639.01", "document_total": "4630639.01", "difference": "0.00", "note": "Matched."}}
    monkeypatch.setattr(api, "_result_documents", documents)
    result = api.post_query_adaptive(question="Show related billing docs for 2001 current displayed data",
        db=MagicMock(), current_user=None, tableHint=None, contextData={"previousPlan": {"result_reference": {"id": "saved"}}},
        overrideSql=None, threadId=None, investigationId=None, conversationHistory=None, newQuestion=False, analysisMode=method)
    assert result["pipeline"] == "result_first_drilldown"
    assert result["answer_status"] == "SUCCESS" and result["llm_calls"] == 0
    assert calls == [("saved", {"row_index": 0, "measure": "billed_sales"})]
    assert "4630639.01" in result["answer"]


def test_basic_ambiguous_currency_requires_selection_without_a_model(monkeypatch):
    from app.api import adaptive_query as api
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent", lambda *_a, **_k: pytest.fail("No model needed"))
    monkeypatch.setattr("app.services.analyst_drilldown.load_artifact", lambda *_: {
        "rows": [{"year": "2001", "currency": "USD", "billed_sales": "10"},
                 {"year": "2001", "currency": "EUR", "billed_sales": "20"}], "measures": ["billed_sales"]})
    result = api.post_query_adaptive(question="Show related billing docs for 2001", db=MagicMock(), current_user=None,
        tableHint=None, contextData={"previousPlan": {"result_reference": {"id": "saved"}}}, overrideSql=None,
        threadId=None, investigationId=None, conversationHistory=None, newQuestion=False, analysisMode="basic")
    assert result["answer_status"] == "CLARIFICATION" and result["rowCount"] == 2


def test_saved_result_cannot_answer_a_different_year_or_currency():
    from app.services.analyst_drilldown import select_row
    artifact = {"rows": [{"year": "2001", "currency": "USD", "billed_sales": "10"}], "measures": ["billed_sales"]}
    assert select_row(artifact, "Show related invoices for 2002") == "scope_mismatch"
    assert select_row(artifact, "Show related invoices for 2001 EUR") == "scope_mismatch"


def test_displayed_amount_selects_its_exact_contributors_and_rejects_wrong_values():
    from app.services.analyst_drilldown import select_row
    artifact = {"rows": [{"year": "2001", "currency": "USD", "billed_sales": "4630639.01"},
                         {"year": "2001", "currency": "EUR", "billed_sales": "200"}], "measures": ["billed_sales"]}
    assert select_row(artifact, "Open invoices behind 4,630,639 in 2001") == (0, "billed_sales")
    assert select_row(artifact, "Open invoices behind 4,630,639.01 in 2001") == (0, "billed_sales")
    assert select_row(artifact, "Open invoices behind 4,630,839 in 2001") == "scope_mismatch"
    artifact["rows"].append({"year": "2001", "currency": "DEM", "billed_sales": "4630639.01"})
    assert select_row(artifact, "Open invoices behind 4,630,639 in 2001") == "ambiguous"
