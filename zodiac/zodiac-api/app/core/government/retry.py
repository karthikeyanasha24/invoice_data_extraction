"""Retry policy for government HTTP (Phase 7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

from .base import RETRYABLE_GOV_CODES, GovernmentStatus


@dataclass(frozen=True)
class GovernmentRetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 0.5
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    retryable_codes: FrozenSet[str] = field(default_factory=lambda: RETRYABLE_GOV_CODES)

    def should_retry(self, attempt: int, error_code: str, status: GovernmentStatus) -> bool:
        if attempt >= self.max_attempts:
            return False
        if status is GovernmentStatus.RETRY:
            return True
        if status in (GovernmentStatus.REJECTED, GovernmentStatus.ACCEPTED, GovernmentStatus.PENDING):
            return False
        return error_code in self.retryable_codes

    def delay_for(self, attempt: int) -> float:
        if self.initial_delay_seconds <= 0:
            return 0.0
        delay = self.initial_delay_seconds * (self.multiplier ** max(attempt - 1, 0))
        return min(delay, self.max_delay_seconds)


NO_GOV_RETRY = GovernmentRetryPolicy(max_attempts=1)
DEFAULT_GOV_RETRY = GovernmentRetryPolicy()
