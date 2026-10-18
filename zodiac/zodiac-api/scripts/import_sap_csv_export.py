"""Add SAP SQL Server CSV exports to the app database without replacing tables.

The export can be previewed safely with --dry-run. Import requires an explicit
--apply flag, creates only new tables in the current PostgreSQL schema, and
rolls back the entire batch if any table fails validation or loading.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
from zipfile import ZipFile

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from sqlalchemy.engine import make_url


SOURCE_TO_TARGET = {
    "dbo___PSIF_ACK.csv": ("PSIF_ACK_DBO", "dbo./PSIF/ACK"),
    "erp___PSIF_ACK.csv": ("PSIF_ACK", "erp./PSIF/ACK"),
    "erp___PSIF_INV_HDR.csv": ("PSIF_INV_HDR", "erp./PSIF/INV_HDR"),
    "erp___PSIF_INV_ITEM.csv": ("PSIF_INV_ITEM", "erp./PSIF/INV_ITEM"),
    "erp___PSIF_INV_TYPE.csv": ("PSIF_INV_TYPE", "erp./PSIF/INV_TYPE"),
    "erp___PSIF_RBKP_MSG.csv": ("PSIF_RBKP_MSG", "erp./PSIF/RBKP_MSG"),
    "erp___PSIF_SLS_HDR.csv": ("PSIF_SLS_HDR", "erp./PSIF/SLS_HDR"),
    "erp___PSIF_SLS_ITEM.csv": ("PSIF_SLS_ITEM", "erp./PSIF/SLS_ITEM"),
    "erp___PSIF_SLS_MSG.csv": ("PSIF_SLS_MSG", "erp./PSIF/SLS_MSG"),
    "erp___PSIF_SLS_PARTNR.csv": ("PSIF_SLS_PARTNR", "erp./PSIF/SLS_PARTNR"),
    "erp__VBKD.csv": ("VBKD", "erp.VBKD"),
}


def inspect_archive(path: Path) -> list[dict[str, object]]:
    plans: list[dict[str, object]] = []
    with ZipFile(path) as archive:
        by_name = {Path(info.filename).name: info for info in archive.infolist() if not info.is_dir()}
        missing = sorted(set(SOURCE_TO_TARGET) - set(by_name))
        extra = sorted(set(by_name) - set(SOURCE_TO_TARGET))
        if missing or extra:
            raise ValueError(f"Unexpected ZIP contents; missing={missing}, extra={extra}")

        for file_name, (table_name, source_name) in SOURCE_TO_TARGET.items():
            info = by_name[file_name]
            with archive.open(info) as binary, io.TextIOWrapper(
                binary, encoding="utf-8-sig", newline=""
            ) as stream:
                reader = csv.reader(stream)
                header = next(reader, None)
                if not header:
                    raise ValueError(f"CSV has no header: {file_name}")
                columns = [name.strip().lower() for name in header]
                if any(not name for name in columns):
                    raise ValueError(f"CSV has a blank column name: {file_name}")
                if len(set(columns)) != len(columns):
                    raise ValueError(f"CSV column names collide after lowercasing: {file_name}")
                rows = 0
                for line_number, row in enumerate(reader, start=2):
                    if len(row) != len(columns):
                        raise ValueError(
                            f"{file_name} row {line_number} has {len(row)} values; expected {len(columns)}"
                        )
                    rows += 1
            plans.append({
                "file": info.filename,
                "table": table_name,
                "source": source_name,
                "columns": columns,
                "rows": rows,
            })
    return plans


def import_archive(path: Path, plans: list[dict[str, object]]) -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    database_url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured in the API environment")
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    url = make_url(database_url)
    print(f"Connecting to configured database {url.database} on {url.host}; credentials are not displayed.")
    with ZipFile(path) as archive, psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = 0")
            cursor.execute("SELECT current_schema()")
            schema_name = cursor.fetchone()[0]
            if not schema_name:
                raise RuntimeError("The database connection has no current schema")

            for plan in plans:
                table_name = str(plan["table"])
                cursor.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                    (schema_name, table_name),
                )
                if cursor.fetchone():
                    raise RuntimeError(
                        f"Refusing to overwrite existing table {schema_name}.{table_name}; no data was imported"
                    )

            for plan in plans:
                table_name = str(plan["table"])
                columns = [str(name) for name in plan["columns"]]
                create_stmt = sql.SQL("CREATE TABLE {} ({})").format(
                    sql.Identifier(schema_name, table_name),
                    sql.SQL(", ").join(
                        sql.SQL("{} TEXT").format(sql.Identifier(column)) for column in columns
                    ),
                )
                cursor.execute(create_stmt)
                cursor.execute(
                    sql.SQL("COMMENT ON TABLE {} IS %s").format(sql.Identifier(schema_name, table_name)),
                    (f"Imported from SQL Server table {plan['source']} on SAP export date 2026-10-19",),
                )

                copy_stmt = sql.SQL(
                    "COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')"
                ).format(
                    sql.Identifier(schema_name, table_name),
                    sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                )
                with archive.open(str(plan["file"])) as binary, io.TextIOWrapper(
                    binary, encoding="utf-8-sig", newline=""
                ) as stream:
                    cursor.copy_expert(copy_stmt.as_string(connection), stream)

                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(schema_name, table_name))
                )
                loaded = cursor.fetchone()[0]
                if loaded != plan["rows"]:
                    raise RuntimeError(
                        f"Row count mismatch for {table_name}: expected {plan['rows']}, loaded {loaded}"
                    )
                print(f"Loaded {schema_name}.{table_name}: {loaded} rows, {len(columns)} columns")
        # psycopg2 commits on successful context exit; any error rolls back all tables.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_file", type=Path, help="Path to SAP_export_*.zip")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate CSVs and show target plan only")
    mode.add_argument("--apply", action="store_true", help="Create new tables and import rows transactionally")
    args = parser.parse_args()

    path = args.zip_file.resolve(strict=True)
    plans = inspect_archive(path)
    total_rows = sum(int(plan["rows"]) for plan in plans)
    print(f"Validated {len(plans)} CSV files and {total_rows:,} rows in {path.name}.")
    for plan in plans:
        print(f"  {plan['source']} -> {plan['table']}: {plan['rows']:,} rows, {len(plan['columns'])} columns")

    if args.apply:
        import_archive(path, plans)
        print("Import committed successfully; existing tables were not replaced.")
    else:
        print("Dry run only; no database changes were made.")


if __name__ == "__main__":
    main()
