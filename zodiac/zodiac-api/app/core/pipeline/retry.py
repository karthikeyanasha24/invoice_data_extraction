"""
Retry policy (Phase 4).

Retry is a platform responsibility, not a country one: an adapter reports a
stable `error_code` and the orchestrator decides whether to try again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

#: Codes that are usually worth another attempt (transport, not content).
DEFAULT_RETRYABLE_CODES: FrozenSet[str] = frozenset(
    {"SUBMIT_FAILED", "TIMEOUT", "TRANSIENT", "ERP_UPDATE_FAILED", "ERP_TIMEOUT"}
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    initial_delay_seconds: float = 0.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    retryable_codes: FrozenSet[str] = field(default_factory=lambda: DEFAULT_RETRYABLE_CODES)

    def should_retry(self, attempt: int, error_code: str) -> bool:
        """`attempt` is 1-based and counts the try that just failed."""
        if attempt >= self.max_attempts:
            return False
        if not self.retryable_codes:
            return True
        return error_code in self.retryable_codes

    def delay_for(self, attempt: int) -> float:
        if self.initial_delay_seconds <= 0:
            return 0.0
        delay = self.initial_delay_seconds * (self.multiplier ** max(attempt - 1, 0))
        return min(delay, self.max_delay_seconds)


#: Default for every stage: run once, surface the failure.
NO_RETRY = RetryPolicy(max_attempts=1)

#: Sensible default for network-bound stages, opt-in per plan.
TRANSPORT_RETRY = RetryPolicy(max_attempts=3, initial_delay_seconds=0.5)
