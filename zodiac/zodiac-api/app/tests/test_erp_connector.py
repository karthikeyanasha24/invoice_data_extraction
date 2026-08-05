"""
Phase 6 tests — HttpErpConnector idempotency and error classification.

Run from zodiac-api:

  python -m unittest app.tests.test_erp_connector -v
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.core.erp import (
    CanonicalConfirmation,
    DocumentStatus,
    ErpPushRequest,
    HttpErpConnector,
    InMemoryOutboxStore,
    derive_idempotency_key,
)
from app.core.erp.models import (
    ERP_AUTH_FAILED,
    ERP_DUPLICATE,
    ERP_NOT_CONFIGURED,
    ERP_REJECTED,
    ERP_TIMEOUT,
    ERP_UPDATE_FAILED,
)


def _confirmation(**overrides) -> CanonicalConfirmation:
    base = dict(
        correlation_id="corr-1",
        customer_id="acme",
        accepted=True,
        status=DocumentStatus.ACCEPTED,
        idempotency_key=derive_idempotency_key("acme", "corr-1"),
        external_document_number="DOC-1",
    )
    base.update(overrides)
    return CanonicalConfirmation(**base)


def _request(**overrides) -> ErpPushRequest:
    base = dict(
        customer_id="acme",
        confirmation=_confirmation(),
        callback_url="https://erp.example/hook",
        connection_key="primary",
    )
    base.update(overrides)
    return ErpPushRequest(**base)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {"ok": True}
        self.text = text or str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeHttp:
    def __init__(self, responses=None):
        self.responses = list(responses or [FakeResponse()])
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if not self.responses:
            return FakeResponse(500, {"error": "none left"})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestHttpErpConnector(unittest.TestCase):
    def test_successful_push_sends_idempotency_header(self):
        http = FakeHttp()
        store = InMemoryOutboxStore()
        connector = HttpErpConnector(memory_store=store, http_client=http)
        result = connector.push_confirmation(_request())

        self.assertTrue(result.success)
        self.assertEqual(result.status, DocumentStatus.ERP_ACKNOWLEDGED)
        self.assertEqual(http.calls[0]["headers"]["X-Idempotency-Key"], result.idempotency_key)
        self.assertEqual(
            http.calls[0]["json"]["confirmation"]["external_document_number"], "DOC-1"
        )
        self.assertEqual(store.get(result.idempotency_key)["status"], "SUCCESS")

    def test_duplicate_short_circuits_without_second_http_call(self):
        http = FakeHttp([FakeResponse(), FakeResponse()])
        store = InMemoryOutboxStore()
        connector = HttpErpConnector(memory_store=store, http_client=http)
        first = connector.push_confirmation(_request())
        second = connector.push_confirmation(_request())

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertTrue(second.duplicate)
        self.assertEqual(second.error.error_code, ERP_DUPLICATE)
        self.assertEqual(len(http.calls), 1)

    def test_missing_url_is_not_configured(self):
        connector = HttpErpConnector(memory_store=InMemoryOutboxStore(), http_client=FakeHttp())
        result = connector.push_confirmation(
            _request(callback_url=None, base_url=None)
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error.error_code, ERP_NOT_CONFIGURED)
        self.assertFalse(result.error.retryable)

    def test_auth_failure_not_retryable(self):
        http = FakeHttp([FakeResponse(401, {"error": "no"})])
        connector = HttpErpConnector(memory_store=InMemoryOutboxStore(), http_client=http)
        result = connector.push_confirmation(_request())
        self.assertEqual(result.error.error_code, ERP_AUTH_FAILED)
        self.assertFalse(result.error.retryable)

    def test_business_rejection_not_retryable(self):
        http = FakeHttp([FakeResponse(422, {"error": "bad"})])
        connector = HttpErpConnector(memory_store=InMemoryOutboxStore(), http_client=http)
        result = connector.push_confirmation(_request())
        self.assertEqual(result.error.error_code, ERP_REJECTED)
        self.assertFalse(result.error.retryable)

    def test_server_error_is_retryable(self):
        http = FakeHttp([FakeResponse(503, {"error": "busy"})])
        connector = HttpErpConnector(memory_store=InMemoryOutboxStore(), http_client=http)
        result = connector.push_confirmation(_request())
        self.assertEqual(result.error.error_code, ERP_UPDATE_FAILED)
        self.assertTrue(result.error.retryable)

    def test_timeout_is_retryable(self):
        http = FakeHttp([TimeoutError("slow")])
        connector = HttpErpConnector(memory_store=InMemoryOutboxStore(), http_client=http)
        result = connector.push_confirmation(_request())
        self.assertEqual(result.error.error_code, ERP_TIMEOUT)
        self.assertTrue(result.error.retryable)

    def test_health_check(self):
        connector = HttpErpConnector()
        self.assertTrue(
            connector.health_check(SimpleNamespace(callback_url="https://x", base_url=None))
        )
        self.assertFalse(connector.health_check(SimpleNamespace(callback_url=None, base_url=None)))

    def test_connector_does_not_branch_on_country_code(self):
        """Same payload path for any country_code on the confirmation."""
        codes = ("mx_cfdi", "sample_gst", "germany", None)
        http = FakeHttp([FakeResponse() for _ in codes])
        store = InMemoryOutboxStore()
        connector = HttpErpConnector(memory_store=store, http_client=http)

        for code in codes:
            conf = _confirmation(
                correlation_id=f"corr-{code}",
                idempotency_key=derive_idempotency_key("acme", f"corr-{code}"),
                country_code=code,
            )
            result = connector.push_confirmation(_request(confirmation=conf))
            self.assertTrue(result.success, code)
            sent = http.calls[-1]["json"]["confirmation"]
            self.assertNotIn("country_code", sent)


if __name__ == "__main__":
    unittest.main()
