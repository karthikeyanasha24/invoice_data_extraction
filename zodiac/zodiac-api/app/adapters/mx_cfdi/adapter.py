"""
Adapter #1 — Mexico CFDI.

This is a **façade**. Every stage delegates to the SAT/SAP services that are
already running in production:

    parse / validate      -> app.utils.cfdi_parser.CFDIParser
    ingest                -> app.services.sat_processor.SATDocumentProcessor
    map                   -> app.services.sat_supplier_mapping_service.SATSupplierMappingService
    apply_business_rules  -> app.services.sat_canonical_merge_service.SATCanonicalMergeService
    transform / format    -> app.services.sap_transformer.SAPTransformer
    submit                -> app.services.sap_api_client.sap_client
    bulk submit           -> app.services.sap_send_all.SAPBulkSender

No SAT service is moved, copied or rewritten, and no business logic is
reimplemented here. Nothing in the existing `/api/v1/sat/*` routes calls this
class, so production behaviour is unchanged.

Service imports are lazy (inside methods) so that importing the adapter
package never pulls in httpx/SAP configuration.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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
from .config import (
    FORMAT_JSON,
    FORMAT_XML,
    MERGE_STRATEGY_CANONICAL,
    MERGE_STRATEGY_SIMPLE,
    MX_CFDI_COUNTRY_CODE,
    MX_CFDI_DISPLAY_NAME,
    MX_CFDI_DOCUMENT_TYPES,
    MxCfdiConfig,
)

logger = logging.getLogger("zodiac-api.adapters.mx_cfdi")


class MxCfdiAdapter(CountryAdapter):
    """Mexico CFDI → SAP pipeline, expressed through the CountryAdapter contract."""

    country_code = MX_CFDI_COUNTRY_CODE
    display_name = MX_CFDI_DISPLAY_NAME
    supported_document_types = MX_CFDI_DOCUMENT_TYPES

    def __init__(
        self,
        db: Any = None,
        config: Optional[MxCfdiConfig] = None,
        government_connector: Any = None,
    ):
        self.db = db
        self.config = config or MxCfdiConfig()
        # Optional Phase 7 port. Default is AlreadyStamped — Mexico has no live
        # SAT/PAC HTTP. Pipeline submit() still targets SAP (ERP), unchanged.
        self.government_connector = government_connector

    def get_government_connector(self):
        if self.government_connector is None:
            from ...core.government import AlreadyStampedGovernmentConnector

            self.government_connector = AlreadyStampedGovernmentConnector()
        return self.government_connector

    def capabilities(self) -> List[AdapterCapability]:
        # GOVERNMENT_API is absent: today CFDI stamps arrive inside the uploaded
        # XML; there is no live SAT/PAC call in the codebase.
        return [
            AdapterCapability.PARSE,
            AdapterCapability.VALIDATE,
            AdapterCapability.MAP,
            AdapterCapability.BUSINESS_RULES,
            AdapterCapability.TRANSFORM,
            AdapterCapability.FORMAT,
            AdapterCapability.SUBMIT,
            AdapterCapability.CONFIRMATION,
        ]

    # ----------------------------------------------------------- internals

    def _db(self, ctx: Optional[AdapterContext] = None):
        return (ctx.db if ctx is not None and ctx.db is not None else self.db)

    @staticmethod
    def _xml_from(ctx: AdapterContext) -> Optional[str]:
        payload = ctx.payload
        if payload is None:
            return None
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return payload.get("xml_content") or payload.get("xml")
        return None

    # -------------------------------------------------------------- stages

    def parse(self, ctx: AdapterContext) -> StageResult:
        """Delegates to CFDIParser.parse_cfdi — the exact production parser."""
        from ...utils.cfdi_parser import CFDIParser

        xml_content = self._xml_from(ctx)
        if not xml_content:
            return StageResult.fail(
                AdapterStage.PARSE, "No CFDI XML supplied in context payload", ERROR_PARSING
            )
        try:
            cfdi_data = CFDIParser.parse_cfdi(xml_content)
        except Exception as exc:  # mirrors SATDocumentProcessor's PARSING_FAILED branch
            logger.error("CFDI parsing failed: %s", exc)
            return StageResult.fail(AdapterStage.PARSE, str(exc), ERROR_PARSING)

        ctx.set_output(AdapterStage.PARSE, cfdi_data)
        ctx.document_type = ctx.document_type or cfdi_data.get("doc_type")
        return StageResult.ok(AdapterStage.PARSE, cfdi_data)

    def validate(self, ctx: AdapterContext) -> StageResult:
        """
        Delegates to CFDIParser.validate_cfdi_structure.

        Duplicate-UUID detection stays in `ingest()`, because it is a storage
        concern owned by SATDocumentProcessor.
        """
        from ...utils.cfdi_parser import CFDIParser

        xml_content = self._xml_from(ctx)
        if not xml_content:
            return StageResult.fail(
                AdapterStage.VALIDATE, "No CFDI XML supplied in context payload", ERROR_VALIDATION
            )

        is_valid, error_msg = CFDIParser.validate_cfdi_structure(xml_content)
        result = {"is_valid": is_valid, "error": error_msg}
        ctx.set_output(AdapterStage.VALIDATE, result)
        if not is_valid:
            return StageResult.fail(AdapterStage.VALIDATE, error_msg or "Invalid CFDI", ERROR_VALIDATION)
        return StageResult.ok(AdapterStage.VALIDATE, result)

    def ingest(self, ctx: AdapterContext) -> StageResult:
        """
        Full production intake: validate + parse + duplicate check + persist.

        Delegates to SATDocumentProcessor.process_cfdi_document, i.e. the same
        call the `/api/v1/sat/intake` route makes.
        """
        from ...services.sat_processor import SATDocumentProcessor

        db = self._db(ctx)
        if db is None:
            return StageResult.fail(
                AdapterStage.VALIDATE, "A database session is required for ingest", ERROR_VALIDATION
            )
        xml_content = self._xml_from(ctx)
        if not xml_content:
            return StageResult.fail(
                AdapterStage.VALIDATE, "No CFDI XML supplied in context payload", ERROR_VALIDATION
            )

        source = ctx.metadata.get("source", "admin")
        result = SATDocumentProcessor(db).process_cfdi_document(
            user_id=ctx.user_id,
            xml_content=xml_content,
            source=source,
        )
        if result.get("success"):
            return StageResult.ok(AdapterStage.VALIDATE, result, status=result.get("status"))
        return StageResult.fail(
            AdapterStage.VALIDATE,
            result.get("error", "CFDI intake failed"),
            result.get("status", ERROR_VALIDATION),
        )

    def map(self, ctx: AdapterContext) -> StageResult:
        """
        Supplier RFC → SAP GL account, via SATSupplierMappingService.

        Falls back to the shared DEFAULT mapping exactly like
        SATCanonicalMergeService._merge_vendor_documents does.
        """
        from ...services.sat_supplier_mapping_service import SATSupplierMappingService

        db = self._db(ctx)
        if db is None:
            return StageResult.fail(
                AdapterStage.MAP, "A database session is required for mapping", ERROR_MAPPING
            )

        parsed = ctx.get_output(AdapterStage.PARSE) or {}
        supplier_rfc = (
            ctx.metadata.get("supplier_rfc")
            or parsed.get("supplier_rfc")
            or (ctx.payload.get("supplier_rfc") if isinstance(ctx.payload, dict) else None)
        )
        if not supplier_rfc:
            return StageResult.fail(AdapterStage.MAP, "supplier_rfc is required", ERROR_MAPPING)

        service = SATSupplierMappingService(db)
        mapping = service.get_mapping_by_rfc(supplier_rfc)
        used_default = False
        if mapping is None:
            mapping = service.get_or_create_default_mapping()
            used_default = mapping is not None

        if mapping is None:
            return StageResult.fail(
                AdapterStage.MAP, f"No mapping found for RFC {supplier_rfc}", ERROR_MAPPING
            )

        data = {
            "supplier_rfc": supplier_rfc,
            "mapping": mapping,
            "gl_account": getattr(mapping, "gl_account", None),
            "used_default": used_default,
        }
        ctx.set_output(AdapterStage.MAP, data)
        return StageResult.ok(AdapterStage.MAP, data, used_default=used_default)

    def apply_business_rules(self, ctx: AdapterContext) -> StageResult:
        """
        Mexico merge rules, via SATCanonicalMergeService.merge_documents_for_period.

        The simple-merge strategy currently lives inside the
        `/api/v1/sat/simple-merge` route, not a service, so it is not delegated
        here (see PHASE_3.md, "Known limitations").
        """
        from ...services.sat_canonical_merge_service import SATCanonicalMergeService

        strategy = ctx.metadata.get("merge_strategy", self.config.merge_strategy)
        if strategy == MERGE_STRATEGY_SIMPLE:
            return StageResult.fail(
                AdapterStage.BUSINESS_RULES,
                "Simple merge is implemented in the sat_simple_merge route; "
                "delegation requires extracting it into a service (Phase 4)",
                ERROR_BUSINESS_RULES,
            )
        if strategy != MERGE_STRATEGY_CANONICAL:
            return StageResult.fail(
                AdapterStage.BUSINESS_RULES, f"Unknown merge strategy '{strategy}'", ERROR_BUSINESS_RULES
            )

        db = self._db(ctx)
        if db is None:
            return StageResult.fail(
                AdapterStage.BUSINESS_RULES, "A database session is required", ERROR_BUSINESS_RULES
            )

        company_code = ctx.metadata.get("company_code") or self.config.company_code
        fiscal_year = ctx.metadata.get("fiscal_year")
        fiscal_period = ctx.metadata.get("fiscal_period")
        missing = [
            name
            for name, value in (
                ("company_code", company_code),
                ("fiscal_year", fiscal_year),
                ("fiscal_period", fiscal_period),
            )
            if value in (None, "")
        ]
        if missing:
            return StageResult.fail(
                AdapterStage.BUSINESS_RULES,
                f"Missing required context: {', '.join(missing)}",
                ERROR_BUSINESS_RULES,
            )

        try:
            result = SATCanonicalMergeService(db).merge_documents_for_period(
                user_id=ctx.user_id,
                company_code=company_code,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a stage failure
            logger.error("Canonical merge failed: %s", exc, exc_info=True)
            return StageResult.fail(AdapterStage.BUSINESS_RULES, str(exc), ERROR_BUSINESS_RULES)

        ctx.set_output(AdapterStage.BUSINESS_RULES, result)
        return StageResult.ok(AdapterStage.BUSINESS_RULES, result, strategy=strategy)

    def transform(self, ctx: AdapterContext) -> StageResult:
        """
        Merged document → SAP document list, via SAPTransformer.

        Chooses `transform_canonical_to_sap_format` or
        `transform_simple_to_sap_format` from the document supplied in the
        context; the transformer itself is untouched.
        """
        from ...services.sap_transformer import SAPTransformer

        document = ctx.metadata.get("document") or ctx.get_output(AdapterStage.BUSINESS_RULES)
        if document is None:
            return StageResult.fail(
                AdapterStage.TRANSFORM,
                "A merged document is required in metadata['document']",
                ERROR_TRANSFORM,
            )

        kind = ctx.metadata.get("document_kind") or self._infer_document_kind(document)
        transformer = SAPTransformer(self._db(ctx))
        try:
            if kind == MERGE_STRATEGY_SIMPLE:
                sap_documents = transformer.transform_simple_to_sap_format(document)
            elif kind == MERGE_STRATEGY_CANONICAL:
                sap_documents = transformer.transform_canonical_to_sap_format(document)
            else:
                return StageResult.fail(
                    AdapterStage.TRANSFORM, f"Unknown document kind '{kind}'", ERROR_TRANSFORM
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("SAP transform failed: %s", exc, exc_info=True)
            return StageResult.fail(AdapterStage.TRANSFORM, str(exc), ERROR_TRANSFORM)

        ctx.set_output(AdapterStage.TRANSFORM, sap_documents)
        return StageResult.ok(AdapterStage.TRANSFORM, sap_documents, document_kind=kind)

    @staticmethod
    def _infer_document_kind(document: Any) -> str:
        """Kind is derived from the model class, never from a country check."""
        name = type(document).__name__
        if name == "SATSimpleMerged":
            return MERGE_STRATEGY_SIMPLE
        if name == "SATCanonicalMerged":
            return MERGE_STRATEGY_CANONICAL
        return "unknown"

    def format(self, ctx: AdapterContext) -> StageResult:
        """
        Produce the wire payload.

        JSON: the transformer output is already the exact SAP wire shape, so it
        is passed through unchanged (byte-identical to today's send path).
        XML: delegates to SAPTransformer.transform_canonical_to_sap_xml.
        """
        output_format = ctx.metadata.get("output_format", self.config.output_format)

        if output_format == FORMAT_JSON:
            sap_documents = ctx.get_output(AdapterStage.TRANSFORM)
            if sap_documents is None:
                return StageResult.fail(
                    AdapterStage.FORMAT, "transform() must run before format()", ERROR_FORMAT
                )
            ctx.set_output(AdapterStage.FORMAT, sap_documents)
            return StageResult.ok(AdapterStage.FORMAT, sap_documents, content_type="application/json")

        if output_format == FORMAT_XML:
            from ...services.sap_transformer import SAPTransformer

            document = ctx.metadata.get("document")
            if document is None:
                return StageResult.fail(
                    AdapterStage.FORMAT, "metadata['document'] is required for XML output", ERROR_FORMAT
                )
            try:
                xml_payload = SAPTransformer(self._db(ctx)).transform_canonical_to_sap_xml(document)
            except Exception as exc:  # noqa: BLE001
                logger.error("SAP XML format failed: %s", exc, exc_info=True)
                return StageResult.fail(AdapterStage.FORMAT, str(exc), ERROR_FORMAT)

            ctx.set_output(AdapterStage.FORMAT, xml_payload)
            return StageResult.ok(AdapterStage.FORMAT, xml_payload, content_type="application/xml")

        return StageResult.fail(
            AdapterStage.FORMAT, f"Unsupported output format '{output_format}'", ERROR_FORMAT
        )

    async def submit(self, ctx: AdapterContext) -> StageResult:
        """
        Send the formatted payload, via the existing `sap_client` singleton.

        Mexico has no live government submission today — the CFDI is already
        stamped when it reaches us — so the submission target is SAP, exactly
        as the current `/send-to-sap` routes do.
        """
        from ...services.sap_api_client import sap_client

        payload = ctx.get_output(AdapterStage.FORMAT) or ctx.get_output(AdapterStage.TRANSFORM)
        if payload is None:
            return StageResult.fail(
                AdapterStage.SUBMIT, "format() must run before submit()", ERROR_SUBMIT
            )

        document_type = ctx.metadata.get("document_type_hint", self.config.document_type_hint)
        portal_reference = ctx.metadata.get("portal_reference") or ctx.correlation_id

        response = await sap_client.send_json_to_sap_with_session(
            payload=payload,
            document_type=document_type,
            portal_reference=portal_reference,
        )
        ctx.set_output(AdapterStage.SUBMIT, response)

        if response.get("success"):
            # Pattern A (ERP_INTEGRATION_CONTRACT §9): submit IS the ERP write.
            # Platform erp_update must skip unless workspace erp_update_mode=always.
            ctx.metadata["erp_fulfilled_in_submit"] = True
            return StageResult.ok(AdapterStage.SUBMIT, response)
        return StageResult.fail(
            AdapterStage.SUBMIT, response.get("error", "SAP submission failed"), ERROR_SUBMIT,
            sap_status_code=response.get("sap_status_code"),
        )

    async def submit_period(self, ctx: AdapterContext) -> StageResult:
        """Bulk period send, via the existing SAPBulkSender."""
        from ...services.sap_send_all import SAPBulkSender

        db = self._db(ctx)
        if db is None:
            return StageResult.fail(AdapterStage.SUBMIT, "A database session is required", ERROR_SUBMIT)

        fiscal_year = ctx.metadata.get("fiscal_year")
        fiscal_period = ctx.metadata.get("fiscal_period")
        if fiscal_year is None or fiscal_period is None:
            return StageResult.fail(
                AdapterStage.SUBMIT, "fiscal_year and fiscal_period are required", ERROR_SUBMIT
            )

        response = await SAPBulkSender(db).send_all_to_sap(
            user_id=ctx.user_id,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        )
        ctx.set_output(AdapterStage.SUBMIT, response)
        if response.get("success", True):
            return StageResult.ok(AdapterStage.SUBMIT, response)
        return StageResult.fail(
            AdapterStage.SUBMIT, response.get("error", "Bulk SAP submission failed"), ERROR_SUBMIT
        )

    def receive_confirmation(self, ctx: AdapterContext, response: Any = None) -> StageResult:
        """
        Normalize a SAP response into a canonical confirmation.

        Extraction mirrors the existing `/send-to-sap` routes: read
        `document_number` or `sap_document_number` from the nested
        `sap_response` dict. The synthetic `SM…`/`TB…` fallback reference that
        those routes generate is deliberately not reproduced — inventing an
        identifier is a persistence decision, not a country rule.
        """
        payload = response if response is not None else ctx.get_output(AdapterStage.SUBMIT)
        if not isinstance(payload, dict):
            return StageResult.fail(
                AdapterStage.CONFIRMATION, "No SAP response available to confirm", ERROR_CONFIRMATION
            )

        inner = payload.get("sap_response")
        document_number = None
        if isinstance(inner, dict):
            document_number = inner.get("document_number") or inner.get("sap_document_number")

        accepted = bool(payload.get("success"))
        confirmation: Dict[str, Any] = {
            "accepted": accepted,
            "document_number": document_number,
            "status_code": payload.get("sap_status_code"),
            "error": payload.get("error"),
            "raw_response": payload,
            # Opaque to HttpErpConnector; consumed by WorkspaceErpUpdater skip policy.
            "erp_fulfilled_in_submit": accepted
            or bool(ctx.metadata.get("erp_fulfilled_in_submit")),
            "extensions": {
                "erp_fulfilled_in_submit": accepted
                or bool(ctx.metadata.get("erp_fulfilled_in_submit")),
            },
        }
        ctx.set_output(AdapterStage.CONFIRMATION, confirmation)

        if confirmation["accepted"]:
            return StageResult.ok(AdapterStage.CONFIRMATION, confirmation)
        return StageResult.fail(
            AdapterStage.CONFIRMATION,
            confirmation["error"] or "SAP did not accept the document",
            ERROR_CONFIRMATION,
        )


def build_mx_cfdi_adapter(
    db: Any = None, config: Any = None, government_connector: Any = None, **_ignored: Any
) -> MxCfdiAdapter:
    """Registry factory. Accepts a WorkspaceAdapterConfig row, dict, or MxCfdiConfig."""
    if config is None or isinstance(config, MxCfdiConfig):
        resolved = config
    else:
        resolved = MxCfdiConfig.from_workspace(config)
    return MxCfdiAdapter(
        db=db, config=resolved, government_connector=government_connector
    )
