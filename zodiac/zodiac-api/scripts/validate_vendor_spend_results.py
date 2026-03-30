"""
Offline checks for "top vendors by total spend" exports (RBKP-style: one row per vendor × currency).

Usage:
  python validate_vendor_spend_results.py
  python validate_vendor_spend_results.py path/to/your_export.csv

CSV columns: vendor_id,vendor_name,currency,total_spend,invoice_count
(total_spend must be numeric, document currency — same semantics as SUM(rb.rmwwr) per waers.)
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = []
        for row in r:
            row["total_spend"] = Decimal(str(row["total_spend"]).strip())
            row["invoice_count"] = int(str(row["invoice_count"]).strip())
            rows.append(row)
    return rows


def assert_descending_global_spend(rows: list[dict[str, object]]) -> None:
    """Mirrors ORDER BY total_invoice_amount DESC on the (vendor, currency) grain."""
    amounts = [r["total_spend"] for r in rows]  # type: ignore[list-item]
    for i in range(1, len(amounts)):
        if amounts[i - 1] < amounts[i]:
            raise AssertionError(
                f"Row order breaks DESC spend: index {i - 1} {amounts[i - 1]} < index {i} {amounts[i]}"
            )


def top_vendors_per_currency(rows: list[dict[str, object]], n: int = 5) -> dict[str, list[tuple[str, str, Decimal]]]:
    """currency -> top n (vendor_name, vendor_id, spend)."""
    by_curr: dict[str, list[tuple[str, str, Decimal]]] = defaultdict(list)
    for r in rows:
        c = str(r["currency"])
        by_curr[c].append((str(r["vendor_name"]), str(r["vendor_id"]), r["total_spend"]))  # type: ignore[arg-type]
    out: dict[str, list[tuple[str, str, Decimal]]] = {}
    for c, lst in by_curr.items():
        lst.sort(key=lambda t: t[2], reverse=True)
        out[c] = lst[:n]
    return out


def vendor_totals_all_currencies(rows: list[dict[str, object]]) -> list[tuple[str, str, Decimal, int]]:
    """
    Sums spend across currencies per vendor (NOT economically valid unless FX converted).
    Used only to show why naive DEM+EUR addition in narrative summaries is misleading.
    """
    agg: dict[tuple[str, str], tuple[Decimal, int]] = {}
    for r in rows:
        key = (str(r["vendor_id"]), str(r["vendor_name"]))
        spend, inv = r["total_spend"], r["invoice_count"]  # type: ignore[assignment]
        if key in agg:
            s, ic = agg[key]
            agg[key] = (s + spend, ic + inv)  # type: ignore[operator]
        else:
            agg[key] = (spend, inv)  # type: ignore[assignment]
    ranked = [(vid, name, s, ic) for (vid, name), (s, ic) in agg.items()]
    ranked.sort(key=lambda t: t[2], reverse=True)
    return ranked


def main() -> int:
    base = Path(__file__).resolve().parent
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "vendor_spend_sample.csv"
    if not csv_path.is_file():
        print(f"Missing CSV: {csv_path}", file=sys.stderr)
        return 1

    rows = load_rows(csv_path)
    assert_descending_global_spend(rows)
    print(f"OK: {len(rows)} rows in strict DESC order by total_spend ({csv_path.name}).")

    print("\nTop 5 per currency (valid comparison within same currency only):")
    for curr, top in sorted(top_vendors_per_currency(rows).items()):
        print(f"  {curr}:")
        for name, vid, amt in top:
            print(f"    {name} ({vid}): {amt}")

    print("\nNaive sum across currencies per vendor (illustrative - do not treat as one 'total spend'):")
    for vid, name, combined, invs in vendor_totals_all_currencies(rows)[:5]:
        print(f"  {name} ({vid}): raw sum={combined} invoice_rows_summed={invs}")

    # Spot-check known figures from the sample file (Tiefland DEM + EUR rows)
    tiefland = [r for r in rows if r["vendor_id"] == "0000001075"]
    if len(tiefland) == 2:
        dem = next(r for r in tiefland if r["currency"] == "DEM")
        eur = next(r for r in tiefland if r["currency"] == "EUR")
        assert dem["total_spend"] == Decimal("1785705275.25")  # type: ignore[comparison-overlap]
        assert eur["total_spend"] == Decimal("1084431725.74")  # type: ignore[comparison-overlap]
        assert dem["invoice_count"] == 62 and eur["invoice_count"] == 69  # type: ignore[comparison-overlap]
        print("\nOK: Tiefland Glass AG DEM/EUR amounts and invoice counts match embedded sample expectations.")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
