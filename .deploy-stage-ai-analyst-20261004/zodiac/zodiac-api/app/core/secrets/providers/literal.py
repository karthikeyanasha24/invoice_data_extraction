"""Literal (unprefixed) secret values — backward compatible."""
from __future__ import annotations


class LiteralSecretProvider:
    name = "literal"

    def handles(self, scheme: str) -> bool:
        return False  # only used for unprefixed values

    def resolve(self, scheme: str, path: str, *, raw_ref: str) -> str:
        return path if path else raw_ref
