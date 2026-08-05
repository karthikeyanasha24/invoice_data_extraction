# Demo Script — First Customer (≈25 minutes)

**Environment:** Staging API + frontend. Sandbox ERP/Government endpoints.  
**Login:** Admin user. Pilot customer workspace ready (`onboarding-status.ready` preferred).

---

## 0. Pre-demo (5 min, off camera)

1. `GET /health` → healthy  
2. `GET /health/ready` → ready  
3. Open Workspaces → pilot customer → Overview shows readiness  
4. Sample invoice file staged (see `SAMPLE_DATA.md`)  
5. Monitoring + AI Ops tabs load  

---

## 1. Administrator creates / selects customer (2 min)

**Show:** Customers admin (existing) → pilot customer ID.  
**Say:** “Customer identity is unchanged; workspace is the exclusive operating space.”

---

## 2. Workspace (3 min)

**Show:** `/workspace` → open pilot → Overview flags (pipeline, monitoring, AI scoped, ERP mode).  
**Show:** Settings checklist (onboarding status).  
**Say:** “Configuration is refs-only — no plaintext secrets in the database.”

---

## 3. Invoice processing (5 min)

**Show:** Existing invoice / SAT path for Mexico (or workspace Invoices tab).  
Upload or open a known sample.  
**Say:** “Legacy SAT/V1/V2 stay production-safe. Platform pipeline is opt-in.”

If pipeline demo enabled: trigger dry-run / opt-in execution for this workspace only.

---

## 4. Government submission (3 min)

**Show:** Adapter `mx_cfdi` enabled; government endpoint = sandbox.  
**Show:** Submit result / CFDI or confirmation artifact (sandbox).  
**Say:** “Government connector is workspace-configured; retries are built in.”

---

## 5. Confirmation → ERP (3 min)

**Show:** ERP connection (base URL masked, auth type, secret refs).  
**Show:** Confirmation / ERP update outcome.  
**Say:** “`erp_update_mode=auto` prevents double SAP update when submit already fulfilled ERP.”

---

## 6. Monitoring (3 min)

**Show:** Workspace → Monitoring — timeline, stages, correlation_id.  
**Say:** “Ops visibility per customer; isolation enforced.”

---

## 7. AI Ops (3 min)

**Show:** Workspace → AI Ops — ask “What failed today?” / retry stats (ops data).  
**Say:** “AI Ops reads monitoring only. AI never joins the invoice pipeline.”

---

## 8. Close (2 min)

**Show:** Rollback story — disable `ENABLE_PIPELINE_API` or `pipeline_enabled` without touching SAT.  
**Ask:** Staging sign-off for limited production pilot.
