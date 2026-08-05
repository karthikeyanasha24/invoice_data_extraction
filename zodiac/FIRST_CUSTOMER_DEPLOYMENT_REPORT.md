# First Customer Deployment Report

**Platform:** BridgeEDI / Zodiac  
**Date:** 2026-08-02  
**Scope:** Deployment readiness, staging validation posture, pilot Go/No-Go  
**Constraint:** No architecture, pipeline, adapter, or AI redesign  

---

## 1. Executive summary

BridgeEDI platform implementation and first-customer onboarding workflow are complete and stable. Deployment readiness is **conditional**: engineering and ops tooling are in place; **live staging connectivity** (migrations on target DB, resolvable secrets, sandbox ERP/Government) remains an operational gate owned by the pilot deployment team.

**Decision: CONDITIONAL GO (single-customer pilot)** — see §7.

---

## 2. Deployment readiness (verified)

| Area | Status | Evidence |
|------|--------|----------|
| Database / migrations | Ready (scripts + probe) | `app/migrations/phase2|6|8_*.sql`; `GET /health/ready` |
| Environment variables | Documented | `docs/operations/CONFIGURATION_GUIDE.md` |
| Secret resolution | Ready (code) | `app/core/secrets`; unit tests green |
| ERP connectivity | Ready (connector); live TBD | ERP connector + workspace ERP config |
| Government connectivity | Ready (connector); live TBD | Government connector + adapter endpoint refs |
| Workspace readiness | Ready | `GET .../onboarding-status`; Settings UI |
| Monitoring | Ready | Monitoring API + workspace tab |
| AI Ops | Ready (ops-only) | AI Ops API; contract: no invoice pipeline |
| Health endpoints | Ready | `/health`, `/health/ready` |
| Rollback | Ready (docs) | `docs/operations/ROLLBACK_GUIDE.md` |
| Onboarding UX | Ready | `CUSTOMER_ONBOARDING_IMPLEMENTATION.md` |

### Automated verification (this session)

| Suite | Result |
|-------|--------|
| `test_customer_onboarding` + `test_secret_resolver` + `test_production_readiness` | **35 OK** |
| `scripts/demo_first_customer_e2e.py` | **Ready: True** |
| `scripts/staging_failure_scenarios.py` | **PASS** (missing env, vault unavailable, disabled adapter/ops) |

### Still must be checked on the **target** staging host

- Migrations applied → `/health/ready`  
- Non-placeholder `SECRET_KEY` / `API_HASH_KEY`  
- `API_DEBUG=false`, `CORS_ALLOW_ALL=false`  
- ERP/Gov sandbox round-trip with real customer endpoints  
- Certificate / RFC mapping for Mexico pilot  

Use: [`FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md`](FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md)

---

## 3. Known risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Migrations not applied on Neon/prod | High | Run phase2/6/8; gate on `/health/ready` |
| Placeholder `SECRET_KEY` / empty `API_HASH_KEY` | High | Rotate before any external traffic |
| `SECRET_RESOLVER=literal` left in prod | High | Use default resolver + env/vault |
| Double ERP update (MX submit + platform) | Medium | `erp_update_mode=auto` (default recommendation) |
| No app-level circuit breaker / DLQ (PR4 optional) | Medium | Pilot scale; flag rollback; runbooks RB-1..3 |
| No edge rate limit | Medium | WAF / API gateway |
| Live gov/ERP outage during pilot | Medium | Sandbox first; pause `pipeline_enabled` |
| Secrets exposed in chat/logs historically | High | Rotate DB password and API keys |
| Multi-instance V1 `status_tracker` limit | Medium | Keep SAT scale cautious; pipeline opt-in |

---

## 4. Remaining operational tasks

1. Apply SQL migrations on staging (and later prod) DB.  
2. Harden env: secrets, `API_DEBUG=false`, CORS exact origins.  
3. Wire pilot ERP/Gov sandbox refs; prove resolve + connectivity.  
4. Complete [`demo/first_customer/STAGING_VALIDATION_RECORD.md`](demo/first_customer/STAGING_VALIDATION_RECORD.md) live rows.  
5. Run Mexico sample invoice on existing SAT path; then optional pipeline dry-run.  
6. Rehearse flag rollback (`ENABLE_PIPELINE_API=false`).  
7. Customer Success: demo package walkthrough ([`demo/first_customer/`](demo/first_customer/)).  
8. Sign [`FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md`](FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md) and production gate.  
9. Rotate any credentials that were shared in local `.env` / chat.

---

## 5. Production checklist (pilot)

Minimum before production URL cutover:

- [ ] Staging journey §B all pass  
- [ ] Failure tests §C live rows for gov/ERP down + recovery  
- [ ] `/health/ready` green on production DB  
- [ ] `ENABLE_PIPELINE_API=false` until first successful sandbox pipeline (or keep SAT-only)  
- [ ] Single pilot workspace only  
- [ ] `erp_update_mode` agreed with customer  
- [ ] On-call + runbooks RB-1..RB-3  
- [ ] Rollback image tags known  

Full gate: [`PRODUCTION_READINESS_CHECKLIST.md`](PRODUCTION_READINESS_CHECKLIST.md)

---

## 6. Pilot recommendation

| Item | Recommendation |
|------|----------------|
| Scope | **One** customer workspace (Mexico / `mx_cfdi`) |
| Primary path | Existing SAT/CFDI (unchanged) |
| Platform pipeline | Opt-in after sandbox dry-run |
| Government / ERP | Sandbox → production cutover with checklist |
| AI Ops | Read-only ops; no automated remediations |
| sample_gst | Not customer-facing |
| Success metric | Sandbox invoice → confirmation → ERP (or intentional skip) → monitoring timeline |

Demo materials: [`demo/first_customer/DEMO_SCRIPT.md`](demo/first_customer/DEMO_SCRIPT.md)

---

## 7. Go / No-Go decision

| Option | Meaning |
|--------|---------|
| **GO (full)** | All P0 ops items closed including live staging ERP/Gov — **not yet claimed** |
| **CONDITIONAL GO (pilot)** | Platform + onboarding + docs + automated failure sims ready; live staging checklist incomplete |
| **NO-GO** | Architecture or critical security gap — **not applicable** |

### Official recommendation

**CONDITIONAL GO — single-customer pilot**

**Conditions before production traffic:**

1. Staging validation record completed and signed.  
2. `/health/ready` green; secrets resolvable; non-debug API.  
3. Sandbox government + ERP success with recorded correlation_id.  
4. Rollback rehearsal completed.  
5. Customer Success dry-run of demo script.

---

## 8. Artifacts delivered (this work)

| Artifact | Path |
|----------|------|
| Deployment checklist | `FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md` |
| This report | `FIRST_CUSTOMER_DEPLOYMENT_REPORT.md` |
| Demo package | `demo/first_customer/` |
| Journey sim | `scripts/demo_first_customer_e2e.py` |
| Failure sim | `scripts/staging_failure_scenarios.py` |

No platform redesign. No new frameworks. Stop for operational execution and sign-off.
