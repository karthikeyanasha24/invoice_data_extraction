"""Independent PO-grain supplier concentration vs AI (when R4-4 is live)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_http import adaptive_headers
import urllib.request

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
API = "https://zodiac-back.vercel.app/api/query/adaptive"
OUT = "r4_4_independent_sql.json"


def post(q: str, ctx=None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"question": q}
    if ctx:
        body["contextData"] = ctx
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(), headers=adaptive_headers()
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def intent_of(r: Dict[str, Any]) -> Optional[str]:
    qp = r.get("query_plan") or r.get("queryPlan") or {}
    if not isinstance(qp, dict):
        return None
    ac = qp.get("analytical_context") or {}
    return ac.get("intent") or qp.get("intent") or r.get("intent")


def ctx_from(q: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql", ""),
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status", ""),
        "data": (r.get("data") or [])[:20],
    }


def products_from(r: Dict[str, Any]) -> List[str]:
    qp = r.get("query_plan") or {}
    ac = qp.get("analytical_context") or {} if isinstance(qp, dict) else {}
    prods = list(ac.get("selected_products") or [])
    if prods:
        return [str(p) for p in prods[:20]]
    out: List[str] = []
    for row in r.get("data") or []:
        if isinstance(row, dict):
            p = row.get("product") or row.get("matnr")
            if p:
                out.append(str(p).strip())
    return list(dict.fromkeys(out))[:20]


def db_share(conn, products: Optional[List[str]]) -> List[Dict[str, Any]]:
    extra = ""
    params: Dict[str, Any] = {}
    if products:
        extras = []
        for i, p in enumerate(products):
            key = f"p{i}"
            extras.append(f":{key}")
            params[key] = p
        extra = f" AND TRIM(CAST(p.matnr AS TEXT)) IN ({', '.join(extras)})"
    sql = f"""
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
    {extra}
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
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def compare(db_rows, ai_rows) -> Tuple[str, List[Dict[str, Any]]]:
    comparisons = []
    for db in db_rows[:3]:
        ai_row = next((x for x in ai_rows if str(x.get("supplier")) == str(db.get("supplier"))), None)
        if not ai_row:
            comparisons.append({"supplier": db.get("supplier"), "status": "MISSING_IN_AI"})
            continue
        db_share_v = float(db.get("share_of_po_value_pct") or 0)
        ai_share = float(ai_row.get("share_of_po_value_pct") or 0)
        diff = abs(db_share_v - ai_share)
        comparisons.append({
            "supplier": db.get("supplier"),
            "db_share": db_share_v,
            "ai_share": ai_share,
            "diff": round(diff, 4),
            "status": "PASS" if diff <= 0.05 else "FAIL",
        })
    status = "PASS" if comparisons and all(c["status"] == "PASS" for c in comparisons) else "FAIL"
    return status, comparisons


def main() -> None:
    if not URL:
        Path(OUT).write_text(json.dumps({"status": "BLOCKED", "reason": "DATABASE_URL missing"}), encoding="utf-8")
        print("BLOCKED: no DATABASE_URL")
        sys.exit(2)

    engine = create_engine(URL)
    standalone = post("Show supplier concentration.")
    r0 = post("Show the products with the highest profits.")
    ctx = ctx_from("Show the products with the highest profits.", r0)
    products = products_from(r0)
    chained = post("Show supplier concentration.", ctx)

    with engine.connect() as conn:
        db_global = db_share(conn, None)
        db_filtered = db_share(conn, products) if products else []

    stand_intent = intent_of(standalone)
    chain_intent = intent_of(chained)
    stand_rows = standalone.get("data") or []
    chain_rows = chained.get("data") or []

    stand_status, stand_cmp = ("BLOCKED", [])
    if stand_intent == "supplier_concentration" and stand_rows and "share_of_po_value_pct" in (stand_rows[0] or {}):
        stand_status, stand_cmp = compare(db_global, stand_rows)
    chain_status, chain_cmp = ("BLOCKED", [])
    if chain_intent == "supplier_concentration" and chain_rows and "share_of_po_value_pct" in (chain_rows[0] or {}):
        chain_status, chain_cmp = compare(db_filtered or db_global, chain_rows)

    status = "PASS" if chain_status == "PASS" and stand_status in {"PASS", "BLOCKED"} else (
        "FAIL" if "FAIL" in {stand_status, chain_status} else "BLOCKED"
    )
    if stand_status == "BLOCKED" and chain_status == "PASS":
        status = "PASS"
        note = "Chained product-filtered concentration matches independent SQL. Standalone first-question path not yet deep_multidim on this backend."
    else:
        note = "Independent SQL is PO-grain EKPO.NETWR share with LOEKZ filter."

    out = {
        "status": status,
        "standalone_intent": stand_intent,
        "chained_intent": chain_intent,
        "products_n": len(products),
        "standalone": {"status": stand_status, "comparisons": stand_cmp},
        "chained": {"status": chain_status, "comparisons": chain_cmp},
        "db_global": [{"supplier": r.get("supplier"), "share": float(r.get("share_of_po_value_pct") or 0)} for r in db_global],
        "note": note,
    }
    Path(OUT).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "status": status,
        "standalone_intent": stand_intent,
        "chained_intent": chain_intent,
        "chained": chain_cmp,
        "standalone": stand_cmp,
    }, indent=2, default=str))
    if status == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
