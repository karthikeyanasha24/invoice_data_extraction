"""Generic qualitative-threshold semantics.

Distinguishes:
  - explicit numeric thresholds (quantity > 1000)
  - relative thresholds (above/below average)
  - percentile/rank thresholds (top 10%)
  - undefined qualitative adjectives (high / low / significant)

Never invents thresholds. Uses approved business definitions when configured;
otherwise returns a structured clarification request.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Approved business definitions (empty by default — filled only from config).
# Keys are normalized predicate phrases; values are executable predicates.
_APPROVED_THRESHOLD_DEFS: Dict[str, Dict[str, Any]] = {}

try:
    from .business_semantic_layer import THRESHOLD_DEFINITIONS as _BSL_DEFS  # type: ignore

    if isinstance(_BSL_DEFS, dict):
        _APPROVED_THRESHOLD_DEFS.update(_BSL_DEFS)
except Exception:
    pass

_EXPLICIT_NUMERIC = re.compile(
    r"(?:[<>]=?\s*\d|>=\s*\d|<=\s*\d|"
    r"\b(?:greater|more|less|fewer|over|under|above|below)\s+than\s+\d|"
    r"\b(?:at\s+least|at\s+most|no\s+more\s+than|no\s+less\s+than)\s+\d)",
    re.I,
)
_RELATIVE_AVG = re.compile(
    r"\b(?:above|over|greater than|higher than|below|under|less than)\s+(?:the\s+)?average\b",
    re.I,
)
_PERCENTILE = re.compile(
    r"\b(?:top|bottom)\s+\d{1,3}\s*%|\bpercentile\b|\bquartile\b|\bdecile\b",
    re.I,
)
# Qualitative adjectives that need a definition when no numeric/relative rule exists.
# Word boundaries exclude highest/lowest/largest/smallest (ranking morphology).
_QUAL_ADJ = re.compile(
    r"\b(?:"
    r"high|low|significant|large|small|important|recent|"
    r"unusual(?:ly)?|underperforming|profitable"
    r")\b",
    re.I,
)
_RANKING_MORPH = re.compile(
    r"\b(?:highest|lowest|largest|smallest|most|least|top\s+\d+|bottom\s+\d+|best|worst)\b",
    re.I,
)
_DUAL_QUAL = re.compile(
    r"\b(high|low|significant|large|small)\b"
    r".{0,60}?\b(but|and|with|yet)\b"
    r".{0,60}?\b(high|low|significant|large|small|relatively\s+low|relatively\s+high)\b",
    re.I,
)
_QUAL_PHRASE = re.compile(
    r"\b(high|low|significant|large|small|important|recent|unusual(?:ly)?|underperforming|profitable)"
    r"\s+((?:relatively\s+)?(?:billed\s+)?(?:quantity|qty|value|amount|sales|revenue|margin|"
    r"volume|orders?|invoices?|customers?|materials?|suppliers?|vendors?|"
    r"performing\s+\w+|\w+(?:\s+\w+){0,2}))",
    re.I,
)


def register_threshold_definition(key: str, definition: Dict[str, Any]) -> None:
    """Register an approved business definition (tests / config)."""
    _APPROVED_THRESHOLD_DEFS[str(key).strip().lower()] = dict(definition)


def clear_threshold_definitions() -> None:
    _APPROVED_THRESHOLD_DEFS.clear()


def resolve_approved_definitions(question: str) -> List[Dict[str, Any]]:
    """Return approved definitions that match qualitative phrases in the question."""
    ql = (question or "").lower()
    found: List[Dict[str, Any]] = []
    for key, defn in _APPROVED_THRESHOLD_DEFS.items():
        if key and key in ql:
            found.append({"key": key, **defn})
    return found


def _qualitative_phrases(question: str) -> List[str]:
    ql = (question or "").lower()
    # Strip ranking morphology so "highest" does not leave a bare "high".
    stripped = _RANKING_MORPH.sub(" ", ql)
    phrases: List[str] = []
    for m in _QUAL_PHRASE.finditer(stripped):
        phrase = f"{m.group(1)} {m.group(2).strip()}"
        phrases.append(re.sub(r"\s+", " ", phrase).strip())
    if not phrases and _QUAL_ADJ.search(stripped):
        for m in _QUAL_ADJ.finditer(stripped):
            phrases.append(m.group(0).lower())
    # Deduplicate preserving order
    out: List[str] = []
    seen = set()
    for p in phrases:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def detect_threshold_clarification(question: str) -> Optional[Dict[str, Any]]:
    """If qualitative thresholds are undefined, return a clarification payload fragment.

    Returns None when:
      - no qualitative language is present
      - explicit / relative / percentile thresholds are present
      - approved business definitions cover the predicates
      - the question is a pure ranking (highest/lowest) without separate high/low cues
    """
    q = (question or "").strip()
    if not q:
        return None
    ql = q.lower()

    if _EXPLICIT_NUMERIC.search(ql) or _RELATIVE_AVG.search(ql) or _PERCENTILE.search(ql):
        return None

    approved = resolve_approved_definitions(q)
    if approved:
        return None

    phrases = _qualitative_phrases(q)
    if not phrases:
        return None

    # Pure ranking: "highest sales" / "lowest quantity" — no clarification.
    if _RANKING_MORPH.search(ql) and not _DUAL_QUAL.search(ql):
        stripped = _RANKING_MORPH.sub(" ", ql)
        if not _QUAL_ADJ.search(stripped):
            return None

    # Dual qualitative ("high X but low Y") always needs definitions.
    # Single qualitative without ranking also needs definitions.
    if not (_DUAL_QUAL.search(ql) or (phrases and not _RANKING_MORPH.search(ql))):
        # Ranking + leftover qualitative adjective (e.g. "unusually high") → clarify.
        if not re.search(r"\b(unusual(?:ly)?|significant|important|underperforming|profitable|recent)\b", ql):
            return None

    pretty = ", ".join(f'"{p}"' for p in phrases[:4]) or "qualitative terms"
    return {
        "type": "threshold_definition",
        "parameters": phrases,
        "message": (
            f"The query needs thresholds for {pretty}. "
            "What quantity and value thresholds should I use "
            "(numeric limits, percentiles, or relative-to-average rules)?"
        ),
    }


def merge_threshold_ops(ops: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Attach clarification or approved threshold defs onto analytical ops."""
    clar = detect_threshold_clarification(question)
    if clar:
        # Do not overwrite an existing stronger clarification (e.g. comparison_period).
        existing = ops.get("clarification")
        if not (isinstance(existing, dict) and existing.get("type")):
            ops["clarification"] = clar
        return ops
    approved = resolve_approved_definitions(question)
    if approved:
        ops["threshold_definitions"] = approved
    return ops
