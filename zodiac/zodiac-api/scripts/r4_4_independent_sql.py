"""Independent PO-grain supplier concentration vs AI (when R4-4 is live)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_http import adaptive_headers
import urllib.request

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
API = "https://zodiac-back.vercel.app/api/query/adaptive"
OUT = "r4_4_independent_sql.json"

SQL = """
WITH po AS (
  SELECT
    TRIM(CAST(ek.lifnr AS TEXT)) AS supplier,
    MAX(l.name1) AS supplier_name,
    SUM(CAST(NULLIF(TRIM(CAST(p.netwr AS TEXT)), '') AS NUMERIC)) AS purchase_value
  FROM "EKPO" p
  JOIN "EKKO" ek ON TRIM(CAST(p.ebeln AS TEXT)) = TRIM(CAST(ek.ebeln AS TEXT))
  LEFT JOIN "LFA1" l ON TRIM(CAST(ek.lifnr AS TEXT)) = TRIM(CAST(l.lifnr AS TEXT))
  WHERE p.matnr IS NOT NULL AND TRIM(CAST(p.matnr AS TEXT)) <> ''
    AND TRIM(COALESCE(p.loekz, '')) = ''
    AND TRIM(COALESCE(ek.loekz, '')) = ''
  GROUP BY TRIM(CAST(ek.lifnr AS TEXT))
)
SELECT supplier, supplier_name, purchase_value,
  CASE WHEN SUM(purchase_value) OVER () > 0
    THEN ROUND(100.0 * purchase_value / SUM(purchase_value) OVER (), 2)
    ELSE NULL END AS share_of_po_value_pct
FROM po
ORDER BY purchase_value DESC NULLS LAST
LIMIT 5
"""


def main() -> None:
    if not URL:
        Path(OUT).write_text(json.dumps({"status": "BLOCKED", "reason": "DATABASE_URL missing"}), encoding="utf-8")
        print("BLOCKED: no DATABASE_URL")
        sys.exit(2)
    engine = create_engine(URL)
    with engine.connect() as conn:
        db_rows = [dict(r._mapping) for r in conn.execute(text(SQL))]
    req = urllib.request.Request(
        API,
        data=json.dumps({"question": "Show supplier concentration."}).encode(),
        headers=adaptive_headers(),
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        ai = json.load(resp)
    intent = ((ai.get("query_plan") or {}).get("analytical_context") or {}).get("intent") or (ai.get("query_plan") or {}).get("intent")
    ai_rows = ai.get("data") or []
    comparisons = []
    if intent == "supplier_concentration" and db_rows and ai_rows:
        for i, db in enumerate(db_rows[:3]):
            ai_row = next((x for x in ai_rows if str(x.get("supplier")) == str(db.get("supplier"))), None)
            if not ai_row:
                comparisons.append({"supplier": db.get("supplier"), "status": "MISSING_IN_AI"})
                continue
            db_share = float(db.get("share_of_po_value_pct") or 0)
            ai_share = float(ai_row.get("share_of_po_value_pct") or 0)
            diff = abs(db_share - ai_share)
            comparisons.append({
                "supplier": db.get("supplier"),
                "db_share": db_share,
                "ai_share": ai_share,
                "diff": diff,
                "status": "PASS" if diff <= 0.05 else "FAIL",
            })
        status = "PASS" if comparisons and all(c["status"] == "PASS" for c in comparisons) else "FAIL"
    else:
        status = "BLOCKED"
    out = {
        "status": status,
        "ai_intent": intent,
        "db_top": [{"supplier": r.get("supplier"), "share": float(r.get("share_of_po_value_pct") or 0)} for r in db_rows],
        "comparisons": comparisons,
        "note": "Independent SQL is PO-grain EKPO.NETWR share. Not live until intent is supplier_concentration.",
    }
    Path(OUT).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": status, "ai_intent": intent, "db_n": len(db_rows), "comparisons": comparisons}, indent=2, default=str))
    if status == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
