"""
Run the catalog RBKP + LFA1 vendor-spend query against DATABASE_URL.

Does not import app.database (that module exits the process if DATABASE_URL is unset).

Usage (from repo root or zodiac-api):
  set DATABASE_URL=postgresql://...
  python scripts/run_vendor_spend_query.py
  python scripts/run_vendor_spend_query.py 50

Optional: place .env next to zodiac-api with DATABASE_URL.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

# Catalog SQL: app/sql_catalog.json id vendor_invoice_totals_by_vendor (LIMIT adjusted).
# Set SAP_SCHEMA (e.g. sap) if tables are not on the connection search_path.
def _vendor_spend_sql(schema: str) -> str:
    p = f"{schema}." if schema else ""
    return f"""
SELECT l.name1 AS vendor_name,
       rb.lifnr AS vendor_number,
       SUM(rb.rmwwr) AS total_invoice_amount,
       COUNT(DISTINCT rb.belnr) AS invoice_count,
       rb.waers AS currency
FROM {p}RBKP rb
LEFT JOIN {p}LFA1 l ON rb.lifnr = l.lifnr
WHERE rb.rmwwr IS NOT NULL
GROUP BY rb.lifnr, l.name1, rb.waers
HAVING SUM(rb.rmwwr) > 0
ORDER BY total_invoice_amount DESC
LIMIT :lim
"""


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    api_root = Path(__file__).resolve().parents[1]
    for p in (api_root / ".env", api_root.parent / ".env"):
        if p.is_file():
            load_dotenv(p)
            return


def main() -> int:
    _load_dotenv()
    url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not url:
        print(
            "DATABASE_URL is not set. Set it to the Postgres URL that contains RBKP/LFA1, then re-run.\n"
            "Optional: SAP_SCHEMA=myschema if tables are qualified (e.g. myschema.rbkp).\n"
            "This script matches sql_catalog.json: vendor totals by currency (SUM rmwwr, GROUP BY lifnr, waers).",
            file=sys.stderr,
        )
        return 1

    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    lim = 20
    if len(sys.argv) > 1:
        try:
            lim = max(1, min(5000, int(sys.argv[1])))
        except ValueError:
            print(f"Invalid limit: {sys.argv[1]}", file=sys.stderr)
            return 1

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("Install sqlalchemy: pip install sqlalchemy", file=sys.stderr)
        return 1

    schema = (os.getenv("SAP_SCHEMA") or "").strip().strip('"')
    sql = _vendor_spend_sql(schema)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), {"lim": lim})
            rows = result.mappings().all()
    except Exception as e:
        print(
            f"Query failed ({type(e).__name__}): {e}\n"
            "If RBKP/LFA1 live under a schema, set SAP_SCHEMA and retry.",
            file=sys.stderr,
        )
        return 1

    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["vendor_name", "vendor_number", "total_invoice_amount", "invoice_count", "currency"])
    for r in rows:
        w.writerow(
            [
                r["vendor_name"],
                r["vendor_number"],
                r["total_invoice_amount"],
                r["invoice_count"],
                r["currency"],
            ]
        )
    print(f"-- {len(rows)} row(s), LIMIT {lim}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
