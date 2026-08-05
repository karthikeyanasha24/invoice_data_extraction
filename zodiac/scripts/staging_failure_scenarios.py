#!/usr/bin/env python3
"""
Staging failure-scenario simulation for first-customer deployment.

Does not call live ERP/Government. Documents expected platform behavior using
onboarding checklist + secret resolver contracts.

Usage (from zodiac-api):

  python ../scripts/staging_failure_scenarios.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "zodiac-api"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.workspace.onboarding import evaluate_onboarding  # noqa: E402


def _line(title: str, expected: str, evidence: str) -> None:
    print(f"\n[{title}]")
    print(f"  Expected: {expected}")
    print(f"  Evidence: {evidence}")


def main() -> int:
    print("BridgeEDI first-customer failure scenarios (simulated)")
    print("=" * 60)

    # --- Invalid / missing credentials (secret resolution) ---
    os.environ.pop("MISSING_PILOT_TOKEN", None)
    os.environ.pop("SECRET_RESOLVER", None)
    try:
        from app.core.secrets import (
            SecretResolutionError,
            get_default_secret_resolver,
            reset_default_secret_resolver_for_tests,
        )

        reset_default_secret_resolver_for_tests()
        resolver = get_default_secret_resolver()
        try:
            resolver.resolve("env:MISSING_PILOT_TOKEN")
            _line(
                "Invalid/missing credentials",
                "Resolve fails; connector must not send env: as bearer",
                "UNEXPECTED: resolve succeeded",
            )
            ok_secrets = False
        except SecretResolutionError as e:
            _line(
                "Invalid/missing credentials",
                "Resolve fails; connector must not send env: as bearer",
                f"SecretResolutionError code={e.code}",
            )
            ok_secrets = True
    except Exception as e:
        _line(
            "Invalid/missing credentials",
            "Resolve fails structuredly",
            f"Import/runtime note: {e}",
        )
        ok_secrets = False

    # --- Expired / unavailable vault ---
    try:
        from app.core.secrets import (
            SecretResolutionError,
            get_default_secret_resolver,
            reset_default_secret_resolver_for_tests,
        )

        reset_default_secret_resolver_for_tests()
        r = get_default_secret_resolver()
        try:
            r.resolve("vault:pilot/missing")
            vault_ok = False
            detail = "UNEXPECTED success"
        except SecretResolutionError as e:
            vault_ok = True
            detail = f"code={e.code}"
        _line(
            "Expired/unconfigured vault secret",
            "VAULT_UNAVAILABLE or structured failure; ref not sent as token",
            detail,
        )
    except Exception as e:
        vault_ok = False
        _line("Expired/unconfigured vault secret", "Structured failure", str(e))

    # --- Workspace / adapter disabled ---
    disabled_ws = evaluate_onboarding(
        customer_exists=True,
        has_settings=True,
        pipeline_enabled=False,
        monitoring_enabled=True,
        ai_scoped=True,
        erp=SimpleNamespace(
            connection_key="primary",
            base_url="https://erp.example",
            auth_type="none",
            client_id_ref=None,
            client_secret_ref=None,
        ),
        adapters=[
            SimpleNamespace(
                country_code="mx_cfdi",
                enabled=False,
                endpoint_url_ref="https://gov.example",
            )
        ],
    )
    _line(
        "Adapter disabled",
        "onboarding missing adapter_enabled; not customer-ready",
        f"ready={disabled_ws['ready']} missing={disabled_ws['missing']}",
    )

    no_pipeline = evaluate_onboarding(
        customer_exists=True,
        has_settings=True,
        pipeline_enabled=False,
        monitoring_enabled=False,
        ai_scoped=False,
        erp=SimpleNamespace(
            connection_key="primary",
            base_url="https://erp.example",
            auth_type="none",
            client_secret_ref=None,
            client_id_ref=None,
        ),
        adapters=[
            SimpleNamespace(
                country_code="mx_cfdi",
                enabled=True,
                endpoint_url_ref="https://gov.example",
            )
        ],
    )
    _line(
        "Workspace ops disabled (monitoring/AI/pipeline off)",
        "ready=false; pipeline/monitoring/ai steps fail",
        f"missing={no_pipeline['missing']}",
    )

    # --- Documented live failure tests (manual in staging) ---
    print("\n[Manual staging - record in STAGING_VALIDATION_RECORD.md]")
    for row in (
        ("Government unavailable", "Point endpoint_url_ref to closed port; expect retries then FAILED submit"),
        ("ERP unavailable", "Point base_url to closed port; expect ERP timeout/retryable failure"),
        ("Retry behavior", "Confirm government retry policy attempts; ERP transport max retries"),
        ("Recovery", "Restore endpoints; reprocess correlation_id; timeline shows success"),
        ("Flag rollback", "ENABLE_PIPELINE_API=false; SAT path still works"),
    ):
        print(f"  - {row[0]}: {row[1]}")

    print("\n" + "=" * 60)
    sim_ok = ok_secrets and vault_ok and (not disabled_ws["ready"]) and (not no_pipeline["ready"])
    print(f"Simulated failure checks: {'PASS' if sim_ok else 'REVIEW'}")
    return 0 if sim_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
