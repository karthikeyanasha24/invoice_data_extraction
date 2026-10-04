"""
Mexico CFDI country configuration.

Declarative only — no behaviour. Values mirror what the existing SAT services
already do; nothing here changes production behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

MX_CFDI_COUNTRY_CODE = "mx_cfdi"
MX_CFDI_DISPLAY_NAME = "Mexico — CFDI (SAT)"
MX_CFDI_ALIASES: Tuple[str, ...] = ("mx", "mex", "mexico", "cfdi")

#: Normalized document types produced by CFDIParser._map_tipo_comprobante.
MX_CFDI_DOCUMENT_TYPES: Tuple[str, ...] = (
    "INVOICE",
    "CREDIT_NOTE",
    "PAYMENT",
    "PAYROLL",
    "TRANSFER",
)

#: CFDI versions the existing parser understands.
MX_CFDI_SUPPORTED_VERSIONS: Tuple[str, ...] = ("3.3", "4.0")

#: Merge strategies implemented today by the SAT layer.
MERGE_STRATEGY_CANONICAL = "canonical"
MERGE_STRATEGY_SIMPLE = "simple"

#: Wire formats the SAP transformer can emit today.
FORMAT_JSON = "json"
FORMAT_XML = "xml"


@dataclass
class MxCfdiConfig:
    """
    Per-workspace configuration for the Mexico adapter.

    Populated from `workspace_adapter_config` (Phase 2) by the caller. Secret
    material is referenced (`vault:`/`env:`), never inlined — see
    `core.workspace.context.is_valid_secret_ref`.
    """

    company_code: Optional[str] = None
    merge_strategy: str = MERGE_STRATEGY_CANONICAL
    output_format: str = FORMAT_JSON
    document_type_hint: str = "CANONICAL"
    endpoint_url_ref: Optional[str] = None
    auth_secret_ref: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workspace(cls, adapter_config: Any = None) -> "MxCfdiConfig":
        """Build config from a WorkspaceAdapterConfig row or a plain dict."""
        if adapter_config is None:
            return cls()

        if isinstance(adapter_config, dict):
            extra = adapter_config.get("extra_config") or {}
            get = adapter_config.get
        else:
            extra = getattr(adapter_config, "extra_config", None) or {}
            get = lambda key, default=None: getattr(adapter_config, key, default)  # noqa: E731

        if not isinstance(extra, dict):
            extra = {}

        return cls(
            company_code=extra.get("company_code"),
            merge_strategy=extra.get("merge_strategy", MERGE_STRATEGY_CANONICAL),
            output_format=extra.get("output_format", FORMAT_JSON),
            document_type_hint=extra.get("document_type_hint", "CANONICAL"),
            endpoint_url_ref=get("endpoint_url_ref"),
            auth_secret_ref=get("auth_secret_ref"),
            extra=extra,
        )
