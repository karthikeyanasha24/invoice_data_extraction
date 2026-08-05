"""Adapter #1 — Mexico CFDI (façade over the existing SAT/SAP implementation)."""
from .config import (
    MX_CFDI_ALIASES,
    MX_CFDI_COUNTRY_CODE,
    MX_CFDI_DISPLAY_NAME,
    MX_CFDI_DOCUMENT_TYPES,
    MxCfdiConfig,
)
from .adapter import MxCfdiAdapter, build_mx_cfdi_adapter

__all__ = [
    "MxCfdiAdapter",
    "build_mx_cfdi_adapter",
    "MxCfdiConfig",
    "MX_CFDI_COUNTRY_CODE",
    "MX_CFDI_DISPLAY_NAME",
    "MX_CFDI_ALIASES",
    "MX_CFDI_DOCUMENT_TYPES",
]
