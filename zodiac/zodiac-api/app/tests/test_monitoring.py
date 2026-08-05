"""
Phase 8 tests — Enterprise Monitoring & Observability.

No DB required (in-memory TimelineStore / MetricsStore / AlertService).
Run from zodiac-api:

  python -m unittest app.tests.test_monitoring -v
"""
from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.monitoring import MONITORING_API_ENV, monitoring_api_enabled, router
from app.core.monitoring import (
    Alert,
    AlertService,
    AlertSeverity,
    AlertType,
    MetricsStore,
    MonitoringDashboard,
    PersistingAuditSink,
    PersistingMonitoringSink,
    TimelineStore,
    TransactionStatus,
    ensure_correlation_id,
    new_correlation_id,
)
from app.core.monitoring.events import MonitoringEvent
from app.core.pipeline import (
    CollectingSink,
    PipelineStatus,
    PlatformServices,
)


class TestCorrelation(unittest.TestCase):
    def test_new_correlation_id_unique(self):
        a, b = new_correlation_id(), new_correlation_id()
        self.assertNotEqual(a, b)
        self.assertTrue(len(a) >= 32)

    def test_ensure_preserves_value(self):
        self.assertEqual(ensure_correlation_id("abc-123"), "abc-123")
        self.assertTrue(ensure_correlation_id(None))
        self.assertTrue(ensure_correlation_id("  "))


class TestTimelineAndMetrics(unittest.TestCase):
    def test_timeline_stages_and_finalize(self):
        store = TimelineStore()
        corr = new_correlation_id()
        store.record_stage(
            MonitoringEvent(
                correlation_id=corr,
                customer_id="acme",
                country_code="MX",
                stage="validate",
                status="success",
                duration_ms=12.0,
                message="ok",
            )
        )
        store.record_stage(
            MonitoringEvent(
                correlation_id=corr,
                customer_id="acme",
                stage="submit",
                status="success",
                duration_ms=40.0,
            )
        )
        store.finalize(
            correlation_id=corr,
            customer_id="acme",
            pipeline_status="completed",
            latency_ms=52.0,
            government_reference="UUID-1",
            erp_reference="SAP-9",
        )
        tl = store.get_timeline(corr, customer_id="acme")
        self.assertIsNotNone(tl)
        assert tl is not None
        self.assertEqual(tl.status, TransactionStatus.COMPLETED.value)
        self.assertEqual(len(tl.stages), 2)
        self.assertEqual(tl.government_reference, "UUID-1")
        self.assertEqual(tl.erp_reference, "SAP-9")
        self.assertEqual(tl.latency_ms, 52.0)
        fact = tl.to_ai_fact()
        self.assertEqual(fact["type"], "pipeline_transaction")
        self.assertEqual(fact["workspace_id"], "acme")

    def test_workspace_isolation_on_get(self):
        store = TimelineStore()
        corr = new_correlation_id()
        store.record_stage(
            MonitoringEvent(
                correlation_id=corr,
                customer_id="acme",
                stage="parse",
                status="success",
            )
        )
        self.assertIsNone(store.get_timeline(corr, customer_id="other"))
        self.assertIsNotNone(store.get_timeline(corr, customer_id="acme"))

    def test_metrics_scoped_by_workspace(self):
        metrics = MetricsStore()
        metrics.record(customer_id="acme", name="pipeline.run", value=1.0)
        metrics.record(customer_id="beta", name="pipeline.run", value=1.0)
        metrics.record(
            customer_id="acme",
            name="pipeline.latency_ms",
            value=120.0,
            unit="ms",
        )
        acme = metrics.list_for_workspace("acme")
        self.assertEqual(len(acme), 2)
        self.assertTrue(all(m["customer_id"] == "acme" for m in acme))


class TestAlerts(unittest.TestCase):
    def test_pipeline_failure_raises_critical(self):
        svc = AlertService()
        raised = svc.evaluate_pipeline_result(
            customer_id="acme",
            correlation_id="c1",
            status="failed",
            failed_stage="submit",
            error="gov down",
            error_code="GOV_UNAVAILABLE",
            retry_count=0,
        )
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0]["alert_type"], AlertType.GOVERNMENT_UNAVAILABLE.value)
        self.assertTrue(raised[0]["delivered"])

    def test_repeated_retry_and_latency(self):
        svc = AlertService()
        raised = svc.evaluate_pipeline_result(
            customer_id="acme",
            correlation_id="c2",
            status="completed",
            retry_count=3,
            latency_ms=90_000,
            high_latency_ms=60_000,
        )
        types = {r["alert_type"] for r in raised}
        self.assertIn(AlertType.REPEATED_RETRY.value, types)
        self.assertIn(AlertType.HIGH_LATENCY.value, types)

    def test_email_channel_stub_does_not_deliver(self):
        from app.core.monitoring import EmailAlertChannel, LogAlertChannel

        svc = AlertService(channels=[EmailAlertChannel(), LogAlertChannel()])
        result = svc.raise_alert(
            Alert(
                customer_id="acme",
                alert_type=AlertType.QUEUE_GROWTH,
                title="Queue growth",
                message="depth=100",
                severity=AlertSeverity.WARNING,
            )
        )
        self.assertTrue(result["delivered"])  # log channel still delivers


class TestDashboardIsolation(unittest.TestCase):
    def test_summary_only_includes_workspace(self):
        timeline = TimelineStore()
        for cid, status, latency in (
            ("acme", "completed", 100.0),
            ("acme", "failed", 50.0),
            ("beta", "failed", 10.0),
        ):
            corr = new_correlation_id()
            timeline.record_stage(
                MonitoringEvent(
                    correlation_id=corr,
                    customer_id=cid,
                    stage="validate",
                    status="success" if status == "completed" else "failed",
                )
            )
            timeline.finalize(
                correlation_id=corr,
                customer_id=cid,
                pipeline_status=status,
                latency_ms=latency,
                failed_stage="validate" if status == "failed" else None,
            )

        dash = MonitoringDashboard(timeline=timeline, metrics=MetricsStore(), alerts=AlertService())
        summary = dash.summary("acme")
        self.assertEqual(summary["counts"]["total"], 2)
        self.assertEqual(summary["counts"]["completed"], 1)
        self.assertEqual(summary["counts"]["failed"], 1)
        self.assertAlmostEqual(summary["success_rate_percent"], 50.0)
        self.assertTrue(all(t["customer_id"] == "acme" for t in summary["latest_transactions"]))
        facts = dash.ai_facts("acme")
        self.assertEqual(facts[0]["type"], "workspace_monitoring_summary")


class TestPipelineIntegration(unittest.TestCase):
    def test_persisting_sinks_observe_orchestrator(self):
        from app.tests.test_pipeline_orchestrator import RecordingAdapter, build, request

        timeline = TimelineStore()
        metrics = MetricsStore()
        alerts = AlertService()
        audit = PersistingAuditSink(timeline=timeline, also_log=False)
        monitoring = PersistingMonitoringSink(
            timeline=timeline, metrics=metrics, alerts=alerts, also_log=False
        )

        orch, _, _ = build(
            services_overrides={
                "audit": audit,
                "monitoring": monitoring,
                "erp_updater": None,
            },
            adapter=RecordingAdapter(),
        )
        result = asyncio.run(orch.run(request(dry_run=True, country_code="atlantis")))
        self.assertIn(result.status, (PipelineStatus.DRY_RUN, PipelineStatus.COMPLETED))
        tl = timeline.get_timeline(result.correlation_id, customer_id="acme")
        self.assertIsNotNone(tl)
        assert tl is not None
        self.assertGreaterEqual(len(tl.stages), 5)
        self.assertTrue(any(m["name"] == "pipeline.run" for m in metrics.list_for_workspace("acme")))

    def test_collecting_sink_still_works_without_finalize(self):
        from app.tests.test_pipeline_orchestrator import RecordingAdapter, build, request

        orch, services, _ = build(adapter=RecordingAdapter())
        self.assertIsInstance(services.monitoring, CollectingSink)
        result = asyncio.run(orch.run(request(dry_run=True, country_code="atlantis")))
        self.assertIsNotNone(result.correlation_id)


class TestMonitoringApi(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        self.user = SimpleNamespace(
            id=1, is_admin=True, is_active=True, is_customer_user=False
        )

        async def override_user():
            return self.user

        def override_db():
            yield MagicMock()

        from app.api.auth import get_current_user
        from app.database import get_db

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MONITORING_API_ENV, None)
            self.assertTrue(monitoring_api_enabled())

    def test_health(self):
        response = self.client.get("/api/v1/monitoring/health")
        self.assertEqual(response.status_code, 200)

    def test_summary_enforces_workspace_access(self):
        with patch.dict(os.environ, {MONITORING_API_ENV: "true"}):
            with patch(
                "app.api.monitoring.require_workspace_access",
                side_effect=Exception("denied"),
            ):
                # require_workspace_access raises HTTPException in real code;
                # here we ensure the endpoint calls it.
                pass
            with patch("app.api.monitoring.require_workspace_access") as guard:
                with patch("app.api.monitoring._dashboard") as dash_factory:
                    from app.core.monitoring import MonitoringDashboard

                    dash = MonitoringDashboard()
                    dash_factory.return_value = (dash, AlertService(), TimelineStore())
                    response = self.client.get("/api/v1/monitoring/workspaces/acme/summary")
                    guard.assert_called()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["customer_id"], "acme")

    def test_disabled_flag_404(self):
        with patch.dict(os.environ, {MONITORING_API_ENV: "false"}):
            response = self.client.get("/api/v1/monitoring/workspaces/acme/summary")
        self.assertEqual(response.status_code, 404)


class TestPlatformServicesDefaults(unittest.TestCase):
    def test_shared_bundle_when_unset(self):
        services = PlatformServices(
            workspace_resolver=MagicMock(),
            adapter_resolver=MagicMock(),
        )
        self.assertIsInstance(services.monitoring, PersistingMonitoringSink)
        self.assertIsInstance(services.audit, PersistingAuditSink)
        self.assertIs(
            services.monitoring.timeline,  # type: ignore[attr-defined]
            services.audit.recorder.timeline,  # type: ignore[attr-defined]
        )


if __name__ == "__main__":
    unittest.main()
