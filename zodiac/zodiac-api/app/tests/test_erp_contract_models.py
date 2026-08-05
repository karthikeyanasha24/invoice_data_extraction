"""
Phase 6 tests — ERP contract models + normalization.

Run from zodiac-api:

  python -m unittest app.tests.test_erp_contract_models -v
"""
from __future__ import annotations

import unittest

from app.core.erp import (
    CanonicalConfirmation,
    DocumentStatus,
    derive_idempotency_key,
    normalize_confirmation,
    try_normalize_confirmation,
)
from app.core.erp.models import ERP_INVALID_PAYLOAD


class TestNormalizeConfirmation(unittest.TestCase):
    def test_maps_mexico_document_number_alias(self):
        conf = normalize_confirmation(
            {"accepted": True, "document_number": "SAP-42"},
            customer_id="acme",
            correlation_id="c-1",
            country_code="mx_cfdi",
        )
        self.assertEqual(conf.external_document_number, "SAP-42")
        self.assertEqual(conf.status, DocumentStatus.ACCEPTED)
        self.assertEqual(conf.country_code, "mx_cfdi")
        self.assertEqual(conf.idempotency_key, derive_idempotency_key("acme", "c-1"))

    def test_maps_sample_ack_number_alias(self):
        conf = normalize_confirmation(
            {"success": True, "ack_number": "SAMPLE-ACK-1", "irn": "abc"},
            customer_id="pilot",
            correlation_id="c-2",
        )
        self.assertEqual(conf.external_document_number, "SAMPLE-ACK-1")
        self.assertTrue(conf.accepted)
        self.assertEqual(conf.extensions.get("irn"), "abc")

    def test_rejected_confirmation(self):
        conf = normalize_confirmation(
            {"accepted": False, "error": "rejected"},
            customer_id="acme",
            correlation_id="c-3",
        )
        self.assertEqual(conf.status, DocumentStatus.REJECTED)
        self.assertFalse(conf.accepted)

    def test_passthrough_canonical(self):
        original = CanonicalConfirmation(
            correlation_id="c-4",
            customer_id="acme",
            accepted=True,
            status=DocumentStatus.ACCEPTED,
            idempotency_key="fixed-key",
            external_document_number="X",
        )
        conf = normalize_confirmation(
            original, customer_id="acme", correlation_id="c-4"
        )
        self.assertIs(conf, original)
        self.assertEqual(conf.idempotency_key, "fixed-key")

    def test_erp_payload_excludes_extensions_and_country(self):
        conf = normalize_confirmation(
            {"accepted": True, "document_number": "N-1", "custom_field": 1},
            customer_id="acme",
            correlation_id="c-5",
            country_code="sample_gst",
        )
        payload = conf.erp_payload()
        self.assertEqual(payload["external_document_number"], "N-1")
        self.assertNotIn("country_code", payload)
        self.assertNotIn("extensions", payload)
        self.assertNotIn("custom_field", payload)

    def test_invalid_payload(self):
        conf, err = try_normalize_confirmation(
            None, customer_id="acme", correlation_id="c-6"
        )
        self.assertIsNone(conf)
        self.assertEqual(err.error_code, ERP_INVALID_PAYLOAD)


class TestIdempotencyKey(unittest.TestCase):
    def test_stable_derivation(self):
        a = derive_idempotency_key("acme", "corr")
        b = derive_idempotency_key("acme", "corr")
        c = derive_idempotency_key("other", "corr")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)


if __name__ == "__main__":
    unittest.main()
