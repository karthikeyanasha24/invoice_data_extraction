"""
BridgeEDI Core — Enterprise Monitoring & Observability (Phase 8).

Observes the invoice pipeline without changing country / ERP / government logic.
"""
from .alerts import (
    Alert,
    AlertService,
    AlertSeverity,
    AlertType,
    EmailAlertChannel,
    LogAlertChannel,
    SlackAlertChannel,
    WebhookAlertChannel,
)
from .correlation import ensure_correlation_id, new_correlation_id
from .dashboard import MonitoringDashboard
from .events import MonitoringEvent, TimelineStage, TransactionTimeline
from .metrics import MetricsStore
from .sinks import PersistingAuditSink, PersistingMonitoringSink, build_default_monitoring_bundle
from .status import TransactionStatus
from .timeline import TimelineStore

__all__ = [
    "MonitoringEvent",
    "TimelineStage",
    "TransactionTimeline",
    "TimelineStore",
    "MetricsStore",
    "Alert",
    "AlertService",
    "AlertType",
    "AlertSeverity",
    "LogAlertChannel",
    "EmailAlertChannel",
    "SlackAlertChannel",
    "WebhookAlertChannel",
    "MonitoringDashboard",
    "PersistingAuditSink",
    "PersistingMonitoringSink",
    "build_default_monitoring_bundle",
    "TransactionStatus",
    "new_correlation_id",
    "ensure_correlation_id",
]
