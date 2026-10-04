"""Audit trail helpers that mirror pipeline AuditSink entries (Phase 8)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .events import MonitoringEvent
from .timeline import TimelineStore

logger = logging.getLogger("zodiac-api.monitoring.audit")


class AuditRecorder:
    """Records stage audit entries into the timeline store."""

    def __init__(self, timeline: Optional[TimelineStore] = None):
        self.timeline = timeline or TimelineStore()
        self._entries: List[Dict[str, Any]] = []

    def record(self, entry: Dict[str, Any]) -> None:
        self._entries.append(dict(entry))
        try:
            event = MonitoringEvent.from_audit_entry(entry)
            if event.correlation_id and event.customer_id:
                self.timeline.record_stage(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audit record failed: %s", exc)

    @property
    def entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)
