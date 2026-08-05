"""
Phase 2 review tests — access isolation, secret refs, pagination helpers.
No live DB required. Run from zodiac-api:

  python -m unittest app.tests.test_workspace_access -v
  python -m unittest app.tests.test_workspace_isolation -v
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.core.workspace.context import (
    assert_ai_workspace_scope,
    is_valid_secret_ref,
    require_workspace_access,
    user_can_access_customer,
    WorkspaceContext,
)
from app.schemas.workspace import WorkspaceAdapterUpsert, WorkspaceErpUpsert


class TestSecretRefs(unittest.TestCase):
    def test_accepts_prefixed_refs(self):
        for v in ("vault:x", "env:FOO", "secret:bar", "arn:aws:…", "kms:key", "ref:id"):
            self.assertTrue(is_valid_secret_ref(v), v)

    def test_rejects_plaintext(self):
        self.assertFalse(is_valid_secret_ref("SuperSecretPassword123"))

    def test_erp_schema_rejects_plaintext(self):
        with self.assertRaises(Exception):
            WorkspaceErpUpsert(client_secret_ref="plaintext-password-value")

    def test_erp_schema_accepts_vault_ref(self):
        body = WorkspaceErpUpsert(client_secret_ref="vault:acme/erp/secret")
        self.assertEqual(body.client_secret_ref, "vault:acme/erp/secret")

    def test_adapter_allows_https_endpoint(self):
        body = WorkspaceAdapterUpsert(
            country_code="India",
            endpoint_url_ref="https://gov.example/api",
        )
        self.assertEqual(body.country_code, "india")
        self.assertTrue(body.endpoint_url_ref.startswith("https://"))


class TestWorkspaceAccess(unittest.TestCase):
    def test_admin_requires_customer_exists(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = (1,)
        admin = SimpleNamespace(id=1, is_admin=True, is_customer_user=False)
        self.assertTrue(user_can_access_customer(db, admin, "ACME"))

        db.query.return_value.filter.return_value.first.return_value = None
        self.assertFalse(user_can_access_customer(db, admin, "MISSING"))

    def test_customer_a_cannot_access_customer_b(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [("ACME",)]
        user = SimpleNamespace(id=9, is_admin=False, is_customer_user=True)
        self.assertTrue(user_can_access_customer(db, user, "ACME"))
        self.assertFalse(user_can_access_customer(db, user, "OTHERCO"))

    def test_require_access_hides_existence_for_customer_user(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [("ACME",)]
        user = SimpleNamespace(id=9, is_admin=False, is_customer_user=True)
        with self.assertRaises(HTTPException) as ctx:
            require_workspace_access(db, user, "OTHERCO")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_ai_scope_guard(self):
        ctx = WorkspaceContext(customer_id="ACME", ai_scoped=False)
        with self.assertRaises(HTTPException):
            assert_ai_workspace_scope(ctx)
        assert_ai_workspace_scope(WorkspaceContext(customer_id="ACME", ai_scoped=True))


class TestMultiTenantShape(unittest.TestCase):
    """Document structural readiness for N customers / N ERPs / N adapters."""

    def test_connection_key_normalization(self):
        body = WorkspaceErpUpsert(connection_key="Billing Primary")
        self.assertEqual(body.connection_key, "billing_primary")

    def test_context_enabled_countries(self):
        adapters = [
            SimpleNamespace(country_code="mx_cfdi", enabled=True),
            SimpleNamespace(country_code="india", enabled=False),
            SimpleNamespace(country_code="uae", enabled=True),
        ]
        ctx = WorkspaceContext(customer_id="ACME", adapters=adapters)  # type: ignore
        self.assertEqual(ctx.enabled_country_codes(), ["mx_cfdi", "uae"])


if __name__ == "__main__":
    unittest.main()
