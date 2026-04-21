from app.api.adaptive_query import _schema_reference_violations, _sql_guardrail_violations


def test_sql_guardrail_flags_invoice_header_logic_when_vbrk_netwr_missing() -> None:
    question = "show zero and negative invoice values"
    sql = """
    SELECT p."vbeln", SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "vbrp" p
    GROUP BY p."vbeln"
    HAVING SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) > 0
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "vbrk.netwr" in joined
    assert "having > 0" in joined


def test_sql_guardrail_flags_irrelevant_industry_table() -> None:
    question = "show invoices by customer"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr"
    LEFT JOIN "T016T" t ON c."brsch" = t."brsch"
    """
    violations = _sql_guardrail_violations(question, sql)
    assert any("t016t" in v.lower() for v in violations)


def test_schema_reference_violations_detect_unknown_table_and_column() -> None:
    sql = """
    SELECT "VBRK"."not_a_real_column"
    FROM "VBRK"
    JOIN "__THIS_TABLE_DOES_NOT_EXIST__" x ON 1=1
    """
    violations = _schema_reference_violations(sql)
    joined = " | ".join(violations).lower()
    assert "unknown column" in joined


def test_schema_reference_violations_accept_valid_vbrk_vbrp_query() -> None:
    sql = """
    SELECT k."vbeln", k."fkdat", k."netwr", p."matnr", p."netwr"
    FROM "VBRK" k
    JOIN "vbrp" p ON k."vbeln" = p."vbeln"
    """
    violations = _schema_reference_violations(sql)
    assert violations == []


def test_schema_reference_violations_validate_alias_dot_column_refs() -> None:
    sql = """
    SELECT k.vbeln, p.matnr, p.netwr
    FROM "VBRK" k
    JOIN "vbrp" p ON k.vbeln = p.vbeln
    """
    violations = _schema_reference_violations(sql)
    assert violations == []


def test_schema_reference_violations_flag_unknown_alias_column() -> None:
    sql = """
    SELECT k.vbeln, p.not_a_column
    FROM "VBRK" k
    JOIN "vbrp" p ON k.vbeln = p.vbeln
    """
    violations = _schema_reference_violations(sql)
    joined = " | ".join(violations).lower()
    assert "unknown column" in joined


def test_sql_guardrail_flags_ambiguous_unqualified_netwr_for_invoice_value() -> None:
    question = "invoice total value with zero and negative invoices"
    sql = """
    SELECT vbeln, netwr
    FROM "VBRK"
    WHERE CAST(NULLIF(TRIM(CAST(netwr AS TEXT)), '') AS NUMERIC) <= 0
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "ambiguous netwr" in joined


def test_sql_guardrail_flags_select_star_for_structured_output() -> None:
    question = "show invoices by customer"
    sql = 'SELECT * FROM "VBRK"'
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "select *" in joined


def test_sql_guardrail_flags_missing_order_by_for_ranking_intent() -> None:
    question = "top customers by invoice amount"
    sql = """
    SELECT k."kunag", SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_amount
    FROM "VBRK" k
    GROUP BY k."kunag"
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "order by" in joined


def test_sql_guardrail_requires_limit_for_row_level_listing() -> None:
    question = "show invoices with customer names"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    LEFT JOIN "KNA1" c
      ON LPAD(TRIM(k."kunag"), 10, '0') = LPAD(TRIM(c."kunnr"), 10, '0')
    ORDER BY k."fkdat" DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "include limit" in joined


def test_sql_guardrail_requires_distinct_for_invoice_listing_with_vbrp_join() -> None:
    question = "show invoices with customer names and product lines"
    sql = """
    SELECT k."vbeln", c."name1", p."matnr"
    FROM "VBRK" k
    JOIN "vbrp" p
      ON LPAD(TRIM(k."vbeln"), 10, '0') = LPAD(TRIM(p."vbeln"), 10, '0')
    LEFT JOIN "KNA1" c
      ON LPAD(TRIM(k."kunag"), 10, '0') = LPAD(TRIM(c."kunnr"), 10, '0')
    ORDER BY k."fkdat" DESC
    LIMIT 200
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "duplicate invoices" in joined


def test_sql_guardrail_blocks_vbrk_gjahr_for_billing_year_queries() -> None:
    question = "billing invoices in year 2001"
    sql = """
    SELECT k."vbeln", k."gjahr", k."netwr"
    FROM "VBRK" k
    WHERE k."gjahr" = '2001'
    ORDER BY k."vbeln" DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "gjahr" in joined and "fkdat" in joined


def test_sql_guardrail_blocks_sum_netwr_without_cast() -> None:
    question = "top customers by invoice amount"
    sql = """
    SELECT p."vbeln", SUM(p."netwr") AS total_amount
    FROM "vbrp" p
    GROUP BY p."vbeln"
    ORDER BY total_amount DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "sum on netwr" in joined


def test_sql_guardrail_blocks_avg_money_without_safe_cast() -> None:
    question = "average invoice amount by customer"
    sql = """
    SELECT k."kunag", AVG(k."netwr") AS avg_amount
    FROM "VBRK" k
    GROUP BY k."kunag"
    ORDER BY avg_amount DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "monetary aggregate uses raw text amount" in joined


def test_sql_guardrail_blocks_item_level_invoice_count_pattern() -> None:
    question = "invoice count by customer"
    sql = """
    SELECT p."vbeln", p."posnr", COUNT(*) AS invoice_count
    FROM "vbrp" p
    GROUP BY p."vbeln", p."posnr"
    ORDER BY invoice_count DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "item-level" in joined and "vbrk" in joined


def test_sql_guardrail_requires_count_distinct_vbeln_for_invoice_count() -> None:
    question = "invoice count by customer"
    sql = """
    SELECT k."kunag", COUNT(*) AS invoice_count
    FROM "VBRK" k
    JOIN "vbrp" p ON LPAD(TRIM(k."vbeln"),10,'0') = LPAD(TRIM(p."vbeln"),10,'0')
    GROUP BY k."kunag"
    ORDER BY invoice_count DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "count(distinct" in joined


def test_sql_guardrail_requires_currency_for_monetary_query() -> None:
    question = "top customers by invoice amount"
    sql = """
    SELECT k."kunag", SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_amount
    FROM "VBRK" k
    GROUP BY k."kunag"
    ORDER BY total_amount DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "currency" in joined


def test_sql_guardrail_blocks_join_without_on_condition() -> None:
    question = "show invoices with customer names"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    JOIN "KNA1" c
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "missing on condition" in joined


def test_sql_guardrail_blocks_tautological_join_condition() -> None:
    question = "show invoices with customer names"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    JOIN "KNA1" c ON 1=1
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "tautological" in joined


def test_sql_guardrail_blocks_aggregated_monetary_query_without_currency_grouping() -> None:
    question = "total invoice amount by customer"
    sql = """
    SELECT k."kunag", SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_amount
    FROM "VBRK" k
    GROUP BY k."kunag"
    ORDER BY total_amount DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "mixed-currency" in joined


def test_sql_guardrail_blocks_aggregate_amount_with_currency_not_grouped() -> None:
    question = "total invoice amount by customer and currency"
    sql = """
    SELECT k."kunag", k."waerk",
           SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_amount
    FROM "VBRK" k
    GROUP BY k."kunag"
    ORDER BY total_amount DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "does not group by currency" in joined


def test_sql_guardrail_flags_vbrk_vbrp_missing_vbeln_join_key() -> None:
    question = "show billing header and item values"
    sql = """
    SELECT k."vbeln", p."matnr", p."netwr"
    FROM "VBRK" k
    JOIN "vbrp" p ON 1=1
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "tautological" in joined or "vbeln join key" in joined


def test_sql_guardrail_flags_vbrk_vbrp_join_without_lpad_normalization() -> None:
    question = "show billing header and item values"
    sql = """
    SELECT k."vbeln", p."matnr", p."netwr"
    FROM "VBRK" k
    JOIN "vbrp" p ON k."vbeln" = p."vbeln"
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "leading-zero mismatches" in joined


def test_sql_guardrail_flags_vbrk_kna1_missing_customer_key_join() -> None:
    question = "show invoices with customer name"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    JOIN "KNA1" c ON k."fkdat" = c."erdat"
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "customer key join" in joined or "kunag" in joined


def test_sql_guardrail_flags_vbrk_kna1_join_without_lpad_normalization() -> None:
    question = "show invoices with customer name"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    JOIN "KNA1" c ON k."kunag" = c."kunnr"
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "accurate matching" in joined


def test_sql_guardrail_blocks_cast_to_date_on_sap_text_dates() -> None:
    question = "show billing invoices for year 2001"
    sql = """
    SELECT k."vbeln"
    FROM "VBRK" k
    WHERE CAST(k."fkdat" AS DATE) >= DATE '2001-01-01'
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "must not be cast to date" in joined


def test_sql_guardrail_requires_trim_on_sap_date_comparison() -> None:
    question = "show billing invoices in year 2001"
    sql = """
    SELECT k."vbeln"
    FROM "VBRK" k
    WHERE k."fkdat" >= '20010101'
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "date comparisons should use trim" in joined


def test_sql_guardrail_requires_non_empty_check_for_sap_date_filter() -> None:
    question = "show billing invoices in year 2001"
    sql = """
    SELECT k."vbeln"
    FROM "VBRK" k
    WHERE TRIM(k."fkdat") >= '20010101'
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "exclude empty values" in joined


def test_sql_guardrail_blocks_positive_filter_when_zero_negative_requested() -> None:
    question = "show zero and negative invoice values"
    sql = """
    SELECT k."vbeln", CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC) AS invoice_amount
    FROM "VBRK" k
    WHERE CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC) > 0
    ORDER BY k."vbeln" DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "hides requested rows" in joined


def test_sql_guardrail_blocks_raw_text_money_comparison_without_cast() -> None:
    question = "show negative sales lines"
    sql = """
    SELECT p."vbeln", p."matnr", p."netwr"
    FROM "vbrp" p
    WHERE p."netwr" < 0
    ORDER BY p."vbeln" DESC
    LIMIT 100
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "monetary comparison appears to use raw text amount" in joined


# ─── New guardrail tests (5 additional accuracy safeguards) ──────────────────


def test_sql_guardrail_rbkp_rseg_join_requires_gjahr() -> None:
    """RBKP+RSEG join on belnr alone is wrong — belnr repeats across fiscal years."""
    question = "show vendor invoice receipts with amounts"
    sql = """
    SELECT r."belnr", r."lifnr",
           SUM(CAST(NULLIF(TRIM(CAST(s."wrbtr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "RBKP" r
    JOIN "RSEG" s ON r."belnr" = s."belnr"
    GROUP BY r."belnr", r."lifnr"
    ORDER BY total DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "gjahr" in joined


def test_sql_guardrail_bkpf_bseg_join_requires_all_three_keys() -> None:
    """BKPF+BSEG must join on belnr + bukrs + gjahr to avoid cross-company/year matches."""
    question = "show accounting document line items with amounts"
    sql = """
    SELECT b."belnr", s."hkont",
           SUM(CAST(NULLIF(TRIM(CAST(s."dmbtr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "BKPF" b
    JOIN "BSEG" s ON b."belnr" = s."belnr"
    GROUP BY b."belnr", s."hkont"
    ORDER BY total DESC
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    # Must flag both missing keys
    assert "bukrs" in joined
    assert "gjahr" in joined


def test_sql_guardrail_makt_join_requires_language_filter() -> None:
    """MAKT join without spras='E' multiplies rows (one per language), corrupting aggregates."""
    question = "show top materials by billed amount with description"
    sql = """
    SELECT p."matnr", t."maktx",
           SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "vbrp" p
    LEFT JOIN "MAKT" t ON p."matnr" = t."matnr"
    GROUP BY p."matnr", t."maktx"
    ORDER BY total DESC LIMIT 20
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "spras" in joined


def test_sql_guardrail_active_po_query_requires_loekz_filter() -> None:
    """Open/active PO queries must filter EKKO/EKPO.loekz to exclude deleted records."""
    question = "show open purchase orders for active vendors"
    sql = """
    SELECT k."ebeln", k."lifnr", p."matnr",
           CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC) AS value
    FROM "EKKO" k
    JOIN "EKPO" p ON k."ebeln" = p."ebeln"
    ORDER BY k."bedat" DESC LIMIT 100
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "loekz" in joined


def test_sql_guardrail_quantity_aggregation_without_uom_flagged() -> None:
    """SUM(menge) without meins/UOM grouping adds incompatible units (EA + KG + M = nonsense)."""
    question = "total ordered quantity by vendor"
    sql = """
    SELECT k."lifnr",
           SUM(CAST(NULLIF(TRIM(CAST(p."menge" AS TEXT)), '') AS NUMERIC)) AS total_qty
    FROM "EKKO" k
    JOIN "EKPO" p ON k."ebeln" = p."ebeln"
    GROUP BY k."lifnr"
    ORDER BY total_qty DESC LIMIT 50
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "meins" in joined
