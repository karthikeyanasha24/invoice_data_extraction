"""
SampleGstAdapter — CountryAdapter façade for the Phase 5 scaffold.

Wires country-owned modules (validation, mapping, rules, formatting, connector).
Does not import mx_cfdi or any SAT/SAP production service.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from ..base import (
    ERROR_BUSINESS_RULES,
    ERROR_CONFIRMATION,
    ERROR_FORMAT,
    ERROR_MAPPING,
    ERROR_PARSING,
    ERROR_SUBMIT,
    ERROR_TRANSFORM,
    ERROR_VALIDATION,
    AdapterCapability,
    AdapterContext,
    AdapterStage,
    CountryAdapter,
    StageResult,
)
from . import connector, formatting, mapping, rules, validation
from .config import (
    SAMPLE_GST_COUNTRY_CODE,
    SAMPLE_GST_DISPLAY_NAME,
    SAMPLE_GST_DOCUMENT_TYPES,
    SampleGstConfig,
)

logger = logging.getLogger("zodiac-api.adapters.sample_gst")


class SampleGstAdapter(CountryAdapter):
    """Configurable sample GST e-invoice adapter (non-production scaffold)."""

    country_code = SAMPLE_GST_COUNTRY_CODE
    display_name = SAMPLE_GST_DISPLAY_NAME
    supported_document_types = SAMPLE_GST_DOCUMENT_TYPES

    def __init__(
        self,
        db: Any = None,
        config: Optional[SampleGstConfig] = None,
        government_connector: Any = None,
    ):
        # db is accepted for registry DI parity; this sample does not use it.
        self.db = db
        self.config = config or SampleGstConfig()
        # Injected GovernmentConnector (Phase 7); when None, factory chooses mock/HTTP.
        self.government_connector = government_connector

    def capabilities(self) -> List[AdapterCapability]:
        caps = [
            AdapterCapability.PARSE,
            AdapterCapability.VALIDATE,
            AdapterCapability.MAP,
            AdapterCapability.BUSINESS_RULES,
            AdapterCapability.TRANSFORM,
            AdapterCapability.FORMAT,
            AdapterCapability.SUBMIT,
            AdapterCapability.CONFIRMATION,
            AdapterCapability.GOVERNMENT_API,
        ]
        return caps

    def parse(self, ctx: AdapterContext) -> StageResult:
        try:
            document = validation.parse_payload(ctx.payload)
        except ValueError as exc:
            return StageResult.fail(AdapterStage.PARSE, str(exc), ERROR_PARSING)

        ctx.set_output(AdapterStage.PARSE, document)
        ctx.document_type = ctx.document_type or document.get("document_type")
        return StageResult.ok(AdapterStage.PARSE, document)

    def validate(self, ctx: AdapterContext) -> StageResult:
        document = ctx.get_output(AdapterStage.PARSE)
        if document is None:
            try:
                document = validation.parse_payload(ctx.payload)
            except ValueError as exc:
                return StageResult.fail(AdapterStage.VALIDATE, str(exc), ERROR_VALIDATION)

        is_valid, error, errors = validation.validate_document(
            document, expected_currency=self.config.expected_currency
        )
        result = {"is_valid": is_valid, "error": error, "errors": errors}
        ctx.set_output(AdapterStage.VALIDATE, result)
        if not is_valid:
            return StageResult.fail(
                AdapterStage.VALIDATE, error or "Invalid sample GST document", ERROR_VALIDATION,
                errors=errors,
            )
        return StageResult.ok(AdapterStage.VALIDATE, result)

    def map(self, ctx: AdapterContext) -> StageResult:
        document = ctx.get_output(AdapterStage.PARSE)
        if not isinstance(document, dict):
            return StageResult.fail(
                AdapterStage.MAP, "parse() must run before map()", ERROR_MAPPING
            )
        try:
            mapped = mapping.map_parties(document, self.config)
        except Exception as exc:  # noqa: BLE001
            logger.error("Sample GST mapping failed: %s", exc, exc_info=True)
            return StageResult.fail(AdapterStage.MAP, str(exc), ERROR_MAPPING)

        ctx.set_output(AdapterStage.MAP, mapped)
        return StageResult.ok(
            AdapterStage.MAP, mapped, used_default=mapped.get("used_default_ledger")
        )

    def apply_business_rules(self, ctx: AdapterContext) -> StageResult:
        document = ctx.get_output(AdapterStage.PARSE)
        mapped = ctx.get_output(AdapterStage.MAP)
        if not isinstance(document, dict) or not isinstance(mapped, dict):
            return StageResult.fail(
                AdapterStage.BUSINESS_RULES,
                "parse() and map() must run before apply_business_rules()",
                ERROR_BUSINESS_RULES,
            )

        accepted, error, meta = rules.apply_rules(document, mapped, self.config)
        ctx.set_output(AdapterStage.BUSINESS_RULES, meta)
        if not accepted:
            return StageResult.fail(
                AdapterStage.BUSINESS_RULES, error or "Business rule violation", ERROR_BUSINESS_RULES,
                **meta,
            )
        return StageResult.ok(AdapterStage.BUSINESS_RULES, meta)

    def transform(self, ctx: AdapterContext) -> StageResult:
        document = ctx.get_output(AdapterStage.PARSE)
        mapped = ctx.get_output(AdapterStage.MAP)
        rules_meta = ctx.get_output(AdapterStage.BUSINESS_RULES) or {}
        if not isinstance(document, dict) or not isinstance(mapped, dict):
            return StageResult.fail(
                AdapterStage.TRANSFORM,
                "parse() and map() must run before transform()",
                ERROR_TRANSFORM,
            )
        try:
            transformed = formatting.transform_document(document, mapped, rules_meta)
        except Exception as exc:  # noqa: BLE001
            return StageResult.fail(AdapterStage.TRANSFORM, str(exc), ERROR_TRANSFORM)

        ctx.set_output(AdapterStage.TRANSFORM, transformed)
        return StageResult.ok(AdapterStage.TRANSFORM, transformed)

    def format(self, ctx: AdapterContext) -> StageResult:
        transformed = ctx.get_output(AdapterStage.TRANSFORM)
        if not isinstance(transformed, dict):
            return StageResult.fail(
                AdapterStage.FORMAT, "transform() must run before format()", ERROR_FORMAT
            )
        payload = formatting.format_payload(
            transformed, self.config, correlation_id=ctx.correlation_id
        )
        ctx.set_output(AdapterStage.FORMAT, payload)
        return StageResult.ok(
            AdapterStage.FORMAT, payload, content_type="application/json"
        )

    async def submit(self, ctx: AdapterContext) -> StageResult:
        payload = ctx.get_output(AdapterStage.FORMAT)
        if not isinstance(payload, dict):
            return StageResult.fail(
                AdapterStage.SUBMIT, "format() must run before submit()", ERROR_SUBMIT
            )
        # Government HTTP/auth/retry is owned by core.government — not this adapter.
        response = await connector.submit_payload(
            payload,
            self.config,
            customer_id=ctx.customer_id,
            correlation_id=ctx.correlation_id,
            submission_id=ctx.correlation_id,
            connector=self.government_connector,
        )
        ctx.set_output(AdapterStage.SUBMIT, response)
        if response.get("success"):
            return StageResult.ok(AdapterStage.SUBMIT, response)
        return StageResult.fail(
            AdapterStage.SUBMIT,
            response.get("error") or "Sample GST submission failed",
            ERROR_SUBMIT,
            mode=response.get("mode"),
        )

    def receive_confirmation(self, ctx: AdapterContext, response: Any = None) -> StageResult:
        payload = response if response is not None else ctx.get_output(AdapterStage.SUBMIT)
        confirmation = connector.normalize_confirmation(payload)
        ctx.set_output(AdapterStage.CONFIRMATION, confirmation)
        if confirmation.get("accepted"):
            return StageResult.ok(AdapterStage.CONFIRMATION, confirmation)
        return StageResult.fail(
            AdapterStage.CONFIRMATION,
            confirmation.get("error") or "Government did not accept the document",
            ERROR_CONFIRMATION,
        )


def build_sample_gst_adapter(
    db: Any = None, config: Any = None, government_connector: Any = None, **_ignored: Any
) -> SampleGstAdapter:
    """Registry factory. Accepts a WorkspaceAdapterConfig row, dict, or SampleGstConfig."""
    if config is None or isinstance(config, SampleGstConfig):
        resolved = config
    else:
        resolved = SampleGstConfig.from_workspace(config)
    return SampleGstAdapter(
        db=db, config=resolved, government_connector=government_connector
    )
