"""
Phase 5 tests — Sample GST adapter + multi-adapter architecture proof.

Proves a second country can be added with only:
  1. a new adapter package
  2. bootstrap registration
  3. workspace configuration

and that the pipeline / orchestrator / registry design are unchanged.

Run from zodiac-api:

  python -m unittest app.tests.test_sample_gst_adapter -v
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import tokenize
import unittest
from types import SimpleNamespace
from typing import Any, Dict

from app.adapters import AdapterContext, ensure_builtin_adapters
from app.adapters.registry import AdapterRegistry
from app.adapters.sample_gst import SampleGstAdapter, build_sample_gst_adapter
from app.adapters.sample_gst.config import SampleGstConfig
from app.core.pipeline import (
    STAGE_CONFIRMATION,
    STAGE_FORMAT,
    STAGE_MAP,
    STAGE_PARSE,
    STAGE_SUBMIT,
    STAGE_VALIDATE,
    CollectingSink,
    InvoicePipelineOrchestrator,
    PipelineRequest,
    PipelineStatus,
    PlatformServices,
    StageStatus,
    default_stage_plan,
)


def _irn(seed: str = "invoice-1") -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


# Valid-looking GSTINs matching the sample regex (different states → interstate).
SELLER_GSTIN = "27AAPFU0939F1ZV"  # state 27
BUYER_GSTIN = "29AABCT1332L1ZV"   # state 29
SAME_STATE_BUYER = "27AABCT1332L1ZV"


def sample_document(**overrides) -> Dict[str, Any]:
    doc = {
        "schema_version": "1.0",
        "document_type": "TAX_INVOICE",
        "document_number": "INV-1001",
        "document_date": "2026-03-01",
        "irn": _irn(),
        "currency": "INR",
        "place_of_supply": "29",
        "total_amount": 118000.0,
        "seller": {"gstin": SELLER_GSTIN, "name": "West Seller Pvt Ltd"},
        "buyer": {"gstin": BUYER_GSTIN, "name": "South Buyer Pvt Ltd"},
        "eway_bill_id": "EWAY-123456789012",
        "line_items": [
            {
                "hsn": "998314",
                "description": "Software services",
                "amount": 100000.0,
                "tax_rate": 0.18,
            },
            {
                "hsn": "998315",
                "description": "Support",
                "amount": 18000.0,
                "tax_rate": 0.18,
            },
        ],
    }
    doc.update(overrides)
    return doc


def _ctx(payload=None, config=None, **meta) -> AdapterContext:
    return AdapterContext(
        customer_id="pilot",
        country_code="sample_gst",
        payload=payload if payload is not None else sample_document(),
        metadata=meta,
    )


class TestSampleRulesDifferFromMexico(unittest.TestCase):
    """Country-specific behaviour that CFDI does not implement."""

    def setUp(self):
        self.adapter = SampleGstAdapter(
            config=SampleGstConfig(
                eway_threshold=50_000,
                tax_id_ledger_map={SELLER_GSTIN: "LEDGER-WEST-27"},
                endpoint_url_ref="https://gov.example/sample-gst/ack",
                auth_secret_ref="vault:sample/gst/token",
            )
        )

    def test_json_not_xml_is_required(self):
        result = self.adapter.parse(_ctx(payload="<Comprobante/>"))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "PARSING_FAILED")
        self.assertIn("JSON", result.error)

    def test_validation_requires_gstin_and_irn(self):
        bad = sample_document(irn="not-an-irn", seller={"gstin": "SHORT", "name": "X"})
        adapter = SampleGstAdapter()
        ctx = _ctx(payload=bad)
        adapter.parse(ctx)
        result = adapter.validate(ctx)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "VALIDATION_FAILED")
        self.assertTrue(any("irn" in e for e in result.meta["errors"]))
        self.assertTrue(any("gstin" in e for e in result.meta["errors"]))

    def test_mapping_uses_workspace_ledger_table_not_sat_service(self):
        ctx = _ctx()
        self.adapter.parse(ctx)
        self.adapter.validate(ctx)
        result = self.adapter.map(ctx)
        self.assertTrue(result.success)
        self.assertEqual(result.data["ledger_account"], "LEDGER-WEST-27")
        self.assertEqual(result.data["supply_type"], "INTER_STATE")
        self.assertFalse(result.data["used_default_ledger"])

    def test_interstate_above_threshold_requires_eway_bill(self):
        doc = sample_document(eway_bill_id=None, total_amount=118000.0)
        # Keep line sum equal to total so only the e-way rule fires.
        adapter = SampleGstAdapter(config=SampleGstConfig(eway_threshold=50_000))
        ctx = _ctx(payload=doc)
        adapter.parse(ctx)
        adapter.validate(ctx)
        adapter.map(ctx)
        result = adapter.apply_business_rules(ctx)
        self.assertFalse(result.success)
        self.assertIn("eway_bill_id", result.error)

    def test_intrastate_does_not_require_eway_bill(self):
        doc = sample_document(
            buyer={"gstin": SAME_STATE_BUYER, "name": "Local Buyer"},
            eway_bill_id=None,
            place_of_supply="27",
        )
        adapter = SampleGstAdapter(config=SampleGstConfig(eway_threshold=50_000))
        ctx = _ctx(payload=doc)
        for step in (adapter.parse, adapter.validate, adapter.map):
            self.assertTrue(step(ctx).success)
        result = adapter.apply_business_rules(ctx)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["supply_type"], "INTRA_STATE")

    def test_format_is_camelcase_government_envelope_not_sap_list(self):
        ctx = _ctx()
        for step in (
            self.adapter.parse,
            self.adapter.validate,
            self.adapter.map,
            self.adapter.apply_business_rules,
            self.adapter.transform,
        ):
            self.assertTrue(step(ctx).success, step.__name__)

        result = self.adapter.format(ctx)
        self.assertTrue(result.success)
        payload = result.data
        self.assertEqual(payload["schema"], "sample-gst-einvoice")
        self.assertIn("invoice", payload)
        self.assertIn("sellerGstin", payload["invoice"])
        self.assertIn("hsnCode", payload["invoice"]["lineItems"][0])
        # Mexico SAP shape markers must not appear.
        self.assertNotIn("DS_UUID", payload)
        self.assertNotIn("GL_ACCOUNT", payload)
        self.assertIsInstance(payload, dict)
        self.assertNotIsInstance(payload, list)

    def test_submit_mock_and_confirmation_use_ack_number(self):
        ctx = _ctx()
        for step in (
            self.adapter.parse,
            self.adapter.validate,
            self.adapter.map,
            self.adapter.apply_business_rules,
            self.adapter.transform,
            self.adapter.format,
        ):
            self.assertTrue(step(ctx).success)

        submit = asyncio.run(self.adapter.submit(ctx))
        self.assertTrue(submit.success)
        self.assertEqual(submit.data["mode"], "mock")
        self.assertTrue(str(submit.data["ack_number"]).startswith("SAMPLE-ACK-"))

        confirmation = self.adapter.receive_confirmation(ctx, submit.data)
        self.assertTrue(confirmation.success)
        self.assertEqual(confirmation.data["document_number"], submit.data["ack_number"])

    def test_config_from_workspace_row(self):
        row = SimpleNamespace(
            endpoint_url_ref="https://gov.example/ack",
            auth_secret_ref="vault:x",
            extra_config={
                "eway_threshold": 10_000,
                "tax_id_ledger_map": {SELLER_GSTIN: "L-1"},
                "expected_currency": "INR",
            },
        )
        adapter = build_sample_gst_adapter(config=row)
        self.assertEqual(adapter.config.eway_threshold, 10_000.0)
        self.assertEqual(adapter.config.tax_id_ledger_map[SELLER_GSTIN], "L-1")
        self.assertEqual(adapter.config.endpoint_url_ref, "https://gov.example/ack")


class TestNoMexicoCodeReuse(unittest.TestCase):
    FORBIDDEN_IMPORTS = (
        "app.adapters.mx_cfdi",
        "app.utils.cfdi_parser",
        "app.services.sat_processor",
        "app.services.sap_transformer",
        "app.services.sap_api_client",
        "app.services.sat_canonical_merge_service",
        "app.services.sat_supplier_mapping_service",
    )

    def test_sample_package_does_not_import_mexico_or_sat(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "adapters" / "sample_gst"
        offenders = []
        for path in sorted(root.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in self.FORBIDDEN_IMPORTS:
                if forbidden in text:
                    offenders.append(f"{path.name}: {forbidden}")
        self.assertEqual(offenders, [])


class TestArchitectureExtensionProof(unittest.TestCase):
    """Adding a country = package + registration + workspace config."""

    PIPELINE_DIR = pathlib.Path(__file__).resolve().parents[1] / "core" / "pipeline"
    PHASE5_MARKER = "sample_gst"

    def test_pipeline_package_has_no_sample_gst_references(self):
        offenders = []
        for path in sorted(self.PIPELINE_DIR.glob("*.py")):
            with tokenize.open(path) as handle:
                for tok in tokenize.generate_tokens(handle.readline):
                    if tok.type in (tokenize.COMMENT, tokenize.STRING):
                        continue
                    if self.PHASE5_MARKER in tok.string.lower():
                        offenders.append(f"{path.name}:{tok.start[0]}")
        self.assertEqual(offenders, [], "Pipeline must not know about sample_gst")

    def test_registry_resolves_both_adapters_without_country_conditionals(self):
        reg = AdapterRegistry()
        ensure_builtin_adapters(reg)

        mx = reg.resolve("mx")
        sample = reg.resolve("sample")
        self.assertEqual(mx.country_code, "mx_cfdi")
        self.assertEqual(sample.country_code, "sample_gst")
        self.assertNotEqual(type(mx), type(sample))

    def test_pipeline_runs_sample_adapter_without_engine_changes(self):
        adapter = SampleGstAdapter(
            config=SampleGstConfig(
                tax_id_ledger_map={SELLER_GSTIN: "LEDGER-1"},
                eway_threshold=50_000,
            )
        )
        doc = sample_document()

        class Resolver:
            def resolve(self, request, workspace):
                return "sample_gst", adapter, SimpleNamespace(extra_config={})

        services = PlatformServices(
            workspace_resolver=SimpleNamespace(
                resolve=lambda request, principal: SimpleNamespace(
                    customer_id="pilot",
                    workspace_id="pilot",
                    pipeline_enabled=True,
                    ai_scoped=True,
                    monitoring_enabled=True,
                    adapters=[],
                )
            ),
            adapter_resolver=Resolver(),
            monitoring=CollectingSink(),
            ai_events=CollectingSink(),
            audit=CollectingSink(),
        )

        # Exact same default plan the platform ships — not a custom StagePlan.
        orchestrator = InvoicePipelineOrchestrator(
            services=services, plan=default_stage_plan()
        )
        result = asyncio.run(
            orchestrator.run(
                PipelineRequest(
                    customer_id="pilot",
                    payload=json.dumps(doc),
                    user=SimpleNamespace(id=1, is_active=True),
                    country_code="sample_gst",
                )
            )
        )

        self.assertEqual(result.status, PipelineStatus.COMPLETED, result.error)
        self.assertEqual(result.country_code, "sample_gst")
        by_name = {s.stage: s for s in result.stages}
        for name in (STAGE_PARSE, STAGE_VALIDATE, STAGE_MAP, STAGE_FORMAT, STAGE_SUBMIT, STAGE_CONFIRMATION):
            self.assertIs(by_name[name].status, StageStatus.SUCCESS, name)
        self.assertTrue(str(result.confirmation["document_number"]).startswith("SAMPLE-ACK-"))

    def test_workspace_config_selects_sample_via_registry_resolver(self):
        from app.core.pipeline.hooks import RegistryAdapterResolver

        ensure_builtin_adapters()
        workspace = SimpleNamespace(
            customer_id="pilot",
            adapters=[
                SimpleNamespace(
                    country_code="sample_gst",
                    enabled=True,
                    endpoint_url_ref="https://gov.example/ack",
                    auth_secret_ref="vault:sample/token",
                    extra_config={"eway_threshold": 1_000, "default_ledger": "L-PILOT"},
                )
            ],
        )
        request = SimpleNamespace(
            country_code="sample_gst",
            db=None,
            customer_id="pilot",
        )
        code, adapter, config = RegistryAdapterResolver().resolve(request, workspace)
        self.assertEqual(code, "sample_gst")
        self.assertIsInstance(adapter, SampleGstAdapter)
        self.assertEqual(adapter.config.default_ledger, "L-PILOT")
        self.assertEqual(adapter.config.eway_threshold, 1_000.0)

    def test_mexico_still_resolves_and_parses_after_sample_registration(self):
        """Regression: Adapter #1 is unaffected by Adapter #2."""
        from app.utils.cfdi_parser import CFDIParser

        reg = AdapterRegistry()
        ensure_builtin_adapters(reg)
        mx = reg.resolve("mx_cfdi")

        cfdi = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"'
            ' xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" Version="4.0"'
            ' Serie="A" Folio="1" Fecha="2026-01-15T10:30:00" SubTotal="100.00"'
            ' Total="116.00" Moneda="MXN" TipoDeComprobante="I">'
            '<cfdi:Emisor Rfc="AAA010101AAA" Nombre="Proveedor"/>'
            '<cfdi:Receptor Rfc="BBB020202BBB" Nombre="Cliente"/>'
            '<cfdi:Complemento><tfd:TimbreFiscalDigital'
            ' UUID="11111111-2222-3333-4444-555555555555"'
            ' FechaTimbrado="2026-01-15T10:35:00"/></cfdi:Complemento>'
            '</cfdi:Comprobante>'
        )
        ctx = AdapterContext(customer_id="acme", country_code="mx_cfdi", payload=cfdi)
        parsed = mx.parse(ctx)
        self.assertTrue(parsed.success)
        self.assertEqual(parsed.data, CFDIParser.parse_cfdi(cfdi))
        self.assertTrue(mx.validate(ctx).success)


class TestCreditNoteRule(unittest.TestCase):
    def test_credit_note_requires_original_irn(self):
        doc = sample_document(
            document_type="CREDIT_NOTE",
            original_irn=None,
            total_amount=18000.0,
            line_items=[{
                "hsn": "998314",
                "description": "Credit",
                "amount": 18000.0,
                "tax_rate": 0.18,
            }],
            # Intrastate + below threshold so only credit-note rule fires.
            buyer={"gstin": SAME_STATE_BUYER, "name": "Local"},
            eway_bill_id=None,
            place_of_supply="27",
        )
        adapter = SampleGstAdapter()
        ctx = _ctx(payload=doc)
        for step in (adapter.parse, adapter.validate, adapter.map):
            self.assertTrue(step(ctx).success, step.__name__)
        result = adapter.apply_business_rules(ctx)
        self.assertFalse(result.success)
        self.assertIn("original_irn", result.error)


if __name__ == "__main__":
    unittest.main()
