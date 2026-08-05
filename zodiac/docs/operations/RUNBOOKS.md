# Runbooks

Incident playbooks for BridgeEDI enterprise surfaces.  
Legacy SAT/Mexico path remains the production workhorse; treat new pipeline as opt-in.

---

## RB-1 — Pipeline failure spike

**Symptoms:** Many `FAILED` timelines; AI Ops “What failed today?” non-empty; customer reports.

**Steps**

1. Confirm scope: one workspace or many?  
2. If new pipeline only: set `ENABLE_PIPELINE_API=false` or workspace `pipeline_enabled=false`.  
3. Inspect top `failed_stage` via Monitoring summary / AI Ops analytics.  
4. If `validate`/`map`: fix customer payload or adapter config (`rules_version`).  
5. If `submit` / government alerts: see RB-2.  
6. If `erp_update`: see RB-3.  
7. Capture correlation_ids for postmortem.

**Escape:** Mexico SAT direct routes unaffected when pipeline flag is off.

---

## RB-2 — Government unavailable

**Symptoms:** `government_unavailable` alerts; submit failures; sample GST mock/HTTP errors.

**Steps**

1. Check external status / sandbox vs prod URL in workspace adapter config.  
2. Verify `endpoint_url_ref` and auth secret refs (do not paste secrets into tickets).  
3. Pause pipeline for affected workspace.  
4. Confirm Mexico: CFDI is already-stamped — do not invent SAT timbrado; AlreadyStamped path should not call live PAC.  
5. Resume after government health recovers; reprocess failed correlation_ids deliberately.

---

## RB-3 — ERP delays / failures

**Symptoms:** `erp_unavailable`, failed `erp_update`, missing ERP refs.

**Steps**

1. Check workspace ERP connection (`base_url`, auth refs, active flag).  
2. Inspect `erp_push_outbox` for duplicate/stuck idempotency keys.  
3. Validate outbound network / TLS to ERP.  
4. Retry is built into pipeline transport for ERP (max 3); do not hammer manually.  
5. If secret refs unresolved in runtime, escalate Task 10.5 — do not put plaintext in DB.  
6. **Mexico / dual-write check:** If pipeline `submit` already called SAP and `erp_update` also fires, set workspace flag `erp_update_mode` to `auto` (default skip when `erp_fulfilled_in_submit`) or `never`. Use `always` only when a second confirmation webhook is required. See `ERP_INTEGRATION_CONTRACT.md` §9.

---

## RB-4 — Workspace isolation / IDOR concern

**Symptoms:** User claims to see another customer’s data.

**Steps**

1. Treat as Sev-1 security.  
2. Disable AI Ops + Monitoring API flags if blast radius unclear.  
3. Collect user id, workspace id, endpoint, timestamp.  
4. Verify `user_customers` assignments and admin bit.  
5. Reproduce with non-admin token against other `customer_id` — expect **404**.  
6. Patch + rotate credentials if confirmed.

---

## RB-5 — Database migration / missing table

**Symptoms:** Monitoring/ERP errors mentioning undefined table; API warnings on persist.

**Steps**

1. Confirm which table (`pipeline_*`, `erp_push_outbox`, `workspace_*`).  
2. Apply missing migration from Migration Guide.  
3. Soft-fail sinks mean pipeline may still succeed without metrics — fix DB ASAP.  
4. Backfill not required for empty new tables.

---

## RB-6 — CORS / frontend cannot call API

**Symptoms:** Browser CORS errors after deploy.

**Steps**

1. Ensure frontend origin is in `CORS_ORIGINS`.  
2. Ensure `CORS_ALLOW_ALL=false` in prod.  
3. Redeploy/restart API to pick up env.  
4. Emergency only: temporary `CORS_ALLOW_ALL=true`, then fix origins.

---

## RB-7 — Certificate / auth outage

**Symptoms:** Login failures; API key rejects; cert upload issues.

**Steps**

1. Separate from BridgeEDI pipeline — use existing cert/auth runbooks.  
2. Confirm `SECRET_KEY` not rotated accidentally without session invalidation plan.  
3. Check API key allow-list / suspension flags.

---

## Severity cheat sheet

| Sev | Example | First action |
|-----|---------|--------------|
| 1 | Cross-tenant data leak | Disable exposed APIs; investigate |
| 2 | Pilot pipeline down | Flag off; keep SAT |
| 3 | Monitoring lag | Fix DB; pipeline may be fine |
| 4 | AI Ops recommendation noise | Disable AI Ops flag |
