"""
Invoice Processing Orchestrator (Phase 4).

The shared execution engine for BridgeEDI. It owns *sequencing only*:

    authenticate → resolve workspace → resolve country adapter → parse →
    validate → map → business rules → transform → format → submit →
    receive confirmation → ERP update → monitoring → AI event

It contains no country logic and no country names. It knows only that a
`CountryAdapter` was resolved from the registry for the workspace's configured
country code.

Additive and opt-in: nothing in the existing SAT flow calls this engine, and a
workspace only runs on it when `workspace_settings.pipeline_enabled` is true.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .hooks import PlatformServices
from .stages import StagePlan, StageSpec, default_stage_plan
from .types import (
    PipelineExecution,
    PipelineRequest,
    PipelineResult,
    PipelineStatus,
    StageFailed,
    StageOutcome,
    StageSkipped,
    StageStatus,
)

logger = logging.getLogger("zodiac-api.pipeline.orchestrator")


class InvoicePipelineOrchestrator:
    """
    Runs a `PipelineRequest` through a `StagePlan`.

    Both collaborators are injected, so behaviour is configured rather than
    coded: swap a hook to change *how* a step is done, edit the plan to change
    *which* steps run.
    """

    def __init__(
        self,
        services: Optional[PlatformServices] = None,
        plan: Optional[StagePlan] = None,
        sleep: Optional[Callable[[float], Any]] = None,
    ):
        self.services = services or PlatformServices()
        self.plan = plan or default_stage_plan()
        self._sleep = sleep or asyncio.sleep

    async def run(self, request: PipelineRequest) -> PipelineResult:
        execution = PipelineExecution(request=request, services=self.services)
        started_at = datetime.now(timezone.utc)
        halted = False

        logger.info(
            "▶ pipeline start %s customer=%s dry_run=%s",
            request.correlation_id,
            request.customer_id,
            request.dry_run,
        )

        for spec in self.plan:
            if halted and not spec.always_run:
                outcome = self._skipped(spec.name, "Pipeline halted by an earlier failure")
            elif request.dry_run and spec.skip_on_dry_run:
                outcome = self._skipped(spec.name, "Skipped on dry run")
            else:
                outcome = await self._run_stage(spec, execution)

            execution.stages.append(outcome)
            self._audit(execution, outcome)

            if outcome.status is StageStatus.FAILED:
                halted = True

        result = self._build_result(execution, started_at)
        self._observe_complete(result, execution)
        return result

    # ------------------------------------------------------------ internals

    async def _run_stage(self, spec: StageSpec, execution: PipelineExecution) -> StageOutcome:
        attempt = 0
        started = time.perf_counter()

        while True:
            attempt += 1
            try:
                result = spec.handler(execution)
                if inspect.isawaitable(result):
                    result = await result
            except StageSkipped as skip:
                return self._skipped(
                    spec.name, skip.reason, attempts=attempt, elapsed=started, meta=skip.meta
                )
            except StageFailed as failure:
                if spec.retry.should_retry(attempt, failure.error_code):
                    delay = spec.retry.delay_for(attempt)
                    logger.warning(
                        "↻ stage '%s' failed (%s), retrying in %.2fs [%s/%s]",
                        spec.name, failure.error_code, delay, attempt, spec.retry.max_attempts,
                    )
                    if delay:
                        await self._sleep(delay)
                    continue
                return StageOutcome(
                    stage=spec.name,
                    status=StageStatus.FAILED,
                    attempts=attempt,
                    duration_ms=self._elapsed_ms(started),
                    error=failure.message,
                    error_code=failure.error_code,
                    meta=dict(failure.meta),
                )
            except Exception as exc:  # noqa: BLE001 - a stage must never crash the engine
                logger.error("✖ stage '%s' raised: %s", spec.name, exc, exc_info=True)
                return StageOutcome(
                    stage=spec.name,
                    status=StageStatus.FAILED,
                    attempts=attempt,
                    duration_ms=self._elapsed_ms(started),
                    error=str(exc),
                    error_code="UNEXPECTED_ERROR",
                    meta={"exception": type(exc).__name__},
                )

            return StageOutcome(
                stage=spec.name,
                status=StageStatus.SUCCESS,
                attempts=attempt,
                duration_ms=self._elapsed_ms(started),
                detail=self._summarize(result),
            )

    def _skipped(
        self,
        name: str,
        reason: str,
        attempts: int = 0,
        elapsed: Optional[float] = None,
        meta: Optional[dict] = None,
    ) -> StageOutcome:
        return StageOutcome(
            stage=name,
            status=StageStatus.SKIPPED,
            attempts=attempts,
            duration_ms=self._elapsed_ms(elapsed) if elapsed else 0.0,
            detail=reason,
            meta=dict(meta or {}),
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000

    @staticmethod
    def _summarize(result: Any) -> Optional[str]:
        """Stage payloads can be large; keep only a short, loggable summary."""
        if result is None:
            return None
        if isinstance(result, dict):
            return ", ".join(f"{k}={v}" for k, v in list(result.items())[:4]) or None
        if isinstance(result, (list, tuple)):
            return f"{len(result)} item(s)"
        if isinstance(result, (str, int, float, bool)):
            return str(result)[:200]
        return type(result).__name__

    def _audit(self, execution: PipelineExecution, outcome: StageOutcome) -> None:
        entry = {
            "correlation_id": execution.correlation_id,
            "customer_id": execution.customer_id,
            "country_code": execution.country_code,
            "document_type": getattr(execution.request, "document_type", None),
            "principal_id": getattr(execution.principal, "id", None),
            **outcome.to_dict(),
        }
        try:
            self.services.audit.record(entry)
        except Exception as exc:  # noqa: BLE001 - auditing must not fail a run
            logger.warning("Audit sink error on stage '%s': %s", outcome.stage, exc)

    def _observe_complete(
        self, result: PipelineResult, execution: PipelineExecution
    ) -> None:
        """
        Optional Phase 8 observer hook — never mutates result or stage outcomes.
        Only runs when the monitoring sink exposes finalize_pipeline_result.
        """
        finalize = getattr(self.services.monitoring, "finalize_pipeline_result", None)
        if not callable(finalize):
            return
        adapter_name = None
        if execution.adapter is not None:
            adapter_name = getattr(execution.adapter, "display_name", None) or getattr(
                execution.adapter, "country_code", None
            )
        try:
            finalize(result, adapter_name=adapter_name)
        except Exception as exc:  # noqa: BLE001 - monitoring must not fail a run
            logger.warning("Monitoring finalize error: %s", exc)

    def _build_result(
        self, execution: PipelineExecution, started_at: datetime
    ) -> PipelineResult:
        failed = next((s for s in execution.stages if s.status is StageStatus.FAILED), None)

        if failed is not None:
            status = PipelineStatus.FAILED
        elif execution.request.dry_run:
            status = PipelineStatus.DRY_RUN
        else:
            status = PipelineStatus.COMPLETED

        confirmation = None
        events: list = []
        if execution.adapter_ctx is not None:
            from ...adapters.base import AdapterStage

            confirmation = execution.adapter_ctx.get_output(AdapterStage.CONFIRMATION)
            events = list(execution.adapter_ctx.events)

        logger.info(
            "■ pipeline %s %s customer=%s country=%s",
            status.value,
            execution.correlation_id,
            execution.customer_id,
            execution.country_code,
        )

        return PipelineResult(
            correlation_id=execution.correlation_id,
            customer_id=execution.customer_id,
            country_code=execution.country_code,
            status=status,
            stages=list(execution.stages),
            error=failed.error if failed else None,
            error_code=failed.error_code if failed else None,
            failed_stage=failed.stage if failed else None,
            confirmation=confirmation,
            events=events,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
