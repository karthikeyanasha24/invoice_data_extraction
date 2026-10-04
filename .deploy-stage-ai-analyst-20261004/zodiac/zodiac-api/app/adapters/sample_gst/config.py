"""
Sample GST country configuration (Phase 5).

Declarative only. Values come from workspace_adapter_config.extra_config so a
pilot workspace can tune validation thresholds, tax mappings, and the mock
government endpoint without code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

SAMPLE_GST_COUNTRY_CODE = "sample_gst"
SAMPLE_GST_DISPLAY_NAME = "Sample — GST e-Invoice (scaffold)"
SAMPLE_GST_ALIASES: Tuple[str, ...] = ("sample", "demo_gst", "gst_sample")

SAMPLE_GST_DOCUMENT_TYPES: Tuple[str, ...] = (
    "TAX_INVOICE",
    "CREDIT_NOTE",
    "DEBIT_NOTE",
)

#: Schema version this sample understands (deliberately different from CFDI 3.3/4.0).
SAMPLE_GST_SCHEMA_VERSION = "1.0"

#: Default interstate amount above which an e-way bill id is required.
DEFAULT_EWAY_THRESHOLD = 50_000.0


@dataclass
class SampleGstConfig:
    """
    Per-workspace knobs for the sample adapter.

    Secret material is referenced (`vault:` / `env:`), never inlined — same
    convention as Phase 2 workspace schemas.
    """

    #: Mock / partner government base URL reference (not a live SAT call).
    endpoint_url_ref: Optional[str] = None
    auth_secret_ref: Optional[str] = None
    #: When True, submit() hits a live HTTP endpoint; default is an in-process mock.
    live_submit: bool = False
    #: Reject interstate invoices above this amount unless eway_bill_id is set.
    eway_threshold: float = DEFAULT_EWAY_THRESHOLD
    #: GSTIN → ledger account overrides (workspace-local mapping table).
    tax_id_ledger_map: Dict[str, str] = field(default_factory=dict)
    #: Default ledger when no GSTIN match exists.
    default_ledger: str = "GST-DEFAULT-LEDGER"
    #: Currency code expected on documents (sample rule: single currency).
    expected_currency: str = "INR"
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workspace(cls, adapter_config: Any = None) -> "SampleGstConfig":
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

        ledger_map = extra.get("tax_id_ledger_map") or {}
        if not isinstance(ledger_map, dict):
            ledger_map = {}

        threshold = extra.get("eway_threshold", DEFAULT_EWAY_THRESHOLD)
        try:
            threshold_f = float(threshold)
        except (TypeError, ValueError):
            threshold_f = DEFAULT_EWAY_THRESHOLD

        return cls(
            endpoint_url_ref=get("endpoint_url_ref") or extra.get("endpoint_url_ref"),
            auth_secret_ref=get("auth_secret_ref") or extra.get("auth_secret_ref"),
            live_submit=bool(extra.get("live_submit", False)),
            eway_threshold=threshold_f,
            tax_id_ledger_map={str(k).upper(): str(v) for k, v in ledger_map.items()},
            default_ledger=str(extra.get("default_ledger", "GST-DEFAULT-LEDGER")),
            expected_currency=str(extra.get("expected_currency", "INR")),
            extra=extra,
        )
