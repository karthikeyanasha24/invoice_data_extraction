"""
Pipeline stages (Phase 4).

The orchestrator executes an ordered `StagePlan`. Each stage is a named spec
holding a handler, so any stage can be replaced, removed, or wrapped without
touching the engine:

    plan = default_stage_plan().replace(STAGE_SUBMIT, my_handler)

Handlers signal outcomes by raising `StageFailed` or `StageSkipped`; anything
returned becomes the stage's detail payload. No handler here mentions a
country — the country-specific stages simply call the resolved adapter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace as dataclass_replace
from typing import Any, Callable, Iterable, List, Optional

from .retry import NO_RETRY, TRANSPORT_RETRY, RetryPolicy
from .types import PipelineExecution, StageFailed, StageSkipped

logger = logging.getLogger("zodiac-api.pipeline.stages")

STAGE_AUTHENTICATE = "authenticate"
STAGE_RESOLVE_WORKSPACE = "resolve_workspace"
STAGE_RESOLVE_ADAPTER = "resolve_adapter"
STAGE_PARSE = "parse"
STAGE_VALIDATE = "validate"
STAGE_MAP = "map"
STAGE_BUSINESS_RULES = "business_rules"
STAGE_TRANSFORM = "transform"
STAGE_FORMAT = "format"
STAGE_SUBMIT = "submit"
STAGE_CONFIRMATION = "receive_confirmation"
STAGE_ERP_UPDATE = "erp_update"
STAGE_MONITORING = "monitoring"
STAGE_AI_EVENT = "ai_event"

StageHandler = Callable[[PipelineExecution], Any]


@dataclass(frozen=True)
class StageSpec:
    """One replaceable step."""

    name: str
    handler: StageHandler
    #: Finalizers run even after a failure (monitoring, AI).
    always_run: bool = False
    #: Stages that reach an external system are skipped on a dry run.
    skip_on_dry_run: bool = False
    retry: RetryPolicy = NO_RETRY


class StagePlan:
    """Ordered, editable list of stages."""

    def __init__(self, specs: Iterable[StageSpec]):
        self._specs: List[StageSpec] = list(specs)

    def __iter__(self):
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def names(self) -> List[str]:
        return [s.name for s in self._specs]

    def copy(self) -> "StagePlan":
        return StagePlan(self._specs)

    def get(self, name: str) -> StageSpec:
        for spec in self._specs:
            if spec.name == name:
                return spec
        raise KeyError(f"Unknown stage '{name}'. Plan: {', '.join(self.names())}")

    def _index(self, name: str) -> int:
        for index, spec in enumerate(self._specs):
            if spec.name == name:
                return index
        raise KeyError(f"Unknown stage '{name}'. Plan: {', '.join(self.names())}")

    def replace(self, name: str, handler: StageHandler, **overrides: Any) -> "StagePlan":
        index = self._index(name)
        self._specs[index] = dataclass_replace(self._specs[index], handler=handler, **overrides)
        return self

    def configure(self, name: str, **overrides: Any) -> "StagePlan":
        """Change retry/dry-run behaviour without changing the handler."""
        index = self._index(name)
        self._specs[index] = dataclass_replace(self._specs[index], **overrides)
        return self

    def insert_before(self, name: str, spec: StageSpec) -> "StagePlan":
        self._specs.insert(self._index(name), spec)
        return self

    def insert_after(self, name: str, spec: StageSpec) -> "StagePlan":
        self._specs.insert(self._index(name) + 1, spec)
        return self

    def remove(self, name: str) -> "StagePlan":
        self._specs.pop(self._index(name))
        return self


# ------------------------------------------------------------ adapter glue


def _unwrap(result: Any, stage: str) -> Any:
    """Turn a `StageResult` from the adapter into pipeline control flow."""
    if result is None:
        return None
    if getattr(result, "success", True):
        return getattr(result, "data", result)
    raise StageFailed(
        getattr(result, "error", f"{stage} failed") or f"{stage} failed",
        getattr(result, "error_code", "STAGE_FAILED") or "STAGE_FAILED",
        **getattr(result, "meta", {}),
    )


def adapter_stage(method_name: str, is_async: bool = False) -> StageHandler:
    """Build a handler that delegates one stage to the resolved adapter."""

    if is_async:

        async def async_handler(execution: PipelineExecution) -> Any:
            method = getattr(execution.adapter, method_name)
            return _unwrap(await method(execution.adapter_ctx), method_name)

        async_handler.__name__ = f"adapter_{method_name}"
        return async_handler

    def handler(execution: PipelineExecution) -> Any:
        method = getattr(execution.adapter, method_name)
        return _unwrap(method(execution.adapter_ctx), method_name)

    handler.__name__ = f"adapter_{method_name}"
    return handler


# -------------------------------------------------------- platform stages


def stage_authenticate(execution: PipelineExecution) -> Any:
    """Confirm the caller. Transport-level auth happens upstream."""
    try:
        principal = execution.services.authenticator.authenticate(execution.request)
    except PermissionError as exc:
        raise StageFailed(str(exc), "UNAUTHENTICATED") from exc
    execution.principal = principal
    return {"principal_id": getattr(principal, "id", None)}


def stage_resolve_workspace(execution: PipelineExecution) -> Any:
    """Load the Phase 2 workspace; tenancy is enforced by the resolver."""
    from fastapi import HTTPException

    try:
        workspace = execution.services.workspace_resolver.resolve(
            execution.request, execution.principal
        )
    except HTTPException as exc:
        code = "WORKSPACE_NOT_FOUND" if exc.status_code == 404 else "WORKSPACE_ACCESS_DENIED"
        raise StageFailed(str(exc.detail), code, status_code=exc.status_code) from exc
    except PermissionError as exc:
        raise StageFailed(str(exc), "WORKSPACE_ACCESS_DENIED") from exc

    if not getattr(workspace, "pipeline_enabled", False):
        # The orchestrator is opt-in: a workspace runs on it only when enabled.
        raise StageFailed(
            f"Pipeline is not enabled for workspace '{execution.customer_id}'",
            "PIPELINE_DISABLED",
        )

    execution.workspace = workspace
    return {"workspace_id": getattr(workspace, "workspace_id", execution.customer_id)}


def stage_resolve_adapter(execution: PipelineExecution) -> Any:
    """
    Resolve the country adapter through the registry.

    This is the only place the pipeline touches a country code, and it treats
    it purely as an opaque key.
    """
    from ...adapters import AdapterContext
    from ...adapters.registry import AdapterRegistryError

    try:
        country_code, adapter, config = execution.services.adapter_resolver.resolve(
            execution.request, execution.workspace
        )
    except PermissionError as exc:
        raise StageFailed(str(exc), "COUNTRY_NOT_ENABLED") from exc
    except (LookupError, AdapterRegistryError) as exc:
        raise StageFailed(str(exc), "ADAPTER_NOT_RESOLVED") from exc

    request = execution.request
    extra = getattr(config, "extra_config", None)
    execution.country_code = country_code
    execution.adapter = adapter
    execution.adapter_config = config
    execution.adapter_ctx = AdapterContext(
        customer_id=request.customer_id,
        country_code=country_code,
        payload=request.payload,
        document_type=request.document_type,
        user_id=getattr(execution.principal, "id", None),
        db=request.db,
        correlation_id=request.correlation_id,
        config=dict(extra) if isinstance(extra, dict) else {},
        metadata=dict(request.metadata),
    )
    return {"country_code": country_code, "adapter": type(adapter).__name__}


def stage_receive_confirmation(execution: PipelineExecution) -> Any:
    """
    Normalize the submit response into a confirmation.

    Passes the SUBMIT stage output into the adapter so the adapter never has
    to dig for it — and so a replaced submit handler still wires through.
    """
    from ...adapters.base import AdapterStage

    response = execution.adapter_output(AdapterStage.SUBMIT)
    return _unwrap(
        execution.adapter.receive_confirmation(execution.adapter_ctx, response),
        STAGE_CONFIRMATION,
    )


def stage_update_erp(execution: PipelineExecution) -> Any:
    """
    Write the confirmation back to the ERP.

    Prefers the injected Core ERP connector (Phase 6); otherwise asks the
    adapter, whose default reports the stage as not yet implemented.
    """
    from ...adapters.base import AdapterStage

    confirmation = execution.adapter_output(AdapterStage.CONFIRMATION)
    updater = execution.services.erp_updater

    if updater is not None:
        try:
            return updater.update(execution, confirmation)
        except NotImplementedError as exc:
            raise StageSkipped(str(exc) or "ERP connector not implemented") from exc

    result = execution.adapter.update_erp(execution.adapter_ctx)
    if getattr(result, "success", False):
        return getattr(result, "data", None)
    if getattr(result, "error_code", None) == "NOT_IMPLEMENTED":
        raise StageSkipped(result.error or "ERP update not implemented for this adapter")
    raise StageFailed(result.error or "ERP update failed", result.error_code or "ERP_UPDATE_FAILED")


def stage_monitoring(execution: PipelineExecution) -> Any:
    """Emit every event collected during the run. Always runs."""
    from ...adapters.base import AdapterStage

    workspace = execution.workspace
    if workspace is not None and not getattr(workspace, "monitoring_enabled", True):
        raise StageSkipped("Monitoring is disabled for this workspace")

    status = "FAILED" if execution.failed else "SUCCESS"
    failed = next((s for s in execution.stages if s.status.value == "failed"), None)

    if execution.adapter is not None and execution.adapter_ctx is not None:
        execution.adapter.generate_monitoring_event(
            execution.adapter_ctx,
            AdapterStage.MONITORING,
            status,
            failed.error if failed else None,
            failed_stage=failed.stage if failed else None,
        )
        events = list(execution.adapter_ctx.events)
    else:
        # Failure before adapter resolution still deserves an event.
        events = [
            {
                "correlation_id": execution.correlation_id,
                "customer_id": execution.customer_id,
                "country_code": execution.country_code,
                "stage": failed.stage if failed else STAGE_MONITORING,
                "status": status,
                "detail": failed.error if failed else None,
            }
        ]

    for event in events:
        execution.services.monitoring.emit(event)
    return {"emitted": len(events)}


def stage_ai_event(execution: PipelineExecution) -> Any:
    """Emit a workspace-scoped run summary for AI. Always runs."""
    workspace = execution.workspace
    if workspace is None:
        raise StageSkipped("Workspace was not resolved")
    if not getattr(workspace, "ai_scoped", True):
        raise StageSkipped("AI is not scoped for this workspace")

    failed = next((s for s in execution.stages if s.status.value == "failed"), None)
    event = {
        "correlation_id": execution.correlation_id,
        "customer_id": execution.customer_id,
        "country_code": execution.country_code,
        "status": "FAILED" if execution.failed else "SUCCESS",
        "failed_stage": failed.stage if failed else None,
        "dry_run": execution.request.dry_run,
        "stages": [s.to_dict() for s in execution.stages],
    }
    execution.services.ai_events.emit(event)
    return {"emitted": 1}


def default_stage_plan() -> StagePlan:
    """
    The canonical BridgeEDI flow.

    Parse is executed as part of the validation step of the documented flow;
    it is a distinct stage because the `CountryAdapter` contract defines it and
    later stages read its output.
    """
    return StagePlan(
        [
            StageSpec(STAGE_AUTHENTICATE, stage_authenticate),
            StageSpec(STAGE_RESOLVE_WORKSPACE, stage_resolve_workspace),
            StageSpec(STAGE_RESOLVE_ADAPTER, stage_resolve_adapter),
            StageSpec(STAGE_PARSE, adapter_stage("parse")),
            StageSpec(STAGE_VALIDATE, adapter_stage("validate")),
            StageSpec(STAGE_MAP, adapter_stage("map")),
            StageSpec(STAGE_BUSINESS_RULES, adapter_stage("apply_business_rules")),
            StageSpec(STAGE_TRANSFORM, adapter_stage("transform")),
            StageSpec(STAGE_FORMAT, adapter_stage("format")),
            StageSpec(STAGE_SUBMIT, adapter_stage("submit", is_async=True), skip_on_dry_run=True),
            StageSpec(STAGE_CONFIRMATION, stage_receive_confirmation, skip_on_dry_run=True),
            StageSpec(
                STAGE_ERP_UPDATE,
                stage_update_erp,
                skip_on_dry_run=True,
                retry=TRANSPORT_RETRY,
            ),
            StageSpec(STAGE_MONITORING, stage_monitoring, always_run=True),
            StageSpec(STAGE_AI_EVENT, stage_ai_event, always_run=True),
        ]
    )
