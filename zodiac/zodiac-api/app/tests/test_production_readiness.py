"""
Phase 10 — Production readiness regression / security smoke tests.

No new business features. Validates gates, isolation posture, and CORS hardening.
Run from zodiac-api:

  python -m unittest app.tests.test_production_readiness -v
"""
from __future__ import annotations

import os
import pathlib
import re
import unittest
from unittest.mock import patch


class TestFeatureFlagDefaults(unittest.TestCase):
    def test_pipeline_api_default_off(self):
        from app.api.pipeline import PIPELINE_API_ENV, pipeline_api_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PIPELINE_API_ENV, None)
            self.assertFalse(pipeline_api_enabled())

    def test_monitoring_and_ai_ops_default_on(self):
        from app.api.ai_ops import AI_OPS_API_ENV, ai_ops_api_enabled
        from app.api.monitoring import MONITORING_API_ENV, monitoring_api_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MONITORING_API_ENV, None)
            os.environ.pop(AI_OPS_API_ENV, None)
            self.assertTrue(monitoring_api_enabled())
            self.assertTrue(ai_ops_api_enabled())


class TestCorsHardening(unittest.TestCase):
    def test_server_honors_cors_origins_not_star_by_default(self):
        """Static check: production middleware must not hardcode allow_origins=['*']."""
        server = (
            pathlib.Path(__file__).resolve().parents[1] / "server.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CORS_ALLOW_ALL", server)
        self.assertIn("_cors_origins", server)
        # Legacy insecure pattern should not remain as the only middleware config.
        self.assertNotRegex(
            server,
            r'allow_origins=\["\*"\].*# Allow all origins for now',
        )


class TestIsolationInvariants(unittest.TestCase):
    def test_monitoring_api_calls_require_workspace_access(self):
        text = (
            pathlib.Path(__file__).resolve().parents[1] / "api" / "monitoring.py"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("require_workspace_access"), 4)

    def test_ai_ops_uses_resolve_ai_workspace(self):
        text = (
            pathlib.Path(__file__).resolve().parents[1] / "api" / "ai_ops.py"
        ).read_text(encoding="utf-8")
        self.assertIn("resolve_ai_workspace", text)
        self.assertIn("authorize_cross_workspace", text)

    def test_ai_package_forbidden_imports(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "core" / "ai"
        forbidden = re.compile(
            r"models\.invoice|zodiac_invoice|sap_sql_agent|InvoicePipelineOrchestrator"
        )
        for path in root.glob("*.py"):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), path.name)


class TestSecretRefPolicy(unittest.TestCase):
    def test_valid_secret_ref_helpers(self):
        from app.core.workspace.context import is_valid_secret_ref

        self.assertTrue(is_valid_secret_ref("vault:secret/erp"))
        self.assertTrue(is_valid_secret_ref("env:ERP_TOKEN"))
        self.assertFalse(is_valid_secret_ref("super-secret-password"))


class TestMigrationFilesPresent(unittest.TestCase):
    def test_phase_migrations_exist(self):
        mig = pathlib.Path(__file__).resolve().parents[1] / "migrations"
        for name in (
            "phase2_workspace_tables.sql",
            "phase6_erp_outbox.sql",
            "phase8_monitoring_tables.sql",
            "README.md",
        ):
            self.assertTrue((mig / name).is_file(), name)


class TestProductionDocsPresent(unittest.TestCase):
    def test_gate_and_ops_pack(self):
        zodiac = pathlib.Path(__file__).resolve().parents[3]
        self.assertTrue((zodiac / "PRODUCTION_READINESS_CHECKLIST.md").is_file())
        self.assertTrue((zodiac / "CUSTOMER_ONBOARDING_IMPLEMENTATION.md").is_file())
        self.assertTrue((zodiac / "FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md").is_file())
        self.assertTrue((zodiac / "FIRST_CUSTOMER_DEPLOYMENT_REPORT.md").is_file())
        self.assertTrue((zodiac / "FINAL_GO_LIVE_VALIDATION.md").is_file())
        self.assertTrue((zodiac / "RELEASE_NOTES_v1.0.md").is_file())
        self.assertTrue((zodiac / "CHANGELOG.md").is_file())
        self.assertTrue((zodiac / "REPOSITORY_AUDIT.md").is_file())
        self.assertTrue((zodiac / "ENGINEERING_REVIEW_v1.0.md").is_file())
        self.assertTrue(
            (zodiac / "zodiac-api" / ".env.example").is_file()
            or (pathlib.Path(__file__).resolve().parents[2] / ".env.example").is_file()
        )
        self.assertTrue((zodiac / "demo" / "first_customer" / "DEMO_SCRIPT.md").is_file())
        ops = zodiac / "docs" / "operations"
        for name in (
            "README.md",
            "DEPLOYMENT_GUIDE.md",
            "ROLLBACK_GUIDE.md",
            "MIGRATION_GUIDE.md",
            "CONFIGURATION_GUIDE.md",
            "MONITORING_GUIDE.md",
            "RUNBOOKS.md",
        ):
            self.assertTrue((ops / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
