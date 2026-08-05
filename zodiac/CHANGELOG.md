# Changelog

All notable changes to BridgeEDI / Zodiac are documented here.  
Format inspired by [Keep a Changelog](https://keepachangelog.com/).

---

## [1.0.0] — 2026-08-02 — Enterprise Release Candidate

### Added

#### Workspace & onboarding
- Customer workspace APIs and UI shell  
- ERP / adapter configuration with secret-ref validation  
- `GET /api/v1/workspace/{id}/onboarding-status`  
- Flags merge on settings PATCH; `erp_update_mode` in UI  

#### Pipeline & adapters
- Shared invoice pipeline orchestrator (opt-in API)  
- Country adapter registry; `mx_cfdi` + `sample_gst` builtins  
- Startup registration of builtin adapters  

#### ERP & government
- Core ERP HTTP connector + push outbox tables  
- ERP ownership policy / double-write skip (PR0–PR1)  
- Government connector (HTTP, mock, already-stamped) with retries/idempotency  

#### Secrets
- Central secret resolver (`env:`, `vault:`, literal mode) wired to ERP + government (PR2)  

#### Monitoring & AI Ops
- Pipeline monitoring tables, APIs, workspace UI  
- Alert service (log channel; webhook when `ALERT_WEBHOOK_URL` set)  
- AI Ops APIs/UI consuming monitoring only  

#### Deployment & ops
- `/health/ready` enterprise table probe  
- `AUTO_APPLY_ENTERPRISE_SCHEMA` opt-in  
- `scripts/apply_enterprise_migrations.py`  
- Production config posture checks on startup (`DEPLOY_ENV`)  
- Ops guides, handbooks, go-live validation, demo package  
- `zodiac-api/.env.example`  

### Changed
- CORS honors `CORS_ORIGINS`; `CORS_ALLOW_ALL` not default for prod  
- `API_DEBUG` default for `python -m app.server` is `false`  
- Historical planning docs marked superseded for v1.0  

### Fixed
- Double ERP update risk for MX when platform ERP also enabled (`erp_update_mode`)  
- Vault/env refs not sent as bearer tokens when unresolved  

### Security
- Workspace isolation tests; AI Ops forbidden invoice imports  
- Plaintext secrets rejected in workspace ERP/adapter schemas  

### Deprecated
- Planning-only status of `IMPLEMENTATION_PLAN.md` / `IMPLEMENTATION_ROADMAP.md` / `IMPLEMENTATION_TASKS.md` as go-live sources (kept for history)  

### Removed
- None from production runtime in this release (additive strategy)  

---

## Migration notes (1.0.0)

Apply expand-only SQL **in order** against the target database:

1. `zodiac-api/app/migrations/phase2_workspace_tables.sql`  
2. `zodiac-api/app/migrations/phase6_erp_outbox.sql`  
3. `zodiac-api/app/migrations/phase8_monitoring_tables.sql`  

Helper:

```bash
cd zodiac/zodiac-api
# DATABASE_URL must be set
python ../scripts/apply_enterprise_migrations.py
```

Verify: `GET /health/ready` → `status: ready`.

Do **not** DROP tables on rollback — disable features via flags ([`docs/operations/ROLLBACK_GUIDE.md`](docs/operations/ROLLBACK_GUIDE.md)).

---

## Deployment notes (1.0.0)

1. Copy [`zodiac-api/.env.example`](zodiac-api/.env.example) → `.env`; set strong secrets.  
2. `DEPLOY_ENV=PRODUCTION`, `API_DEBUG=false`, `CORS_ALLOW_ALL=false`.  
3. Keep `ENABLE_PIPELINE_API=false` until sandbox pipeline dry-run.  
4. Deploy API image (`Dockerfile` / uvicorn `app.server:app`) + frontend.  
5. Confirm `/health` and `/health/ready`.  
6. Onboard pilot workspace until `onboarding-status.ready=true`.  

Full gate: [`PRODUCTION_READINESS_CHECKLIST.md`](PRODUCTION_READINESS_CHECKLIST.md) · [`FINAL_GO_LIVE_VALIDATION.md`](FINAL_GO_LIVE_VALIDATION.md)

---

## Breaking changes

| Change | Impact | Mitigation |
|--------|--------|------------|
| Workspace secret fields reject plaintext | Old plaintext configs cannot be saved | Migrate to `env:` / `vault:` refs |
| Production CORS no longer assumes `*` when origins set | Misconfigured origins block browser | Set `CORS_ORIGINS` exactly |
| Pipeline API off by default | Callers of `/api/v1/pipeline/*` get disabled | Set `ENABLE_PIPELINE_API=true` deliberately |

SAT / V1 / V2 routes: **no breaking changes**.

---

## Pre-1.0 milestones (summary)

| Milestone | Theme |
|-----------|-------|
| Phase 2 | Workspace |
| Phase 3–5 | Adapters + registry + sample country |
| Phase 4 | Shared pipeline |
| Phase 6–7 | ERP + government connectors |
| Phase 8–9 | Monitoring + AI Ops |
| Phase 10 | Production readiness pack |
| PR0–PR2 | ERP ownership, double-write skip, secrets |
| Pilot pack | Onboarding, deploy scripts, go-live validation |
