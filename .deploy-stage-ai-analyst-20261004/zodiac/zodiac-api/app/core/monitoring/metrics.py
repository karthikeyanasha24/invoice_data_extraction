"""Metrics recording for pipeline monitoring (Phase 8)."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("zodiac-api.monitoring.metrics")


class MetricsStore:
    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self._memory: List[Dict[str, Any]] = []

    def record(
        self,
        *,
        customer_id: str,
        name: str,
        value: float,
        unit: Optional[str] = None,
        correlation_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = {
            "customer_id": customer_id,
            "name": name,
            "value": float(value),
            "unit": unit,
            "correlation_id": correlation_id,
            "tags": tags or {},
        }
        if self.db is None:
            self._memory.append(entry)
            return
        try:
            from ...models.monitoring import PipelineMetric

            self.db.add(
                PipelineMetric(
                    customer_id=customer_id,
                    correlation_id=correlation_id,
                    name=name,
                    value=float(value),
                    unit=unit,
                    tags=tags or None,
                )
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Metric persist failed: %s", exc)
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            self._memory.append(entry)

    def list_for_workspace(self, customer_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
        if self.db is None:
            return [m for m in self._memory if m["customer_id"] == customer_id][-limit:]
        try:
            from ...models.monitoring import PipelineMetric

            rows = (
                self.db.query(PipelineMetric)
                .filter(PipelineMetric.customer_id == customer_id)
                .order_by(PipelineMetric.recorded_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "customer_id": r.customer_id,
                    "name": r.name,
                    "value": r.value,
                    "unit": r.unit,
                    "correlation_id": r.correlation_id,
                    "tags": r.tags or {},
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Metric list failed: %s", exc)
            return []
