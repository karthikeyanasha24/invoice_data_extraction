"""Timeline persistence and reconstruction (Phase 8)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .events import MonitoringEvent, TimelineStage, TransactionTimeline
from .status import TransactionStatus, map_pipeline_status

logger = logging.getLogger("zodiac-api.monitoring.timeline")


class TimelineStore:
    """Persists / loads pipeline timelines. Safe no-op when db is None."""

    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self._memory: Dict[str, TransactionTimeline] = {}

    def record_stage(self, event: MonitoringEvent) -> None:
        if self.db is None:
            self._record_memory(event)
            return
        try:
            from ...models.monitoring import PipelineEvent, PipelineTimeline

            row = (
                self.db.query(PipelineTimeline)
                .filter(PipelineTimeline.correlation_id == event.correlation_id)
                .first()
            )
            if row is None:
                row = PipelineTimeline(
                    correlation_id=event.correlation_id,
                    customer_id=event.customer_id,
                    country_code=event.country_code,
                    adapter_name=event.adapter_name,
                    document_type=event.document_type,
                    status=TransactionStatus.RUNNING.value,
                    current_stage=event.stage,
                    started_at=event.occurred_at.replace(tzinfo=None)
                    if event.occurred_at.tzinfo
                    else event.occurred_at,
                )
                self.db.add(row)
            else:
                row.current_stage = event.stage
                row.country_code = event.country_code or row.country_code
                if event.attempt and event.attempt > 1:
                    row.retry_count = int(row.retry_count or 0) + 1
                if event.status == "failed":
                    row.status = TransactionStatus.FAILED.value
                    row.failure_reason = event.message
                    row.failed_stage = event.stage
                elif event.attempt and event.attempt > 1 and row.status != TransactionStatus.FAILED.value:
                    row.status = TransactionStatus.RETRYING.value

            if event.government_reference:
                row.government_reference = event.government_reference
            if event.erp_reference:
                row.erp_reference = event.erp_reference

            self.db.add(
                PipelineEvent(
                    correlation_id=event.correlation_id,
                    customer_id=event.customer_id,
                    country_code=event.country_code,
                    stage=event.stage,
                    status=event.status,
                    message=event.message,
                    duration_ms=event.duration_ms,
                    attempt=event.attempt,
                    error_code=event.error_code,
                    payload=event.extras or None,
                    occurred_at=event.occurred_at.replace(tzinfo=None)
                    if getattr(event.occurred_at, "tzinfo", None)
                    else event.occurred_at,
                )
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - monitoring must never break pipeline
            logger.warning("Timeline persist failed: %s", exc)
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            self._record_memory(event)

    def finalize(
        self,
        *,
        correlation_id: str,
        customer_id: str,
        pipeline_status: str,
        latency_ms: Optional[float] = None,
        failure_reason: Optional[str] = None,
        failed_stage: Optional[str] = None,
        government_reference: Optional[str] = None,
        erp_reference: Optional[str] = None,
        country_code: Optional[str] = None,
        adapter_name: Optional[str] = None,
    ) -> None:
        status = map_pipeline_status(pipeline_status)
        if self.db is None:
            tl = self._memory.get(correlation_id)
            if tl is None:
                tl = TransactionTimeline(
                    correlation_id=correlation_id,
                    customer_id=customer_id,
                    country_code=country_code,
                    adapter_name=adapter_name,
                    status=status.value,
                )
                self._memory[correlation_id] = tl
            tl.status = status.value
            tl.latency_ms = latency_ms
            tl.failure_reason = failure_reason
            tl.failed_stage = failed_stage
            if government_reference:
                tl.government_reference = government_reference
            if erp_reference:
                tl.erp_reference = erp_reference
            if country_code:
                tl.country_code = country_code
            if adapter_name:
                tl.adapter_name = adapter_name
            tl.completed_at = datetime.utcnow().isoformat()
            return
        try:
            from ...models.monitoring import PipelineTimeline

            row = (
                self.db.query(PipelineTimeline)
                .filter(PipelineTimeline.correlation_id == correlation_id)
                .first()
            )
            if row is None:
                row = PipelineTimeline(
                    correlation_id=correlation_id,
                    customer_id=customer_id,
                    country_code=country_code,
                    adapter_name=adapter_name,
                )
                self.db.add(row)
            row.status = status.value
            row.latency_ms = latency_ms
            row.failure_reason = failure_reason or row.failure_reason
            row.failed_stage = failed_stage or row.failed_stage
            if government_reference:
                row.government_reference = government_reference
            if erp_reference:
                row.erp_reference = erp_reference
            row.completed_at = datetime.utcnow()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timeline finalize failed: %s", exc)
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass

    def get_timeline(self, correlation_id: str, customer_id: Optional[str] = None) -> Optional[TransactionTimeline]:
        if self.db is None:
            tl = self._memory.get(correlation_id)
            if tl and customer_id and tl.customer_id != customer_id:
                return None
            return tl
        try:
            from ...models.monitoring import PipelineEvent, PipelineTimeline

            q = self.db.query(PipelineTimeline).filter(
                PipelineTimeline.correlation_id == correlation_id
            )
            if customer_id:
                q = q.filter(PipelineTimeline.customer_id == customer_id)
            row = q.first()
            if row is None:
                return None
            events = (
                self.db.query(PipelineEvent)
                .filter(PipelineEvent.correlation_id == correlation_id)
                .order_by(PipelineEvent.occurred_at.asc(), PipelineEvent.id.asc())
                .all()
            )
            return self._row_to_timeline(row, events)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timeline load failed: %s", exc)
            return self._memory.get(correlation_id)

    def list_for_workspace(
        self, customer_id: str, *, limit: int = 50, status: Optional[str] = None
    ) -> List[TransactionTimeline]:
        if self.db is None:
            items = [t for t in self._memory.values() if t.customer_id == customer_id]
            if status:
                items = [t for t in items if t.status == status]
            return items[:limit]
        try:
            from ...models.monitoring import PipelineEvent, PipelineTimeline

            q = self.db.query(PipelineTimeline).filter(
                PipelineTimeline.customer_id == customer_id
            )
            if status:
                q = q.filter(PipelineTimeline.status == status)
            rows = q.order_by(PipelineTimeline.started_at.desc()).limit(limit).all()
            result = []
            for row in rows:
                events = (
                    self.db.query(PipelineEvent)
                    .filter(PipelineEvent.correlation_id == row.correlation_id)
                    .order_by(PipelineEvent.occurred_at.asc())
                    .all()
                )
                result.append(self._row_to_timeline(row, events))
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timeline list failed: %s", exc)
            return []

    def _record_memory(self, event: MonitoringEvent) -> None:
        tl = self._memory.get(event.correlation_id)
        if tl is None:
            tl = TransactionTimeline(
                correlation_id=event.correlation_id,
                customer_id=event.customer_id,
                country_code=event.country_code,
                adapter_name=event.adapter_name,
                document_type=event.document_type,
                status=TransactionStatus.RUNNING.value,
                started_at=event.occurred_at.isoformat(),
            )
            self._memory[event.correlation_id] = tl
        tl.current_stage = event.stage
        if event.attempt > 1:
            tl.retry_count += 1
        if event.status == "failed":
            tl.status = TransactionStatus.FAILED.value
            tl.failure_reason = event.message
            tl.failed_stage = event.stage
        if event.government_reference:
            tl.government_reference = event.government_reference
        if event.erp_reference:
            tl.erp_reference = event.erp_reference
        tl.stages.append(
            TimelineStage(
                stage=event.stage,
                status=event.status,
                timestamp=event.occurred_at.isoformat(),
                duration_ms=event.duration_ms,
                message=event.message,
                attempt=event.attempt,
                error_code=event.error_code,
            )
        )

    @staticmethod
    def _row_to_timeline(row: Any, events: List[Any]) -> TransactionTimeline:
        stages = [
            TimelineStage(
                stage=e.stage,
                status=e.status,
                timestamp=e.occurred_at.isoformat() if e.occurred_at else "",
                duration_ms=e.duration_ms,
                message=e.message,
                attempt=e.attempt or 1,
                error_code=e.error_code,
            )
            for e in events
        ]
        return TransactionTimeline(
            correlation_id=row.correlation_id,
            customer_id=row.customer_id,
            country_code=row.country_code,
            adapter_name=row.adapter_name,
            document_type=row.document_type,
            status=row.status,
            current_stage=row.current_stage,
            retry_count=int(row.retry_count or 0),
            latency_ms=row.latency_ms,
            failure_reason=row.failure_reason,
            failed_stage=row.failed_stage,
            government_reference=row.government_reference,
            erp_reference=row.erp_reference,
            started_at=row.started_at.isoformat() if row.started_at else None,
            completed_at=row.completed_at.isoformat() if row.completed_at else None,
            stages=stages,
        )
