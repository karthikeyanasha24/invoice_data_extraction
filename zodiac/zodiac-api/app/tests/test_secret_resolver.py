"""
PR2 — Centralized SecretResolver tests.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from app.core.secrets import (
    CompositeSecretResolver,
    SecretResolutionError,
    get_default_secret_resolver,
    parse_secret_ref,
    reset_default_secret_resolver_for_tests,
)
from app.core.secrets.providers.env import EnvSecretProvider
from app.core.secrets.providers.vault import VaultSecretProvider
from app.core.secrets.resolver import LiteralOnlyResolver


class TestParseRef(unittest.TestCase):
    def test_literal(self):
        scheme, path = parse_secret_ref("password123")
        self.assertIsNone(scheme)
        self.assertEqual(path, "password123")

    def test_env(self):
        scheme, path = parse_secret_ref("env:ERP_API_KEY")
        self.assertEqual(scheme, "env")
        self.assertEqual(path, "ERP_API_KEY")

    def test_vault(self):
        scheme, path = parse_secret_ref("vault:erp/api-key")
        self.assertEqual(scheme, "vault")
        self.assertEqual(path, "erp/api-key")


class TestLiteralAndEnv(unittest.TestCase):
    def setUp(self):
        self.resolver = CompositeSecretResolver()

    def test_literal_value(self):
        self.assertEqual(self.resolver.resolve("password123"), "password123")

    def test_empty_returns_none(self):
        self.assertIsNone(self.resolver.resolve(None))
        self.assertIsNone(self.resolver.resolve("  "))

    def test_env_resolves(self):
        with patch.dict(os.environ, {"ERP_API_KEY": "super-secret"}, clear=False):
            self.assertEqual(self.resolver.resolve("env:ERP_API_KEY"), "super-secret")

    def test_missing_env_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DOES_NOT_EXIST_BRIDGEEDI", None)
            with self.assertRaises(SecretResolutionError) as ctx:
                self.resolver.resolve("env:DOES_NOT_EXIST_BRIDGEEDI")
            self.assertEqual(ctx.exception.code, "MISSING_ENV_VAR")
            self.assertNotIn("super", str(ctx.exception).lower())

    def test_invalid_env_name(self):
        with self.assertRaises(SecretResolutionError) as ctx:
            EnvSecretProvider().resolve("env", "bad-name!", raw_ref="env:bad-name!")
        self.assertEqual(ctx.exception.code, "INVALID_ENV_REF")


class TestVaultProvider(unittest.TestCase):
    def setUp(self):
        self.resolver = CompositeSecretResolver()

    def test_invalid_vault_uri(self):
        with self.assertRaises(SecretResolutionError) as ctx:
            self.resolver.resolve("vault:")
        self.assertEqual(ctx.exception.code, "INVALID_VAULT_URI")

    def test_vault_unavailable_without_config(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ.keys()):
                if key.startswith("BRIDGEEDI_VAULT") or key in ("VAULT_ADDR", "VAULT_TOKEN"):
                    os.environ.pop(key, None)
            with self.assertRaises(SecretResolutionError) as ctx:
                self.resolver.resolve("vault:erp/api-key")
            self.assertEqual(ctx.exception.code, "VAULT_UNAVAILABLE")

    def test_vault_json_map(self):
        payload = json.dumps({"erp/api-key": "from-json"})
        with patch.dict(os.environ, {"BRIDGEEDI_VAULT_JSON": payload}, clear=False):
            self.assertEqual(self.resolver.resolve("vault:erp/api-key"), "from-json")

    def test_vault_env_bridge(self):
        with patch.dict(
            os.environ, {"BRIDGEEDI_VAULT_SAP_PASSWORD": "bridged"}, clear=False
        ):
            self.assertEqual(self.resolver.resolve("vault:sap/password"), "bridged")


class TestUnknownAndUnconfigured(unittest.TestCase):
    def test_unknown_provider(self):
        resolver = CompositeSecretResolver()
        with self.assertRaises(SecretResolutionError) as ctx:
            resolver.resolve("foo:bar")
        self.assertEqual(ctx.exception.code, "UNKNOWN_PROVIDER")

    def test_secret_scheme_not_configured(self):
        resolver = CompositeSecretResolver()
        with self.assertRaises(SecretResolutionError) as ctx:
            resolver.resolve("secret:acme/erp")
        self.assertEqual(ctx.exception.code, "PROVIDER_NOT_CONFIGURED")


class TestLiteralOnlyCompat(unittest.TestCase):
    def test_prefixed_returns_none(self):
        resolver = LiteralOnlyResolver()
        self.assertIsNone(resolver.resolve("vault:secret/gov"))
        self.assertEqual(resolver.resolve("tok-123"), "tok-123")


class TestGovernmentAuthIntegration(unittest.TestCase):
    def test_literal_bearer_still_works(self):
        from app.core.government.auth import build_auth
        from app.core.government.base import GovernmentEndpointConfig

        cfg = GovernmentEndpointConfig(
            customer_id="acme",
            country_code="x",
            auth_type="bearer",
            auth_secret_ref="tok-123",
        )
        material = build_auth(cfg, CompositeSecretResolver())
        self.assertEqual(material.headers.get("Authorization"), "Bearer tok-123")

    def test_env_bearer(self):
        from app.core.government.auth import build_auth
        from app.core.government.base import GovernmentEndpointConfig

        cfg = GovernmentEndpointConfig(
            customer_id="acme",
            country_code="x",
            auth_type="bearer",
            auth_secret_ref="env:GOV_CLIENT_SECRET",
        )
        with patch.dict(os.environ, {"GOV_CLIENT_SECRET": "gov-secret"}, clear=False):
            material = build_auth(cfg, CompositeSecretResolver())
        self.assertEqual(material.headers.get("Authorization"), "Bearer gov-secret")

    def test_vault_unresolved_does_not_send_ref_as_token(self):
        from app.core.government.auth import build_auth
        from app.core.government.base import GovernmentEndpointConfig

        cfg = GovernmentEndpointConfig(
            customer_id="acme",
            country_code="x",
            auth_type="bearer",
            auth_secret_ref="vault:secret/gov",
        )
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ.keys()):
                if key.startswith("BRIDGEEDI_VAULT") or key in ("VAULT_ADDR", "VAULT_TOKEN"):
                    os.environ.pop(key, None)
            material = build_auth(cfg, CompositeSecretResolver())
        self.assertNotIn("Authorization", material.headers)
        self.assertEqual(material.error_code, "SECRET_UNRESOLVED")


class TestErpConnectorIntegration(unittest.TestCase):
    def test_resolves_env_bearer_before_http(self):
        from app.core.erp.connector import HttpErpConnector
        from app.core.erp.models import CanonicalConfirmation, DocumentStatus, ErpPushRequest
        from datetime import datetime, timezone

        captured = {}

        class Client:
            def post(self, url, json=None, headers=None, timeout=None):
                captured["headers"] = dict(headers or {})
                return MagicMock(status_code=200, json=lambda: {"ok": True}, text="{}")

        connector = HttpErpConnector(
            memory_store=__import__(
                "app.core.erp.connector", fromlist=["InMemoryOutboxStore"]
            ).InMemoryOutboxStore(),
            http_client=Client(),
            secret_resolver=CompositeSecretResolver(),
        )
        conf = CanonicalConfirmation(
            correlation_id="c1",
            customer_id="acme",
            status=DocumentStatus.ACCEPTED,
            accepted=True,
            received_at=datetime.now(timezone.utc).isoformat(),
            idempotency_key="idem-1",
        )
        req = ErpPushRequest(
            customer_id="acme",
            confirmation=conf,
            callback_url="https://erp.example/hook",
            auth_type="bearer",
            client_secret_ref="env:SAP_PASSWORD",
            extra_config={},
        )
        with patch.dict(os.environ, {"SAP_PASSWORD": "sap-secret"}, clear=False):
            result = connector.push_confirmation(req)
        self.assertTrue(result.success)
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer sap-secret")
        # Ensure raw ref never appeared
        self.assertNotIn("env:SAP_PASSWORD", str(captured))


class TestDefaultResolverMode(unittest.TestCase):
    def tearDown(self):
        reset_default_secret_resolver_for_tests()

    def test_literal_mode(self):
        with patch.dict(os.environ, {"SECRET_RESOLVER": "literal"}, clear=False):
            reset_default_secret_resolver_for_tests()
            resolver = get_default_secret_resolver()
            self.assertIsInstance(resolver, LiteralOnlyResolver)


if __name__ == "__main__":
    unittest.main()
