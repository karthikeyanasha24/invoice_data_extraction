# Staging Validation Record — First Customer

**Pilot customer_id:** ________________  
**Environment:** staging  
**Date:** ________________  
**Operator:** ________________  

Fill during staging. Simulated portions already executed in CI/dev are marked.

---

## A. Deployment verification

| Check | Result | Notes / evidence |
|-------|--------|------------------|
| `GET /health` | ☐ pass ☐ fail | |
| `GET /health/ready` | ☐ pass ☐ fail | missing_tables= |
| Migrations phase2/6/8 | ☐ pass ☐ fail | |
| Env: `SECRET_KEY` non-default | ☐ pass ☐ fail | |
| Env: `API_DEBUG=false` | ☐ pass ☐ fail | |
| Env: `CORS_ALLOW_ALL=false` | ☐ pass ☐ fail | |
| `SECRET_RESOLVER` production mode | ☐ pass ☐ fail | |
| ERP secret resolves | ☐ pass ☐ fail | |
| Gov secret resolves | ☐ pass ☐ fail | |
| Onboarding `ready=true` | ☐ pass ☐ fail | |

**Automated (dev):** onboarding + secrets + production_readiness unit suites — **35 tests OK** (2026-08-02).

---

## B. Customer journey (record each step)

| # | Step | Action | Result | correlation_id / artifact |
|---|------|--------|--------|---------------------------|
| 1 | Administrator | Login admin | ☐ | |
| 2 | Customer | Create/select customer | ☐ | |
| 3 | Workspace | Enable settings | ☐ | |
| 4 | ERP | Configure base_url + refs | ☐ | |
| 5 | Secrets | Confirm resolve on host | ☐ | |
| 6 | Adapter | Enable `mx_cfdi` | ☐ | |
| 7 | Government | Sandbox endpoint | ☐ | |
| 8 | Invoice | Upload sample | ☐ | |
| 9 | Pipeline | Opt-in dry-run (if enabled) | ☐ | |
| 10 | Government submit | Sandbox submit | ☐ | |
| 11 | Confirmation | Status observed | ☐ | |
| 12 | ERP | Update / skip per mode | ☐ | |
| 13 | Monitoring | Timeline visible | ☐ | |
| 14 | AI Ops | Ops question answered | ☐ | |

**Simulated journey script:** `python zodiac/scripts/demo_first_customer_e2e.py` → Ready: True.

---

## C. Failure tests

| Scenario | How tested | Result | Recovery |
|----------|------------|--------|----------|
| Invalid / missing credentials | `env:MISSING_*` resolve | ☐ Simulated PASS (structured error) ☐ Live | |
| Government unavailable | Bad sandbox URL / closed port | ☐ | Pause workspace pipeline; restore; retry |
| ERP unavailable | Bad ERP URL | ☐ | Outbox inspect; retry |
| Expired / vault secret | `vault:` without config | ☐ Simulated PASS | |
| Workspace pipeline disabled | `pipeline_enabled=false` | ☐ | |
| Adapter disabled | `enabled=false` | ☐ Simulated PASS (not ready) | |
| Retry behavior | Observe gov/ERP retries | ☐ | |
| Recovery | Restore + reprocess | ☐ | |
| Flag rollback | `ENABLE_PIPELINE_API=false` | ☐ | SAT path still works |

**Simulated script:** `python zodiac/scripts/staging_failure_scenarios.py`

---

## D. Sign-off

| Role | Pass/Fail | Signature |
|------|-----------|-----------|
| Engineering | ☐ | |
| DevOps | ☐ | |
| Customer Success | ☐ | |

**Staging gate:** ☐ Proceed to limited production · ☐ Hold
