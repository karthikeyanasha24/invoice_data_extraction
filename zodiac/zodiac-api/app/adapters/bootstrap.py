"""
Built-in adapter registration (Phase 3/5).

Kept separate from `registry.py` so importing the registry never imports
country code, and importing the adapters package never imports production
SAT/SAP services. Registration is explicit and idempotent.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional
from weakref import WeakSet

from .registry import AdapterRegistry, registry as default_registry

logger = logging.getLogger("zodiac-api.adapters.bootstrap")

_lock = threading.RLock()
#: WeakSet avoids the classic `id(obj)` reuse bug after GC in long test runs.
_bootstrapped_registries: "WeakSet[AdapterRegistry]" = WeakSet()


def register_builtin_adapters(
    target: Optional[AdapterRegistry] = None,
    replace: bool = False,
) -> AdapterRegistry:
    """Register every adapter shipped with the platform."""
    reg = target or default_registry

    # Imported lazily: keeps country packages and SAT/SAP out of module import time.
    from .mx_cfdi import MX_CFDI_ALIASES, MX_CFDI_COUNTRY_CODE, build_mx_cfdi_adapter
    from .sample_gst import (
        SAMPLE_GST_ALIASES,
        SAMPLE_GST_COUNTRY_CODE,
        build_sample_gst_adapter,
    )

    reg.register(
        MX_CFDI_COUNTRY_CODE,
        build_mx_cfdi_adapter,
        aliases=MX_CFDI_ALIASES,
        replace=replace,
    )
    # Phase 5 — sample non-Mexico adapter (scaffold). Registration only; no
    # pipeline / orchestrator / registry-design changes.
    reg.register(
        SAMPLE_GST_COUNTRY_CODE,
        build_sample_gst_adapter,
        aliases=SAMPLE_GST_ALIASES,
        replace=replace,
    )
    return reg


def ensure_builtin_adapters(target: Optional[AdapterRegistry] = None) -> AdapterRegistry:
    """
    Idempotent variant safe to call from request paths or app startup.

    Never raises on duplicate registration. Re-registers when a registry was
    previously marked bootstrapped but is empty (e.g. after clear(), or when
    a new registry reused a recycled object id under the old id-based cache).
    """
    reg = target or default_registry
    with _lock:
        if reg in _bootstrapped_registries and reg.available():
            return reg
        try:
            register_builtin_adapters(reg, replace=True)
            _bootstrapped_registries.add(reg)
        except Exception as exc:  # noqa: BLE001 - bootstrap must never break callers
            logger.warning("Built-in adapter registration issue: %s", exc)
    return reg
