"""
Adapter Registry (Phase 3, Task 3.2).

Resolves a workspace's `country_code` to a `CountryAdapter` instance.

The platform must never contain `if country == "MX"`. Countries are data:
    Workspace → country_code → registry.resolve() → adapter → pipeline

Adapters are registered as *factories* so each resolution can receive its own
dependencies (db session, workspace config) — dependency injection, not
globals.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional

from .base import CountryAdapter

logger = logging.getLogger("zodiac-api.adapters.registry")

AdapterFactory = Callable[..., CountryAdapter]


class AdapterRegistryError(Exception):
    """Base class for registry errors."""


class AdapterNotRegisteredError(AdapterRegistryError):
    """Raised when a country has no adapter. Callers translate to 4xx/5xx."""

    def __init__(self, country_code: str, available: Iterable[str]):
        self.country_code = country_code
        self.available = sorted(available)
        super().__init__(
            f"No country adapter registered for '{country_code}'. "
            f"Available: {', '.join(self.available) or 'none'}"
        )


class AdapterAlreadyRegisteredError(AdapterRegistryError):
    """Raised on duplicate registration without an explicit replace."""


def normalize_country_code(country_code: Optional[str]) -> str:
    if not country_code or not str(country_code).strip():
        raise AdapterRegistryError("country_code is required")
    return str(country_code).strip().lower().replace("-", "_")


class AdapterRegistry:
    """Thread-safe country_code → adapter factory map."""

    def __init__(self) -> None:
        self._factories: Dict[str, AdapterFactory] = {}
        self._aliases: Dict[str, str] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ mutation

    def register(
        self,
        country_code: str,
        factory: AdapterFactory,
        aliases: Iterable[str] = (),
        replace: bool = False,
    ) -> str:
        key = normalize_country_code(country_code)
        if not callable(factory):
            raise AdapterRegistryError(
                f"Factory for '{key}' must be callable, got {type(factory)!r}"
            )

        with self._lock:
            if key in self._factories and not replace:
                raise AdapterAlreadyRegisteredError(
                    f"Adapter '{key}' is already registered; pass replace=True to override"
                )
            self._factories[key] = factory

            for alias in aliases:
                alias_key = normalize_country_code(alias)
                if alias_key == key:
                    continue
                existing = self._aliases.get(alias_key)
                if existing and existing != key and not replace:
                    raise AdapterAlreadyRegisteredError(
                        f"Alias '{alias_key}' already points to '{existing}'"
                    )
                self._aliases[alias_key] = key

        logger.info("Registered country adapter '%s'", key)
        return key

    def unregister(self, country_code: str) -> bool:
        key = normalize_country_code(country_code)
        with self._lock:
            removed = self._factories.pop(key, None) is not None
            for alias, target in list(self._aliases.items()):
                if target == key:
                    self._aliases.pop(alias, None)
        return removed

    def clear(self) -> None:
        with self._lock:
            self._factories.clear()
            self._aliases.clear()

    # ----------------------------------------------------------- resolution

    def _canonical_key(self, country_code: str) -> str:
        key = normalize_country_code(country_code)
        return self._aliases.get(key, key)

    def is_registered(self, country_code: str) -> bool:
        try:
            return self._canonical_key(country_code) in self._factories
        except AdapterRegistryError:
            return False

    def resolve(self, country_code: str, **dependencies: Any) -> CountryAdapter:
        """
        Build an adapter for `country_code`.

        Extra keyword arguments (e.g. `db`, `config`) are injected into the
        factory. Factories that ignore them stay compatible.
        """
        key = self._canonical_key(country_code)
        with self._lock:
            factory = self._factories.get(key)

        if factory is None:
            raise AdapterNotRegisteredError(key, self._factories.keys())

        adapter = factory(**dependencies)
        if not isinstance(adapter, CountryAdapter):
            raise AdapterRegistryError(
                f"Factory for '{key}' returned {type(adapter)!r}, "
                "which is not a CountryAdapter"
            )
        return adapter

    # ------------------------------------------------------------ discovery

    def available(self) -> List[str]:
        with self._lock:
            return sorted(self._factories.keys())

    def aliases(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._aliases)

    def describe(self, **dependencies: Any) -> List[Dict[str, Any]]:
        """Catalog for config UIs. Failures are reported, never raised."""
        catalog: List[Dict[str, Any]] = []
        for key in self.available():
            try:
                catalog.append(self.resolve(key, **dependencies).describe())
            except Exception as exc:  # noqa: BLE001 - catalog must not break callers
                logger.warning("Could not describe adapter '%s': %s", key, exc)
                catalog.append({"country_code": key, "error": str(exc)})
        return catalog


#: Process-wide registry used by the platform.
registry = AdapterRegistry()
