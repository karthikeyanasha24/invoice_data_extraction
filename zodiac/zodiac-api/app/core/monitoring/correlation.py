"""Correlation ID helpers (Phase 8)."""
from __future__ import annotations

import uuid
from typing import Optional


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def ensure_correlation_id(value: Optional[str]) -> str:
    if value and str(value).strip():
        return str(value).strip()
    return new_correlation_id()
