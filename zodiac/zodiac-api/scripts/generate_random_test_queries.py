"""
Generate random read-only SQL smoke tests from tables_columns.csv.

Use this to verify the DB and your AI/SQL path return non-generic answers per table.

Usage (from zodiac-api directory):
  python scripts/generate_random_test_queries.py
  python scripts/generate_random_test_queries.py --queries 30 --seed 42
  python scripts/generate_random_test_queries.py --execute --queries 15

Default CSV: zodiac-api/tables_columns.csv (same folder as parent of scripts/).
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_SIMPLE_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


def quote_pg_ident(ident: str) -> str:
    if _SIMPLE_IDENT.match(ident) and ident.islower():
        return ident
    return '"' + ident.replace('"', '""') + '"'


def load_table_columns(csv_path: Path) -> dict[tuple[str, str], list[str]]:
    by_table: dict[tuple[str, str], list[str]] = defaultdict(list)
    with csv_path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            schema = row["schema"].strip()
            table = row["table"].strip()
            col = row["column"].strip()
            by_table[(schema, table)].append(col)
    return dict(by_table)


def random_query(
    schema: str,
    table: str,
    columns: list[str],
    rng: random.Random,
    max_cols: int,
    limit: int,
) -> str:
    k = min(max_cols, len(columns))
    cols = rng.sample(columns, k=k)
    if schema != "public":
        tref = f"{quote_pg_ident(schema)}.{quote_pg_ident(table)}"
    else:
        tref = quote_pg_ident(table)
    sel = ", ".join(quote_pg_ident(c) for c in cols)
    return f"SELECT {sel} FROM {tref} LIMIT {limit};"


def count_query(schema: str, table: str) -> str:
    if schema != "public":
        tref = f"{quote_pg_ident(schema)}.{quote_pg_ident(table)}"
    else:
        tref = quote_pg_ident(table)
    return f"SELECT COUNT(*)::bigint AS n FROM {tref};"


def main() -> int:
    parser = argparse.ArgumentParser(description="Random SQL smoke tests from CSV.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "tables_columns.csv",
        help="Path to tables_columns.csv",
    )
    parser.add_argument("--queries", type=int, default=25, help="How many random SELECTs")
    parser.add_argument("--counts", type=int, default=5, help="How many random COUNT(*) queries")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--max-cols", type=int, default=4, help="Max columns per SELECT")
    parser.add_argument("--limit", type=int, default=5, help="LIMIT for SELECTs")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run queries against DATABASE_URL (read-only)",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help="Skip tables whose name starts with this prefix (repeatable)",
    )
    args = parser.parse_args()

    if not args.csv.is_file():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    by_table = load_table_columns(args.csv)

    keys = list(by_table.keys())
    for p in args.exclude_prefix:
        keys = [k for k in keys if not k[1].startswith(p)]

    if not keys:
        print("No tables left after filters.", file=sys.stderr)
        return 1

    lines: list[str] = []
    lines.append("-- Random SELECTs (paste into SQL runner / compare with AI narrative)\n")
    for _ in range(args.queries):
        schema, table = rng.choice(keys)
        cols = by_table[(schema, table)]
        if not cols:
            continue
        lines.append(
            random_query(
                schema, table, cols, rng, max_cols=args.max_cols, limit=args.limit
            )
        )

    lines.append("\n-- Random COUNT(*) (sanity: row counts differ per table)\n")
    for _ in range(args.counts):
        schema, table = rng.choice(keys)
        cols = by_table[(schema, table)]
        if not cols:
            continue
        lines.append(count_query(schema, table))

    out = "\n".join(lines) + "\n"
    sys.stdout.write(out)

    if args.execute:
        url = os.getenv("DATABASE_URL")
        if not url:
            print("DATABASE_URL not set; cannot --execute.", file=sys.stderr)
            return 1
        from sqlalchemy import create_engine, text

        eng = create_engine(url, pool_pre_ping=True)
        with eng.connect() as conn:
            for sql in lines:
                s = sql.strip()
                if not s or s.startswith("--"):
                    continue
                try:
                    conn.execute(text(s))
                except Exception as e:
                    print(f"-- FAIL: {s}\n--   {e}\n", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
