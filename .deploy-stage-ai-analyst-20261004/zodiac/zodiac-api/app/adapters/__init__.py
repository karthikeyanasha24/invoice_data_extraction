"""
BridgeEDI — Country Adapter Framework (Phase 3).

A Country Adapter owns the *country-specific* portion of an invoice exchange:
format, mapping, validation, business rules, government endpoint, response mapping.

The shared platform keeps ownership of: authentication, customer workspace,
storage, monitoring, auditing, AI, retry, queues, logging, ERP connectivity.

Importing this package has no side effects on production services.
Adapters are registered explicitly via `ensure_builtin_adapters()`.
"""
from .base import (
    AdapterCapability,
    AdapterContext,
    AdapterStage,
    CountryAdapter,
    StageResult,
)
from .registry import (
    AdapterAlreadyRegisteredError,
    AdapterNotRegisteredError,
    AdapterRegistry,
    registry,
)
from .bootstrap import ensure_builtin_adapters

__all__ = [
    "AdapterCapability",
    "AdapterContext",
    "AdapterStage",
    "CountryAdapter",
    "StageResult",
    "AdapterRegistry",
    "AdapterNotRegisteredError",
    "AdapterAlreadyRegisteredError",
    "registry",
    "ensure_builtin_adapters",
]
