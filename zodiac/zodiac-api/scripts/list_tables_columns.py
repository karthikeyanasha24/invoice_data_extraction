"""
List all tables and columns from the database configured by DATABASE_URL.

Usage (from zodiac-api directory):
  python scripts/list_tables_columns.py
  python scripts/list_tables_columns.py --schema public
  python scripts/list_tables_columns.py --csv tables_columns.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pprint
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load .env from zodiac-api root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="List tables and columns (PostgreSQL).")
    parser.add_argument(
        "--schema",
        default="public",
        help="Table schema (default: public)",
    )
    parser.add_argument(
        "--format",
        choices=["pretty", "dict", "json"],
        default="pretty",
        help="Output format: pretty (default), dict (Python literal), json",
    )
    parser.add_argument(
        "--csv",
        metavar="FILE",
        help="If set, also write CSV with columns: schema, table, column, data_type",
    )
    args = parser.parse_args()

    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    engine = create_engine(url, pool_pre_ping=True)

    sql = text(
        """
        SELECT
            c.table_schema,
            c.table_name,
            c.column_name,
            c.data_type,
            c.ordinal_position
        FROM information_schema.columns c
        WHERE c.table_schema = :schema
        ORDER BY c.table_name, c.ordinal_position
        """
    )

    rows_out: list[dict] = []
    grouped: dict[str, list[dict[str, str]]] = {}

    with engine.connect() as conn:
        result = conn.execute(sql, {"schema": args.schema})
        current_table: str | None = None
        for row in result.mappings():
            schema = row["table_schema"]
            table = row["table_name"]
            col = row["column_name"]
            dtype = row["data_type"]
            rows_out.append(
                {
                    "schema": schema,
                    "table": table,
                    "column": col,
                    "data_type": dtype,
                }
            )
            key = f"{schema}.{table}"
            grouped.setdefault(key, []).append({"column": col, "data_type": dtype})
            if args.format == "pretty":
                if key != current_table:
                    if current_table is not None:
                        print()
                    print(f"=== {key} ===")
                    current_table = key
                print(f"  {col}  ({dtype})")

    if args.format == "pretty":
        if current_table is not None:
            print()
    elif args.format == "dict":
        pprint.pprint(grouped, sort_dicts=True, width=120)
    elif args.format == "json":
        print(json.dumps(grouped, indent=2, sort_keys=True))

    if args.csv:
        path = Path(args.csv)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["schema", "table", "column", "data_type"])
            w.writeheader()
            w.writerows(rows_out)
        print(f"Wrote {len(rows_out)} rows to {path.resolve()}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
