"""Composite secret resolver — single entry point for the platform."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from .base import SecretProvider, SecretResolutionError, SecretResolver, parse_secret_ref
from .providers.env import EnvSecretProvider
from .providers.literal import LiteralSecretProvider
from .providers.unconfigured import UnconfiguredProvider
from .providers.vault import VaultSecretProvider

logger = logging.getLogger("zodiac-api.secrets")

_DEFAULT: Optional["CompositeSecretResolver"] = None


class CompositeSecretResolver:
    """
    Resolves literals and scheme-prefixed refs via registered providers.

    Unknown schemes → SecretResolutionError(UNKNOWN_PROVIDER) — never silent.
    """

    def __init__(self, providers: Optional[List[SecretProvider]] = None):
        self._literal = LiteralSecretProvider()
        self._providers: List[SecretProvider] = list(
            providers
            if providers is not None
            else [
                EnvSecretProvider(),
                VaultSecretProvider(),
                UnconfiguredProvider("secret"),
                UnconfiguredProvider("arn"),
                UnconfiguredProvider("kms"),
                UnconfiguredProvider("ref"),
            ]
        )
        self._by_scheme: Dict[str, SecretProvider] = {}
        for provider in self._providers:
            # Register all schemes the provider claims via common names
            for scheme in _schemes_for(provider):
                self._by_scheme[scheme] = provider

    def resolve(self, ref: Optional[str]) -> Optional[str]:
        if ref is None:
            return None
        raw = str(ref).strip()
        if raw == "":
            return None

        scheme, path = parse_secret_ref(raw)
        if scheme is None:
            return self._literal.resolve("", path, raw_ref=raw)

        provider = self._by_scheme.get(scheme)
        if provider is None:
            raise SecretResolutionError(
                "UNKNOWN_PROVIDER",
                f"Unknown secret provider '{scheme}'",
                provider=scheme,
            )
        try:
            return provider.resolve(scheme, path, raw_ref=raw)
        except SecretResolutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Secret provider '%s' failed (%s)", provider.name, type(exc).__name__
            )
            raise SecretResolutionError(
                "PROVIDER_ERROR",
                f"Secret provider '{provider.name}' failed",
                provider=provider.name,
            ) from exc


class LiteralOnlyResolver:
    """
    Backward-compatible resolver used by older tests: literals only;
    prefixed refs return None (never echoed as credentials).
    """

    def resolve(self, ref: Optional[str]) -> Optional[str]:
        if ref is None:
            return None
        raw = str(ref).strip()
        if raw == "":
            return None
        scheme, path = parse_secret_ref(raw)
        if scheme is not None:
            return None
        return path


def get_default_secret_resolver() -> SecretResolver:
    """
    Platform default.

    SECRET_RESOLVER=literal → LiteralOnlyResolver (legacy/test)
    otherwise → CompositeSecretResolver (env + vault + stubs)
    """
    global _DEFAULT
    mode = (os.environ.get("SECRET_RESOLVER") or "default").strip().lower()
    if mode in ("literal", "legacy"):
        return LiteralOnlyResolver()
    if _DEFAULT is None:
        _DEFAULT = CompositeSecretResolver()
    return _DEFAULT


def reset_default_secret_resolver_for_tests() -> None:
    global _DEFAULT
    _DEFAULT = None


def _schemes_for(provider: SecretProvider) -> List[str]:
    name = getattr(provider, "name", "") or ""
    if name:
        return [name]
    return []
