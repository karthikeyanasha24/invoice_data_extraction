"""
Phase 3 tests — MxCfdiAdapter (Adapter #1) façade parity.

Proves the adapter produces the *same* results as the existing production
services and delegates with identical arguments. No DB and no network:
DB-backed and HTTP-backed services are patched at their production import
paths, so a failure here means the façade drifted from production.

Run from zodiac-api:

  python -m unittest app.tests.test_mx_cfdi_adapter_parity -v
"""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.adapters import AdapterContext, AdapterStage
from app.adapters.mx_cfdi import MxCfdiAdapter, build_mx_cfdi_adapter
from app.adapters.mx_cfdi.config import FORMAT_JSON, MERGE_STRATEGY_SIMPLE
from app.utils.cfdi_parser import CFDIParser

VALID_CFDI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
                  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                  Version="4.0" Serie="A" Folio="1234"
                  Fecha="2026-01-15T10:30:00" SubTotal="1000.00" Total="1160.00"
                  Moneda="MXN" TipoDeComprobante="I" FormaPago="03"
                  MetodoPago="PUE" LugarExpedicion="64000">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="Proveedor Demo SA de CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Cliente Demo SA de CV" UsoCFDI="G03"
                 DomicilioFiscalReceptor="64000"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1" ClaveUnidad="H87"
                   Descripcion="Servicio de consultoria" ValorUnitario="1000.00"
                   Importe="1000.00"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1"
                             UUID="11111111-2222-3333-4444-555555555555"
                             FechaTimbrado="2026-01-15T10:35:00"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""

# Missing Complemento/TimbreFiscalDigital.
INVALID_CFDI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0">
  <cfdi:Emisor Rfc="AAA010101AAA"/>
  <cfdi:Receptor Rfc="BBB020202BBB"/>
</cfdi:Comprobante>
"""


class SATCanonicalMerged:  # noqa: N801 - name drives adapter kind inference
    """Stand-in for the ORM row; only the fields the transformer reads."""

    def __init__(self):
        self.id = "canon-1"
        self.vendor_rfc = "AAA010101AAA"
        self.vendor_name = "Proveedor Demo SA de CV"
        self.fiscal_year = 2026
        self.fiscal_period = 1
        self.currency = "MXN"
        self.net_amount = 1160.00
        self.payment_method = "PPD"
        self.sap_gl_account = "9999999999"
        self.linked_document_ids = []


def _ctx(**kwargs) -> AdapterContext:
    kwargs.setdefault("customer_id", "acme")
    kwargs.setdefault("country_code", "mx_cfdi")
    return AdapterContext(**kwargs)


class TestParseValidateParity(unittest.TestCase):
    """parse()/validate() must equal a direct CFDIParser call."""

    def setUp(self):
        self.adapter = MxCfdiAdapter()

    def test_parse_matches_cfdi_parser(self):
        result = self.adapter.parse(_ctx(payload=VALID_CFDI_XML))
        self.assertTrue(result.success)
        self.assertEqual(result.data, CFDIParser.parse_cfdi(VALID_CFDI_XML))

    def test_parse_accepts_bytes_and_dict_payloads(self):
        expected = CFDIParser.parse_cfdi(VALID_CFDI_XML)
        for payload in (
            VALID_CFDI_XML.encode("utf-8"),
            {"xml_content": VALID_CFDI_XML},
            {"xml": VALID_CFDI_XML},
        ):
            self.assertEqual(self.adapter.parse(_ctx(payload=payload)).data, expected)

    def test_parse_stores_output_and_document_type(self):
        ctx = _ctx(payload=VALID_CFDI_XML)
        self.adapter.parse(ctx)
        self.assertEqual(ctx.document_type, "INVOICE")
        self.assertIsNotNone(ctx.get_output(AdapterStage.PARSE))

    def test_parse_failure_mirrors_parser_error(self):
        result = self.adapter.parse(_ctx(payload="<not-xml"))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "PARSING_FAILED")

    def test_validate_matches_cfdi_parser_on_valid_document(self):
        is_valid, error = CFDIParser.validate_cfdi_structure(VALID_CFDI_XML)
        result = self.adapter.validate(_ctx(payload=VALID_CFDI_XML))
        self.assertEqual((result.data["is_valid"], result.data["error"]), (is_valid, error))
        self.assertTrue(result.success)

    def test_validate_matches_cfdi_parser_on_invalid_document(self):
        is_valid, error = CFDIParser.validate_cfdi_structure(INVALID_CFDI_XML)
        result = self.adapter.validate(_ctx(payload=INVALID_CFDI_XML))
        self.assertFalse(is_valid)
        self.assertFalse(result.success)
        self.assertEqual(result.error, error)
        self.assertEqual(result.error_code, "VALIDATION_FAILED")


class TestIngestDelegation(unittest.TestCase):
    """ingest() must call the same processor as /api/v1/sat/intake."""

    @patch("app.services.sat_processor.SATDocumentProcessor")
    def test_delegates_with_identical_arguments(self, processor_cls):
        processor_cls.return_value.process_cfdi_document.return_value = {
            "success": True, "status": "VALIDATED", "document_id": "doc-1"
        }
        db = MagicMock()
        ctx = _ctx(payload=VALID_CFDI_XML, user_id=7, db=db, metadata={"source": "supplier"})

        result = MxCfdiAdapter().ingest(ctx)

        processor_cls.assert_called_once_with(db)
        processor_cls.return_value.process_cfdi_document.assert_called_once_with(
            user_id=7, xml_content=VALID_CFDI_XML, source="supplier"
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "VALIDATED")

    @patch("app.services.sat_processor.SATDocumentProcessor")
    def test_duplicate_status_is_surfaced_unchanged(self, processor_cls):
        processor_cls.return_value.process_cfdi_document.return_value = {
            "success": False, "status": "DUPLICATE", "error": "already exists"
        }
        result = MxCfdiAdapter(db=MagicMock()).ingest(_ctx(payload=VALID_CFDI_XML, user_id=1))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "DUPLICATE")

    def test_requires_a_database_session(self):
        self.assertFalse(MxCfdiAdapter().ingest(_ctx(payload=VALID_CFDI_XML)).success)


class TestMappingDelegation(unittest.TestCase):
    @patch("app.services.sat_supplier_mapping_service.SATSupplierMappingService")
    def test_uses_rfc_mapping_when_present(self, service_cls):
        mapping = SimpleNamespace(gl_account="1234567890")
        service_cls.return_value.get_mapping_by_rfc.return_value = mapping

        ctx = _ctx(db=MagicMock(), metadata={"supplier_rfc": "AAA010101AAA"})
        result = MxCfdiAdapter().map(ctx)

        service_cls.return_value.get_mapping_by_rfc.assert_called_once_with("AAA010101AAA")
        service_cls.return_value.get_or_create_default_mapping.assert_not_called()
        self.assertTrue(result.success)
        self.assertIs(result.data["mapping"], mapping)
        self.assertFalse(result.data["used_default"])

    @patch("app.services.sat_supplier_mapping_service.SATSupplierMappingService")
    def test_falls_back_to_default_mapping_like_canonical_merge(self, service_cls):
        service_cls.return_value.get_mapping_by_rfc.return_value = None
        service_cls.return_value.get_or_create_default_mapping.return_value = SimpleNamespace(
            gl_account="9999999999"
        )
        result = MxCfdiAdapter(db=MagicMock()).map(_ctx(metadata={"supplier_rfc": "ZZZ"}))
        self.assertTrue(result.success)
        self.assertTrue(result.data["used_default"])

    @patch("app.services.sat_supplier_mapping_service.SATSupplierMappingService")
    def test_reads_rfc_from_parse_output(self, service_cls):
        service_cls.return_value.get_mapping_by_rfc.return_value = SimpleNamespace(gl_account="1")
        adapter = MxCfdiAdapter(db=MagicMock())
        ctx = _ctx(payload=VALID_CFDI_XML)
        adapter.parse(ctx)
        adapter.map(ctx)
        service_cls.return_value.get_mapping_by_rfc.assert_called_once_with("AAA010101AAA")


class TestBusinessRulesDelegation(unittest.TestCase):
    @patch("app.services.sat_canonical_merge_service.SATCanonicalMergeService")
    def test_delegates_canonical_merge_with_identical_arguments(self, service_cls):
        service_cls.return_value.merge_documents_for_period.return_value = {
            "total": 2, "documents": []
        }
        db = MagicMock()
        ctx = _ctx(
            db=db,
            user_id=7,
            metadata={"company_code": "1000", "fiscal_year": 2026, "fiscal_period": 1},
        )

        result = MxCfdiAdapter().apply_business_rules(ctx)

        service_cls.assert_called_once_with(db)
        service_cls.return_value.merge_documents_for_period.assert_called_once_with(
            user_id=7, company_code="1000", fiscal_year=2026, fiscal_period=1
        )
        self.assertEqual(result.data["total"], 2)

    def test_missing_period_context_is_reported_not_raised(self):
        result = MxCfdiAdapter(db=MagicMock()).apply_business_rules(_ctx(user_id=1))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BUSINESS_RULES_FAILED")

    def test_simple_merge_strategy_is_explicitly_unsupported(self):
        ctx = _ctx(db=MagicMock(), metadata={"merge_strategy": MERGE_STRATEGY_SIMPLE})
        self.assertFalse(MxCfdiAdapter().apply_business_rules(ctx).success)


class TestTransformParity(unittest.TestCase):
    """transform() output must equal SAPTransformer's output byte for byte."""

    TIMESTAMPS = ("ISSUE_DATETIME", "DS_STAMP_DATETIME")

    def _strip_timestamps(self, docs):
        cleaned = []
        for doc in docs:
            copy = dict(doc)
            for key in self.TIMESTAMPS:
                self.assertIn(key, copy)
                copy.pop(key)
            cleaned.append(copy)
        return cleaned

    def test_canonical_transform_matches_sap_transformer(self):
        from app.services.sap_transformer import SAPTransformer

        canonical = SATCanonicalMerged()
        expected = SAPTransformer(None).transform_canonical_to_sap_format(canonical)

        ctx = _ctx(metadata={"document": canonical})
        result = MxCfdiAdapter().transform(ctx)

        self.assertTrue(result.success)
        self.assertEqual(self._strip_timestamps(result.data), self._strip_timestamps(expected))
        self.assertEqual(result.meta["document_kind"], "canonical")

    @patch("app.services.sap_transformer.SAPTransformer")
    def test_simple_document_routes_to_simple_transformer(self, transformer_cls):
        transformer_cls.return_value.transform_simple_to_sap_format.return_value = [{"A": 1}]

        class SATSimpleMerged:  # noqa: N801 - name drives kind inference
            pass

        ctx = _ctx(metadata={"document": SATSimpleMerged()})
        result = MxCfdiAdapter().transform(ctx)

        transformer_cls.return_value.transform_simple_to_sap_format.assert_called_once()
        transformer_cls.return_value.transform_canonical_to_sap_format.assert_not_called()
        self.assertEqual(result.data, [{"A": 1}])

    def test_unknown_document_kind_is_reported(self):
        result = MxCfdiAdapter().transform(_ctx(metadata={"document": object()}))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TRANSFORM_FAILED")


class TestFormat(unittest.TestCase):
    def test_json_format_passes_transform_output_through_unchanged(self):
        adapter = MxCfdiAdapter()
        canonical = SATCanonicalMerged()
        ctx = _ctx(metadata={"document": canonical, "output_format": FORMAT_JSON})
        transformed = adapter.transform(ctx).data

        result = adapter.format(ctx)

        self.assertTrue(result.success)
        self.assertIs(result.data, transformed)
        self.assertEqual(result.meta["content_type"], "application/json")

    @patch("app.services.sap_transformer.SAPTransformer")
    def test_xml_format_delegates_to_transformer(self, transformer_cls):
        transformer_cls.return_value.transform_canonical_to_sap_xml.return_value = "<X/>"
        canonical = SATCanonicalMerged()
        ctx = _ctx(metadata={"document": canonical, "output_format": "xml"})

        result = MxCfdiAdapter().format(ctx)

        transformer_cls.return_value.transform_canonical_to_sap_xml.assert_called_once_with(canonical)
        self.assertEqual(result.data, "<X/>")

    def test_format_requires_transform_first(self):
        self.assertFalse(MxCfdiAdapter().format(_ctx()).success)


class TestSubmitAndConfirmation(unittest.TestCase):
    def test_submit_uses_the_existing_sap_client(self):
        payload = [{"DS_UUID": "abc"}]
        sap_response = {"success": True, "sap_response": {"document_number": "SAP-42"}}

        async def fake_send(**kwargs):
            fake_send.kwargs = kwargs
            return sap_response

        ctx = _ctx(metadata={"portal_reference": "ref-9", "document_type_hint": "SIMPLE_MERGE"})
        ctx.set_output(AdapterStage.FORMAT, payload)

        with patch("app.services.sap_api_client.sap_client") as client:
            client.send_json_to_sap_with_session = fake_send
            result = asyncio.run(MxCfdiAdapter().submit(ctx))

        self.assertEqual(
            fake_send.kwargs,
            {"payload": payload, "document_type": "SIMPLE_MERGE", "portal_reference": "ref-9"},
        )
        self.assertTrue(result.success)

    def test_submit_failure_is_returned_not_raised(self):
        async def fake_send(**kwargs):
            return {"success": False, "error": "Timeout connecting to SAP.", "sap_status_code": 500}

        ctx = _ctx()
        ctx.set_output(AdapterStage.FORMAT, [{"A": 1}])
        with patch("app.services.sap_api_client.sap_client") as client:
            client.send_json_to_sap_with_session = fake_send
            result = asyncio.run(MxCfdiAdapter().submit(ctx))

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SUBMIT_FAILED")
        self.assertEqual(result.meta["sap_status_code"], 500)

    def test_submit_period_delegates_to_bulk_sender(self):
        async def fake_send_all(**kwargs):
            fake_send_all.kwargs = kwargs
            return {"success": True, "sent": 3}

        ctx = _ctx(db=MagicMock(), user_id=7, metadata={"fiscal_year": 2026, "fiscal_period": 1})
        with patch("app.services.sap_send_all.SAPBulkSender") as sender_cls:
            sender_cls.return_value.send_all_to_sap = fake_send_all
            result = asyncio.run(MxCfdiAdapter().submit_period(ctx))

        self.assertEqual(fake_send_all.kwargs, {"user_id": 7, "fiscal_year": 2026, "fiscal_period": 1})
        self.assertTrue(result.success)

    def test_confirmation_extraction_matches_send_to_sap_route(self):
        """Same keys the /send-to-sap handlers read: document_number, then sap_document_number."""
        adapter = MxCfdiAdapter()

        primary = adapter.receive_confirmation(_ctx(), {
            "success": True, "sap_response": {"document_number": "SAP-1"}
        })
        self.assertEqual(primary.data["document_number"], "SAP-1")

        fallback_key = adapter.receive_confirmation(_ctx(), {
            "success": True, "sap_response": {"sap_document_number": "SAP-2"}
        })
        self.assertEqual(fallback_key.data["document_number"], "SAP-2")

    def test_confirmation_without_document_number_stays_none(self):
        result = MxCfdiAdapter().receive_confirmation(_ctx(), {"success": True, "sap_response": "OK"})
        self.assertTrue(result.success)
        self.assertIsNone(result.data["document_number"])

    def test_rejected_submission_produces_a_failed_confirmation(self):
        result = MxCfdiAdapter().receive_confirmation(
            _ctx(), {"success": False, "error": "SAP returned status 500", "sap_status_code": 500}
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "SAP returned status 500")

    def test_confirmation_reads_submit_output_when_no_response_passed(self):
        ctx = _ctx()
        ctx.set_output(AdapterStage.SUBMIT, {"success": True, "sap_response": {"document_number": "X"}})
        self.assertEqual(MxCfdiAdapter().receive_confirmation(ctx).data["document_number"], "X")


class TestPlatformOwnedStages(unittest.TestCase):
    def test_update_erp_defers_to_core_connector(self):
        result = MxCfdiAdapter().update_erp(_ctx())
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "NOT_IMPLEMENTED")

    def test_monitoring_event_is_built_but_not_persisted(self):
        ctx = _ctx(user_id=7)
        result = MxCfdiAdapter().generate_monitoring_event(
            ctx, AdapterStage.SUBMIT, "SUCCESS", "sent", sap_document_number="SAP-1"
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["stage"], "submit")
        self.assertEqual(result.data["customer_id"], "acme")
        self.assertEqual(result.data["sap_document_number"], "SAP-1")
        self.assertEqual(len(ctx.events), 1)


class TestFactoryAndMetadata(unittest.TestCase):
    def test_factory_accepts_workspace_adapter_config_row(self):
        row = SimpleNamespace(
            endpoint_url_ref="vault:mx/endpoint",
            auth_secret_ref="vault:mx/secret",
            extra_config={"company_code": "1000", "merge_strategy": "canonical"},
        )
        adapter = build_mx_cfdi_adapter(db=None, config=row)
        self.assertEqual(adapter.config.company_code, "1000")
        self.assertEqual(adapter.config.endpoint_url_ref, "vault:mx/endpoint")

    def test_factory_tolerates_missing_config(self):
        self.assertIsInstance(build_mx_cfdi_adapter(), MxCfdiAdapter)

    def test_describe_reports_country_metadata(self):
        described = MxCfdiAdapter().describe()
        self.assertEqual(described["country_code"], "mx_cfdi")
        self.assertIn("INVOICE", described["supported_document_types"])
        # No live SAT/PAC integration exists today.
        self.assertNotIn("government_api", described["capabilities"])


if __name__ == "__main__":
    unittest.main()
