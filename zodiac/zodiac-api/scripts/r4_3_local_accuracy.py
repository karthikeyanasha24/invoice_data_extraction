"""Local R4-3 accuracy: TestClient (new code) vs independent SQL on DATABASE_URL."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)
os.environ.setdefault("PYTHONPATH", str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from app.server import app  # noqa: E402

from scripts.r4_3_independent_sql import COMPARE_SQL, GROUP_SQL, INV_TOP_SQL, cmp_top  # noqa: E402

OUT = ROOT / "r4_3_local_accuracy.json"


def post(client: TestClient, q: str, ctx=None):
    body = {"question": q}
    if ctx:
        body["contextData"] = ctx
    r = client.post("/api/query/adaptive", json=body, timeout=180)
    r.raise_for_status()
    return r.json()


def intent_of(p: dict) -> str:
    qp = p.get("query_plan") or {}
    ac = qp.get("analytical_context") or {}
    return str(ac.get("intent") or qp.get("intent") or "")


def run():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("BLOCKED: No DATABASE_URL")
    eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 30}, use_native_hstore=False)
    client = TestClient(app)
    cases_spec = [
        ("Show inventory.", INV_TOP_SQL, "product", "stock_value", "inventory_analysis"),
        ("Show inventory versus sales.", COMPARE_SQL, "product", "stock_value", "inventory_sales_comparison"),
        ("Show inventory versus sales.", COMPARE_SQL, "product", "revenue", "inventory_sales_comparison"),
        ("Show inventory by product group.", GROUP_SQL, "product_group", "stock_value", "inventory_sales_comparison"),
        ("Which products have high inventory but low sales?", None, None, None, "inventory_risk_analysis"),
        ("Which products have low inventory but high sales?", None, None, None, "inventory_risk_analysis"),
        ("Show inventory by plant.", None, None, None, "inventory_by_plant"),
        ("Show inventory aging.", None, None, None, "inventory_aging_gap"),
    ]
    cases = []
    with eng.connect() as conn:
        for q, sql, key, metric, exp_intent in cases_spec:
            p = post(client, q)
            ac_intent = intent_of(p)
            row = {
                "question": q,
                "status": p.get("answer_status"),
                "intent": ac_intent,
                "expected_intent": exp_intent,
                "intent_ok": (
                    ac_intent == exp_intent
                    if not exp_intent.endswith("_gap")
                    else p.get("answer_status") == "CANNOT_ANSWER"
                ),
                "rows": p.get("rowCount") or len(p.get("data") or []),
                "sql_has_vbrp_join_mbew": (
                    "VBRP" in (p.get("sql") or "").upper()
                    and 'JOIN "MBEW"' in (p.get("sql") or "")
                    and "NETWR" in (p.get("sql") or "").upper()
                    and "inventory_agg" not in (p.get("sql") or "")
                ),
                "sample": (p.get("data") or [None])[0],
            }
            if sql and key and metric:
                ind = [dict(r) for r in conn.execute(text(sql)).mappings()]
                collapsed, seen = [], set()
                for r in p.get("data") or []:
                    k = str(r.get(key) or "")
                    if not k or k in seen:
                        continue
                    seen.add(k)
                    collapsed.append(r)
                diffs = cmp_top(collapsed, ind, key, metric)
                row["metric"] = metric
                row["ind_top"] = ind[0] if ind else {}
                row["diffs"] = diffs
                row["mismatches"] = sum(1 for d in diffs if not d["ok"])
            cases.append(row)

    report = {
        "source": "local TestClient + DATABASE_URL",
        "cases": cases,
        "total_mismatches": sum(c.get("mismatches") or 0 for c in cases),
        "intent_fail": sum(1 for c in cases if not c.get("intent_ok")),
        "fanout": sum(1 for c in cases if c.get("sql_has_vbrp_join_mbew")),
    }
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("total_mismatches", "intent_fail", "fanout")}, indent=2))
    for c in cases:
        print(
            c["question"][:48],
            c["status"],
            c["intent"],
            "rows",
            c["rows"],
            "mm",
            c.get("mismatches"),
        )


if __name__ == "__main__":
    run()
