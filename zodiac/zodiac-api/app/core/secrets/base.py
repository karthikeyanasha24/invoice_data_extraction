"""Secret resolution contracts (PR2)."""
from __future__ import annotations

import re
from typing import Optional, Protocol, Tuple, runtime_checkable

# scheme:rest — scheme must look like a provider id (not a bare password).
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):(.*)$", re.IGNORECASE)


class SecretResolutionError(Exception):
    """
    Structured failure resolving a secret reference.

    `message` must never include the resolved secret value or full ref payload.
    """

    def __init__(self, code: str, message: str, *, provider: Optional[str] = None):
        self.code = code
        self.message = message
        self.provider = provider
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict:
        return {
            "error_code": self.code,
            "message": self.message,
            "provider": self.provider,
        }


@runtime_checkable
class SecretProvider(Protocol):
    """One pluggable backend (env, vault, …)."""

    name: str

    def handles(self, scheme: str) -> bool: ...

    def resolve(self, scheme: str, path: str, *, raw_ref: str) -> str: ...


@runtime_checkable
class SecretResolver(Protocol):
    def resolve(self, ref: Optional[str]) -> Optional[str]: ...


def parse_secret_ref(ref: str) -> Tuple[Optional[str], str]:
    """
    Split `env:NAME` → ('env', 'NAME').
    Literals without a provider scheme → (None, full_string).
    """
    value = str(ref).strip()
    match = _SCHEME_RE.match(value)
    if not match:
        return None, value
    scheme = match.group(1).lower()
    path = match.group(2)
    return scheme, path
