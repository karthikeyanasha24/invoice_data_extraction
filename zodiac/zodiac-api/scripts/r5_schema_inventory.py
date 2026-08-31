"""Inventory migrated PostgreSQL tables into a machine-readable catalog snapshot.

Does not print credentials. DATABASE schema wins; output is evidence-tagged.

Usage (from zodiac-api):
  python scripts/r5_schema_inventory.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
OUT = ROOT / "app" / "data_catalog" / "generated_inventory.json"


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set; skipping live inventory.", file=sys.stderr)
        return 2
    engine = create_engine(url, pool_pre_ping=True)
    tables_sql = text(
        """
        SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable
        FROM information_schema.columns c
        WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
    )
    pk_sql = text(
        """
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = 'public'
        """
    )
    grouped: dict = {}
    pks: dict = {}
    with engine.connect() as conn:
        for row in conn.execute(tables_sql).mappings():
            t = row["table_name"]
            grouped.setdefault(t, {"schema": row["table_schema"], "columns": []})
            grouped[t]["columns"].append(
                {
                    "column_name": row["column_name"],
                    "data_type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                }
            )
        for row in conn.execute(pk_sql).mappings():
            pks.setdefault(row["table_name"], []).append(row["column_name"])
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence": "VERIFIED FROM DATABASE",
        "table_count": len(grouped),
        "tables": {
            name: {
                **info,
                "primary_key": pks.get(name, []),
                "row_count": None,
            }
            for name, info in grouped.items()
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} ({payload['table_count']} tables). Credentials not written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
