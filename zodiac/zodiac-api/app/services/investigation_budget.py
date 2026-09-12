"""Investigation wall-clock budget, cancellation, and stage tracing.

Every adaptive analytics investigation has:
  - a request_id
  - a hard deadline (default 120 seconds) covering LLM + SQL + repair + answer
  - a cancellable flag checked between stages
  - a pipeline_stage for UI status (backend is the source of truth)

Chat is not allowed to run indefinitely. Cancel must stop further LLM calls
and further repair attempts; in-flight SQL is bounded by statement_timeout.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("zodiac-api.investigation_budget")

HARD_LIMIT_SECONDS = float(os.getenv("ADAPTIVE_INVESTIGATION_LIMIT_SECONDS") or "120")

TIMEOUT_USER_MESSAGE = (
    "This analysis exceeded the allowed processing time and was stopped. "
    "No unsupported result was returned."
)
CANCELLED_USER_MESSAGE = (
    "This analysis was cancelled. No unsupported result was returned."
)

_CURRENT: ContextVar[Optional["InvestigationBudget"]] = ContextVar(
    "investigation_budget", default=None
)
_REGISTRY_LOCK = threading.Lock()
_REGISTRY: Dict[str, "InvestigationBudget"] = {}

_STAGE_ALIASES = {
    "intent_analysis": "UNDERSTANDING",
    "intent_analysis_done": "UNDERSTANDING",
    "schema_retrieval": "RETRIEVING_SCHEMA",
    "table_selection": "SELECTING_TABLES",
    "PIPELINE_1_TABLE_SELECTION": "SELECTING_TABLES",
    "column_selection": "SELECTING_COLUMNS",
    "PIPELINE_2_COLUMN_SELECTION": "SELECTING_COLUMNS",
    "query_planning": "BUILDING_PLAN",
    "QUERY_PLAN": "BUILDING_PLAN",
    "plan_validation": "VALIDATING_PLAN",
    "sql_generation": "GENERATING_SQL",
    "PIPELINE_3_SQL_GENERATION": "GENERATING_SQL",
    "sql_validation": "VALIDATING_SQL",
    "SQL_VALIDATION": "VALIDATING_SQL",
    "database_execution": "EXECUTING",
    "db_execute": "EXECUTING",
    "SQL_EXECUTION": "EXECUTING",
    "PLAN_REPAIR": "REPAIRING",
    "SQL_GROUPING_REPAIR": "REPAIRING",
    "RESULT_PLAN_REPAIR": "REPAIRING",
    "result_analysis": "VALIDATING_RESULT",
    "RESULT_VALIDATION": "VALIDATING_RESULT",
    "FINAL_ANSWER": "COMPLETED",
    "llm_call": "UNDERSTANDING",
}


class InvestigationTimeout(Exception):
    """Raised when the investigation deadline is hit or the client cancels."""

    def __init__(self, stage: str = "", elapsed_s: float = 0.0, *, cancelled: bool = False) -> None:
        self.stage = stage or "unknown"
        self.elapsed_s = elapsed_s
        self.cancelled = cancelled
        kind = "cancelled" if cancelled else "timeout"
        super().__init__(f"investigation {kind} at {self.stage} after {elapsed_s:.1f}s")


@dataclass
class InvestigationBudget:
    question: str = ""
    request_id: str = ""
    started_at: float = field(default_factory=time.monotonic)
    started_wall: float = field(default_factory=time.time)
    limit_s: float = HARD_LIMIT_SECONDS
    last_stage: str = "UNDERSTANDING"
    pipeline_stage: str = "UNDERSTANDING"
    cancelled: bool = False
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    sql_attempts: List[Dict[str, Any]] = field(default_factory=list)
    repairs: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    row_count: int = 0
    final_status: str = "running"

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_s(self) -> float:
        if self.cancelled:
            return 0.0
        return max(0.0, float(self.limit_s) - self.elapsed_s())

    def remaining_ms(self) -> int:
        return int(self.remaining_s() * 1000)

    def expired(self) -> bool:
        if self.cancelled:
            return True
        return self.elapsed_s() >= float(self.limit_s)

    def phase(self) -> str:
        rem = self.remaining_s()
        if rem <= 0:
            return "timeout"
        if rem < 20:
            return "closing"
        return "normal"

    def set_stage(self, stage: str) -> None:
        public = _STAGE_ALIASES.get(stage, stage.upper() if stage.isupper() else stage)
        if public in _STAGE_ALIASES.values() or public in {
            "UNDERSTANDING", "RETRIEVING_SCHEMA", "SELECTING_TABLES", "SELECTING_COLUMNS",
            "BUILDING_PLAN", "VALIDATING_PLAN", "GENERATING_SQL", "VALIDATING_SQL",
            "EXECUTING", "REPAIRING", "VALIDATING_RESULT", "COMPLETED", "TIMEOUT",
            "FAILED", "CANCELLED",
        }:
            self.pipeline_stage = public
        else:
            self.pipeline_stage = public or self.pipeline_stage
        self.last_stage = stage

    def checkpoint(self, stage: str) -> None:
        self.set_stage(stage)
        elapsed = self.elapsed_s()
        self.diagnostics.setdefault("stages", []).append(
            {"stage": stage, "pipeline_stage": self.pipeline_stage, "elapsed_s": round(elapsed, 3)}
        )
        logger.info(
            "[budget] id=%s stage=%s public=%s elapsed=%.1fs remaining=%.1fs cancelled=%s",
            self.request_id[:8],
            stage,
            self.pipeline_stage,
            elapsed,
            self.remaining_s(),
            self.cancelled,
        )
        if self.cancelled:
            self.final_status = "cancelled"
            self.pipeline_stage = "CANCELLED"
            raise InvestigationTimeout(stage, elapsed, cancelled=True)
        if self.expired():
            self.final_status = "timeout"
            self.pipeline_stage = "TIMEOUT"
            raise InvestigationTimeout(stage, elapsed)

    def llm_timeout_s(self, default: float = 90.0, floor: float = 3.0) -> float:
        rem = self.remaining_s()
        if rem <= floor:
            self.final_status = "timeout"
            self.pipeline_stage = "TIMEOUT"
            raise InvestigationTimeout("llm_timeout", self.elapsed_s())
        return max(floor, min(default, rem - 1.0))

    def statement_timeout_ms(self, default_ms: int = 20_000) -> int:
        rem_ms = self.remaining_ms()
        if rem_ms <= 0:
            return 1
        return max(1, min(int(default_ms), rem_ms))

    def allow_repair(self, attempt: int, max_attempts: int = 3) -> bool:
        if self.cancelled or self.expired():
            return False
        return attempt < max_attempts and self.remaining_s() > 2.0

    def allow_llm(self) -> bool:
        return (not self.cancelled) and self.remaining_s() > 3.0

    def prefer_simple_strategy(self) -> bool:
        return self.remaining_s() < 25.0

    def record_sql_attempt(
        self,
        *,
        attempt_number: int,
        failure_type: str = "",
        diagnosis: str = "",
        sql: str = "",
        changed_plan: bool = False,
    ) -> None:
        self.sql_attempts.append(
            {
                "attempt_number": attempt_number,
                "failure_type": failure_type,
                "diagnosis": diagnosis[:500],
                "sql": (sql or "")[:800],
                "changed_plan": changed_plan,
                "elapsed_s": round(self.elapsed_s(), 3),
            }
        )

    def public_status(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "pipeline_stage": self.pipeline_stage,
            "elapsed_s": round(self.elapsed_s(), 2),
            "remaining_s": round(self.remaining_s(), 2),
            "cancelled": self.cancelled,
            "timeout": (
                self.final_status == "timeout"
                or (
                    (not self.cancelled)
                    and self.expired()
                    and self.final_status not in {"completed", "cancelled", "cancelling"}
                )
            ),
            "status": self.final_status,
        }

    def trace(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "question": (self.question or "")[:500],
            "status": self.final_status,
            "started_at": self.started_wall,
            "deadline": self.started_wall + float(self.limit_s),
            "tables": list(self.tables),
            "columns": list(self.columns)[:80],
            "sql_attempts": self.sql_attempts,
            "repairs": self.repairs,
            "row_count": self.row_count,
            "latency_ms": int(self.elapsed_s() * 1000),
            "timeout": self.final_status == "timeout",
            "cancelled": self.cancelled,
            "pipeline_stage": self.pipeline_stage,
            "stages": list(self.diagnostics.get("stages") or []),
        }


def current_budget() -> Optional[InvestigationBudget]:
    return _CURRENT.get()


def get_investigation(request_id: str) -> Optional[InvestigationBudget]:
    if not request_id:
        return None
    with _REGISTRY_LOCK:
        return _REGISTRY.get(request_id)


def cancel_investigation(request_id: str) -> bool:
    rid = (request_id or "").strip()
    if not rid:
        return False
    with _REGISTRY_LOCK:
        budget = _REGISTRY.get(rid)
        if budget is None:
            # Case A: cancel before worker registration — park a cancelled placeholder.
            placeholder = InvestigationBudget(
                question="",
                request_id=rid,
                cancelled=True,
                final_status="cancelling",
                pipeline_stage="CANCELLING",
            )
            _REGISTRY[rid] = placeholder
            logger.info("[budget] pre-cancel registered request_id=%s", rid)
            return True
    # Case E: cancel after legitimate completion must not corrupt SUCCESS.
    if budget.final_status in {
        "completed", "success", "clarification", "cannot_answer", "timeout", "cancelled",
    }:
        return False
    budget.cancelled = True
    budget.final_status = "cancelling"
    budget.pipeline_stage = "CANCELLING"
    logger.info("[budget] cancel requested request_id=%s", rid)
    return True


def begin_investigation(
    question: str = "",
    limit_s: Optional[float] = None,
    request_id: str = "",
) -> InvestigationBudget:
    rid = (request_id or "").strip() or uuid.uuid4().hex
    limit = HARD_LIMIT_SECONDS if limit_s is None else float(limit_s)
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(rid)
        if existing is not None and existing.cancelled:
            existing.question = question or existing.question
            existing.limit_s = max(1.0, limit)
            existing.started_at = time.monotonic()
            existing.started_wall = time.time()
            existing.final_status = "cancelling"
            existing.pipeline_stage = "CANCELLING"
            budget = existing
        else:
            budget = InvestigationBudget(
                question=question or "",
                request_id=rid,
                limit_s=max(1.0, limit),
            )
            _REGISTRY[rid] = budget
        if len(_REGISTRY) > 500:
            stale = [
                k for k, v in _REGISTRY.items()
                if v.elapsed_s() > 600 and v.final_status not in {"running", "cancelling"}
            ]
            for k in stale[:200]:
                _REGISTRY.pop(k, None)
    _CURRENT.set(budget)
    logger.info(
        "[budget] start id=%s limit=%.0fs cancelled=%s question=%r",
        rid[:12],
        budget.limit_s,
        budget.cancelled,
        (question or "")[:120],
    )
    return budget


def end_investigation(status: str = "") -> None:
    budget = _CURRENT.get()
    if budget is not None:
        # Prefer CANCELLED over SUCCESS when cancel won the race before completion.
        if budget.cancelled and budget.final_status in {"running", "cancelling", "cancelled", ""}:
            budget.final_status = "cancelled"
            budget.pipeline_stage = "CANCELLED"
        elif status:
            budget.final_status = status
        elif budget.final_status == "running":
            budget.final_status = "completed"
            budget.pipeline_stage = "COMPLETED"
        logger.info(
            "[budget] end id=%s status=%s elapsed=%.1fs",
            budget.request_id[:12],
            budget.final_status,
            budget.elapsed_s(),
        )
    _CURRENT.set(None)


def checkpoint(stage: str) -> None:
    budget = current_budget()
    if budget is not None:
        budget.checkpoint(stage)


def timeout_response(
    stage: str = "",
    elapsed_s: float = 0.0,
    *,
    question: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    budget = current_budget()
    elapsed = elapsed_s or (budget.elapsed_s() if budget else 0.0)
    cancelled = bool(budget and budget.cancelled)
    msg = CANCELLED_USER_MESSAGE if cancelled else TIMEOUT_USER_MESSAGE
    status = "cancelled" if cancelled else "timeout"
    answer_status = "CANCELLED" if cancelled else "TIMEOUT"
    if budget is not None:
        budget.final_status = status
        budget.pipeline_stage = "CANCELLED" if cancelled else "TIMEOUT"
    logger.warning(
        "[budget] %s stage=%s elapsed=%.1fs question=%r",
        status.upper(),
        stage,
        elapsed,
        (question or (budget.question if budget else ""))[:160],
    )
    payload: Dict[str, Any] = {
        "sql": "",
        "rowCount": 0,
        "data": [],
        "summary": msg,
        "answer": msg,
        "answer_status": answer_status,
        "status": status,
        "mode": status,
        "type": "cancelled" if cancelled else "timeout",
        "pipeline": "investigation_budget",
        "sql_generation_method": status,
        "charts": [],
        "keyFindings": [],
        "degraded_fallback": False,
        "request_id": budget.request_id if budget else "",
        "pipeline_stage": "CANCELLED" if cancelled else "TIMEOUT",
        "meta": {
            "investigation_status": status,
            "timeout_stage": stage or (budget.last_stage if budget else ""),
            "elapsed_s": round(elapsed, 2),
            "request_id": budget.request_id if budget else "",
            "investigation_cancelled": cancelled,
        },
        "query_plan": {
            "investigation_timeout": not cancelled,
            "investigation_cancelled": cancelled,
            "timeout_stage": stage,
            "elapsed_s": round(elapsed, 2),
        },
    }
    if extra:
        payload.update(extra)
    return payload


def user_safe_pipeline_message(kind: str = "repair_failed") -> str:
    if kind == "timeout":
        return TIMEOUT_USER_MESSAGE
    if kind == "cancelled":
        return CANCELLED_USER_MESSAGE
    if kind == "data_limitation":
        return "The available data does not contain the information required to answer this."
    if kind == "repair_failed":
        return "I couldn't verify the requested analysis from the available database evidence."
    if kind == "semantic_mismatch":
        return "I couldn't verify the requested analysis from the available database evidence."
    if kind == "empty_success":
        return "No matching records were found for the requested period and condition."
    if kind == "clarification":
        return "I need one more detail to answer this accurately."
    if kind == "technical":
        return "The analysis could not be completed due to a technical problem."
    return "This analysis could not be completed from the verified schema."
