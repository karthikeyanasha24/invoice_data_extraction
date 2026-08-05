#!/usr/bin/env python3
"""
Demo / dry-run documentation for first-customer E2E flow.

Does NOT call live ERP or government systems.
Simulates the platform path with the onboarding checklist + stage notes.

Usage (from zodiac-api or repo root):

  python zodiac/scripts/demo_first_customer_e2e.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

# Allow running without installing package
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "zodiac-api"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.workspace.onboarding import evaluate_onboarding  # noqa: E402


DEMO_CUSTOMER = "DEMO_PILOT_MX"


def stage(title: str, detail: str) -> None:
    print(f"\n==> {title}")
    print(f"    {detail}")


def main() -> int:
    print("BridgeEDI first-customer demo (simulated)")
    print("=" * 56)

    stage(
        "1. Administrator creates customer",
        f"POST /api/v1/customers  customer_id={DEMO_CUSTOMER} (existing customers API)",
    )
    stage(
        "2. Workspace created",
        "POST /api/v1/workspace  or Workspaces UI -> Enable settings",
    )
    stage(
        "3. ERP configured",
        "PUT /api/v1/workspace/{id}/erp  base_url + auth_type + secret refs",
    )
    stage(
        "4. Secrets configured",
        "env:/vault: refs only; SECRET_RESOLVER resolves at connector runtime",
    )
    stage(
        "5. Country adapter enabled",
        "PUT .../adapters  country_code=mx_cfdi enabled=true",
    )
    stage(
        "6. Government endpoint configured",
        "adapter.endpoint_url_ref = https://... or vault:...",
    )
    stage(
        "7. Monitoring enabled",
        "workspace_settings.monitoring_enabled=true -> /workspace/{id}/monitoring",
    )
    stage(
        "8. AI Ops enabled",
        "workspace_settings.ai_scoped=true -> /workspace/{id}/ai (ops only, not invoice path)",
    )
    stage(
        "9. Pipeline path (opt-in)",
        "pipeline_enabled=true AND ENABLE_PIPELINE_API=true on API process",
    )

    os.environ.setdefault("ENABLE_PIPELINE_API", "true")
    result = evaluate_onboarding(
        customer_exists=True,
        has_settings=True,
        pipeline_enabled=True,
        ai_scoped=True,
        monitoring_enabled=True,
        flags={"erp_update_mode": "auto"},
        erp=SimpleNamespace(
            connection_key="primary",
            base_url="https://erp.demo.local/api",
            auth_type="bearer",
            client_id_ref=None,
            client_secret_ref="env:DEMO_ERP_TOKEN",
        ),
        adapters=[
            SimpleNamespace(
                country_code="mx_cfdi",
                enabled=True,
                endpoint_url_ref="https://gov.demo.local/cfdi",
                auth_secret_ref="env:DEMO_GOV_TOKEN",
            )
        ],
    )

    print("\n==> Onboarding checklist (simulated complete config)")
    for s in result["steps"]:
        mark = "OK" if s["ok"] else "MISS"
        req = "req" if s["required"] else "adv"
        print(f"    [{mark}/{req}] {s['key']}: {s['label']}")
        if s.get("detail"):
            print(f"             {s['detail']}")

    print("\n==> Invoice processing path (documented stages)")
    for line in (
        "Customer ERP -> BridgeEDI ingest (existing invoice APIs)",
        "-> Shared pipeline (when enabled) / or legacy SAT path",
        "-> Country adapter mx_cfdi",
        "-> Government connector submit",
        "-> Confirmation",
        "-> ERP update (respect erp_update_mode; skip if already fulfilled)",
        "-> Monitoring timeline/events",
        "-> AI Ops reads monitoring aggregates only",
    ):
        print(f"    {line}")

    print(f"\nReady: {result['ready']}")
    print("GET /api/v1/workspace/{id}/onboarding-status for live checklist")
    print("GET /health/ready for enterprise table probe")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
