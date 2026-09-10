from __future__ import annotations
import json, time, urllib.request

BASE = "http://127.0.0.1:8000"

def login():
    req = urllib.request.Request(
        f"{BASE}/api/v1/user/auth/login",
        data=json.dumps({"email": "puspesh@gmail.com", "password": "12345"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]

def ask(token, q):
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=json.dumps({"question": q, "investigationId": f"ad{int(time.time()*1000)}"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=135) as r:
        d = json.loads(r.read())
    d["_elapsed"] = round(time.time() - t0, 2)
    return d

token = login()
for label, q in [
    ("A", "Which customers generated the highest billed sales?"),
    ("D", "Which country, customer, and industry generated the highest billed sales?"),
]:
    d = ask(token, q)
    rows = d.get("data") or []
    cols = list(rows[0].keys()) if rows else []
    print(label, d.get("answer_status"), len(rows), cols[:6], d.get("_elapsed"), (d.get("sql") or "")[:120].replace("\n"," "))
