from app.api.adaptive_query import _auto_charts


def test_billing_chart_does_not_plot_client_or_document_count_as_money():
    rows = [{"sap_client": "800", "billing_document": str(i), "currency": "DEM",
             "net_sales": -i, "total_matching_documents": 13} for i in range(1, 4)]
    charts = _auto_charts("Negative billed sales", "", rows)
    assert charts
    for chart in charts:
        assert chart.get("y_keys", [chart.get("value_key")]) == ["net_sales"]
    assert rows[0]["total_matching_documents"] == 13


def test_same_currency_sales_in_different_clients_remain_separate_charts():
    rows = [{"sap_client": client, "currency": "USD", "product": product, "sales": amount}
            for client, product, amount in [("100", "A", 3), ("100", "B", 4), ("800", "A", 5), ("800", "B", 6)]]
    charts = _auto_charts("Sales by product", "", rows)
    assert {chart["sap_client"] for chart in charts} == {"100", "800"}
    for chart in charts:
        assert {row["sap_client"] for row in chart["data"]} == {chart["sap_client"]}
        assert "Client " + chart["sap_client"] in chart["title"]


def test_actual_billed_net_alias_excludes_diagnostic_count_and_quantity():
    rows = [{'billing_document': str(i), 'billed_net': -5+i, 'item_net': -2+i,
             'billed_quantity': 3, 'result_rows': 50} for i in range(3)]
    for chart in _auto_charts('Lowest billing values', '', rows):
        assert set(chart['y_keys']) == {'billed_net', 'item_net'}


def test_different_or_missing_source_currencies_use_verified_table():
    rows = [{'billing_document':'B1','billing_currency':'USD','order_currency':'EUR',
             'billing_net_value':4,'order_net_value':6}]
    assert _auto_charts('Compare documents', '', rows) == []
    rows[0]['order_currency'] = None
    assert _auto_charts('Compare documents', '', rows) == []
