"""
First-customer onboarding readiness tests.

No live ERP/gov. Run from zodiac-api:

  python -m unittest app.tests.test_customer_onboarding -v
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.workspace.onboarding import evaluate_onboarding


def _full_ready_kwargs(**overrides):
    erp = SimpleNamespace(
        connection_key="primary",
        base_url="https://erp.example/api",
        auth_type="oauth2",
        client_id_ref="vault:demo/erp/id",
        client_secret_ref="vault:demo/erp/secret",
    )
    adapter = SimpleNamespace(
        country_code="mx_cfdi",
        enabled=True,
        endpoint_url_ref="https://gov.example/submit",
        auth_type="bearer",
        auth_secret_ref="env:GOV_TOKEN",
    )
    base = dict(
        customer_exists=True,
        has_settings=True,
        pipeline_enabled=True,
        ai_scoped=True,
        monitoring_enabled=True,
        flags={"erp_update_mode": "auto"},
        erp=erp,
        adapters=[adapter],
        has_customer_user=True,
    )
    base.update(overrides)
    return base


class TestOnboardingChecklist(unittest.TestCase):
    def test_incomplete_without_settings(self):
        result = evaluate_onboarding(
            customer_exists=True,
            has_settings=False,
        )
        self.assertFalse(result["ready"])
        self.assertIn("workspace_settings", result["missing"])

    def test_erp_secrets_required_for_oauth(self):
        erp = SimpleNamespace(
            connection_key="primary",
            base_url="https://erp.example",
            auth_type="oauth2",
            client_id_ref=None,
            client_secret_ref=None,
        )
        result = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            erp=erp,
            adapters=[],
        )
        self.assertIn("erp_secrets", result["missing"])

    def test_bearer_needs_secret_only(self):
        erp = SimpleNamespace(
            connection_key="primary",
            base_url="https://erp.example",
            auth_type="bearer",
            client_id_ref=None,
            client_secret_ref="env:ERP_TOKEN",
        )
        result = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            pipeline_enabled=True,
            ai_scoped=True,
            monitoring_enabled=True,
            erp=erp,
            adapters=[
                SimpleNamespace(
                    country_code="mx_cfdi",
                    enabled=True,
                    endpoint_url_ref="https://gov.example",
                )
            ],
            has_customer_user=True,
        )
        self.assertNotIn("erp_secrets", result["missing"])

    def test_pipeline_prerequisites_block(self):
        result = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            monitoring_enabled=True,
            ai_scoped=True,
            has_customer_user=True,
        )
        self.assertFalse(result["pipeline_prerequisites_met"])
        self.assertIn("erp_configured", result["pipeline_prerequisites_missing"])

    def test_full_config_ready(self):
        with patch.dict(os.environ, {"ENABLE_PIPELINE_API": "true"}, clear=False):
            result = evaluate_onboarding(**_full_ready_kwargs())
        self.assertTrue(result["ready"])
        self.assertEqual(result["missing"], [])
        self.assertTrue(result["pipeline_prerequisites_met"])
        self.assertEqual(result["summary"]["progress_pct"], 100)
        keys = {s["key"]: s for s in result["steps"]}
        self.assertTrue(keys["pipeline_api_env"]["ok"])
        self.assertTrue(keys["erp_update_mode"]["ok"])
        self.assertTrue(keys["customer_user_assigned"]["ok"])

    def test_e2e_flow_transitions(self):
        """Simulate admin onboarding steps until ready."""
        state = evaluate_onboarding(customer_exists=False, has_settings=False)
        self.assertFalse(state["ready"])

        state = evaluate_onboarding(customer_exists=True, has_settings=False)
        self.assertIn("workspace_settings", state["missing"])

        state = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            monitoring_enabled=True,
            ai_scoped=True,
        )
        self.assertIn("erp_configured", state["missing"])
        self.assertIn("adapter_enabled", state["missing"])

        with patch.dict(os.environ, {"ENABLE_PIPELINE_API": "true"}, clear=False):
            state = evaluate_onboarding(**_full_ready_kwargs())
        self.assertTrue(state["ready"])


class TestHealthReadyStatic(unittest.TestCase):
    def test_server_defines_ready_probe(self):
        import pathlib

        server = (
            pathlib.Path(__file__).resolve().parents[1] / "server.py"
        ).read_text(encoding="utf-8")
        self.assertIn('/health/ready', server)
        self.assertIn("workspace_settings", server)
        self.assertIn("pipeline_timelines", server)


if __name__ == "__main__":
    unittest.main()
