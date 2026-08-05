#!/usr/bin/env python3
"""
Phase 12 — Safe first-customer demo seed (additive, idempotent-ish).

Creates / updates:
  - Demo customer DEMO_PILOT_MX (or --customer-id)
  - Workspace settings (pipeline off by default; optional --ready configures ERP/adapter/gov sandbox refs)
  - Demo portal user (demo.portal@bridgeedi.local by default)
  - Sample monitoring timelines (1 COMPLETED + 1 FAILED) so Monitoring / AI Ops are not empty

Does NOT call live ERP or government APIs.
Does NOT invent production credentials — uses env:/sandbox refs and https://sandbox.example endpoints.

Run from zodiac-api (with DATABASE_URL / .env loaded):

  python ../scripts/seed_first_customer_demo.py
  python ../scripts/seed_first_customer_demo.py --ready
  python ../scripts/seed_first_customer_demo.py --customer-id DE875243162 --seed-monitoring-only
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running as script from zodiac/scripts with zodiac-api on path
API_ROOT = Path(__file__).resolve().parents[1] / "zodiac-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed first-customer demo data")
    parser.add_argument("--customer-id", default="DEMO_PILOT_MX")
    parser.add_argument("--email", default="demo.portal@bridgeedi.local")
    parser.add_argument("--username", default="demoportal")
    parser.add_argument("--password", default="DemoPortal1!")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Also set sandbox ERP/adapter/gov refs and enable pipeline",
    )
    parser.add_argument(
        "--seed-monitoring-only",
        action="store_true",
        help="Only insert monitoring timelines for an existing customer",
    )
    args = parser.parse_args()

    from app.database import SessionLocal
    from app.models.customer import Customer
    from app.models.monitoring import PipelineEvent, PipelineMetric, PipelineTimeline
    from app.models.user import ZodiacUser, get_password_hash
    from app.models.user_customer import UserCustomer
    from app.models.workspace import (
        WorkspaceAdapterConfig,
        WorkspaceErpConnection,
        WorkspaceSettings,
    )

    cid = args.customer_id.strip()
    db = SessionLocal()
    try:
        if not args.seed_monitoring_only:
            customer = db.query(Customer).filter(Customer.customer_id == cid).first()
            if not customer:
                customer = Customer(
                    customer_id=cid,
                    target_format="CFDI",
                    tax_value=0,
                    tax_percentage=0,
                    validation_fields={},
                )
                db.add(customer)
                db.flush()
                print(f"Created customer {cid}")
            else:
                print(f"Customer {cid} already exists")

            ws = (
                db.query(WorkspaceSettings)
                .filter(WorkspaceSettings.customer_id == cid)
                .first()
            )
            if not ws:
                ws = WorkspaceSettings(
                    customer_id=cid,
                    display_name="Demo Pilot Manufacturing MX",
                    pipeline_enabled=False,
                    ai_scoped=True,
                    monitoring_enabled=True,
                    flags={"erp_update_mode": "auto", "demo": True},
                )
                db.add(ws)
                print("Created workspace settings")
            else:
                if not ws.display_name:
                    ws.display_name = "Demo Pilot Manufacturing MX"
                print("Workspace settings present")

            if args.ready:
                erp = (
                    db.query(WorkspaceErpConnection)
                    .filter(
                        WorkspaceErpConnection.customer_id == cid,
                        WorkspaceErpConnection.connection_key == "primary",
                    )
                    .first()
                )
                if not erp:
                    erp = WorkspaceErpConnection(
                        customer_id=cid,
                        connection_key="primary",
                        is_active=True,
                    )
                    db.add(erp)
                erp.base_url = "https://sandbox.example/erp/api"
                erp.callback_url = "https://sandbox.example/erp/callback"
                erp.auth_type = "bearer"
                erp.client_secret_ref = "env:DEMO_ERP_TOKEN"
                erp.is_active = True

                adapter = (
                    db.query(WorkspaceAdapterConfig)
                    .filter(
                        WorkspaceAdapterConfig.customer_id == cid,
                        WorkspaceAdapterConfig.country_code == "mx_cfdi",
                    )
                    .first()
                )
                if not adapter:
                    adapter = WorkspaceAdapterConfig(
                        customer_id=cid,
                        country_code="mx_cfdi",
                    )
                    db.add(adapter)
                adapter.enabled = True
                adapter.endpoint_url_ref = "https://sandbox.example/gov/cfdi"
                adapter.auth_type = "bearer"
                adapter.auth_secret_ref = "env:DEMO_GOV_TOKEN"

                ws.pipeline_enabled = True
                ws.monitoring_enabled = True
                ws.ai_scoped = True
                flags = dict(ws.flags or {})
                flags["erp_update_mode"] = "auto"
                flags["demo"] = True
                ws.flags = flags
                print("Configured sandbox ERP + mx_cfdi + pipeline enabled")

            user = db.query(ZodiacUser).filter(ZodiacUser.email == args.email).first()
            if not user:
                user = ZodiacUser(
                    email=args.email,
                    username=args.username,
                    password_hash=get_password_hash(args.password),
                    is_customer_user=True,
                )
                db.add(user)
                db.flush()
                print(f"Created portal user {args.email} / {args.password}")
            else:
                user.is_customer_user = True
                print(f"Portal user {args.email} already exists")

            link = (
                db.query(UserCustomer)
                .filter(
                    UserCustomer.user_id == user.id,
                    UserCustomer.customer_id == cid,
                )
                .first()
            )
            if not link:
                db.add(UserCustomer(user_id=user.id, customer_id=cid))
                print(f"Assigned {args.email} -> {cid}")

        # Monitoring sample timelines
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        samples = [
            {
                "suffix": "ok",
                "status": "COMPLETED",
                "stage": "ai_event",
                "latency": 1840.0,
                "fail": None,
                "gov": "UUID-DEMO-CFDI-OK-001",
                "erp": "SAP-DEMO-DOC-1001",
            },
            {
                "suffix": "fail",
                "status": "FAILED",
                "stage": "submit",
                "latency": 920.0,
                "fail": "Government sandbox returned TIMEOUT",
                "gov": None,
                "erp": None,
                "error_code": "TIMEOUT",
            },
        ]
        for sample in samples:
            corr = f"demo-{cid}-{sample['suffix']}"[:64]
            existing = (
                db.query(PipelineTimeline)
                .filter(PipelineTimeline.correlation_id == corr)
                .first()
            )
            if existing:
                print(f"Timeline {corr} already present — skip")
                continue
            started = now - timedelta(hours=2 if sample["suffix"] == "ok" else 1)
            completed = started + timedelta(milliseconds=int(sample["latency"]))
            tl = PipelineTimeline(
                correlation_id=corr,
                customer_id=cid,
                country_code="mx_cfdi",
                adapter_name="mx_cfdi",
                document_type="invoice",
                status=sample["status"],
                current_stage=sample["stage"],
                retry_count=1 if sample["status"] == "FAILED" else 0,
                latency_ms=sample["latency"],
                failure_reason=sample["fail"],
                failed_stage="submit" if sample["status"] == "FAILED" else None,
                government_reference=sample["gov"],
                erp_reference=sample["erp"],
                started_at=started,
                completed_at=completed,
                extra={"demo": True, "source": "seed_first_customer_demo"},
            )
            db.add(tl)
            stages = [
                ("authenticate", "COMPLETED", 40),
                ("resolve_workspace", "COMPLETED", 30),
                ("resolve_adapter", "COMPLETED", 25),
                ("validate", "COMPLETED", 120),
                ("map", "COMPLETED", 90),
                ("business_rules", "COMPLETED", 75),
                ("format", "COMPLETED", 110),
            ]
            if sample["status"] == "COMPLETED":
                stages.extend(
                    [
                        ("submit", "COMPLETED", 400),
                        ("receive_confirmation", "COMPLETED", 350),
                        ("erp_update", "COMPLETED", 280),
                        ("monitoring", "COMPLETED", 40),
                        ("ai_event", "COMPLETED", 20),
                    ]
                )
            else:
                stages.append(("submit", "FAILED", 400))
            t = started
            for stage, st, dur in stages:
                t = t + timedelta(milliseconds=dur)
                db.add(
                    PipelineEvent(
                        correlation_id=corr,
                        customer_id=cid,
                        country_code="mx_cfdi",
                        stage=stage,
                        status=st,
                        message=(
                            sample["fail"]
                            if st == "FAILED"
                            else f"Demo stage {stage}"
                        ),
                        duration_ms=float(dur),
                        attempt=1,
                        error_code=sample.get("error_code") if st == "FAILED" else None,
                        occurred_at=t,
                    )
                )
            db.add(
                PipelineMetric(
                    customer_id=cid,
                    correlation_id=corr,
                    name="pipeline.latency_ms",
                    value=float(sample["latency"]),
                    unit="ms",
                    tags={"demo": True, "status": sample["status"]},
                    recorded_at=completed,
                )
            )
            print(f"Seeded timeline {corr} ({sample['status']})")

        print("Done.")
        print(f"  Customer: {cid}")
        print(f"  Portal:   {args.email} / {args.password} -> /customer/login")
        if args.ready:
            print("  Note: sandbox env refs DEMO_ERP_TOKEN / DEMO_GOV_TOKEN are placeholders.")
        return 0
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
