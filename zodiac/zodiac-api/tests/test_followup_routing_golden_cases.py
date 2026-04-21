from app.services.ai_followup_routing import follow_up_requires_fresh_sql


def test_followup_routes_product_breakdown_to_fresh_sql() -> None:
    q = "I got data and now breakdown on product level for the same invoices"
    assert follow_up_requires_fresh_sql(q)


def test_followup_routes_line_item_drilldown_to_fresh_sql() -> None:
    q = "Please show line items and material details by MATNR"
    assert follow_up_requires_fresh_sql(q)


def test_followup_routes_invoice_zero_negative_check_to_fresh_sql() -> None:
    q = "Show zero invoice values and negative invoices using VBRK netwr"
    assert follow_up_requires_fresh_sql(q)


def test_followup_routes_master_join_request_to_fresh_sql() -> None:
    q = "Join VBRP with MARA MAKT MEAN MVKE MARC for deeper analysis"
    assert follow_up_requires_fresh_sql(q)


def test_followup_does_not_force_sql_for_plain_analysis_prompt() -> None:
    q = "Can you summarize what this result means for the business?"
    assert not follow_up_requires_fresh_sql(q)
