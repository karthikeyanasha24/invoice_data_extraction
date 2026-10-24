"""Free RAG must preserve identity, filters, source, and live execution."""
import pytest
from sqlalchemy import create_engine

from app.services import basic_rag as rag
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope

SQL = 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY waerk'


def test_identical_memory_copy_retains_the_checked_training_provenance():
    question = "total billed sales in 2001"
    copied = {"question": question, "sql": SQL, "source": "application"}
    trained = dict(copied, training_example=True, training_example_id="checked", training_revision=3)
    matches = rag.retrieve_examples(question, [copied, trained], use_embeddings=False)
    assert len(matches) == 1
    assert matches[0]["training_example_id"] == "checked"
    assert matches[0]["training_revision"] == 3
    for different in (dict(trained, source="business"), dict(trained, sql=SQL + " LIMIT 1")):
        first = rag.retrieve_examples(question, [copied, different], use_embeddings=False)[0]
        assert not first.get("training_example")
    planned = dict(copied, analysis_plan={"strategy": "identified_values"})
    assert rag.retrieve_examples(question, [planned, trained], use_embeddings=False)[0]["analysis_plan"]


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


def test_singular_plural_business_terms_reuse_the_same_checked_question():
    profit_sql = 'SELECT waerk AS currency, SUM(netwr) - SUM(wavwr) AS profit FROM "VBRP" GROUP BY waerk'
    examples = [{"question": "top products by profits in 2001", "sql": profit_sql}]
    assert rag.recall_sql("top product by profit in 2001", examples) == profit_sql
    assert rag.recall_sql("top product by profit in 2002", examples) == ""


def test_related_examples_do_not_repeat_the_same_sql_for_the_local_model():
    profit_sql = 'SELECT waerk AS currency, SUM(netwr) - SUM(wavwr) AS profit FROM "VBRP" GROUP BY waerk'
    examples = [
        {"question": "profits by product in 2001", "sql": profit_sql},
        {"question": "profits by material in 2002", "sql": profit_sql},
        {"question": "margin by product in 2001", "sql": 'SELECT AVG(margin) FROM "VBRK"'},
    ]
    related = rag.retrieve_examples("profit and margin by product in 2001", examples)
    assert len({example["sql"] for example in related}) == len(related)
    assert all(example["reusable"] is False for example in related)


def test_revenue_or_clearing_sum_cannot_be_replayed_as_profit():
    bad = 'SELECT SUM("BSAD"."dmbtr") AS "total_sales" FROM "BSAD"'
    aliased = 'SELECT SUM("VBRK"."netwr") AS "profit" FROM "VBRK"'
    valid = 'SELECT "VBRP"."waerk" AS "currency", SUM("VBRP"."netwr") - SUM("VBRP"."wavwr") AS "profit" FROM "VBRP" GROUP BY "VBRP"."waerk"'
    question = "show me highest profit"
    assert rag.profit_question_without_profit_sql(question, [{"sql": bad}])
    assert rag.profit_question_without_profit_sql(question, [{"sql": aliased}])
    assert not rag.profit_question_without_profit_sql(question, [{"sql": valid}])
    assert rag.recall_sql(question, [{"question": question, "sql": bad}]) == ""
    assert rag.recall_sql(question, [{"question": question, "sql": valid}]) == valid

    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    assert not rag.save_verified_query(engine, scope, "business", question, bad)
    assert rag.save_verified_query(engine, scope, "business", question, valid)


def test_legacy_billed_total_must_keep_currency_grain():
    legacy = 'SELECT SUM(netwr) AS total_sales FROM "VBRK" WHERE fkdat LIKE \'2001%\''
    grouped = 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY waerk'
    filtered = 'SELECT SUM(netwr) AS total_sales FROM "VBRK" WHERE waerk = \'DEM\''
    multi_currency = 'SELECT SUM(netwr) AS total_sales FROM "VBRK" WHERE waerk IN (\'DEM\', \'USD\')'
    assert rag.mixed_currency_billing_total(legacy)
    assert rag.mixed_currency_billing_total(multi_currency)
    assert not rag.mixed_currency_billing_total(grouped)
    assert not rag.mixed_currency_billing_total(filtered)


def test_unsafe_legacy_total_is_excluded_from_basic_suggestions_and_retrieval():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    legacy = 'SELECT SUM(netwr) AS total_sales FROM "VBRK"'
    grouped = 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY waerk'
    assert rag.save_verified_query(engine, scope, "business", "total billed sales", legacy)
    assert rag.save_verified_query(engine, scope, "business", "billed sales by currency", grouped)
    examples = rag.load_basic_examples(engine, scope, True)
    assert [example["sql"] for example in examples] == [grouped]


def test_saved_business_question_is_loaded_when_basic_uses_application_source():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    question = "Identify the difference in the sales amount for order value and invoice value from the year 2000 and 2001."
    sql = "SELECT 2001 AS year, 10 AS order_value, 8 AS invoice_value"
    assert rag.save_verified_query(engine, scope, "business", question, sql)

    examples = rag.load_basic_examples(engine, scope, use_sap=False)

    assert rag.recall_sql(question, examples) == sql
    assert next(example for example in examples if example["question"] == question)["source"] == "business"


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
