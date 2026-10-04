"""
ERP push outbox helpers (Phase 6).

Model lives in app.models.erp_outbox; this module owns persistence helpers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ...models.erp_outbox import ErpPushOutbox

logger = logging.getLogger("zodiac-api.erp.outbox")

OUTBOX_PENDING = "PENDING"
OUTBOX_SUCCESS = "SUCCESS"
OUTBOX_FAILED = "FAILED"

__all__ = [
    "ErpPushOutbox",
    "OUTBOX_PENDING",
    "OUTBOX_SUCCESS",
    "OUTBOX_FAILED",
    "get_by_idempotency_key",
    "begin_attempt",
    "mark_success",
    "mark_failed",
]


def get_by_idempotency_key(db: Session, idempotency_key: str) -> Optional[ErpPushOutbox]:
    return (
        db.query(ErpPushOutbox)
        .filter(ErpPushOutbox.idempotency_key == idempotency_key)
        .first()
    )


def begin_attempt(
    db: Session,
    *,
    idempotency_key: str,
    customer_id: str,
    correlation_id: str,
    connection_key: str,
    request_hash: Optional[str] = None,
) -> ErpPushOutbox:
    """Insert or reuse a PENDING/FAILED row and increment attempt_count."""
    row = get_by_idempotency_key(db, idempotency_key)
    if row is None:
        row = ErpPushOutbox(
            idempotency_key=idempotency_key,
            customer_id=customer_id,
            correlation_id=correlation_id,
            connection_key=connection_key,
            status=OUTBOX_PENDING,
            request_hash=request_hash,
            attempt_count=1,
        )
        db.add(row)
    else:
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.status = OUTBOX_PENDING
        row.request_hash = request_hash or row.request_hash
        row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def mark_success(db: Session, row: ErpPushOutbox, response_body: Any = None) -> ErpPushOutbox:
    row.status = OUTBOX_SUCCESS
    row.response_body = _serialize(response_body)
    row.last_error = None
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def mark_failed(db: Session, row: ErpPushOutbox, error: str, response_body: Any = None) -> ErpPushOutbox:
    row.status = OUTBOX_FAILED
    row.last_error = (error or "")[:2000]
    if response_body is not None:
        row.response_body = _serialize(response_body)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def _serialize(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:8000]
    try:
        return json.dumps(value, default=str)[:8000]
    except Exception:  # noqa: BLE001
        return str(value)[:8000]
