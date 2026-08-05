"""
Phase 4 tests — Invoice Processing Orchestrator.

No DB and no network. Run from zodiac-api:

  python -m unittest app.tests.test_pipeline_orchestrator -v
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import tokenize
import unittest
from types import SimpleNamespace
from typing import Any, List

from app.adapters.base import (
    AdapterCapability,
    AdapterStage,
    CountryAdapter,
    StageResult,
)
from app.core.pipeline import (
    STAGE_AI_EVENT,
    STAGE_AUTHENTICATE,
    STAGE_BUSINESS_RULES,
    STAGE_CONFIRMATION,
    STAGE_ERP_UPDATE,
    STAGE_FORMAT,
    STAGE_MAP,
    STAGE_MONITORING,
    STAGE_PARSE,
    STAGE_RESOLVE_ADAPTER,
    STAGE_RESOLVE_WORKSPACE,
    STAGE_SUBMIT,
    STAGE_TRANSFORM,
    STAGE_VALIDATE,
    CollectingSink,
    InvoicePipelineOrchestrator,
    PipelineRequest,
    PipelineStatus,
    PlatformServices,
    StageSpec,
    StageStatus,
    TRANSPORT_RETRY,
    default_stage_plan,
)

DOCUMENTED_FLOW = [
    STAGE_AUTHENTICATE,
    STAGE_RESOLVE_WORKSPACE,
    STAGE_RESOLVE_ADAPTER,
    STAGE_PARSE,
    STAGE_VALIDATE,
    STAGE_MAP,
    STAGE_BUSINESS_RULES,
    STAGE_TRANSFORM,
    STAGE_FORMAT,
    STAGE_SUBMIT,
    STAGE_CONFIRMATION,
    STAGE_ERP_UPDATE,
    STAGE_MONITORING,
    STAGE_AI_EVENT,
]


class RecordingAdapter(CountryAdapter):
    """A country the orchestrator has never heard of."""

    country_code = "atlantis"
    display_name = "Atlantis — Test Adapter"
    supported_document_types = ("INVOICE",)

    def __init__(self, db: Any = None, config: Any = None, fail_on: str = None):
        self.db = db
        self.config = config
        self.fail_on = fail_on
        self.calls: List[str] = []
        self.submit_failures = 0

    def capabilities(self):
        return [AdapterCapability.PARSE]

    def _run(self, name: str, stage: AdapterStage, data: Any = None) -> StageResult:
        self.calls.append(name)
        if self.fail_on == name:
            return StageResult.fail(stage, f"{name} rejected", f"{name.upper()}_FAILED")
        return StageResult.ok(stage, data if data is not None else {name: True})

    def parse(self, ctx): return self._run("parse", AdapterStage.PARSE, {"uuid": "u-1"})
    def validate(self, ctx): return self._run("validate", AdapterStage.VALIDATE)
    def map(self, ctx): return self._run("map", AdapterStage.MAP)
    def apply_business_rules(self, ctx): return self._run("business_rules", AdapterStage.BUSINESS_RULES)
    def transform(self, ctx): return self._run("transform", AdapterStage.TRANSFORM)
    def format(self, ctx): return self._run("format", AdapterStage.FORMAT)

    async def submit(self, ctx):
        self.calls.append("submit")
        if self.submit_failures > 0:
            self.submit_failures -= 1
            return StageResult.fail(AdapterStage.SUBMIT, "gateway timeout", "SUBMIT_FAILED")
        if self.fail_on == "submit":
            return StageResult.fail(AdapterStage.SUBMIT, "submit rejected", "SUBMIT_FAILED")
        return StageResult.ok(AdapterStage.SUBMIT, {"success": True})

    def receive_confirmation(self, ctx, response=None):
        self.calls.append("receive_confirmation")
        confirmation = {"accepted": True, "document_number": "DOC-1"}
        ctx.set_output(AdapterStage.CONFIRMATION, confirmation)
        return StageResult.ok(AdapterStage.CONFIRMATION, confirmation)


def workspace(**overrides):
    base = dict(
        customer_id="acme",
        workspace_id="acme",
        pipeline_enabled=True,
        ai_scoped=True,
        monitoring_enabled=True,
        adapters=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class StubWorkspaceResolver:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else workspace()
        self.error = error
        self.calls = 0

    def resolve(self, request, principal):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class StubAdapterResolver:
    def __init__(self, adapter=None, error=None, country_code="atlantis"):
        self.adapter = adapter or RecordingAdapter()
        self.error = error
        self.country_code = country_code

    def resolve(self, request, workspace):
        if self.error:
            raise self.error
        return self.country_code, self.adapter, SimpleNamespace(extra_config={"k": "v"})


def build(services_overrides=None, adapter=None, plan=None, sleeps=None):
    """Orchestrator wired with stubs; returns (orchestrator, services, adapter)."""
    adapter = adapter or RecordingAdapter()
    services = PlatformServices(
        workspace_resolver=StubWorkspaceResolver(),
        adapter_resolver=StubAdapterResolver(adapter),
        monitoring=CollectingSink(),
        ai_events=CollectingSink(),
        audit=CollectingSink(),
    )
    for key, value in (services_overrides or {}).items():
        setattr(services, key, value)

    async def fake_sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return (
        InvoicePipelineOrchestrator(services=services, plan=plan, sleep=fake_sleep),
        services,
        adapter,
    )


def request(**overrides):
    base = dict(
        customer_id="acme",
        payload="<xml/>",
        user=SimpleNamespace(id=7, is_active=True),
        db=None,
    )
    base.update(overrides)
    return PipelineRequest(**base)


def run(orchestrator, req):
    return asyncio.run(orchestrator.run(req))


class TestHappyPath(unittest.TestCase):
    def setUp(self):
        self.orchestrator, self.services, self.adapter = build()
        self.result = run(self.orchestrator, request())

    def test_confirmation_receives_the_submit_output(self):
        """The confirmation stage must hand the submit payload to the adapter."""
        seen = {}

        class ConfirmingAdapter(RecordingAdapter):
            def receive_confirmation(self, ctx, response=None):
                seen["response"] = response
                return super().receive_confirmation(ctx, response)

            async def submit(self, ctx):
                from app.adapters.base import AdapterStage, StageResult
                payload = {"success": True, "sap_response": {"document_number": "X-9"}}
                ctx.set_output(AdapterStage.SUBMIT, payload)
                self.calls.append("submit")
                return StageResult.ok(AdapterStage.SUBMIT, payload)

        orchestrator, _, _ = build(adapter=ConfirmingAdapter())
        run(orchestrator, request())
        self.assertEqual(seen["response"]["sap_response"]["document_number"], "X-9")

    def test_pipeline_completes(self):
        self.assertEqual(self.result.status, PipelineStatus.COMPLETED)
        self.assertTrue(self.result.succeeded)
        self.assertIsNone(self.result.failed_stage)

    def test_stage_order_matches_the_documented_flow(self):
        self.assertEqual([s.stage for s in self.result.stages], DOCUMENTED_FLOW)

    def test_every_stage_except_erp_update_succeeds(self):
        by_name = {s.stage: s for s in self.result.stages}
        for name in DOCUMENTED_FLOW:
            if name == STAGE_ERP_UPDATE:
                continue
            self.assertIs(by_name[name].status, StageStatus.SUCCESS, name)

    def test_adapter_stages_run_in_contract_order(self):
        self.assertEqual(
            self.adapter.calls,
            ["parse", "validate", "map", "business_rules", "transform",
             "format", "submit", "receive_confirmation"],
        )

    def test_confirmation_is_returned(self):
        self.assertEqual(self.result.confirmation["document_number"], "DOC-1")

    def test_erp_update_is_skipped_when_no_erp_configured(self):
        outcome = next(s for s in self.result.stages if s.stage == STAGE_ERP_UPDATE)
        self.assertIs(outcome.status, StageStatus.SKIPPED)

    def test_monitoring_and_ai_receive_events(self):
        self.assertTrue(self.services.monitoring.events)
        self.assertEqual(len(self.services.ai_events.events), 1)

    def test_audit_records_every_stage(self):
        self.assertEqual(len(self.services.audit.events), len(DOCUMENTED_FLOW))
        self.assertEqual(self.services.audit.events[0]["stage"], STAGE_AUTHENTICATE)

    def test_result_serializes(self):
        payload = self.result.to_dict()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["country_code"], "atlantis")
        self.assertEqual(len(payload["stages"]), len(DOCUMENTED_FLOW))


class TestFailureHandling(unittest.TestCase):
    def test_failure_halts_the_run_but_finalizers_still_execute(self):
        orchestrator, services, adapter = build(adapter=RecordingAdapter(fail_on="validate"))
        result = run(orchestrator, request())

        self.assertEqual(result.status, PipelineStatus.FAILED)
        self.assertEqual(result.failed_stage, STAGE_VALIDATE)
        self.assertEqual(result.error_code, "VALIDATE_FAILED")

        by_name = {s.stage: s for s in result.stages}
        for name in (STAGE_MAP, STAGE_BUSINESS_RULES, STAGE_TRANSFORM, STAGE_SUBMIT):
            self.assertIs(by_name[name].status, StageStatus.SKIPPED, name)
        for name in (STAGE_MONITORING, STAGE_AI_EVENT):
            self.assertIs(by_name[name].status, StageStatus.SUCCESS, name)

        self.assertNotIn("map", adapter.calls)

    def test_downstream_adapter_stages_are_not_called_after_a_failure(self):
        orchestrator, _, adapter = build(adapter=RecordingAdapter(fail_on="transform"))
        run(orchestrator, request())
        self.assertEqual(adapter.calls[-1], "transform")

    def test_unexpected_exception_is_contained(self):
        def exploding(execution):
            raise RuntimeError("boom")

        plan = default_stage_plan().replace(STAGE_MAP, exploding)
        orchestrator, services, _ = build(plan=plan)
        result = run(orchestrator, request())

        self.assertEqual(result.error_code, "UNEXPECTED_ERROR")
        self.assertEqual(result.failed_stage, STAGE_MAP)
        self.assertEqual(len(services.ai_events.events), 1)

    def test_ai_event_reports_the_failure(self):
        orchestrator, services, _ = build(adapter=RecordingAdapter(fail_on="format"))
        run(orchestrator, request())
        event = services.ai_events.events[0]
        self.assertEqual(event["status"], "FAILED")
        self.assertEqual(event["failed_stage"], STAGE_FORMAT)


class TestGuardStages(unittest.TestCase):
    def test_missing_principal_is_rejected_before_workspace_resolution(self):
        orchestrator, services, _ = build()
        result = run(orchestrator, request(user=None))

        self.assertEqual(result.error_code, "UNAUTHENTICATED")
        self.assertEqual(result.failed_stage, STAGE_AUTHENTICATE)
        self.assertEqual(services.workspace_resolver.calls, 0)

    def test_inactive_principal_is_rejected(self):
        orchestrator, _, _ = build()
        result = run(orchestrator, request(user=SimpleNamespace(id=1, is_active=False)))
        self.assertEqual(result.error_code, "UNAUTHENTICATED")

    def test_pipeline_is_opt_in_per_workspace(self):
        orchestrator, services, adapter = build()
        services.workspace_resolver.result = workspace(pipeline_enabled=False)
        result = run(orchestrator, request())

        self.assertEqual(result.error_code, "PIPELINE_DISABLED")
        self.assertEqual(adapter.calls, [])

    def test_workspace_access_denial_maps_to_a_stage_failure(self):
        from fastapi import HTTPException

        orchestrator, services, _ = build()
        services.workspace_resolver.error = HTTPException(status_code=404, detail="Workspace not found")
        result = run(orchestrator, request())

        self.assertEqual(result.error_code, "WORKSPACE_NOT_FOUND")
        self.assertEqual(result.failed_stage, STAGE_RESOLVE_WORKSPACE)

    def test_country_not_enabled_for_workspace_is_rejected(self):
        orchestrator, services, _ = build()
        services.adapter_resolver = StubAdapterResolver(error=PermissionError("country not enabled"))
        result = run(orchestrator, request())
        self.assertEqual(result.error_code, "COUNTRY_NOT_ENABLED")

    def test_unresolvable_adapter_is_reported(self):
        orchestrator, services, _ = build()
        services.adapter_resolver = StubAdapterResolver(error=LookupError("no enabled adapter"))
        result = run(orchestrator, request())
        self.assertEqual(result.error_code, "ADAPTER_NOT_RESOLVED")
        self.assertEqual(result.failed_stage, STAGE_RESOLVE_ADAPTER)


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self.orchestrator, self.services, self.adapter = build()
        self.result = run(self.orchestrator, request(dry_run=True))

    def test_status_is_dry_run_and_counts_as_success(self):
        self.assertEqual(self.result.status, PipelineStatus.DRY_RUN)
        self.assertTrue(self.result.succeeded)

    def test_external_stages_are_skipped(self):
        by_name = {s.stage: s for s in self.result.stages}
        for name in (STAGE_SUBMIT, STAGE_CONFIRMATION, STAGE_ERP_UPDATE):
            self.assertIs(by_name[name].status, StageStatus.SKIPPED, name)
        self.assertNotIn("submit", self.adapter.calls)

    def test_local_stages_still_run(self):
        self.assertEqual(
            self.adapter.calls,
            ["parse", "validate", "map", "business_rules", "transform", "format"],
        )


class TestRetry(unittest.TestCase):
    def test_retryable_stage_is_reattempted_with_backoff(self):
        adapter = RecordingAdapter()
        adapter.submit_failures = 2
        sleeps: List[float] = []
        plan = default_stage_plan().configure(STAGE_SUBMIT, retry=TRANSPORT_RETRY)

        orchestrator, _, _ = build(adapter=adapter, plan=plan, sleeps=sleeps)
        result = run(orchestrator, request())

        submit = next(s for s in result.stages if s.stage == STAGE_SUBMIT)
        self.assertIs(submit.status, StageStatus.SUCCESS)
        self.assertEqual(submit.attempts, 3)
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertEqual(result.status, PipelineStatus.COMPLETED)

    def test_retries_are_exhausted_and_then_reported(self):
        adapter = RecordingAdapter(fail_on="submit")
        plan = default_stage_plan().configure(STAGE_SUBMIT, retry=TRANSPORT_RETRY)
        orchestrator, _, _ = build(adapter=adapter, plan=plan, sleeps=[])
        result = run(orchestrator, request())

        submit = next(s for s in result.stages if s.stage == STAGE_SUBMIT)
        self.assertEqual(submit.attempts, 3)
        self.assertEqual(result.error_code, "SUBMIT_FAILED")

    def test_non_retryable_failures_are_not_reattempted(self):
        adapter = RecordingAdapter(fail_on="validate")
        plan = default_stage_plan().configure(STAGE_VALIDATE, retry=TRANSPORT_RETRY)
        orchestrator, _, _ = build(adapter=adapter, plan=plan, sleeps=[])
        result = run(orchestrator, request())

        validate = next(s for s in result.stages if s.stage == STAGE_VALIDATE)
        self.assertEqual(validate.attempts, 1)

    def test_stages_run_once_by_default(self):
        adapter = RecordingAdapter(fail_on="submit")
        orchestrator, _, _ = build(adapter=adapter)
        result = run(orchestrator, request())
        submit = next(s for s in result.stages if s.stage == STAGE_SUBMIT)
        self.assertEqual(submit.attempts, 1)


class TestStagesAreReplaceable(unittest.TestCase):
    def test_a_stage_handler_can_be_swapped(self):
        calls = []

        def custom_submit(execution):
            calls.append(execution.country_code)
            return {"sent": "via-custom-gateway"}

        plan = default_stage_plan().replace(STAGE_SUBMIT, custom_submit)
        orchestrator, _, adapter = build(plan=plan)
        result = run(orchestrator, request())

        self.assertEqual(calls, ["atlantis"])
        self.assertNotIn("submit", adapter.calls)
        self.assertEqual(result.status, PipelineStatus.COMPLETED)

    def test_a_stage_can_be_inserted(self):
        seen = []
        spec = StageSpec("enrich", lambda execution: seen.append(execution.customer_id))
        plan = default_stage_plan().insert_before(STAGE_TRANSFORM, spec)

        orchestrator, _, _ = build(plan=plan)
        result = run(orchestrator, request())

        names = [s.stage for s in result.stages]
        self.assertEqual(names.index("enrich"), names.index(STAGE_TRANSFORM) - 1)
        self.assertEqual(seen, ["acme"])

    def test_a_stage_can_be_removed(self):
        plan = default_stage_plan().remove(STAGE_ERP_UPDATE)
        orchestrator, _, _ = build(plan=plan)
        result = run(orchestrator, request())
        self.assertNotIn(STAGE_ERP_UPDATE, [s.stage for s in result.stages])

    def test_unknown_stage_names_are_rejected(self):
        with self.assertRaises(KeyError):
            default_stage_plan().replace("nope", lambda execution: None)

    def test_editing_a_plan_does_not_affect_a_fresh_default(self):
        default_stage_plan().remove(STAGE_SUBMIT)
        self.assertIn(STAGE_SUBMIT, default_stage_plan().names())


class TestInjectedServices(unittest.TestCase):
    def test_injected_erp_connector_is_used(self):
        class FakeErp:
            def __init__(self):
                self.confirmations = []

            def update(self, execution, confirmation):
                self.confirmations.append(confirmation)
                return {"erp_document": "ERP-9"}

        erp = FakeErp()
        orchestrator, _, _ = build({"erp_updater": erp})
        result = run(orchestrator, request())

        outcome = next(s for s in result.stages if s.stage == STAGE_ERP_UPDATE)
        self.assertIs(outcome.status, StageStatus.SUCCESS)
        self.assertEqual(erp.confirmations[0]["document_number"], "DOC-1")

    def test_workspace_erp_updater_pushes_normalized_confirmation(self):
        from app.core.erp import HttpErpConnector, InMemoryOutboxStore, WorkspaceErpUpdater

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"ok": True}

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def post(self, url, json=None, headers=None, timeout=None):
                self.calls.append({"url": url, "json": json, "headers": headers})
                return FakeResponse()

        http = FakeHttp()
        store = InMemoryOutboxStore()
        connector = HttpErpConnector(memory_store=store, http_client=http)
        updater = WorkspaceErpUpdater(connector=connector)

        erp_row = SimpleNamespace(
            connection_key="primary",
            callback_url="https://erp.example/confirm",
            base_url=None,
            auth_type="none",
            client_id_ref=None,
            client_secret_ref=None,
            extra_config={},
            is_active=True,
        )
        orchestrator, services, _ = build({"erp_updater": updater})
        services.workspace_resolver.result = workspace(erps=[erp_row], erp=erp_row)
        result = run(orchestrator, request())

        outcome = next(s for s in result.stages if s.stage == STAGE_ERP_UPDATE)
        self.assertIs(outcome.status, StageStatus.SUCCESS, result.error)
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0]["url"], "https://erp.example/confirm")
        self.assertIn("X-Idempotency-Key", http.calls[0]["headers"])
        body = http.calls[0]["json"]["confirmation"]
        self.assertEqual(body["external_document_number"], "DOC-1")
        self.assertNotIn("country_code", body)  # erp_payload omits country switch field

    def test_monitoring_can_be_disabled_per_workspace(self):
        orchestrator, services, _ = build()
        services.workspace_resolver.result = workspace(monitoring_enabled=False)
        result = run(orchestrator, request())

        outcome = next(s for s in result.stages if s.stage == STAGE_MONITORING)
        self.assertIs(outcome.status, StageStatus.SKIPPED)
        self.assertEqual(services.monitoring.events, [])
        self.assertEqual(len(services.ai_events.events), 1)

    def test_ai_events_respect_workspace_scoping(self):
        orchestrator, services, _ = build()
        services.workspace_resolver.result = workspace(ai_scoped=False)
        result = run(orchestrator, request())

        outcome = next(s for s in result.stages if s.stage == STAGE_AI_EVENT)
        self.assertIs(outcome.status, StageStatus.SKIPPED)
        self.assertEqual(services.ai_events.events, [])
        self.assertEqual(result.status, PipelineStatus.COMPLETED)

    def test_a_broken_audit_sink_cannot_fail_a_run(self):
        class BrokenAudit:
            def record(self, entry):
                raise IOError("audit backend down")

        orchestrator, _, _ = build({"audit": BrokenAudit()})
        self.assertEqual(run(orchestrator, request()).status, PipelineStatus.COMPLETED)


class TestCountryNeutrality(unittest.TestCase):
    def test_two_different_countries_produce_the_same_stage_sequence(self):
        first_orchestrator, _, _ = build(adapter=RecordingAdapter())

        class OtherCountryAdapter(RecordingAdapter):
            country_code = "utopia"

        second = OtherCountryAdapter()
        second_orchestrator, services, _ = build(adapter=second)
        services.adapter_resolver = StubAdapterResolver(second, country_code="utopia")

        first = run(first_orchestrator, request())
        other = run(second_orchestrator, request())

        self.assertEqual([s.stage for s in first.stages], [s.stage for s in other.stages])
        self.assertEqual(first.country_code, "atlantis")
        self.assertEqual(other.country_code, "utopia")

    def test_pipeline_code_names_no_country(self):
        """
        No country identifier may appear in engine *code*.

        Comments and docstrings are excluded: prose may legitimately mention
        the existing SAT flow when explaining what the engine does not touch.
        """
        forbidden = ("mexico", "cfdi", "sat", "sap", "india", "germany", "uae", "singapore")
        root = pathlib.Path(__file__).resolve().parents[1] / "core" / "pipeline"
        offenders = []
        for path in sorted(root.glob("*.py")):
            with tokenize.open(path) as handle:
                for tok in tokenize.generate_tokens(handle.readline):
                    if tok.type in (tokenize.COMMENT, tokenize.STRING):
                        continue
                    words = re.findall(r"[a-z]+", tok.string.lower())
                    offenders += [
                        f"{path.name}:{tok.start[0]}: {tok.string}"
                        for word in forbidden
                        if word in words
                    ]
        self.assertEqual(offenders, [])


class TestRealAdapterIntegration(unittest.TestCase):
    """
    Drives Adapter #1 through the real registry resolver.

    The engine is given no hint about which country this is; it reads the code
    from the workspace's adapter configuration.
    """

    def test_engine_runs_the_registered_adapter_end_to_end(self):
        from app.core.pipeline.hooks import RegistryAdapterResolver

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
        configured = workspace(
            adapters=[SimpleNamespace(country_code="MX", enabled=True, extra_config={})]
        )

        plan = default_stage_plan()
        for stage in (STAGE_MAP, STAGE_BUSINESS_RULES, STAGE_TRANSFORM, STAGE_FORMAT):
            plan.remove(stage)

        orchestrator, services, _ = build(plan=plan)
        services.workspace_resolver.result = configured
        services.adapter_resolver = RegistryAdapterResolver()

        result = run(orchestrator, request(payload=cfdi, country_code="MX", dry_run=True))

        self.assertEqual(result.status, PipelineStatus.DRY_RUN, result.error)
        self.assertEqual(result.country_code, "MX")
        by_name = {s.stage: s for s in result.stages}
        self.assertIs(by_name[STAGE_PARSE].status, StageStatus.SUCCESS)
        self.assertIs(by_name[STAGE_VALIDATE].status, StageStatus.SUCCESS)
        self.assertTrue(services.monitoring.events)

    def test_country_not_enabled_in_the_workspace_is_blocked(self):
        from app.core.pipeline.hooks import RegistryAdapterResolver

        orchestrator, services, _ = build()
        services.workspace_resolver.result = workspace(
            adapters=[SimpleNamespace(country_code="MX", enabled=False, extra_config={})]
        )
        services.adapter_resolver = RegistryAdapterResolver()

        result = run(orchestrator, request(country_code="MX"))
        self.assertEqual(result.error_code, "COUNTRY_NOT_ENABLED")
        self.assertEqual(result.failed_stage, STAGE_RESOLVE_ADAPTER)


if __name__ == "__main__":
    unittest.main()
