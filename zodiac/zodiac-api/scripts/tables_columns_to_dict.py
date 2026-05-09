#!/usr/bin/env python3
"""
Load zodiac/zodiac-api/tables_columns.csv into Python dictionaries.

CSV columns: schema, table, column, data_type

Produces:
  - tables_dict: table_name -> { column_name: data_type }
  - tables_columns_list: table_name -> [ {"column": ..., "data_type": ...}, ... ]
  - full_rows: optional list of dicts per row

Usage:
  python scripts/tables_columns_to_dict.py
  python scripts/tables_columns_to_dict.py --csv path/to/tables_columns.csv --json-out schema_tables.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_tables_columns(csv_path: Path) -> tuple[
    dict[str, dict[str, str]],
    dict[str, list[dict[str, str]]],
    dict[str, list[dict[str, str]]],
    list[dict[str, str]],
]:
    """
    Returns:
      tables_columns: table -> { column -> data_type }
      tables_meta: table -> list of {"schema", "column", "data_type"}
      schemas_tables: schema -> list of {"table", "column", "data_type"}
      rows: flat list of all rows as dicts
    """
    tables_columns: dict[str, dict[str, str]] = {}
    tables_meta: dict[str, list[dict[str, str]]] = defaultdict(list)
    schemas_tables: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows: list[dict[str, str]] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            schema = (row.get("schema") or "").strip()
            table = (row.get("table") or "").strip()
            column = (row.get("column") or "").strip()
            dtype = (row.get("data_type") or "").strip()
            if not table or not column:
                continue

            rows.append(
                {"schema": schema, "table": table, "column": column, "data_type": dtype}
            )

            if table not in tables_columns:
                tables_columns[table] = {}
            tables_columns[table][column] = dtype

            tables_meta[table].append(
                {"schema": schema, "column": column, "data_type": dtype}
            )
            schemas_tables[schema].append(
                {"table": table, "column": column, "data_type": dtype}
            )

    return (
        tables_columns,
        dict(tables_meta),
        dict(schemas_tables),
        rows,
    )


def main() -> None:
    default_csv = Path(__file__).resolve().parent.parent / "tables_columns.csv"
    parser = argparse.ArgumentParser(description="Convert tables_columns.csv to dict structures / JSON.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=default_csv,
        help=f"Path to tables_columns.csv (default: {default_csv})",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write a single JSON file with tables_columns, tables_meta, schemas_tables, row_count.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON (indent=2)",
    )
    parser.add_argument(
        "--tables-only",
        type=Path,
        default=None,
        help="Writeonly table -> {column: data_type} as JSON.",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    tables_columns, tables_meta, schemas_tables, rows = load_tables_columns(args.csv)

    indent = 2 if args.pretty else None

    payload = {
        "source_csv": str(args.csv.resolve()),
        "table_count": len(tables_columns),
        "column_rows": len(rows),
        "tables_columns": tables_columns,
        "tables_meta": tables_meta,
        "schemas_tables": schemas_tables,
    }

    if args.tables_only:
        args.tables_only.parent.mkdir(parents=True, exist_ok=True)
        with open(args.tables_only, "w", encoding="utf-8") as f:
            json.dump(tables_columns, f, indent=indent, ensure_ascii=False)
        print(f"Wrote {args.tables_only} ({len(tables_columns)} tables)")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=indent, ensure_ascii=False)
        print(f"Wrote full payload -> {args.json_out}")

    if not args.json_out and not args.tables_only:
        # Demo: print small sample
        sample_tables = sorted(tables_columns.keys())[:3]
        print(f"Loaded {len(tables_columns)} tables, {len(rows)} column rows from {args.csv}")
        print("Sample tables_columns keys:", sample_tables)
        for t in sample_tables:
            cols = tables_columns[t]
            preview = list(cols.items())[:5]
            print(f"  {t}: {len(cols)} columns, first 5: {preview}")
        print("\nTip: use --json-out schema_export.json or --tables-only tables_only.json")


if __name__ == "__main__":
    main()
