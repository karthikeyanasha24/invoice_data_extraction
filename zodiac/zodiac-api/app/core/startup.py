"""
Pilot startup helpers for pilot deployability.

Why: adapters were only registered lazily on first pipeline request; enterprise
tables require an explicit apply step. This module wires safe, opt-in startup
actions without redesigning architecture.

Rollback: unset AUTO_APPLY_ENTERPRISE_SCHEMA; remove startup hook registration.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("zodiac-api.startup")

_PLACEHOLDER_SECRET_KEYS = {
    "",
    "your-secret-key-here-change-in-production",
    "changeme",
    "secret",
    "dev-secret",
}


def ensure_adapters_registered() -> None:
    """Register mx_cfdi + sample_gst into the default registry (idempotent)."""
    from ..adapters.bootstrap import ensure_builtin_adapters

    ensure_builtin_adapters()
    logger.info("[startup] Builtin country adapters registered")


def apply_enterprise_schema_if_enabled() -> bool:
    """
    When AUTO_APPLY_ENTERPRISE_SCHEMA=true, create missing tables via SQLAlchemy
    metadata (includes workspace / outbox / monitoring models registered in
    database.init_models). Off by default — prefer SQL migration files in prod.
    """
    flag = (os.environ.get("AUTO_APPLY_ENTERPRISE_SCHEMA") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    from ..database import create_all_tables

    ok = bool(create_all_tables())
    logger.info("[startup] AUTO_APPLY_ENTERPRISE_SCHEMA create_all_tables ok=%s", ok)
    return ok


def validate_production_config() -> Dict[str, Any]:
    """
    Soft validation of deploy posture. Logs warnings; returns structured report.
    Does not refuse to start (so local/dev keeps working).
    """
    deploy = (os.environ.get("DEPLOY_ENV") or os.environ.get("ENV") or "DEV").strip().upper()
    is_prodish = deploy in ("PROD", "PRODUCTION", "STAGING", "STAGE")

    warnings: List[str] = []
    errors: List[str] = []

    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if secret.lower() in _PLACEHOLDER_SECRET_KEYS or len(secret) < 16:
        msg = "SECRET_KEY is missing, short, or a known placeholder"
        (errors if is_prodish else warnings).append(msg)

    api_hash = (os.environ.get("API_HASH_KEY") or "").strip()
    if not api_hash and is_prodish:
        warnings.append("API_HASH_KEY is empty")

    debug = (os.environ.get("API_DEBUG") or "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if debug and is_prodish:
        errors.append("API_DEBUG must be false in STAGING/PRODUCTION")

    cors_all = (os.environ.get("CORS_ALLOW_ALL") or "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if cors_all and is_prodish:
        errors.append("CORS_ALLOW_ALL must be false in STAGING/PRODUCTION")

    resolver = (os.environ.get("SECRET_RESOLVER") or "default").strip().lower()
    if resolver in ("literal", "legacy") and is_prodish:
        warnings.append(
            "SECRET_RESOLVER=literal leaves vault:/env: unresolved — use default for pilot"
        )

    if not (os.environ.get("DATABASE_URL") or "").strip():
        errors.append("DATABASE_URL is required")

    report = {
        "deploy_env": deploy,
        "is_prodish": is_prodish,
        "warnings": warnings,
        "errors": errors,
        "ok": len(errors) == 0,
    }
    for w in warnings:
        logger.warning("[startup:config] %s", w)
    for e in errors:
        logger.error("[startup:config] %s", e)
    if report["ok"]:
        logger.info("[startup:config] deploy_env=%s posture OK", deploy)
    return report


def run_startup() -> Dict[str, Any]:
    """Execute all startup steps. Never raises — logs and returns report."""
    report: Dict[str, Any] = {"adapters": False, "schema_applied": False, "config": {}}
    try:
        ensure_adapters_registered()
        report["adapters"] = True
    except Exception as exc:  # noqa: BLE001
        logger.error("[startup] adapter bootstrap failed: %s", exc)

    try:
        report["schema_applied"] = apply_enterprise_schema_if_enabled()
    except Exception as exc:  # noqa: BLE001
        logger.error("[startup] schema apply failed: %s", exc)

    try:
        report["config"] = validate_production_config()
    except Exception as exc:  # noqa: BLE001
        logger.error("[startup] config validation failed: %s", exc)
        report["config"] = {"ok": False, "errors": [str(exc)], "warnings": []}

    return report
