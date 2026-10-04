"""Authentication strategies for the Government Connector (Phase 7)."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .base import GovernmentEndpointConfig
from ..secrets import (
    LiteralOnlyResolver,
    SecretResolutionError,
    SecretResolver,
    get_default_secret_resolver,
)

logger = logging.getLogger("zodiac-api.government.auth")

# Re-export for backward compatibility with older imports/tests.
SECRET_REF_PREFIXES = ("vault:", "env:", "secret:", "arn:", "kms:", "ref:")
LiteralSecretResolver = LiteralOnlyResolver


@dataclass
class AuthMaterial:
    headers: Dict[str, str] = field(default_factory=dict)
    cert: Optional[tuple] = None  # (cert_path, key_path) for httpx
    notes: str = ""
    error_code: Optional[str] = None


def _resolve(resolver: SecretResolver, ref: Optional[str]) -> Optional[str]:
    """Resolve or return None on structured failure (never echoes refs as secrets)."""
    if ref is None or str(ref).strip() == "":
        return None
    try:
        return resolver.resolve(ref)
    except SecretResolutionError as exc:
        logger.warning(
            "Government auth secret resolution failed code=%s provider=%s",
            exc.code,
            exc.provider,
        )
        return None


def build_auth(
    config: GovernmentEndpointConfig,
    resolver: Optional[SecretResolver] = None,
) -> AuthMaterial:
    resolver = resolver or get_default_secret_resolver()
    auth_type = (config.auth_type or "none").lower().replace("-", "_")
    extra = config.extra or {}

    if auth_type in ("none", "", "null"):
        return AuthMaterial(notes="none")

    if auth_type in ("api_key", "apikey"):
        secret = _resolve(resolver, config.auth_secret_ref) or _resolve(
            resolver, extra.get("api_key")
        )
        header = str(extra.get("api_key_header") or "X-API-Key")
        if not secret:
            return AuthMaterial(notes="api_key_unresolved", error_code="SECRET_UNRESOLVED")
        return AuthMaterial(headers={header: secret}, notes="api_key")

    if auth_type in ("bearer", "jwt"):
        token = _resolve(resolver, config.auth_secret_ref) or _resolve(
            resolver, extra.get("bearer_token")
        )
        if not token:
            return AuthMaterial(notes="bearer_unresolved", error_code="SECRET_UNRESOLVED")
        return AuthMaterial(headers={"Authorization": f"Bearer {token}"}, notes=auth_type)

    if auth_type == "basic":
        user = _resolve(resolver, config.client_id_ref) or _resolve(
            resolver, extra.get("username")
        )
        password = _resolve(resolver, config.client_secret_ref) or _resolve(
            resolver, config.auth_secret_ref
        )
        if not user or not password:
            return AuthMaterial(notes="basic_unresolved", error_code="SECRET_UNRESOLVED")
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        return AuthMaterial(headers={"Authorization": f"Basic {token}"}, notes="basic")

    if auth_type == "oauth2":
        token = _resolve(resolver, extra.get("access_token")) or _resolve(
            resolver, config.auth_secret_ref
        )
        if token:
            return AuthMaterial(headers={"Authorization": f"Bearer {token}"}, notes="oauth2_static")
        return AuthMaterial(notes="oauth2_unresolved", error_code="SECRET_UNRESOLVED")

    if auth_type in ("mtls", "certificate"):
        cert_path = _resolve(resolver, extra.get("cert_path") or extra.get("cert_ref"))
        key_path = _resolve(resolver, extra.get("key_path") or extra.get("key_ref"))
        if cert_path and key_path:
            return AuthMaterial(cert=(cert_path, key_path), notes="mtls")
        return AuthMaterial(notes="mtls_unresolved", error_code="SECRET_UNRESOLVED")

    logger.warning("Unknown government auth_type '%s'", auth_type)
    return AuthMaterial(notes=f"unknown:{auth_type}")


def is_usable_http_url(url: Optional[str]) -> bool:
    if not url:
        return False
    parsed = urlparse(str(url))
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def redact_endpoint(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(str(url))
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
