"""
Alert framework (Phase 8).

Default delivery: structured logs (+ optional webhook when ALERT_WEBHOOK_URL is set).
Email/Slack remain stubs until SMTP/Slack tokens are wired.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("zodiac-api.monitoring.alerts")


class AlertType(str, Enum):
    PIPELINE_FAILURE = "pipeline_failure"
    GOVERNMENT_UNAVAILABLE = "government_unavailable"
    ERP_UNAVAILABLE = "erp_unavailable"
    REPEATED_RETRY = "repeated_retry"
    HIGH_LATENCY = "high_latency"
    QUEUE_GROWTH = "queue_growth"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    customer_id: str
    alert_type: AlertType
    title: str
    message: str
    severity: AlertSeverity = AlertSeverity.WARNING
    correlation_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "workspace_id": self.customer_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "correlation_id": self.correlation_id,
            "payload": dict(self.payload),
        }


class AlertChannel(ABC):
    name: str = "base"

    @abstractmethod
    def deliver(self, alert: Alert) -> bool: ...


class LogAlertChannel(AlertChannel):
    name = "log"

    def deliver(self, alert: Alert) -> bool:
        logger.warning(
            "[alert:%s] workspace=%s type=%s title=%s corr=%s",
            alert.severity.value,
            alert.customer_id,
            alert.alert_type.value,
            alert.title,
            alert.correlation_id,
        )
        return True


class EmailAlertChannel(AlertChannel):
    """Stub — not wired to SMTP in Phase 8."""

    name = "email"

    def deliver(self, alert: Alert) -> bool:
        logger.info("[alert:email:stub] would send: %s", alert.title)
        return False


class SlackAlertChannel(AlertChannel):
    """Future stub."""

    name = "slack"

    def deliver(self, alert: Alert) -> bool:
        logger.info("[alert:slack:stub] would send: %s", alert.title)
        return False


class WebhookAlertChannel(AlertChannel):
    """
    Posts JSON alert payload when ALERT_WEBHOOK_URL is configured.
    Why: pilot ops need a real paging path without redesigning Phase 8.
    Rollback: unset ALERT_WEBHOOK_URL → falls back to stub log only.
    """

    name = "webhook"

    def deliver(self, alert: Alert) -> bool:
        url = (os.environ.get("ALERT_WEBHOOK_URL") or "").strip()
        if not url:
            logger.info("[alert:webhook:stub] would send: %s", alert.title)
            return False
        body = json.dumps(alert.to_dict()).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                ok = 200 <= getattr(resp, "status", 200) < 300
            if ok:
                logger.info("[alert:webhook] delivered type=%s", alert.alert_type.value)
            return ok
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("[alert:webhook] delivery failed: %s", type(exc).__name__)
            return False


def default_alert_channels() -> List[AlertChannel]:
    channels: List[AlertChannel] = [LogAlertChannel()]
    if (os.environ.get("ALERT_WEBHOOK_URL") or "").strip():
        channels.append(WebhookAlertChannel())
    return channels


class AlertService:
    def __init__(
        self,
        db: Optional[Session] = None,
        channels: Optional[List[AlertChannel]] = None,
    ):
        self.db = db
        self.channels = channels or default_alert_channels()
        self._history: List[Dict[str, Any]] = []

    def raise_alert(self, alert: Alert) -> Dict[str, Any]:
        delivered_any = False
        channel_names = []
        for channel in self.channels:
            try:
                ok = channel.deliver(alert)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alert channel %s failed: %s", channel.name, exc)
                ok = False
            channel_names.append(channel.name)
            delivered_any = delivered_any or ok
            self._persist(alert, channel=channel.name, delivered=ok)
        result = {**alert.to_dict(), "channels": channel_names, "delivered": delivered_any}
        self._history.append(result)
        return result

    def evaluate_pipeline_result(
        self,
        *,
        customer_id: str,
        correlation_id: str,
        status: str,
        failed_stage: Optional[str] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        retry_count: int = 0,
        latency_ms: Optional[float] = None,
        high_latency_ms: float = 60_000.0,
    ) -> List[Dict[str, Any]]:
        """Derive alerts from a finished pipeline run — no business logic changes."""
        raised: List[Dict[str, Any]] = []
        if (status or "").lower() == "failed":
            code = (error_code or "").upper()
            if "GOV_" in code or "GOVERNMENT" in code:
                alert_type = AlertType.GOVERNMENT_UNAVAILABLE
            elif "ERP_" in code:
                alert_type = AlertType.ERP_UNAVAILABLE
            else:
                alert_type = AlertType.PIPELINE_FAILURE
            raised.append(
                self.raise_alert(
                    Alert(
                        customer_id=customer_id,
                        correlation_id=correlation_id,
                        alert_type=alert_type,
                        severity=AlertSeverity.CRITICAL,
                        title=f"Pipeline {alert_type.value}",
                        message=error or f"Failed at stage {failed_stage}",
                        payload={"failed_stage": failed_stage, "error_code": error_code},
                    )
                )
            )
        if retry_count >= 2:
            raised.append(
                self.raise_alert(
                    Alert(
                        customer_id=customer_id,
                        correlation_id=correlation_id,
                        alert_type=AlertType.REPEATED_RETRY,
                        severity=AlertSeverity.WARNING,
                        title="Repeated pipeline retries",
                        message=f"Retry count reached {retry_count}",
                        payload={"retry_count": retry_count},
                    )
                )
            )
        if latency_ms is not None and latency_ms >= high_latency_ms:
            raised.append(
                self.raise_alert(
                    Alert(
                        customer_id=customer_id,
                        correlation_id=correlation_id,
                        alert_type=AlertType.HIGH_LATENCY,
                        severity=AlertSeverity.WARNING,
                        title="High pipeline latency",
                        message=f"Latency {latency_ms:.0f}ms exceeded threshold {high_latency_ms:.0f}ms",
                        payload={"latency_ms": latency_ms},
                    )
                )
            )
        return raised

    def list_for_workspace(self, customer_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        if self.db is None:
            return [h for h in self._history if h.get("customer_id") == customer_id][-limit:]
        try:
            from ...models.monitoring import AlertHistory

            rows = (
                self.db.query(AlertHistory)
                .filter(AlertHistory.customer_id == customer_id)
                .order_by(AlertHistory.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "customer_id": r.customer_id,
                    "correlation_id": r.correlation_id,
                    "alert_type": r.alert_type,
                    "severity": r.severity,
                    "title": r.title,
                    "message": r.message,
                    "channel": r.channel,
                    "delivered": r.delivered,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alert list failed: %s", exc)
            return []

    def _persist(self, alert: Alert, *, channel: str, delivered: bool) -> None:
        if self.db is None:
            return
        try:
            from ...models.monitoring import AlertHistory

            self.db.add(
                AlertHistory(
                    customer_id=alert.customer_id,
                    correlation_id=alert.correlation_id,
                    alert_type=alert.alert_type.value,
                    severity=alert.severity.value,
                    title=alert.title,
                    message=alert.message,
                    channel=channel,
                    delivered=delivered,
                    payload=alert.payload or None,
                )
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alert persist failed: %s", exc)
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
