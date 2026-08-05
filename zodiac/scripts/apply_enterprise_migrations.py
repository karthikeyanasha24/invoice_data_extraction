#!/usr/bin/env python3
"""
Apply BridgeEDI expand-only enterprise SQL migrations.

Why: tables are not created by default on API start. Ops must apply once per DB.
Alternative: set AUTO_APPLY_ENTERPRISE_SCHEMA=true (SQLAlchemy create_all).

Usage:

  cd zodiac/zodiac-api
  set DATABASE_URL=postgresql://...
  python ../scripts/apply_enterprise_migrations.py

Rollback: leave tables in place (expand-only); disable features via flags.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "zodiac-api"
MIG = ROOT / "app" / "migrations"
FILES = (
    "phase2_workspace_tables.sql",
    "phase6_erp_outbox.sql",
    "phase8_monitoring_tables.sql",
)


def main() -> int:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("ERROR: DATABASE_URL is required")
        return 2
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 required (pip install psycopg2-binary)")
        return 2

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        for name in FILES:
            path = MIG / name
            if not path.is_file():
                print(f"ERROR: missing {path}")
                return 1
            sql = path.read_text(encoding="utf-8")
            print(f"Applying {name} ...")
            cur.execute(sql)
            print(f"  OK {name}")
        print("All enterprise migrations applied.")
        print("Verify: GET /health/ready")
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
