"""Distinguish comparisons of document values from changes between periods."""
import re

COMPARISON = re.compile(r'\b(?:compare|comparison|compared|versus|vs\.?|against|difference|reconcile)\b', re.I)
DOCUMENT_FAMILIES = (
    (re.compile(r'(?<!purchase )(?<!production )(?<!ascending )(?<!descending )(?<!sort )\b(?:sales\s+)?orders?\b(?!\s+by\b)', re.I), {'VBAK','VBAP'}),
    (re.compile(r'(?<!supplier )(?<!vendor )\b(?:billing\s+documents?|billing\s+items?|invoices?|billed)\b', re.I), {'VBRK','VBRP'}),
    (re.compile(r'\bdeliver(?:y|ies)\b', re.I), {'LIKP','LIPS'}),
    (re.compile(r'\bpurchase\s+orders?\b', re.I), {'EKKO','EKPO'}),
    (re.compile(r'\b(?:supplier|vendor)\s+invoices?\b', re.I), {'RBKP','RSEG'}),
)


def cross_source_years(question):
    """Two value sources with a year scope do not imply year-over-year growth."""
    q = question or ''
    years = sorted(set(re.findall(r'\b(?:19|20)\d{2}\b', q)))
    if len(years) < 2 or not COMPARISON.search(q):
        return []
    if sum(bool(pattern.search(q)) for pattern,_ in DOCUMENT_FAMILIES) < 2:
        return []
    if re.search(r'\b(?:growth|grew|increas\w*|decreas\w*|declin\w*|change|yoy|year[- ]over[- ]year|previous|prior|linked|related|same)\b|'
                 r'\b\d{4}\s*(?:vs\.?|versus|to|against|compared\s+(?:with|to))\s*\d{4}\b|'
                 r'\b(?:compare|between)\s+(?:the\s+)?(?:years?\s+)?\d{4}\s+and\s+\d{4}\b', q, re.I):
        return []
    return years
