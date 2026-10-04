"""Deterministic source selection. LLM does not choose tables or SQL."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .physical import has_table
from .registry import METRICS, tables_for_domain

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass
class SourceSpec:
    route: str  # billing | sales_order | domain_overview | knowledge | clarify | existing
    domain: str = ""
    metric: str = ""
    dimensions: List[str] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    years: List[str] = field(default_factory=list)
    ranking: str = ""  # highest | lowest | ""
    needs_clarification: bool = False
    clarification_message: str = ""
    reason: str = ""
    named_table: str = ""

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route,
            "domain": self.domain,
            "metric": self.metric,
            "dimensions": self.dimensions,
            "tables": self.tables,
            "years": self.years,
            "reason": self.reason,
            "named_table": self.named_table,
            "needs_clarification": self.needs_clarification,
        }


def _ql(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def _years(q: str) -> List[str]:
    return _YEAR_RE.findall(q or "")


def _dims(ql: str) -> List[str]:
    dims = []
    if re.search(r"\b(customers?|clients?|buyers?|who|whom|whose)\b", ql):
        dims.append("customer")
    if re.search(r"\b(countr(?:y|ies)|nations?)\b", ql):
        dims.append("country")
    if re.search(r"\b(industr(?:y|ies)|sectors?)\b", ql):
        dims.append("industry")
    if re.search(r"\b(products?|materials?|skus?)\b", ql):
        dims.append("product")
    if re.search(r"\b(vendors?|suppliers?)\b", ql) and "concentration" not in ql:
        dims.append("vendor")
    return dims


def _explicit_sales_order(ql: str) -> bool:
    return bool(
        re.search(
            r"\b(sales\s+orders?|sales-order|order\s+value|ordered|placed the most orders|"
            r"from vbak|from vbap|from vbep|from vbed|"
            r"\bvbak\b|\bvbap\b|\bvbep\b|\bvbed\b)\b",
            ql,
        )
    )


def _explicit_invoice(ql: str) -> bool:
    return bool(
        re.search(
            r"\b(invoices?|billing|billed|billed revenue|billing document|from vbrk|from vbrp|"
            r"\bvbrk\b|\bvbrp\b)\b",
            ql,
        )
    )


def _explicit_purchasing(ql: str) -> bool:
    return bool(
        re.search(
            r"\b(purchase orders?|purchasing|procurement|vendor spend|spend by vendor|"
            r"from ekko|from ekpo|\bekko\b|\bekpo\b)\b",
            ql,
        )
    )


def _explicit_production(ql: str) -> bool:
    return bool(
        re.search(r"\b(production|produced|manufactur|from afko|from afpo|\bafko\b|\bafpo\b)\b", ql)
    )


def _named_sap_table(ql: str) -> str:
    for t in ("vbak", "vbap", "vbep", "vbed", "vbrk", "vbrp", "ekko", "ekpo", "afko", "afpo",
              "kna1", "mara", "makt", "lfa1"):
        if re.search(rf"\b{t}\b", ql):
            return t.upper() if t != "vbrp" else "vbrp"
    return ""


def _ambiguous_sales(ql: str) -> bool:
    if _explicit_sales_order(ql) or _explicit_invoice(ql):
        return False
    if _years(ql):
        return False
    # Ranking "top customers by sales" is the frozen billed-sales path.
    if re.search(r"\btop\s+(\d+\s+)?(customers?|countries|industries)\s+by\s+(sales|revenue)\b", ql):
        return False
    if re.search(r"\b(highest|total|by industry|by country|by product|by customer)\s+sales\b", ql):
        return False
    if re.search(r"\bsales by (industry|country|product|customer|year)\b", ql):
        return False
    if re.fullmatch(r"(show( me)?( our)? )?sales( data)?\.?", ql):
        return True
    if re.fullmatch(r"show me our sales data\.?", ql):
        return True
    return False


def _short_sales_needs_dimension(ql: str) -> bool:
    return bool(re.fullmatch(r"(the\s+)?highest sales\??", ql)) or ql in {"highest sales?", "highest sales"}


def select_source(
    question: str,
    prior_plan: Optional[Dict[str, Any]] = None,
) -> SourceSpec:
    ql = _ql(question)
    years = _years(question)
    dims = _dims(ql)
    named = _named_sap_table(ql)

    prior_ctx = {}
    if isinstance(prior_plan, dict):
        prior_ctx = prior_plan.get("analytical_context") or prior_plan

    # Domain switch: invoices after sales-order context must not reuse VBAK.
    if _explicit_invoice(ql) and not _explicit_sales_order(ql):
        return SourceSpec(
            route="existing",
            domain="invoice",
            metric="billing_revenue" if "count" not in ql else "invoice_count",
            tables=["VBRK", "vbrp"] if has_table("VBRK") else [],
            years=years,
            dimensions=dims,
            reason="explicit_invoice",
        )

    has_prior = bool(prior_ctx.get("deep_analysis") or prior_ctx.get("intent"))
    if has_prior and not _explicit_sales_order(ql) and not named:
        if _ambiguous_sales(ql) or _short_sales_needs_dimension(ql) or ql in {"sales", "highest sales", "highest sales?"}:
            return SourceSpec(route="existing", reason="preserve_followup_context")

    if _short_sales_needs_dimension(ql):
        return SourceSpec(
            route="clarify",
            domain="sales",
            needs_clarification=True,
            clarification_message=(
                "Do you want highest sales by customer, product, country, or another dimension? "
                "If you mean sales orders (VBAK/VBAP) rather than billed invoices (VBRK/VBRP), say so."
            ),
            reason="ambiguous_dimension",
        )

    if named == "VBED" or re.search(r"\bvbed\b", ql):
        if not has_table("VBED"):
            alt = "VBEP" if has_table("VBEP") else ""
            msg = "VBED is not available in the connected migrated dataset."
            if alt:
                msg += f" Schedule-line data in this extract is in {alt}."
            return SourceSpec(
                route="knowledge",
                domain="sales",
                named_table="VBED",
                tables=[alt] if alt else [],
                needs_clarification=True,
                clarification_message=msg,
                reason="table_absent",
            )

    if named in {"VBAK", "VBAP", "VBEP"} or _explicit_sales_order(ql):
        tables = [t for t in ("VBAK", "VBAP", "VBEP") if has_table(t)]
        if named == "VBAK":
            tables = ["VBAK"] if has_table("VBAK") else []
        elif named == "VBAP":
            tables = ["VBAP"] if has_table("VBAP") else []
        elif named == "VBEP":
            tables = ["VBEP"] if has_table("VBEP") else []
        metric = "sales_order_count" if re.search(r"\b(how many|count|number of)\b", ql) else "sales_order_value"
        if named == "VBEP" or "schedul" in ql:
            metric = "sales_schedule"
        return SourceSpec(
            route="sales_order",
            domain="sales",
            metric=metric,
            dimensions=dims,
            tables=tables,
            years=years,
            ranking="highest" if re.search(r"\b(highest|top|most)\b", ql) else "",
            named_table=named,
            reason="explicit_sales_order",
        )

    if _ambiguous_sales(ql) and has_table("VBAK") and has_table("VBRK"):
        return SourceSpec(
            route="clarify",
            domain="sales",
            needs_clarification=True,
            clarification_message=(
                "I found both sales-order data (VBAK/VBAP) and invoiced/billed sales (VBRK/VBRP). "
                "Do you want: 1) Sales orders  2) Invoiced/billed sales?"
            ),
            reason="ambiguous_sales_vs_billing",
        )

    if _explicit_purchasing(ql):
        return SourceSpec(
            route="domain_overview",
            domain="purchasing",
            metric="purchase_value",
            tables=[t for t in ("EKKO", "EKPO", "LFA1") if has_table(t)],
            dimensions=dims,
            years=years,
            reason="explicit_purchasing",
        )

    if _explicit_production(ql):
        return SourceSpec(
            route="domain_overview",
            domain="production",
            metric="production_quantity",
            tables=[t for t in ("AFKO", "AFPO", "AUFK") if has_table(t)],
            dimensions=dims,
            years=years,
            reason="explicit_production",
        )

    if re.search(r"\b(customer master|show customers|customer information|customers\b)\b", ql) and not (
        _explicit_sales_order(ql) or "sales" in ql or "profit" in ql or "invoice" in ql
    ):
        if re.search(r"\b(show|list|master)\b", ql) or ql in {"customers", "show customers."}:
            return SourceSpec(
                route="domain_overview",
                domain="customer",
                tables=[t for t in ("KNA1",) if has_table(t)],
                reason="customer_master",
            )

    if re.search(r"\b(product master|material master|show products|product information)\b", ql) and "sales" not in ql:
        return SourceSpec(
            route="domain_overview",
            domain="product",
            tables=[t for t in ("MARA", "MAKT") if has_table(t)],
            reason="product_master",
        )

    if re.search(r"\b(vendor master|show vendors)\b", ql):
        return SourceSpec(
            route="domain_overview",
            domain="vendor",
            tables=[t for t in ("LFA1",) if has_table(t)],
            reason="vendor_master",
        )

    if re.search(r"\bwhat is (vbak|vbap|vbep|vbed|vbrk|ekko)\b", ql):
        return SourceSpec(
            route="knowledge",
            domain="sales" if named in {"VBAK", "VBAP", "VBEP", "VBED"} else "",
            named_table=named or ql.split()[-1].upper(),
            reason="schema_question",
        )

    # Unqualified sales ranking stays on the frozen billing path.
    return SourceSpec(
        route="existing",
        domain="invoice" if "sales" in ql or "revenue" in ql else "",
        metric="billing_revenue" if "sales" in ql or "revenue" in ql else "",
        tables=tables_for_domain("invoice")[:4] if "sales" in ql else [],
        dimensions=dims,
        years=years,
        reason="existing_governed_path",
    )


def metric_registry_names() -> List[str]:
    return sorted(METRICS.keys())
