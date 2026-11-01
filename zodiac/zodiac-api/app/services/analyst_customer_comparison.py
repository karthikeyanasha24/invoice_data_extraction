"""Reuse the checked comparison capability for unqualified year-scoped requests."""
import re


def plain_customer_comparison_request(question):
    # A capability must never discard an unhandled filter, named entity,
    # ranking limit or extra business question. Anything outside this small
    # unqualified vocabulary continues through ordinary Agentic planning.
    years = list(re.finditer(r"\b(?:19|20)\d{2}\b", question))
    if not years or len({match.group() for match in years}) > 2:
        return False
    # A shared reporting period follows both source names and dimensions.
    # "Orders in 2000 versus invoices in 2004" requires a different plan.
    before_period = question[:years[0].start()]
    if not all(re.search(pattern, before_period, re.I) for pattern in (
            r"\bsales\s+orders?\b", r"\binvoices?\b", r"\bcountr(?:y|ies)\b", r"\bcustomers?\b")):
        return False
    if (len(re.findall(r"\bcountr(?:y|ies)\b", question, re.I)) != 1
            or len(re.findall(r"\bcustomers?\b", question, re.I)) != 1):
        return False
    # Vocabulary alone is insufficient: IN is also a country code, and Sales
    # can be a customer name. Require a plain dimension list before the period.
    dimensions = r"(?:countr(?:y|ies)\s*(?:,|and)\s*customers?|customers?(?:\s+names?)?\s*(?:,|and)\s*countr(?:y|ies))"
    if not re.search(r"\b(?:by|per|each)\s+" + dimensions
                     + r"(?:\s+(?:name|names|value|values))*\s*(?:(?:for|in|from|during|between|the|calendar|year|years)\s+)*$",
                     before_period, re.I):
        return False
    words = set(re.findall(r"[a-z0-9_]+", re.sub(r"\b(?:19|20)\d{2}\b", "", question.lower())))
    allowed = set("compare comparison differences difference major show me identify determine sales order orders invoice invoices value values amount amounts net revenue total totals country countries customer customers name names by per each year years annual calendar for the in from during between and to through until of versus vs against".split())
    return bool(words <= allowed and not re.search(r"[$€£¥%<>=@]", question)
                and re.search(r"\b(?:compare|comparison|difference|differences|versus|vs|against)\b", question, re.I)
                and re.search(r"\bsales\s+orders?\b", question, re.I)
                and re.search(r"\binvoices?\b", question, re.I)
                and re.search(r"\bcountr(?:y|ies)\b", question, re.I)
                and re.search(r"\bcustomers?\b", question, re.I)
                and re.search(r"\b(?:19|20)\d{2}\b", question))


def customer_comparison_sql(question, schema):
    if not plain_customer_comparison_request(question):
        return None
    from .adaptive_structured_sql import build_sales_order_invoice_customer_comparison_sql
    sql = build_sales_order_invoice_customer_comparison_sql(question, list(schema), catalog_schema=schema)
    # Fetch a sentinel row so the ordinary tool can label a bounded result.
    return re.sub(r"LIMIT 200$", "LIMIT 201", sql) if sql else None
