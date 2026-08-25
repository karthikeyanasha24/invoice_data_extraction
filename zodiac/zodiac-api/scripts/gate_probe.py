"""R3 gate probes — run after production deploy to confirm R3 intents are live."""
import json, urllib.request, time

API = "https://zodiac-back.vercel.app/api/query/adaptive"

def post(q, ctx=None):
    body = {"question": q}
    if ctx:
        body["contextData"] = ctx
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    ms = int((time.perf_counter() - t0) * 1000)
    return out, ms

def ctx_from(q, r):
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql", ""),
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status", ""),
        "data": (r.get("data") or [])[:20],
    }

def intent(r):
    ac = (r.get("query_plan") or {}).get("analytical_context") or {}
    return ac.get("intent") or (r.get("query_plan") or {}).get("intent") or ""

probes = []

# Q1
r1, ms1 = post("Show me the products with the highest profits.")
probes.append({"q": "highest profits", "status": r1.get("answer_status"), "pipe": r1.get("pipeline"), "intent": intent(r1), "ms": ms1})

c1 = ctx_from("Show me the products with the highest profits.", r1)

# Q2 suppliers — key R3 probe
r2, ms2 = post("Show their suppliers.", c1)
sql2 = (r2.get("sql") or "").upper()
probes.append({
    "q": "suppliers", "status": r2.get("answer_status"), "pipe": r2.get("pipeline"),
    "intent": intent(r2), "ms": ms2,
    "EKPO": "EKPO" in sql2, "LFA1": "LFA1" in sql2,
    "sample": (r2.get("data") or [])[:2],
})

# Q3 product group — key R3 probe
r3, ms3 = post("Break the products down by product group.", c1)
sql3 = (r3.get("sql") or "").upper()
probes.append({
    "q": "product group", "status": r3.get("answer_status"), "pipe": r3.get("pipeline"),
    "intent": intent(r3), "ms": ms3,
    "MATKL": "MATKL" in sql3,
    "sample": (r3.get("data") or [])[:2],
})

# Q4 ASP — key R3 probe
r4, ms4 = post("Show the average selling price.", c1)
sql4 = (r4.get("sql") or "").upper()
probes.append({
    "q": "ASP", "status": r4.get("answer_status"), "pipe": r4.get("pipeline"),
    "intent": intent(r4), "ms": ms4,
    "FKIMG": "FKIMG" in sql4,
    "sample": (r4.get("data") or [])[:2],
})

# Q5 inventory — key R3 probe
r5, ms5 = post("Show the inventory.", c1)
sql5 = (r5.get("sql") or "").upper()
probes.append({
    "q": "inventory", "status": r5.get("answer_status"), "pipe": r5.get("pipeline"),
    "intent": intent(r5), "ms": ms5,
    "MBEW": "MBEW" in sql5, "MARD": "MARD" in sql5,
    "sample": (r5.get("data") or [])[:2],
})

# Q6 supplier profit safety
r6, ms6 = post("Which suppliers generated the most profit?")
probes.append({
    "q": "supplier profit safety", "status": r6.get("answer_status"), "pipe": r6.get("pipeline"),
    "intent": intent(r6), "ms": ms6,
    "safe": intent(r6) in {"suppliers_of_selection", "CANNOT_ANSWER"} or r6.get("answer_status") == "CANNOT_ANSWER",
    "sample": (r6.get("data") or [])[:2],
})

print(json.dumps(probes, indent=2, default=str))

r3_live = ("EKPO" in sql2) and ("MATKL" in sql3)
print("\n=== R3 LIVE:", r3_live, "===")
for p in probes:
    tag = p["q"].upper().ljust(22)
    print(f"  {tag}  intent={p.get('intent',''):<35} status={p.get('status','')} ms={p.get('ms',0)}")
