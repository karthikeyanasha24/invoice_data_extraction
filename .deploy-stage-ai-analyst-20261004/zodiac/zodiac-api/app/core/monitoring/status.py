"""Transaction status vocabulary for pipeline monitoring (Phase 8)."""
from __future__ import annotations

from enum import Enum


class TransactionStatus(str, Enum):
    RUNNING = "RUNNING"
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DRY_RUN = "DRY_RUN"


class StageEventStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


def map_pipeline_status(status: str) -> TransactionStatus:
    value = (status or "").lower()
    if value in ("completed", "success"):
        return TransactionStatus.COMPLETED
    if value in ("failed", "error"):
        return TransactionStatus.FAILED
    if value in ("dry_run", "dry-run"):
        return TransactionStatus.DRY_RUN
    if value in ("retrying", "retry"):
        return TransactionStatus.RETRYING
    if value in ("pending",):
        return TransactionStatus.PENDING
    return TransactionStatus.RUNNING
