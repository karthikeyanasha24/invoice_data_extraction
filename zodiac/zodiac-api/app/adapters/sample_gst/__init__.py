"""
Adapter #2 — Sample GST e-Invoice (configurable scaffold, Phase 5).

This is intentionally NOT a production country adapter. It proves that a second
country can plug into BridgeEDI with only:

  1. a new package under app/adapters/
  2. a registration line in bootstrap
  3. workspace_adapter_config for the customer

It shares no code with mx_cfdi and imports no SAT/SAP services.
"""
from .config import (
    SAMPLE_GST_ALIASES,
    SAMPLE_GST_COUNTRY_CODE,
    SAMPLE_GST_DISPLAY_NAME,
    SAMPLE_GST_DOCUMENT_TYPES,
    SampleGstConfig,
)
from .adapter import SampleGstAdapter, build_sample_gst_adapter

__all__ = [
    "SampleGstAdapter",
    "build_sample_gst_adapter",
    "SampleGstConfig",
    "SAMPLE_GST_COUNTRY_CODE",
    "SAMPLE_GST_DISPLAY_NAME",
    "SAMPLE_GST_ALIASES",
    "SAMPLE_GST_DOCUMENT_TYPES",
]
