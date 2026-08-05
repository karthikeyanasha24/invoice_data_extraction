"""
Customer onboarding readiness checklist.

Uses existing workspace settings / ERP / adapter rows — no new framework.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


PIPELINE_API_ENV = "ENABLE_PIPELINE_API"


def _step(
    key: str,
    label: str,
    ok: bool,
    *,
    required: bool = True,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ok": ok,
        "required": required,
        "detail": detail,
    }


def _erp_secrets_ok(erp: Any) -> tuple[bool, Optional[str]]:
    if erp is None:
        return False, "No active ERP connection"
    auth = (getattr(erp, "auth_type", None) or "none").strip().lower()
    if auth in ("", "none"):
        return True, "auth_type=none (no secret refs required)"
    if auth in ("api_key", "bearer"):
        secret = getattr(erp, "client_secret_ref", None)
        if secret:
            return True, f"{auth} secret ref present"
        return False, f"{auth} requires client_secret_ref (vault:/env:…)"
    if auth in ("oauth2", "basic"):
        cid = getattr(erp, "client_id_ref", None)
        secret = getattr(erp, "client_secret_ref", None)
        if cid and secret:
            return True, f"{auth} id+secret refs present"
        return False, f"{auth} requires client_id_ref and client_secret_ref"
    # mtls / unknown — base_url enough; refs optional
    return True, f"auth_type={auth} (refs optional at config layer)"


#: Required before an admin may turn pipeline_enabled=true (excludes pipeline itself).
PIPELINE_PREREQUISITE_KEYS = (
    "workspace_settings",
    "erp_configured",
    "erp_secrets",
    "adapter_enabled",
    "government_endpoint",
    "monitoring_enabled",
)


def evaluate_onboarding(
    *,
    customer_exists: bool,
    has_settings: bool,
    pipeline_enabled: bool = False,
    ai_scoped: bool = True,
    monitoring_enabled: bool = True,
    flags: Optional[Dict[str, Any]] = None,
    erp: Any = None,
    adapters: Optional[List[Any]] = None,
    has_customer_user: bool = False,
) -> Dict[str, Any]:
    """
    Build a checklist for first-customer readiness.

    ``ready`` means all required steps are ok (admin can treat customer as
    production-configured for the platform path).
    """
    flags = flags or {}
    adapters = adapters or []
    enabled_adapters = [a for a in adapters if getattr(a, "enabled", False)]
    primary_adapter = enabled_adapters[0] if enabled_adapters else (
        adapters[0] if adapters else None
    )

    erp_base = bool(erp and getattr(erp, "base_url", None))
    secrets_ok, secrets_detail = _erp_secrets_ok(erp)
    adapter_on = bool(enabled_adapters)
    gov_endpoint = bool(
        primary_adapter and getattr(primary_adapter, "endpoint_url_ref", None)
    )
    erp_mode = (flags.get("erp_update_mode") or "").strip().lower()
    pipeline_api = (os.environ.get(PIPELINE_API_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    steps = [
        _step(
            "customer_exists",
            "Customer record exists",
            customer_exists,
            detail=None if customer_exists else "Create via Customers (admin)",
        ),
        _step(
            "workspace_settings",
            "Workspace settings created",
            has_settings,
            detail=(
                None
                if has_settings
                else "Created automatically with the customer, or enable from Workspaces"
            ),
        ),
        _step(
            "erp_configured",
            "ERP connection active with base URL",
            erp_base,
            detail=(
                f"connection_key={getattr(erp, 'connection_key', None)}"
                if erp_base
                else "Configure ERP on workspace Settings"
            ),
        ),
        _step(
            "erp_secrets",
            "ERP secret references configured",
            secrets_ok,
            detail=secrets_detail,
        ),
        _step(
            "adapter_enabled",
            "Country adapter enabled",
            adapter_on,
            detail=(
                f"{getattr(primary_adapter, 'country_code', None)}"
                if adapter_on
                else "Enable mx_cfdi (or target country) on Settings"
            ),
        ),
        _step(
            "government_endpoint",
            "Government endpoint configured",
            gov_endpoint,
            detail=(
                "endpoint_url_ref set"
                if gov_endpoint
                else "Set https://… or vault:/env: ref on adapter"
            ),
        ),
        _step(
            "monitoring_enabled",
            "Monitoring enabled",
            bool(monitoring_enabled),
            detail="workspace_settings.monitoring_enabled",
        ),
        _step(
            "ai_ops_enabled",
            "AI Ops scoped to workspace",
            bool(ai_scoped),
            detail="workspace_settings.ai_scoped (AI never joins invoice pipeline)",
        ),
        _step(
            "customer_user_assigned",
            "Customer portal user assigned",
            bool(has_customer_user),
            detail=(
                "At least one portal user assigned to this customer"
                if has_customer_user
                else "Create a customer user and assign this customer ID"
            ),
        ),
        _step(
            "pipeline_enabled",
            "Shared pipeline enabled for workspace",
            bool(pipeline_enabled),
            detail=(
                "pipeline_enabled=true"
                if pipeline_enabled
                else "Enable only after ERP, adapter, and government are configured"
            ),
        ),
        _step(
            "pipeline_api_env",
            "ENABLE_PIPELINE_API process flag",
            pipeline_api,
            required=False,
            detail=(
                "API routes accepting pipeline executions"
                if pipeline_api
                else "Set ENABLE_PIPELINE_API=true on API process for opt-in pipeline API"
            ),
        ),
        _step(
            "erp_update_mode",
            "ERP update mode explicit (auto/always/never)",
            erp_mode in ("auto", "always", "never"),
            required=False,
            detail=(
                f"flags.erp_update_mode={erp_mode}"
                if erp_mode
                else "Recommended: auto (skip platform ERP when MX submit already updated SAP)"
            ),
        ),
    ]

    required = [s for s in steps if s["required"]]
    missing = [s["key"] for s in required if not s["ok"]]
    ready = len(missing) == 0
    required_ok = len(required) - len(missing)
    progress_pct = int(round(100.0 * required_ok / len(required))) if required else 0

    by_key = {s["key"]: s for s in steps}
    pipeline_prereq_missing = [
        k for k in PIPELINE_PREREQUISITE_KEYS if not by_key.get(k, {}).get("ok")
    ]

    return {
        "ready": ready,
        "missing": missing,
        "steps": steps,
        "pipeline_prerequisites_met": len(pipeline_prereq_missing) == 0,
        "pipeline_prerequisites_missing": pipeline_prereq_missing,
        "summary": {
            "required_total": len(required),
            "required_ok": required_ok,
            "advisory_ok": sum(1 for s in steps if not s["required"] and s["ok"]),
            "advisory_total": sum(1 for s in steps if not s["required"]),
            "progress_pct": progress_pct,
        },
    }
