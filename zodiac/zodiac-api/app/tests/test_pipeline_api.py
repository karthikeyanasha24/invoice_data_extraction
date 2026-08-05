"""
Phase 4 tests — Opt-in Pipeline API.

No DB and no network. Run from zodiac-api:

  python -m unittest app.tests.test_pipeline_api -v
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.pipeline import PIPELINE_API_ENV, pipeline_api_enabled, router
from app.core.pipeline import PipelineResult, PipelineStatus, StageOutcome, StageStatus


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def _user(**overrides):
    base = dict(id=7, is_admin=True, is_active=True, is_customer_user=False)
    base.update(overrides)
    return SimpleNamespace(**base)


class TestFeatureFlag(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PIPELINE_API_ENV, None)
            self.assertFalse(pipeline_api_enabled())

    def test_enabled_for_truthy_values(self):
        for value in ("true", "TRUE", "1", "yes", "on"):
            with patch.dict(os.environ, {PIPELINE_API_ENV: value}):
                self.assertTrue(pipeline_api_enabled(), value)

    def test_health_reports_flag_without_auth(self):
        client = TestClient(_app())
        with patch.dict(os.environ, {PIPELINE_API_ENV: "false"}):
            response = client.get("/api/v1/pipeline/health")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])


class TestApiGates(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.user = _user()

        async def override_user():
            return self.user

        def override_db():
            yield MagicMock()

        from app.api.auth import get_current_user
        from app.database import get_db

        self.app.dependency_overrides[get_current_user] = override_user
        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_stages_404_when_flag_off(self):
        with patch.dict(os.environ, {PIPELINE_API_ENV: "false"}):
            response = self.client.get("/api/v1/pipeline/stages")
        self.assertEqual(response.status_code, 404)

    def test_stages_lists_documented_flow_when_flag_on(self):
        with patch.dict(os.environ, {PIPELINE_API_ENV: "true"}):
            response = self.client.get("/api/v1/pipeline/stages")
        self.assertEqual(response.status_code, 200)
        names = [s["name"] for s in response.json()["stages"]]
        self.assertEqual(names[0], "authenticate")
        self.assertEqual(names[-1], "ai_event")
        self.assertIn("submit", names)
        # No country identifiers in the stage list.
        joined = " ".join(names)
        for word in ("mexico", "cfdi", "india", "germany", "uae"):
            self.assertNotIn(word, joined)

    def test_adapters_catalog_includes_registered_builtin(self):
        with patch.dict(os.environ, {PIPELINE_API_ENV: "true"}):
            response = self.client.get("/api/v1/pipeline/adapters")
        self.assertEqual(response.status_code, 200)
        codes = [a["country_code"] for a in response.json()["adapters"]]
        self.assertIn("mx_cfdi", codes)


class TestRunEndpoint(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.user = _user()

        async def override_user():
            return self.user

        def override_db():
            yield MagicMock()

        from app.api.auth import get_current_user
        from app.database import get_db

        self.app.dependency_overrides[get_current_user] = override_user
        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def _result(self, **overrides):
        base = dict(
            correlation_id="c-1",
            customer_id="acme",
            country_code="atlantis",
            status=PipelineStatus.COMPLETED,
            stages=[
                StageOutcome(stage="authenticate", status=StageStatus.SUCCESS),
                StageOutcome(stage="parse", status=StageStatus.SUCCESS),
            ],
            confirmation={"document_number": "DOC-1"},
            events=[{"stage": "monitoring", "status": "SUCCESS"}],
        )
        base.update(overrides)
        return PipelineResult(**base)

    def test_run_404_when_flag_off(self):
        with patch.dict(os.environ, {PIPELINE_API_ENV: "false"}):
            response = self.client.post(
                "/api/v1/pipeline/run",
                json={"customer_id": "acme", "payload": "<xml/>"},
            )
        self.assertEqual(response.status_code, 404)

    def test_run_returns_orchestrator_result(self):
        orchestrator = MagicMock()
        orchestrator.run = AsyncMock(return_value=self._result())

        with patch.dict(os.environ, {PIPELINE_API_ENV: "true"}):
            with patch("app.core.pipeline.InvoicePipelineOrchestrator", return_value=orchestrator):
                response = self.client.post(
                    "/api/v1/pipeline/run",
                    json={
                        "customer_id": "acme",
                        "payload": "<xml/>",
                        "country_code": "atlantis",
                        "dry_run": True,
                    },
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["country_code"], "atlantis")
        self.assertEqual(body["confirmation"]["document_number"], "DOC-1")
        self.assertTrue(body["succeeded"])

        # Principal and db are injected from the request context.
        call_request = orchestrator.run.await_args.args[0]
        self.assertEqual(call_request.customer_id, "acme")
        self.assertIs(call_request.user, self.user)
        self.assertTrue(call_request.dry_run)

    def test_pipeline_disabled_becomes_http_403(self):
        orchestrator = MagicMock()
        orchestrator.run = AsyncMock(
            return_value=self._result(
                status=PipelineStatus.FAILED,
                error="Pipeline is not enabled",
                error_code="PIPELINE_DISABLED",
                failed_stage="resolve_workspace",
            )
        )

        with patch.dict(os.environ, {PIPELINE_API_ENV: "true"}):
            with patch("app.core.pipeline.InvoicePipelineOrchestrator", return_value=orchestrator):
                response = self.client.post(
                    "/api/v1/pipeline/run",
                    json={"customer_id": "acme", "payload": "<xml/>"},
                )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["error_code"], "PIPELINE_DISABLED")

    def test_processing_failure_stays_in_200_body(self):
        """Validation / mapping failures are reported, not raised as HTTP 5xx."""
        orchestrator = MagicMock()
        orchestrator.run = AsyncMock(
            return_value=self._result(
                status=PipelineStatus.FAILED,
                error="Invalid document",
                error_code="VALIDATION_FAILED",
                failed_stage="validate",
                confirmation=None,
            )
        )

        with patch.dict(os.environ, {PIPELINE_API_ENV: "true"}):
            with patch("app.core.pipeline.InvoicePipelineOrchestrator", return_value=orchestrator):
                response = self.client.post(
                    "/api/v1/pipeline/run",
                    json={"customer_id": "acme", "payload": "<xml/>"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error_code"], "VALIDATION_FAILED")
        self.assertFalse(response.json()["succeeded"])

    def test_rejects_empty_payload(self):
        with patch.dict(os.environ, {PIPELINE_API_ENV: "true"}):
            response = self.client.post(
                "/api/v1/pipeline/run",
                json={"customer_id": "acme", "payload": ""},
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
