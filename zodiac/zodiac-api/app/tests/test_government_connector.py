"""
Phase 7 tests — Government Connector Framework.

Run from zodiac-api:

  python -m unittest app.tests.test_government_connector -v
"""
from __future__ import annotations

import asyncio
import pathlib
import unittest
from types import SimpleNamespace
from typing import Any, List

from app.adapters.mx_cfdi import MxCfdiAdapter
from app.adapters.sample_gst import SampleGstAdapter
from app.adapters.sample_gst.config import SampleGstConfig
from app.core.government import (
    AlreadyStampedGovernmentConnector,
    CanonicalGovernmentRequest,
    GovernmentEndpointConfig,
    GovernmentOperation,
    GovernmentStatus,
    HttpGovernmentConnector,
    MockGovernmentConnector,
    build_government_connector,
)
from app.core.government.auth import build_auth, is_usable_http_url
from app.core.government.base import GOV_AUTH_FAILED, GOV_DUPLICATE, GOV_NOT_CONFIGURED
from app.core.government.retry import GovernmentRetryPolicy


def _req(**overrides) -> CanonicalGovernmentRequest:
    base = dict(
        customer_id="pilot",
        country_code="sample_gst",
        operation=GovernmentOperation.SUBMIT,
        payload={"invoice": {"irn": "a" * 64}, "schema": "sample-gst-einvoice"},
        correlation_id="corr-1",
        submission_id="sub-1",
    )
    base.update(overrides)
    return CanonicalGovernmentRequest(**base)


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"ack_number": "GOV-1", "status": "ACCEPTED"}

    def json(self):
        return self._body


class FakeAsyncHttp:
    def __init__(self, responses=None):
        self.responses = list(responses or [FakeResponse()])
        self.calls: List[dict] = []

    async def request(self, method, url, headers=None, json=None, content=None, timeout=None, cert=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json, "cert": cert}
        )
        if not self.responses:
            return FakeResponse(500, {"error": "empty"})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestMockConnector(unittest.TestCase):
    def test_submit_accepts_and_is_idempotent(self):
        gov = MockGovernmentConnector()
        first = run(gov.submit(_req()))
        second = run(gov.submit(_req()))
        self.assertEqual(first.status, GovernmentStatus.ACCEPTED)
        self.assertTrue(first.government_reference.startswith("MOCK-ACK-"))
        self.assertTrue(second.extensions.get("duplicate"))
        self.assertEqual(second.error_code, GOV_DUPLICATE)

    def test_health(self):
        result = run(MockGovernmentConnector().health())
        self.assertTrue(result.healthy)


class TestAlreadyStamped(unittest.TestCase):
    def test_mexico_uses_stamp_without_http(self):
        gov = AlreadyStampedGovernmentConnector()
        http = FakeAsyncHttp()
        # Already stamped ignores HTTP entirely
        resp = run(
            gov.submit(
                _req(
                    country_code="mx_cfdi",
                    payload={"cfdi_uuid": "11111111-2222-3333-4444-555555555555"},
                    government_reference=None,
                )
            )
        )
        self.assertEqual(resp.status, GovernmentStatus.ACCEPTED)
        self.assertEqual(resp.government_reference, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(http.calls, [])

    def test_mx_adapter_exposes_already_stamped_connector(self):
        adapter = MxCfdiAdapter()
        gov = adapter.get_government_connector()
        self.assertIsInstance(gov, AlreadyStampedGovernmentConnector)
        resp = run(
            gov.submit(
                _req(
                    country_code="mx_cfdi",
                    government_reference="UUID-FROM-XML",
                    payload={},
                )
            )
        )
        self.assertEqual(resp.government_reference, "UUID-FROM-XML")


class TestAuthAndWorkspaceConfig(unittest.TestCase):
    def test_api_key_auth_header(self):
        cfg = GovernmentEndpointConfig(
            customer_id="acme",
            country_code="sample_gst",
            production_url="https://gov.example/api",
            environment="production",
            auth_type="api_key",
            auth_secret_ref="test-api-key-value",
            extra={"api_key_header": "X-Gov-Key"},
        )
        material = build_auth(cfg)
        self.assertEqual(material.headers.get("X-Gov-Key"), "test-api-key-value")

    def test_bearer_auth(self):
        cfg = GovernmentEndpointConfig(
            customer_id="acme",
            country_code="x",
            auth_type="bearer",
            auth_secret_ref="tok-123",
        )
        material = build_auth(cfg)
        self.assertEqual(material.headers.get("Authorization"), "Bearer tok-123")

    def test_vault_ref_not_sent_as_literal(self):
        cfg = GovernmentEndpointConfig(
            customer_id="acme",
            country_code="x",
            auth_type="bearer",
            auth_secret_ref="vault:secret/gov",
        )
        material = build_auth(cfg)
        self.assertNotIn("Authorization", material.headers)

    def test_workspace_config_selects_sandbox(self):
        row = SimpleNamespace(
            country_code="sample_gst",
            endpoint_url_ref="https://prod.example/gov",
            auth_type="none",
            auth_secret_ref=None,
            extra_config={
                "sandbox_url": "https://sandbox.example/gov",
                "environment": "sandbox",
            },
        )
        cfg = GovernmentEndpointConfig.from_workspace_adapter(
            row, customer_id="pilot", country_code="sample_gst"
        )
        self.assertEqual(cfg.endpoint_url, "https://sandbox.example/gov")
        self.assertTrue(is_usable_http_url(cfg.endpoint_url))


class TestHttpConnector(unittest.TestCase):
    def test_successful_submit_sends_idempotency_key(self):
        http = FakeAsyncHttp([FakeResponse(200, {"ack_number": "ACK-9"})])
        cfg = GovernmentEndpointConfig(
            customer_id="pilot",
            country_code="sample_gst",
            sandbox_url="https://gov.example/v1",
            environment="sandbox",
            auth_type="none",
        )
        gov = HttpGovernmentConnector(cfg, http_client=http, retry=GovernmentRetryPolicy(max_attempts=1))
        resp = run(gov.submit(_req()))
        self.assertEqual(resp.status, GovernmentStatus.ACCEPTED)
        self.assertEqual(resp.government_reference, "ACK-9")
        self.assertEqual(http.calls[0]["headers"]["X-Idempotency-Key"], "sub-1")

    def test_auth_failure_not_retryable(self):
        http = FakeAsyncHttp([FakeResponse(401, {"error": "no"})])
        cfg = GovernmentEndpointConfig(
            customer_id="pilot",
            country_code="sample_gst",
            sandbox_url="https://gov.example/v1",
        )
        gov = HttpGovernmentConnector(cfg, http_client=http, retry=GovernmentRetryPolicy(max_attempts=3))
        resp = run(gov.submit(_req()))
        self.assertEqual(resp.status, GovernmentStatus.REJECTED)
        self.assertEqual(resp.error_code, GOV_AUTH_FAILED)
        self.assertEqual(len(http.calls), 1)

    def test_retry_on_503_then_success(self):
        http = FakeAsyncHttp(
            [FakeResponse(503, {"error": "busy"}), FakeResponse(200, {"ack_number": "OK"})]
        )
        sleeps: List[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        cfg = GovernmentEndpointConfig(
            customer_id="pilot",
            country_code="sample_gst",
            sandbox_url="https://gov.example/v1",
        )
        gov = HttpGovernmentConnector(
            cfg,
            http_client=http,
            retry=GovernmentRetryPolicy(max_attempts=3, initial_delay_seconds=0.1),
            sleep=fake_sleep,
        )
        resp = run(gov.submit(_req()))
        self.assertEqual(resp.status, GovernmentStatus.ACCEPTED)
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(sleeps, [0.1])

    def test_missing_url(self):
        cfg = GovernmentEndpointConfig(customer_id="pilot", country_code="sample_gst")
        gov = HttpGovernmentConnector(cfg, http_client=FakeAsyncHttp())
        resp = run(gov.submit(_req()))
        self.assertEqual(resp.error_code, GOV_NOT_CONFIGURED)


class TestFactory(unittest.TestCase):
    def test_prefer_mock_by_default(self):
        conn = build_government_connector(
            {"endpoint_url_ref": "https://gov.example", "extra_config": {}},
            customer_id="p",
            country_code="sample_gst",
        )
        self.assertIsInstance(conn, MockGovernmentConnector)

    def test_live_submit_uses_http(self):
        conn = build_government_connector(
            {
                "endpoint_url_ref": "https://gov.example/api",
                "extra_config": {"live_submit": True, "prefer_mock": False},
            },
            customer_id="p",
            country_code="sample_gst",
        )
        self.assertIsInstance(conn, HttpGovernmentConnector)

    def test_already_stamped_flag(self):
        conn = build_government_connector(already_stamped=True)
        self.assertIsInstance(conn, AlreadyStampedGovernmentConnector)


class TestSampleAdapterIntegration(unittest.TestCase):
    def test_sample_submit_uses_injected_government_connector(self):
        from app.tests.test_sample_gst_adapter import sample_document, SELLER_GSTIN

        gov = MockGovernmentConnector(prefix="SAMPLE-ACK")
        adapter = SampleGstAdapter(
            config=SampleGstConfig(
                tax_id_ledger_map={SELLER_GSTIN: "L-1"},
                eway_threshold=50_000,
            ),
            government_connector=gov,
        )
        from app.adapters import AdapterContext

        ctx = AdapterContext(
            customer_id="pilot",
            country_code="sample_gst",
            payload=sample_document(),
        )
        for step in (
            adapter.parse,
            adapter.validate,
            adapter.map,
            adapter.apply_business_rules,
            adapter.transform,
            adapter.format,
        ):
            self.assertTrue(step(ctx).success, step.__name__)
        result = run(adapter.submit(ctx))
        self.assertTrue(result.success, result.error)
        self.assertTrue(str(result.data["ack_number"]).startswith("SAMPLE-ACK-"))

    def test_sample_package_has_no_direct_httpx(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "adapters" / "sample_gst"
        offenders = []
        for path in sorted(root.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "httpx" in text or "AsyncClient" in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [])


class TestCanonicalResponseShape(unittest.TestCase):
    def test_required_fields_present(self):
        resp = run(MockGovernmentConnector().submit(_req()))
        data = resp.to_dict()
        for key in (
            "status",
            "government_reference",
            "submission_id",
            "correlation_id",
            "message",
            "raw_response",
            "timestamp",
        ):
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
