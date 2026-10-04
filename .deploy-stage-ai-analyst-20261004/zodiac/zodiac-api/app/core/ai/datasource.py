"""
Operational data source — the only path AI Ops uses to read facts (Phase 9).

Implementations must wrap monitoring services. They must not query invoice
processing tables or peek into live PipelineExecution state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from ..monitoring import (
    AlertService,
    MetricsStore,
    MonitoringDashboard,
    TimelineStore,
)


@runtime_checkable
class OperationalDataSource(Protocol):
    """Read-only monitoring façade for AI Ops."""

    def get_summary(self, workspace_id: str, *, limit: int = 100) -> Dict[str, Any]: ...

    def list_timelines(
        self,
        workspace_id: str,
        *,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...

    def list_metrics(self, workspace_id: str, *, limit: int = 200) -> List[Dict[str, Any]]: ...

    def list_alerts(self, workspace_id: str, *, limit: int = 50) -> List[Dict[str, Any]]: ...

    def get_ai_facts(self, workspace_id: str, *, limit: int = 100) -> List[Dict[str, Any]]: ...


class MonitoringOperationalDataSource:
    """
    Default datasource — delegates exclusively to Phase 8 monitoring stores.
    """

    def __init__(
        self,
        dashboard: Optional[MonitoringDashboard] = None,
        timeline: Optional[TimelineStore] = None,
        metrics: Optional[MetricsStore] = None,
        alerts: Optional[AlertService] = None,
    ):
        self.timeline = timeline or TimelineStore()
        self.metrics = metrics or MetricsStore()
        self.alerts = alerts or AlertService()
        self.dashboard = dashboard or MonitoringDashboard(
            timeline=self.timeline, metrics=self.metrics, alerts=self.alerts
        )

    @classmethod
    def from_db(cls, db: Optional[Session] = None) -> "MonitoringOperationalDataSource":
        timeline = TimelineStore(db=db)
        metrics = MetricsStore(db=db)
        alerts = AlertService(db=db)
        return cls(
            dashboard=MonitoringDashboard(
                timeline=timeline, metrics=metrics, alerts=alerts
            ),
            timeline=timeline,
            metrics=metrics,
            alerts=alerts,
        )

    def get_summary(self, workspace_id: str, *, limit: int = 100) -> Dict[str, Any]:
        return self.dashboard.summary(workspace_id, limit=limit)

    def list_timelines(
        self,
        workspace_id: str,
        *,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            t.to_dict()
            for t in self.timeline.list_for_workspace(
                workspace_id, limit=limit, status=status
            )
        ]

    def list_metrics(self, workspace_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
        return self.metrics.list_for_workspace(workspace_id, limit=limit)

    def list_alerts(self, workspace_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        return self.alerts.list_for_workspace(workspace_id, limit=limit)

    def get_ai_facts(self, workspace_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        return self.dashboard.ai_facts(workspace_id, limit=limit)
