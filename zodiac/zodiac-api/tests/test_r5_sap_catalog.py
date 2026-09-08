"""R5 SAP data catalog, source selection, and sales-order vs billing routing."""
from __future__ import annotations

from app.data_catalog.knowledge import local_resolve, verify_proposed_column
from app.data_catalog.physical import has_column, has_table, sap_business_tables
from app.data_catalog.registry import (
    METRICS,
    RELATIONSHIPS,
    domain_for_table,
    get_metric,
    get_table_entry,
    tables_for_domain,
)
from app.data_catalog.source_selector import select_source
from app.services.adaptive_nl_sql_hardening import (
    clarification_payload,
    is_supported_business_question,
)
from app.services.ranking_question_normalizer import normalize_ranking_question
from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout


CLIENT_Q = "Can you show me which customer and country and industry the highest sales reflected?"


def test_physical_inventory_sales_tables():
    names = {t.upper() for t in sap_business_tables()}
    assert "VBAK" in names
    assert "VBAP" in names
    assert "VBEP" in names
    assert "VBED" not in names
    assert "VBRK" in names
    assert has_table("VBAK") and has_column("VBAK", "vbeln") and has_column("VBAK", "kunnr")
    assert has_column("VBAP", "matnr") and has_column("VBAP", "netwr")
    assert has_column("VBEP", "edatu")
    assert not has_table("VBED")


def test_domains_separated():
    assert domain_for_table("VBAK") == "sales"
    assert domain_for_table("VBAP") == "sales"
    assert domain_for_table("VBRK") == "invoice"
    assert domain_for_table("EKKO") == "purchasing"
    assert domain_for_table("AFKO") == "production"
    assert domain_for_table("KNA1") == "customer"
    assert domain_for_table("MARA") == "product"
    assert domain_for_table("LFA1") == "vendor"
    assert domain_for_table("BKPF") == "finance"
    sales = {t.upper() for t in tables_for_domain("sales")}
    invoices = {t.upper() for t in tables_for_domain("invoice")}
    assert "VBAK" in sales
    assert "VBRK" in invoices
    assert "VBAK" not in invoices


def test_metrics_do_not_alias_orders_to_billing():
    so = get_metric("sales_order_count")
    br = get_metric("billing_revenue")
    assert so["authoritative_tables"] == ["VBAK"]
    assert "vbrp" in br["authoritative_tables"] or "VBRK" in br["authoritative_tables"]
    assert "VBRP.NETWR" in so["substitutes_forbidden"] or "billing" in str(so["substitutes_forbidden"]).lower()
    assert "sales_order_value" in METRICS
    assert any(r["source_table"] == "VBAK" and r["target_table"] == "VBAP" for r in RELATIONSHIPS)


def test_client_question_is_not_too_short():
    ok, reason = is_supported_business_question(CLIENT_Q)
    assert ok is True
    assert reason != "too_short"
    rewritten = normalize_ranking_question(CLIENT_Q)
    assert rewritten == "top customers by sales with countries and industries"
    spec = select_source(rewritten)
    assert spec.route == "existing"
    assert spec.needs_clarification is False


def test_highest_sales_bare_is_clarification_not_rejection():
    ok, reason = is_supported_business_question("Highest sales?")
    assert ok is True, reason
    spec = select_source("Highest sales?")
    assert spec.needs_clarification is True
    payload = clarification_payload("Highest sales?", spec.reason)
    assert payload["answer_status"] == "CLARIFICATION"
    assert "rephrase as a business question" not in payload["summary"].lower()
    assert "customer" in payload["summary"].lower() or "dimension" in payload["summary"].lower()


def test_source_selector_sales_vs_invoice_vs_purchasing():
    assert select_source("How many sales orders are there?").route == "sales_order"
    assert select_source("How many sales orders are there?").metric == "sales_order_count"
    assert "VBAK" in select_source("Show me sales from VBAK").tables
    assert select_source("Show me information from VBAP").named_table == "VBAP"
    assert select_source("Show scheduling information from VBED").reason == "table_absent"
    assert select_source("Show invoices").domain == "invoice"
    assert select_source("Show invoices").route == "existing"
    assert select_source("Show purchasing data").domain == "purchasing"
    assert select_source("Show production data").domain == "production"
    assert select_source("Show customer information").domain == "customer"
    assert select_source("Show product information").domain == "product"
    spec = select_source("Show me our sales data.")
    assert spec.needs_clarification is True
    assert "sales-order" in spec.clarification_message.lower() or "vbak" in spec.clarification_message.lower()
    ranked = select_source("Who had the highest sales in 2004?")
    assert ranked.needs_clarification is False
    assert ranked.reason != "ambiguous_sales_vs_billing"
    canon = select_source("top customers by sales in 2004")
    assert canon.needs_clarification is False
    assert canon.domain == "invoice"


def test_followup_sales_does_not_steal_r3_context():
    spec = select_source("Sales", prior_plan={"analytical_context": {"deep_analysis": True, "intent": "product_profitability"}})
    assert spec.route == "existing"
    assert spec.needs_clarification is False


def test_knowledge_vbak_exists_vbed_absent():
    vbak = local_resolve("VBAK")
    assert vbak["exists"] is True
    assert vbak["verified"] is True
    vbed = local_resolve("VBED")
    assert vbed["exists"] is False
    assert verify_proposed_column("VBAK", "netwr") is True
    assert verify_proposed_column("VBAK", "not_a_real_column") is False
    assert verify_proposed_column("VBED", "vbeln") is False


def test_capability_message_is_not_billing_only():
    payload = clarification_payload("zzzz not a question xyz", "no_business_signal")
    text = payload["summary"].lower()
    assert "billing, customers, industries" not in text or "sales orders" in text
    assert "please rephrase as a business question" not in text


def test_fanout_guard_rejects_sales_plus_billing_netwr():
    bad = 'SELECT SUM(p."netwr") FROM "VBAP" p JOIN "vbrp" b ON p."matnr" = b."matnr"'
    assert sql_has_unsafe_monetary_fanout(bad) is True
    good = 'SELECT SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) FROM "VBAP" p JOIN "VBAK" v ON p."vbeln" = v."vbeln"'
    assert sql_has_unsafe_monetary_fanout(good) is False


def test_sales_order_sql_compiler_uses_vbak_not_vbrk():
    from app.data_catalog.source_selector import select_source
    from app.services.sales_order_analysis import try_sales_order_analysis

    captured = {}

    def fake_exec(_db, sql, question=""):
        captured["sql"] = sql
        return [{"order_count": 12}]

    spec = select_source("How many sales orders are there?")
    out = try_sales_order_analysis("How many sales orders are there?", spec, None, fake_exec)
    assert out is not None
    assert "VBAK" in out["sql"]
    assert "VBRK" not in out["sql"].upper().replace("VBAK", "")
    assert "vbrp" not in out["sql"].lower()
    assert out["query_plan"]["domain"] == "sales"
    assert out["column_semantics"]["order_count"]["semantic_type"] == "integer"


def test_customer_country_industry_plan_uses_kna1_when_sales_orders():
    from app.services.sales_order_analysis import try_sales_order_analysis

    captured = {}

    def fake_exec(_db, sql, question=""):
        captured["sql"] = sql
        return [{"customer": "0001", "customer_name": "Acme", "country": "DE", "industry": "Trading", "order_value": 10}]

    spec = select_source("Show sales orders by customer and country and industry")
    assert spec.route == "sales_order"
    out = try_sales_order_analysis("Show sales orders by customer and country and industry", spec, None, fake_exec)
    assert out is not None
    sql = captured["sql"].upper()
    assert "KNA1" in sql
    assert "LAND1" in sql
    assert "BRSCH" in sql
    assert "VBAP" in sql
    assert "VBAK" in sql
    assert out["charts"]
