"""
Phase 9 tests — AI Operational Intelligence.

Uses in-memory monitoring stores. Does not touch adaptive_query / invoice tables.
Run from zodiac-api:

  python -m unittest app.tests.test_ai_ops -v
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.ai_ops import AI_OPS_API_ENV, ai_ops_api_enabled, router
from app.core.ai import (
    AiOpsSecurity,
    MonitoringOperationalDataSource,
    OperationalAnalytics,
    OperationalQueryService,
    OperationalSummarizer,
    RecommendationEngine,
)
from app.core.monitoring import (
    Alert,
    AlertService,
    AlertSeverity,
    AlertType,
    MetricsStore,
    TimelineStore,
    new_correlation_id,
)
from app.core.monitoring.events import MonitoringEvent


def _seed_workspace(source: MonitoringOperationalDataSource, workspace_id: str, *, failed: bool = False):
    corr = new_correlation_id()
    now = datetime.now(timezone.utc)
    source.timeline.record_stage(
        MonitoringEvent(
            correlation_id=corr,
            customer_id=workspace_id,
            stage="validate",
            status="failed" if failed else "success",
            message="bad rfc" if failed else "ok",
            duration_ms=15.0,
            occurred_at=now,
        )
    )
    if failed:
        source.timeline.record_stage(
            MonitoringEvent(
                correlation_id=corr,
                customer_id=workspace_id,
                stage="validate",
                status="failed",
                message="bad rfc",
                occurred_at=now,
            )
        )
        source.timeline.finalize(
            correlation_id=corr,
            customer_id=workspace_id,
            pipeline_status="failed",
            latency_ms=40.0,
            failure_reason="bad rfc",
            failed_stage="validate",
        )
        source.alerts.raise_alert(
            Alert(
                customer_id=workspace_id,
                correlation_id=corr,
                alert_type=AlertType.PIPELINE_FAILURE,
                severity=AlertSeverity.CRITICAL,
                title="Pipeline failure",
                message="bad rfc",
            )
        )
    else:
        source.timeline.finalize(
            correlation_id=corr,
            customer_id=workspace_id,
            pipeline_status="completed",
            latency_ms=120.0,
            government_reference="G-1",
            erp_reference="E-1",
        )
        source.metrics.record(
            customer_id=workspace_id,
            name="pipeline.latency_ms",
            value=120.0,
            unit="ms",
            correlation_id=corr,
        )
    source.metrics.record(
        customer_id=workspace_id,
        name="pipeline.run",
        value=1.0,
        tags={"status": "failed" if failed else "completed"},
    )
    return corr


def _source() -> MonitoringOperationalDataSource:
    timeline = TimelineStore()
    metrics = MetricsStore()
    alerts = AlertService()
    return MonitoringOperationalDataSource(
        timeline=timeline, metrics=metrics, alerts=alerts
    )


class TestQueryClassification(unittest.TestCase):
    def test_classifies_supported_questions(self):
        cases = {
            "What failed today?": "failures_today",
            "Average processing time?": "average_processing_time",
            "Top validation failures": "top_validation_failures",
            "Government outages?": "government_outages",
            "ERP delays?": "erp_delays",
            "Retry statistics?": "retry_statistics",
            "What changed in the last 24 hours?": "changed_last_24h",
            "Which customer has the highest failure rate?": "highest_failure_rate",
            "Most active workspace?": "most_active_workspace",
        }
        for q, intent in cases.items():
            self.assertEqual(OperationalQueryService.classify(q), intent, q)


class TestAnalyticsAndRecommendations(unittest.TestCase):
    def test_metrics_and_failures_today(self):
        source = _source()
        _seed_workspace(source, "acme", failed=True)
        _seed_workspace(source, "acme", failed=False)
        analytics = OperationalAnalytics(source)
        result = analytics.workspace_analytics("acme")
        self.assertEqual(result["workspace_id"], "acme")
        self.assertGreaterEqual(len(result["failures_today"]), 1)
        self.assertIsNotNone(result["average_processing_time_ms"])
        self.assertTrue(result["top_validation_failures"] or result["top_errors"])
        self.assertIn("retry_statistics", result)

    def test_workspace_isolation_in_datasource(self):
        source = _source()
        _seed_workspace(source, "acme", failed=True)
        _seed_workspace(source, "beta", failed=True)
        acme = source.list_timelines("acme")
        beta = source.list_timelines("beta")
        self.assertTrue(all(t["customer_id"] == "acme" for t in acme))
        self.assertTrue(all(t["customer_id"] == "beta" for t in beta))
        self.assertEqual(len(acme), 1)
        self.assertEqual(len(beta), 1)

    def test_recommendations_from_failures(self):
        source = _source()
        _seed_workspace(source, "acme", failed=True)
        source.alerts.raise_alert(
            Alert(
                customer_id="acme",
                alert_type=AlertType.GOVERNMENT_UNAVAILABLE,
                title="Government unavailable",
                message="timeout",
                severity=AlertSeverity.CRITICAL,
            )
        )
        analytics = OperationalAnalytics(source).workspace_analytics("acme")
        recs = RecommendationEngine().generate(analytics)
        codes = {r["code"] for r in recs}
        self.assertIn("REVIEW_FAILURES_TODAY", codes)
        self.assertIn("GOVERNMENT_HEALTH", codes)

    def test_summarizer_narrative(self):
        source = _source()
        _seed_workspace(source, "acme", failed=False)
        summary = OperationalSummarizer(source).summarize("acme")
        self.assertIn("Workspace acme", summary["narrative"])
        self.assertEqual(summary["workspace_id"], "acme")

    def test_ask_average_processing_time(self):
        source = _source()
        _seed_workspace(source, "acme", failed=False)
        result = OperationalQueryService(source).ask("acme", "Average processing time?")
        self.assertEqual(result["intent"], "average_processing_time")
        self.assertEqual(result["source"], "monitoring_operational_datasource")
        self.assertIsNotNone(result["answer"])

    def test_compare_workspaces(self):
        source = _source()
        _seed_workspace(source, "acme", failed=True)
        _seed_workspace(source, "acme", failed=True)
        _seed_workspace(source, "beta", failed=False)
        compare = OperationalAnalytics(source).compare_workspaces(["acme", "beta"])
        self.assertEqual(compare["highest_failure_rate"]["workspace_id"], "acme")
        self.assertIn(compare["most_active_workspace"]["workspace_id"], {"acme", "beta"})


class TestSecurity(unittest.TestCase):
    def test_cross_workspace_requires_flag_and_admin(self):
        sec = AiOpsSecurity()
        user = SimpleNamespace(id=1, is_admin=False)
        db = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            sec.authorize_cross_workspace(
                db, user, ["acme", "beta"], authorize_cross_workspace=True
            )
        self.assertEqual(ctx.exception.status_code, 403)

        admin = SimpleNamespace(id=2, is_admin=True)
        with self.assertRaises(HTTPException):
            sec.authorize_cross_workspace(
                db, admin, ["acme"], authorize_cross_workspace=False
            )

    def test_audit_records_action(self):
        from app.core.ai import AiOpsAuditEvent

        sec = AiOpsSecurity()
        payload = sec.audit(
            AiOpsAuditEvent(
                action="ask",
                workspace_id="acme",
                principal_id=9,
                question_class="failures_today",
            )
        )
        self.assertEqual(payload["action"], "ask")
        self.assertEqual(len(sec.audit_log), 1)


class TestAiOpsApi(unittest.TestCase):
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
        self.source = _source()
        _seed_workspace(self.source, "acme", failed=True)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(AI_OPS_API_ENV, None)
            self.assertTrue(ai_ops_api_enabled())

    def test_health(self):
        response = self.client.get("/api/v1/ai/health")
        self.assertEqual(response.status_code, 200)

    def test_summary_uses_workspace_gate_and_monitoring(self):
        with patch.dict(os.environ, {AI_OPS_API_ENV: "true"}):
            with patch("app.api.ai_ops.resolve_ai_workspace") as resolve:
                with patch("app.api.ai_ops._services") as services:
                    summarizer = OperationalSummarizer(self.source)
                    analytics = OperationalAnalytics(self.source)
                    recommendations = RecommendationEngine()
                    query = OperationalQueryService(self.source)
                    services.return_value = (
                        self.source,
                        analytics,
                        recommendations,
                        summarizer,
                        query,
                    )
                    response = self.client.get("/api/v1/ai/workspace/acme/summary")
                    resolve.assert_called()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["workspace_id"], "acme")

    def test_recommendations_endpoint(self):
        with patch.dict(os.environ, {AI_OPS_API_ENV: "true"}):
            with patch("app.api.ai_ops.resolve_ai_workspace"):
                with patch("app.api.ai_ops._services") as services:
                    analytics = OperationalAnalytics(self.source)
                    recommendations = RecommendationEngine()
                    services.return_value = (
                        self.source,
                        analytics,
                        recommendations,
                        OperationalSummarizer(self.source),
                        OperationalQueryService(self.source),
                    )
                    response = self.client.get(
                        "/api/v1/ai/workspace/acme/recommendations"
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("recommendations", response.json())

    def test_disabled_flag_404(self):
        with patch.dict(os.environ, {AI_OPS_API_ENV: "false"}):
            response = self.client.get("/api/v1/ai/workspace/acme/analytics")
        self.assertEqual(response.status_code, 404)


class TestNoPipelineCoupling(unittest.TestCase):
    def test_ai_package_does_not_import_invoice_models(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1] / "core" / "ai"
        forbidden = re.compile(
            r"models\.invoice|zodiac_invoice|sap_sql_agent|adaptive_query|InvoicePipelineOrchestrator"
        )
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                forbidden.search(text),
                f"Forbidden coupling in {path.name}",
            )


if __name__ == "__main__":
    unittest.main()
