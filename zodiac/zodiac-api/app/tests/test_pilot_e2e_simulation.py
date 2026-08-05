"""
Pilot production simulation — onboarding readiness, invoice pipeline stages,
failure alerts, AI Ops isolation. No live ERP/Government network.

Run from zodiac-api:

  python -m unittest app.tests.test_pilot_e2e_simulation -v
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.adapters.base import AdapterCapability, AdapterStage, CountryAdapter, StageResult
from app.core.monitoring.alerts import AlertService, AlertType
from app.core.pipeline import (
    CollectingSink,
    InvoicePipelineOrchestrator,
    PipelineRequest,
    PipelineStatus,
    PlatformServices,
)
from app.core.startup import validate_production_config
from app.core.workspace.onboarding import evaluate_onboarding


class PilotAdapter(CountryAdapter):
    country_code = "pilot_mx"
    display_name = "Pilot"
    supported_document_types = ("INVOICE",)

    def __init__(self, fail_submit: bool = False):
        self.fail_submit = fail_submit
        self.calls = []

    def capabilities(self):
        return [AdapterCapability.PARSE]

    def _ok(self, name, stage, data=None):
        self.calls.append(name)
        return StageResult.ok(stage, data if data is not None else {name: True})

    def parse(self, ctx):
        return self._ok("parse", AdapterStage.PARSE, {"uuid": "pilot-1"})

    def validate(self, ctx):
        return self._ok("validate", AdapterStage.VALIDATE)

    def map(self, ctx):
        return self._ok("map", AdapterStage.MAP)

    def apply_business_rules(self, ctx):
        return self._ok("business_rules", AdapterStage.BUSINESS_RULES)

    def transform(self, ctx):
        return self._ok("transform", AdapterStage.TRANSFORM)

    def format(self, ctx):
        return self._ok("format", AdapterStage.FORMAT)

    async def submit(self, ctx):
        self.calls.append("submit")
        if self.fail_submit:
            return StageResult.fail(
                AdapterStage.SUBMIT, "gov down", "GOV_UNAVAILABLE"
            )
        payload = {"submitted": True, "erp_fulfilled_in_submit": False}
        ctx.set_output(AdapterStage.SUBMIT, payload)
        return StageResult.ok(AdapterStage.SUBMIT, payload)

    def receive_confirmation(self, ctx, response=None):
        self.calls.append("receive_confirmation")
        confirmation = {"accepted": True}
        ctx.set_output(AdapterStage.CONFIRMATION, confirmation)
        return StageResult.ok(AdapterStage.CONFIRMATION, confirmation)


class TestStartupConfig(unittest.TestCase):
    def test_prod_flags_placeholder_secret(self):
        with patch.dict(
            os.environ,
            {
                "DEPLOY_ENV": "PRODUCTION",
                "SECRET_KEY": "your-secret-key-here-change-in-production",
                "API_DEBUG": "false",
                "CORS_ALLOW_ALL": "false",
                "DATABASE_URL": "postgresql://u:p@localhost/db",
            },
            clear=False,
        ):
            report = validate_production_config()
        self.assertFalse(report["ok"])
        self.assertTrue(any("SECRET_KEY" in e for e in report["errors"]))

    def test_dev_allows_weak_secret_as_warning(self):
        with patch.dict(
            os.environ,
            {
                "DEPLOY_ENV": "DEV",
                "SECRET_KEY": "short",
                "DATABASE_URL": "postgresql://u:p@localhost/db",
            },
            clear=False,
        ):
            report = validate_production_config()
        self.assertTrue(report["ok"])
        self.assertTrue(report["warnings"])


class TestOnboardingFromZero(unittest.TestCase):
    def test_becomes_ready_after_full_config(self):
        incomplete = evaluate_onboarding(customer_exists=True, has_settings=False)
        self.assertFalse(incomplete["ready"])

        with patch.dict(os.environ, {"ENABLE_PIPELINE_API": "true"}, clear=False):
            ready = evaluate_onboarding(
                customer_exists=True,
                has_settings=True,
                pipeline_enabled=True,
                ai_scoped=True,
                monitoring_enabled=True,
                flags={"erp_update_mode": "auto"},
                erp=SimpleNamespace(
                    connection_key="primary",
                    base_url="https://erp.pilot.example/api",
                    auth_type="bearer",
                    client_id_ref=None,
                    client_secret_ref="env:PILOT_ERP_TOKEN",
                ),
                adapters=[
                    SimpleNamespace(
                        country_code="mx_cfdi",
                        enabled=True,
                        endpoint_url_ref="https://gov.sandbox.example/cfdi",
                    )
                ],
            )
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["missing"], [])


class TestInvoiceFlowSimulation(unittest.TestCase):
    def test_happy_path_stages(self):
        adapter = PilotAdapter()

        class StubWorkspaceResolver:
            def resolve(self, request, principal):
                return SimpleNamespace(
                    customer_id="PILOT",
                    workspace_id="PILOT",
                    pipeline_enabled=True,
                    monitoring_enabled=True,
                    ai_scoped=True,
                    flags={"erp_update_mode": "auto"},
                    adapters=[],
                )

        class StubAdapterResolver:
            def resolve(self, request, workspace):
                return (
                    "pilot_mx",
                    adapter,
                    SimpleNamespace(extra_config={}),
                )

        services = PlatformServices(
            workspace_resolver=StubWorkspaceResolver(),
            adapter_resolver=StubAdapterResolver(),
            monitoring=CollectingSink(),
            ai_events=CollectingSink(),
            audit=CollectingSink(),
        )
        orch = InvoicePipelineOrchestrator(services=services)
        result = asyncio.run(
            orch.run(
                PipelineRequest(
                    customer_id="PILOT",
                    payload="<invoice/>",
                    user=SimpleNamespace(id=1, is_active=True),
                    db=None,
                )
            )
        )
        self.assertEqual(result.status, PipelineStatus.COMPLETED)
        self.assertTrue(result.succeeded)
        self.assertIn("submit", adapter.calls)
        self.assertIn("receive_confirmation", adapter.calls)

    def test_gov_failure_raises_alert(self):
        alerts = AlertService()
        raised = alerts.evaluate_pipeline_result(
            customer_id="PILOT",
            correlation_id="c-fail",
            status="failed",
            failed_stage="submit",
            error="gov down",
            error_code="GOV_UNAVAILABLE",
            retry_count=2,
        )
        types = {r["alert_type"] for r in raised}
        self.assertIn(AlertType.GOVERNMENT_UNAVAILABLE.value, types)
        self.assertIn(AlertType.REPEATED_RETRY.value, types)


class TestFailureFlags(unittest.TestCase):
    def test_adapter_disabled_not_ready(self):
        r = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            pipeline_enabled=True,
            monitoring_enabled=True,
            ai_scoped=True,
            erp=SimpleNamespace(
                base_url="https://erp.example",
                auth_type="none",
                client_secret_ref=None,
                client_id_ref=None,
                connection_key="primary",
            ),
            adapters=[
                SimpleNamespace(
                    country_code="mx_cfdi",
                    enabled=False,
                    endpoint_url_ref="https://gov.example",
                )
            ],
        )
        self.assertIn("adapter_enabled", r["missing"])

    def test_pipeline_disabled_not_ready(self):
        r = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            pipeline_enabled=False,
            monitoring_enabled=True,
            ai_scoped=True,
            erp=SimpleNamespace(
                base_url="https://erp.example",
                auth_type="none",
                client_secret_ref=None,
                client_id_ref=None,
                connection_key="primary",
            ),
            adapters=[
                SimpleNamespace(
                    country_code="mx_cfdi",
                    enabled=True,
                    endpoint_url_ref="https://gov.example",
                )
            ],
        )
        self.assertIn("pipeline_enabled", r["missing"])

    def test_missing_secret_env(self):
        from app.core.secrets import (
            SecretResolutionError,
            get_default_secret_resolver,
            reset_default_secret_resolver_for_tests,
        )

        os.environ.pop("PILOT_MISSING", None)
        os.environ.pop("SECRET_RESOLVER", None)
        reset_default_secret_resolver_for_tests()
        with self.assertRaises(SecretResolutionError) as ctx:
            get_default_secret_resolver().resolve("env:PILOT_MISSING")
        self.assertEqual(ctx.exception.code, "MISSING_ENV_VAR")


class TestAiOpsIsolation(unittest.TestCase):
    def test_ai_package_no_invoice_erp_gov_tables(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "core" / "ai"
        forbidden = re.compile(
            r"models\.invoice|zodiac_invoice|sap_sql_agent|InvoicePipelineOrchestrator|"
            r"models\.erp_outbox|WorkspaceErpConnection|sat_documents"
        )
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(forbidden.search(text), path.name)


class TestDeploySurfaces(unittest.TestCase):
    def test_health_ready_and_startup_in_server(self):
        server = (
            pathlib.Path(__file__).resolve().parents[1] / "server.py"
        ).read_text(encoding="utf-8")
        self.assertIn("/health/ready", server)
        self.assertIn("run_startup", server)
        self.assertIn("startup", server)


if __name__ == "__main__":
    unittest.main()
