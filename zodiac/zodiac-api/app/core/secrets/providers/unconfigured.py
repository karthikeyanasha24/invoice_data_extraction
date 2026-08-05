"""Stub providers for registered-but-unimplemented schemes (secret/arn/kms/ref)."""
from __future__ import annotations

from ..base import SecretResolutionError


class UnconfiguredProvider:
    """Recognized scheme that is not wired in this deployment."""

    def __init__(self, name: str):
        self.name = name

    def handles(self, scheme: str) -> bool:
        return scheme == self.name

    def resolve(self, scheme: str, path: str, *, raw_ref: str) -> str:
        raise SecretResolutionError(
            "PROVIDER_NOT_CONFIGURED",
            f"Secret provider '{self.name}' is not configured in this deployment",
            provider=self.name,
        )
