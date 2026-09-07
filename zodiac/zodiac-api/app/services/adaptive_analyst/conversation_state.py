"""Shared conversation / investigation state for the Generative AI page."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InvestigationState:
    conversation_id: str = ""
    metric: str = ""
    dimensions: List[str] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    time_period: str = ""
    ranking: str = ""
    comparison: str = ""
    domain: str = ""
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    last_sql: str = ""
    last_summary: str = ""
    last_user_question: str = ""
    last_resolved_question: str = ""
    entities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_context(
        cls,
        previous_plan: Optional[Dict[str, Any]],
        previous_question: str = "",
        previous_sql: str = "",
    ) -> "InvestigationState":
        plan = previous_plan if isinstance(previous_plan, dict) else {}
        raw = plan.get("investigation_state") or plan.get("analytical_context") or {}
        if not isinstance(raw, dict):
            raw = {}
        dims = raw.get("dimensions") or []
        if isinstance(dims, str):
            dims = [dims]
        tables = raw.get("tables") or raw.get("selected_tables") or []
        cols = raw.get("columns") or raw.get("selected_columns") or []
        return cls(
            conversation_id=str(raw.get("conversation_id") or ""),
            metric=str(raw.get("metric") or raw.get("selected_metric") or ""),
            dimensions=[str(d) for d in dims if d],
            filters=[str(f) for f in (raw.get("filters") or []) if f],
            time_period=str(raw.get("time_period") or raw.get("period") or raw.get("period_label") or ""),
            ranking=str(raw.get("ranking") or ""),
            comparison=str(raw.get("comparison") or ""),
            domain=str(raw.get("domain") or raw.get("active_business_domain") or ""),
            tables=[str(t) for t in tables if t],
            columns=[str(c) for c in cols if c],
            last_sql=str(previous_sql or raw.get("last_sql") or "")[:8000],
            last_summary=str(raw.get("last_summary") or "")[:2000],
            last_user_question=str(previous_question or raw.get("last_user_question") or ""),
            last_resolved_question=str(raw.get("last_resolved_question") or ""),
            entities=[str(e) for e in (raw.get("entities") or []) if e],
        )
