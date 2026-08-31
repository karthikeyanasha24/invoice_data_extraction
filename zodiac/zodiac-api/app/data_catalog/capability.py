"""User-facing capability text from the actual catalog."""
from __future__ import annotations

from .physical import has_table, sap_business_tables
from .registry import available_domains, tables_for_domain


def capability_summary() -> str:
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
    return (
        f"I can answer governed questions across {n} migrated SAP business tables, including {extra}. "
        "Ask about a business metric and dimension (for example: sales orders by customer in 2004, "
        "invoices by industry, purchase-order value by vendor). "
        "Unqualified 'sales' ranking uses billed invoices unless you ask for sales orders."
    )


def domain_table_preview(domain: str, limit: int = 8) -> str:
    tables = tables_for_domain(domain)[:limit]
    return ", ".join(tables) if tables else "(none in this extract)"
