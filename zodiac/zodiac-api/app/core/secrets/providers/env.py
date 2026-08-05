"""Environment-variable secret provider (`env:VAR_NAME`)."""
from __future__ import annotations

import os
import re

from ..base import SecretResolutionError

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvSecretProvider:
    name = "env"

    def handles(self, scheme: str) -> bool:
        return scheme == "env"

    def resolve(self, scheme: str, path: str, *, raw_ref: str) -> str:
        name = (path or "").strip()
        if not name or not _ENV_NAME_RE.match(name):
            raise SecretResolutionError(
                "INVALID_ENV_REF",
                "Environment secret reference is missing or invalid",
                provider=self.name,
            )
        value = os.environ.get(name)
        if value is None or value == "":
            raise SecretResolutionError(
                "MISSING_ENV_VAR",
                f"Environment variable '{name}' is not set",
                provider=self.name,
            )
        return value
