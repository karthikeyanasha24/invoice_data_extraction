"""User-facing capability text from the actual catalog."""
from __future__ import annotations

from .physical import has_table, sap_business_tables
from .registry import available_domains, tables_for_domain


def capability_summary(*, include_examples: bool = False) -> str:
    domains = available_domains()
    bits = []
    if has_table("VBAK"):
        bits.append("sales orders (VBAK/VBAP)")
    if has_table("VBRK"):
        bits.append("billing/invoices (VBRK/VBRP)")
    if has_table("EKKO"):
        bits.append("purchasing (EKKO/EKPO)")
    if has_table("AFKO"):
        bits.append("production (AFKO/AFPO)")
    if has_table("KNA1"):
        bits.append("customers (KNA1)")
    if has_table("MARA"):
        bits.append("products/materials (MARA/MAKT)")
    if has_table("BKPF"):
        bits.append("finance postings (BKPF/BSEG)")
    if has_table("COEP") or has_table("CKIS"):
        bits.append("cost")
    extra = ", ".join(bits) if bits else "the migrated SAP tables in this extract"
    n = len(sap_business_tables())
    summary = (
        f"I can answer governed questions across {n} migrated SAP business tables, including {extra}. "
        "Ask naturally about a business metric, group it by a supported SAP dimension, and add any "
        "relevant time period or filters. Specify sales orders or billing documents when you want "
        "to choose between those sources."
    )
    if include_examples:
        examples = []
        has_billing = has_table("VBRK") and has_table("VBRP")
        has_orders = has_table("VBAK") and has_table("VBAP")
        if has_billing:
            examples.append("Show billed sales by month and currency.")
        if has_billing and has_table("KNA1"):
            examples.append("Which customers had the highest billed sales in 2017?")
        if has_billing and has_table("MARA"):
            examples.append("Which materials had the highest billed sales in the latest year?")
        if has_billing and has_orders:
            examples.append("Compare sales-order item values with their linked billing-item values.")
        if has_table("EKKO") and has_table("EKPO"):
            examples.append("Summarize purchase-order value by supplier and year.")
        if examples:
            summary += " Examples you can try: " + " ".join(examples)
    return summary


def domain_table_preview(domain: str, limit: int = 8) -> str:
    tables = tables_for_domain(domain)[:limit]
    return ", ".join(tables) if tables else "(none in this extract)"
