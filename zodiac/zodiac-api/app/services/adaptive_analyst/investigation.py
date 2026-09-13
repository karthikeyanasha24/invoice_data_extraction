"""Generic multi-step investigation planning (not question-shaped handlers).

Confirm period direction → try schema-supported driver grains → sufficiency gate.
Never invents causal answers without executed evidence.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Cap investigation fan-out to avoid runaway multi-query loops.
MAX_DRIVER_GRAINS = 3
MAX_INVESTIGATION_QUERIES = 5


def is_investigation_request(question: str, semantic: Optional[Dict[str, Any]] = None) -> bool:
    req = semantic if isinstance(semantic, dict) else {}
    period = req.get("period_compare") if isinstance(req.get("period_compare"), dict) else {}
    if period.get("investigation") or req.get("contribution") or period.get("contribution"):
        return True
    ql = (question or "").lower()
    return bool(
        re.search(r"\b(why\s+did|what\s+caused|drivers?\s+of|contribut\w*|accounted\s+for)\b", ql)
        and re.search(r"\b(revenue|sales|billing|decline|decrease|drop|fell|growth|increase)\b", ql)
    )


def available_driver_grains(
    question: str,
    semantic: Optional[Dict[str, Any]] = None,
    *,
    tables: Optional[List[str]] = None,
) -> List[str]:
    """Pick investigation dimensions from question + available schema, not a fixed handler."""
    from ...data_catalog.physical import has_column, has_table

    req = semantic if isinstance(semantic, dict) else {}
    ql = (question or "").lower()
    named: List[str] = []
    for d in req.get("group_by") or req.get("dimensions") or []:
        dd = str(d).lower()
        if dd not in {"year", "month", "quarter"} and dd not in named:
            named.append(dd)
    if re.search(r"\b(materials?|products?)\b", ql) and "material" not in named:
        named.insert(0, "material")
    if re.search(r"\bcountr", ql) and "country" not in named:
        named.insert(0, "country")
    if re.search(r"\b(customers?|clients?)\b", ql) and "customer" not in named:
        named.insert(0, "customer")
    if re.search(r"\bindustr", ql) and "industry" not in named:
        named.insert(0, "industry")

    candidates = named[:]
    # Schema-supported fallbacks when the question did not name a grain ("why did revenue fall?").
    if has_table("KNA1"):
        for g in ("customer", "country", "industry"):
            if g not in candidates:
                if g == "country" and not has_column("KNA1", "land1"):
                    continue
                if g == "industry" and not has_column("KNA1", "brsch"):
                    continue
                candidates.append(g)
    if has_table("vbrp") and has_table("MAKT") and "material" not in candidates:
        candidates.append("material")

    # Prefer grains whose tables are already in the working set when provided.
    tbl_u = {str(t).upper() for t in (tables or [])}
    if tbl_u:
        scored: List[Tuple[int, str]] = []
        for g in candidates:
            score = 0
            if g in {"customer", "country", "industry"} and ("KNA1" in tbl_u or "VBRK" in tbl_u):
                score = 2
            elif g == "material" and ("VBRP" in tbl_u or "MAKT" in tbl_u):
                score = 2
            else:
                score = 1
            scored.append((score, g))
        scored.sort(key=lambda x: (-x[0], candidates.index(x[1])))
        candidates = [g for _, g in scored]

    return candidates[:MAX_DRIVER_GRAINS] or ["customer"]


def plan_investigation_steps(
    question: str,
    semantic: Optional[Dict[str, Any]] = None,
    *,
    tables: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Return ordered investigation steps for adaptive re-planning."""
    if not is_investigation_request(question, semantic):
        return [{"kind": "primary", "role": "answer"}]
    req = semantic if isinstance(semantic, dict) else {}
    period = req.get("period_compare") if isinstance(req.get("period_compare"), dict) else {}
    grains = available_driver_grains(question, semantic, tables=tables)
    op = str(period.get("op") or period.get("condition") or "decline").lower()
    expected = (
        "decline"
        if op in {"decline", "decrease", "decreased"}
        or re.search(r"\b(declin|decreas|drop|fell)\b", (question or "").lower())
        else "growth"
    )
    steps: List[Dict[str, Any]] = [
        {
            "kind": "confirm_direction",
            "role": "gate",
            "aggregate_only": True,
            "expected_direction": expected,
        }
    ]
    for grain in grains:
        steps.append(
            {
                "kind": "drivers",
                "role": "answer",
                "contribution": True,
                "group_by": [grain],
            }
        )
    return steps


def _num(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
        for rk, rv in row.items():
            if str(rk).lower() == k.lower() and rv is not None:
                try:
                    return float(rv)
                except (TypeError, ValueError):
                    continue
    return None


def evaluate_direction_gate(
    confirm_rows: List[Dict[str, Any]],
    *,
    expected_direction: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (verdict, evidence).
    verdict: proceed | no_change | opposite | empty
    """
    if not confirm_rows:
        return "empty", {}
    row = confirm_rows[0]
    change = _num(row, "change", "delta", "diff", "growth")
    period_a = _num(row, "period_a", "base", "prior")
    period_b = _num(row, "period_b", "current", "latest")
    evidence = {
        "period_a": period_a,
        "period_b": period_b,
        "change": change,
        "expected_direction": expected_direction,
    }
    if change is None and period_a is not None and period_b is not None:
        change = period_b - period_a
        evidence["change"] = change
    if change is None:
        return "empty", evidence
    if abs(change) < 1e-9:
        return "no_change", evidence
    declined = change < 0
    if expected_direction == "decline":
        return ("proceed" if declined else "opposite"), evidence
    return ("proceed" if not declined else "opposite"), evidence


def result_has_driver_grain(rows: List[Dict[str, Any]]) -> bool:
    if not rows or not isinstance(rows[0], dict):
        return False
    keys = {str(k).lower() for k in rows[0].keys()}
    entity = any(
        tok in keys or any(tok in k for k in keys)
        for tok in (
            "customer",
            "kunnr",
            "name1",
            "country",
            "land1",
            "material",
            "matnr",
            "industry",
            "brsch",
        )
    )
    change = any(k in keys for k in ("change", "delta", "diff", "contribution_pct", "growth"))
    return entity and change


def top_contribution_share(rows: List[Dict[str, Any]], *, limit: int = 3) -> Optional[float]:
    """Sum of absolute contribution_pct for top-N rows when present."""
    if not rows:
        return None
    scores: List[float] = []
    for row in rows[: max(1, limit)]:
        v = _num(row, "contribution_pct")
        if v is None:
            continue
        scores.append(abs(v))
    if not scores:
        return None
    return sum(scores)


def sufficiency_for_investigation(
    question: str,
    rows: List[Dict[str, Any]],
    *,
    semantic: Optional[Dict[str, Any]] = None,
    confirm_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Whether executed evidence is enough to answer an investigation question."""
    if not is_investigation_request(question, semantic):
        return {"sufficient": True, "reason": "not_investigation"}
    if confirm_evidence and confirm_evidence.get("verdict") in {"opposite", "no_change", "empty"}:
        return {
            "sufficient": True,
            "reason": f"direction_gate_{confirm_evidence.get('verdict')}",
            "answer_mode": "direction_only",
            "evidence": confirm_evidence,
        }
    if result_has_driver_grain(rows):
        share = top_contribution_share(rows, limit=3)
        return {
            "sufficient": True,
            "reason": "drivers_present",
            "answer_mode": "drivers",
            "top_contribution_share": share,
        }
    if rows and len(rows) == 1 and _num(rows[0], "change", "period_a", "period_b") is not None:
        return {
            "sufficient": False,
            "reason": "confirm_only",
            "next_step": "drivers",
        }
    return {"sufficient": False, "reason": "insufficient_evidence", "next_step": "drivers"}


def evidence_based_summary(
    *,
    confirm: Optional[Dict[str, Any]],
    driver_rows: List[Dict[str, Any]],
    grain: str = "customer",
) -> str:
    """Governed language: contribution, not unsupported real-world causality."""
    parts: List[str] = []
    if confirm and confirm.get("change") is not None:
        ch = confirm["change"]
        pa, pb = confirm.get("period_a"), confirm.get("period_b")
        if ch < 0:
            parts.append(
                f"The available data shows revenue declined by {abs(ch):,.2f}"
                + (f" (from {pa:,.2f} to {pb:,.2f})" if pa is not None and pb is not None else "")
                + "."
            )
        elif ch > 0:
            parts.append(
                f"The available data shows revenue increased by {ch:,.2f}"
                + (f" (from {pa:,.2f} to {pb:,.2f})" if pa is not None and pb is not None else "")
                + "."
            )
        else:
            parts.append("The available data shows essentially no net change in revenue.")
    if driver_rows and result_has_driver_grain(driver_rows):
        label_key = None
        for k in driver_rows[0].keys():
            kl = str(k).lower()
            if any(t in kl for t in ("name", "customer", "country", "material", "industry")):
                label_key = k
                break
        top = driver_rows[0]
        label = top.get(label_key) if label_key else None
        pct = _num(top, "contribution_pct")
        ch = _num(top, "change")
        if label is not None and pct is not None:
            parts.append(
                f"By {grain}, '{label}' accounted for {abs(pct):.1f}% of the measured change"
                + (f" (change={ch:,.2f})" if ch is not None else "")
                + ". This is a contribution finding from the data, not an external causal claim."
            )
        elif label is not None:
            parts.append(
                f"By {grain}, '{label}' was the largest contributor to the measured change "
                "in the available data."
            )
    return " ".join(parts).strip()
