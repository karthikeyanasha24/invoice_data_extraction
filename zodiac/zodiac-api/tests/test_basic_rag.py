"""Free RAG must preserve identity, filters, source, and live execution."""
import pytest
from sqlalchemy import create_engine

from app.services import basic_rag as rag
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope

SQL = 'SELECT SUM(netwr) AS total_sales FROM "VBRK"'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("BASIC_EMBED_MODEL", raising=False)
    monkeypatch.setattr("app.services.basic_local_provider.ollama_post",
                        lambda *_a, **_k: pytest.fail("Unexpected model request"))
    rag._embeddings.cache_clear()


def test_paraphrased_revenue_reuses_query_but_never_cached_numbers():
    examples = [{"question": "total billed sales in 2001", "sql": SQL}]
    assert rag.recall_sql("Please show overall revenue during 2001", examples) == SQL
    assert rag.recall_sql("total revenue in 2002", examples) == ""


@pytest.mark.parametrize("saved,new", [
    ("sales for Acme", "sales for Beta"),
    ("sales for France", "sales for Germany"),
    ("sales USD", "sales EUR"),
    ("top 5 customers by sales", "top 10 customers by sales"),
    ("top 5 customers by sales", "bottom 5 customers by sales"),
    ("sales above -100.50", "sales above 100.50"),
    ("sales by month", "sales by quarter"),
    ("sales for client 800", "sales for customer 800"),
    ("sales for France excluding Germany", "sales for Germany excluding France"),
    ("sales for 'AcMe'", "sales for 'ACME'"),
    ("total sales", "average sales"),
    ("count invoices", "list invoices"),
    ("sales for customer Acme and material Widget", "sales for customer Widget and material Acme"),
])
def test_similar_questions_with_different_scope_never_reuse(saved, new):
    assert rag.recall_sql(new, [{"question": saved, "sql": SQL}]) == ""


def test_memory_is_bound_to_user_permissions_source_and_dataset(monkeypatch):
    engine = create_engine("sqlite://")
    owner = TrustedAiExecutionScope(user_id=1, sap_access="full")
    assert rag.save_verified_query(engine, owner, "business", "total revenue", SQL)
    assert rag.load_verified_queries(engine, owner, "business")[0]["sql"] == SQL
    assert not rag.load_verified_queries(engine, TrustedAiExecutionScope(user_id=2, sap_access="full"), "business")
    assert not rag.load_verified_queries(engine, TrustedAiExecutionScope(user_id=1, sap_access="none"), "business")
    assert not rag.load_verified_queries(engine, owner, "application")
    monkeypatch.setenv("AI_ANALYST_DATASET_VERSION", "next-extract")
    assert not rag.load_verified_queries(engine, owner, "business")


def test_memory_upsert_and_readonly_ctes():
    engine = create_engine("sqlite://")
    owner = TrustedAiExecutionScope(user_id=1, sap_access="full")
    sql = 'WITH totals AS (SELECT SUM(netwr) FROM "VBRK") SELECT * FROM totals'
    assert rag.save_verified_query(engine, owner, "business", "revenue", sql)
    assert rag.save_verified_query(engine, owner, "business", "revenue", sql)
    assert len(rag.load_verified_queries(engine, owner, "business")) == 1
    for bad in ['DELETE FROM "VBRK"', 'SELECT 1; SELECT 2', 'SELECT * INTO x FROM "VBRK"',
                'WITH removed AS (DELETE FROM "VBRK" RETURNING *) SELECT * FROM removed']:
        assert not rag.save_verified_query(engine, owner, "business", "revenue", bad)


def test_semantic_embeddings_are_batched_cached_and_cannot_authorize_reuse(monkeypatch):
    monkeypatch.setenv("BASIC_EMBED_MODEL", "embeddinggemma")
    calls = []
    def embed(endpoint, payload, timeout):
        calls.append(payload)
        assert endpoint == "/api/embed"
        return {"embeddings": [[1.0, 0.0] for _ in payload["input"]]}
    monkeypatch.setattr("app.services.basic_local_provider.ollama_post", embed)
    examples = [{"question": "revenue in 2001", "sql": SQL}]
    first = rag.retrieve_examples("turnover in 2002", examples)
    assert first[0]["retrieval"] == "ollama_embedding"
    assert first[0]["similarity"] == 1.0 and first[0]["reusable"] is False
    assert rag.retrieve_examples("turnover in 2002", examples) == first
    assert len(calls) == 1 and len(calls[0]["input"]) == 2
    assert rag.recall_sql("turnover in 2002", examples) == ""


def test_exact_reuse_and_templates_do_not_spend_embedding_calls(monkeypatch):
    monkeypatch.setenv("BASIC_EMBED_MODEL", "embeddinggemma")
    assert rag.recall_sql("turnover in 2001", [{"question": "sales in 2001", "sql": SQL}]) == SQL


def test_missing_embedding_runtime_falls_back_to_offline_retrieval(monkeypatch):
    monkeypatch.setenv("BASIC_EMBED_MODEL", "missing")
    monkeypatch.setattr("app.services.basic_local_provider.ollama_post", lambda *_: (_ for _ in ()).throw(ConnectionError()))
    examples = rag.retrieve_examples("revenue in 2002", [{"question": "revenue in 2001", "sql": SQL}])
    assert examples[0]["retrieval"] == "bm25" and examples[0]["reusable"] is False
