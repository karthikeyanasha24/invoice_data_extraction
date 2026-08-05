"""
Vault secret provider (`vault:path/to/secret`).

Resolution order (no silent success across unrelated providers):
1. Process-local map from BRIDGEEDI_VAULT_JSON (tests / controlled inject)
2. Env bridge BRIDGEEDI_VAULT_<PATH_AS_ENV> (ops without Vault agent)
3. HTTP KV read when VAULT_ADDR + VAULT_TOKEN are set
4. Otherwise VAULT_UNAVAILABLE (structured error — never return the raw ref)
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import quote

from ..base import SecretResolutionError

logger = logging.getLogger("zodiac-api.secrets.vault")

_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")


class VaultSecretProvider:
    name = "vault"

    def handles(self, scheme: str) -> bool:
        return scheme == "vault"

    def resolve(self, scheme: str, path: str, *, raw_ref: str) -> str:
        secret_path = (path or "").strip().lstrip("/")
        if not secret_path or not _PATH_RE.match(secret_path):
            raise SecretResolutionError(
                "INVALID_VAULT_URI",
                "Vault secret path is missing or invalid",
                provider=self.name,
            )

        from_json = _lookup_vault_json(secret_path)
        if from_json is not None:
            return from_json

        from_env = _lookup_vault_env_bridge(secret_path)
        if from_env is not None:
            return from_env

        addr = (os.environ.get("VAULT_ADDR") or "").strip()
        token = (os.environ.get("VAULT_TOKEN") or "").strip()
        if addr and token:
            value = _http_vault_read(addr, token, secret_path)
            if value is not None:
                return value
            raise SecretResolutionError(
                "VAULT_NOT_FOUND",
                "Vault path did not return a secret value",
                provider=self.name,
            )

        raise SecretResolutionError(
            "VAULT_UNAVAILABLE",
            "Vault is not configured (set VAULT_ADDR/VAULT_TOKEN or BRIDGEEDI_VAULT_JSON)",
            provider=self.name,
        )


def _lookup_vault_json(path: str) -> Optional[str]:
    raw = os.environ.get("BRIDGEEDI_VAULT_JSON")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecretResolutionError(
            "INVALID_VAULT_URI",
            "BRIDGEEDI_VAULT_JSON is not valid JSON",
            provider="vault",
        ) from exc
    if not isinstance(data, dict):
        raise SecretResolutionError(
            "INVALID_VAULT_URI",
            "BRIDGEEDI_VAULT_JSON must be a JSON object",
            provider="vault",
        )
    value = data.get(path)
    if value is None:
        return None
    return str(value)


def _lookup_vault_env_bridge(path: str) -> Optional[str]:
    key = "BRIDGEEDI_VAULT_" + re.sub(r"[^A-Za-z0-9]", "_", path).upper()
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _http_vault_read(addr: str, token: str, path: str) -> Optional[str]:
    import httpx

    base = addr.rstrip("/")
    candidates = [
        f"{base}/v1/{quote(path, safe='/')}",
        f"{base}/v1/secret/data/{quote(path, safe='/')}",
    ]
    headers = {"X-Vault-Token": token}
    for url in candidates:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vault HTTP request failed (provider=vault code=%s)", type(exc).__name__)
            continue
        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            logger.warning("Vault HTTP status=%s (provider=vault)", response.status_code)
            continue
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            continue
        extracted = _extract_vault_value(body)
        if extracted is not None:
            return extracted
    return None


def _extract_vault_value(body: Dict[str, Any]) -> Optional[str]:
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(inner, dict):
        return None
    for key in ("value", "token", "password", "secret", "api_key"):
        if key in inner and inner[key] is not None:
            return str(inner[key])
    for value in inner.values():
        if isinstance(value, str) and value:
            return value
    return None
