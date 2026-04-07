"""
Load billing line items for a calendar year (via VBRK.fkdat), run data-quality
checks, and print summary analysis.

Matches Zodiac SAP conventions: year from SUBSTRING(TRIM(fkdat),1,4) — not gjahr.
Join VBRP–VBRK with LPAD(TRIM(vbeln),10,'0').

Usage (from zodiac-api directory):
  python scripts/analyze_billing_year_data_quality.py
  python scripts/analyze_billing_year_data_quality.py 1999

Uses zodiac-api/.env: DATABASE_URL is loaded with override=True so it wins over a bad
shell DATABASE_URL. Optional: SAP_SCHEMA if tables are schema-qualified.

Does not import app.database (exits if DATABASE_URL unset when imported).
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    api_root = Path(__file__).resolve().parents[1]
    for p in (api_root / ".env", api_root.parent / ".env"):
        if p.is_file():
            load_dotenv(p, override=True)
            return


def _table_prefix() -> str:
    s = (os.getenv("SAP_SCHEMA") or "").strip().strip('"')
    return f'{s}.' if s else ""


def _sales_lines_sql(prefix: str) -> str:
    return f"""
SELECT
    TRIM(v."vbeln") AS vbeln,
    TRIM(v."posnr") AS posnr,
    TRIM(v."matnr") AS matnr,
    TRIM(r."fkdat") AS fkdat,
    TRIM(CAST(v."netwr" AS TEXT)) AS netwr_text,
    TRIM(r."waerk") AS waerk
FROM {prefix}vbrp v
JOIN {prefix}"VBRK" r
  ON LPAD(TRIM(v."vbeln"), 10, '0') = LPAD(TRIM(r."vbeln"), 10, '0')
WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = :year
"""


def _parse_amount(raw: Optional[str]) -> Tuple[Optional[Decimal], Optional[str]]:
    if raw is None:
        return None, "null"
    s = raw.strip()
    if s == "":
        return None, "empty"
    try:
        return Decimal(s), None
    except InvalidOperation:
        return None, f"unparseable:{s[:40]}"


def _analyze(rows: List[Dict[str, Any]], year: str) -> Dict[str, Any]:
    n = len(rows)
    issues: List[str] = []
    amounts: List[Decimal] = []
    bad_netwr = 0
    wrong_year_fkdat = 0
    dup_keys: Counter[Tuple[str, str]] = Counter()

    for r in rows:
        fk = (r.get("fkdat") or "").strip()
        if len(fk) >= 4 and fk[:4] != year:
            wrong_year_fkdat += 1
        vb = (r.get("vbeln") or "").strip()
        ps = (r.get("posnr") or "").strip()
        dup_keys[(vb, ps)] += 1

        val, err = _parse_amount(r.get("netwr_text"))
        if err:
            bad_netwr += 1
            if bad_netwr <= 5:
                issues.append(f"netwr {err} vbeln={vb} posnr={ps}")
        elif val is not None:
            amounts.append(val)

    duplicate_line_keys = sum(1 for _k, c in dup_keys.items() if c > 1)

    zero = sum(1 for a in amounts if a == 0)
    positive = sum(1 for a in amounts if a > 0)
    negative = sum(1 for a in amounts if a < 0)

    smallest_positive: Optional[Decimal] = None
    for a in amounts:
        if a > 0:
            if smallest_positive is None or a < smallest_positive:
                smallest_positive = a

    monthly: Counter[str] = Counter()
    for r in rows:
        fk = (r.get("fkdat") or "").strip()
        if len(fk) >= 6:
            monthly[fk[:6]] += 1

    stats: Dict[str, Any] = {}
    if amounts:
        stats["min"] = min(amounts)
        stats["max"] = max(amounts)
        stats["sum"] = sum(amounts, start=Decimal("0"))
        stats["mean"] = mean(amounts)
        if len(amounts) > 1:
            stats["pstdev"] = pstdev(amounts)
        else:
            stats["pstdev"] = None

    currencies = Counter((r.get("waerk") or "").strip() or "(blank)" for r in rows)

    data_ok = (
        bad_netwr == 0
        and wrong_year_fkdat == 0
        and duplicate_line_keys == 0
        and n > 0
    )

    return {
        "row_count": n,
        "parsed_amounts": len(amounts),
        "bad_netwr": bad_netwr,
        "wrong_year_fkdat": wrong_year_fkdat,
        "duplicate_line_keys": duplicate_line_keys,
        "zero_netwr": zero,
        "positive_netwr": positive,
        "negative_netwr": negative,
        "smallest_positive": smallest_positive,
        "stats": stats,
        "monthly_row_counts": dict(sorted(monthly.items())),
        "currencies": dict(currencies.most_common(20)),
        "sample_issues": issues,
        "data_ok": data_ok,
    }


def _print_report(year: str, rep: Dict[str, Any]) -> None:
    print(f"=== Billing data quality & analysis — year {year} ===\n")
    status = "OK (checks passed)" if rep["data_ok"] else "REVIEW (see issues below)"
    print(f"Overall: {status}\n")
    print(f"Rows (VBRP lines joined to VBRK in year): {rep['row_count']}")
    print(f"Parsed netwr values: {rep['parsed_amounts']}")
    if rep["bad_netwr"]:
        print(f"Unparseable / empty netwr: {rep['bad_netwr']}")
    if rep["wrong_year_fkdat"]:
        print(f"fkdat year mismatch vs filter: {rep['wrong_year_fkdat']}")
    if rep["duplicate_line_keys"]:
        print(f"(vbeln, posnr) keys with duplicates: {rep['duplicate_line_keys']}")

    print("\n--- Amount distribution (parsed netwr) ---")
    print(f"  Zero: {rep['zero_netwr']}")
    print(f"  Positive: {rep['positive_netwr']}")
    print(f"  Negative: {rep['negative_netwr']}")
    if rep["smallest_positive"] is not None:
        print(f"  Smallest positive: {rep['smallest_positive']}")

    st = rep["stats"]
    if st:
        print("\n--- Numeric summary ---")
        print(f"  Min: {st['min']}")
        print(f"  Max: {st['max']}")
        print(f"  Sum: {st['sum']}")
        m = st["mean"]
        print(f"  Mean: {m:.6f}" if isinstance(m, Decimal) else f"  Mean: {m}")
        ps = st.get("pstdev")
        if ps is not None:
            print(f"  Pop. stdev: {ps:.6f}" if isinstance(ps, Decimal) else f"  Pop. stdev: {ps}")

    print("\n--- Rows per YYYYMM (fkdat) ---")
    for ym, cnt in rep["monthly_row_counts"].items():
        print(f"  {ym}: {cnt}")

    print("\n--- WAERK (header currency) frequency ---")
    for cur, cnt in rep["currencies"].items():
        print(f"  {cur}: {cnt}")

    if rep["sample_issues"]:
        print("\n--- Sample netwr issues (up to 5) ---")
        for line in rep["sample_issues"]:
            print(f"  {line}")


def main() -> int:
    _load_dotenv()
    url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not url:
        print(
            "DATABASE_URL is not set. Point it at the Postgres DB with vbrp / VBRK, then re-run.\n"
            "Optional: SAP_SCHEMA=myschema for qualified tables.",
            file=sys.stderr,
        )
        return 1

    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    year = "1999"
    if len(sys.argv) > 1:
        y = sys.argv[1].strip()
        if not (y.isdigit() and len(y) == 4):
            print("Year must be a four-digit string, e.g. 1999", file=sys.stderr)
            return 1
        year = y

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("Install sqlalchemy: pip install sqlalchemy", file=sys.stderr)
        return 1

    prefix = _table_prefix()
    sql = _sales_lines_sql(prefix)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), {"year": year})
            rows = [dict(row._mapping) for row in result]
    except Exception as e:
        print(
            f"Query failed ({type(e).__name__}): {e}\n"
            "If tables live under a schema, set SAP_SCHEMA and retry.",
            file=sys.stderr,
        )
        return 1

    rep = _analyze(rows, year)
    _print_report(year, rep)
    print("\nDone.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
