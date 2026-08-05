# BridgeEDI Operations Handbook

**Audience:** DevOps, on-call engineers, Technical Owner  
**Pilot posture:** CONDITIONAL GO — single customer  
**Related:** [`docs/operations/`](docs/operations/) · [`RUNBOOKS.md`](docs/operations/RUNBOOKS.md) · [`FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md`](FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md)

Architecture is frozen. This handbook is **how we run** the platform, not how we redesign it.

---

## 1. Operating model

| Role | Responsibility |
|------|----------------|
| On-call | Incidents, flag flips, health probes |
| DevOps | Deploys, migrations, backups, secrets |
| Support / CS | First-line customer issues → escalate |
| Engineering | Defects after triage; no drive-by features |

**Primary production path (pilot):** existing Mexico SAT / CFDI / SAP.  
**Opt-in path:** shared pipeline (`ENABLE_PIPELINE_API` + workspace `pipeline_enabled`).  
**Escape hatch:** disable pipeline flags; SAT continues.

---

## 2. Daily operations

| Timebox | Task | Pass criteria |
|---------|------|---------------|
| Start of day | `GET /health` and `GET /health/ready` | healthy / ready |
| Start of day | Pilot workspace Monitoring summary | No unexplained Sev-1/2 spike |
| Start of day | AI Ops: “What failed yesterday?” (optional) | Review failed stages |
| Ongoing | Ticket queue | Sev-1 same day; Sev-2 within SLA |
| End of day | Note open incidents + correlation_ids | Handoff to next on-call |

### Daily health commands

```text
GET /health
GET /health/ready
GET /api/v1/workspace/{pilot}/onboarding-status   # still ready?
```

If `/health/ready` → 503: apply missing migrations ([Migration Guide](docs/operations/MIGRATION_GUIDE.md)). Do not invent schema fixes in production without change control.

---

## 3. Weekly maintenance

| Task | Owner | Notes |
|------|-------|-------|
| Review failed timelines / ERP outbox stuck rows | Ops | By `customer_id`, `correlation_id` |
| Confirm backup / PITR window for Postgres | DevOps | Provider console (Neon/Supabase/etc.) |
| Dependency advisory skim (`pip-audit` / `npm audit`) | Eng | Waive or schedule |
| Feature-flag inventory | Tech Owner | Pipeline on/off? CORS? SECRET_RESOLVER? |
| Customer sync (15 min) | CS | Open issues, volume, satisfaction |
| Certificate / token expiry check (Mexico) | Support | Existing cert flows |

---

## 4. Monthly maintenance

| Task | Owner |
|------|-------|
| Restore drill (staging): restore snapshot → `/health/ready` | DevOps |
| Rollback rehearsal: flip `ENABLE_PIPELINE_API=false` | Ops |
| Access review: admin users, `user_customers` assignments | Security |
| Secret rotation schedule (ERP/Gov env vars or vault) | DevOps |
| Capacity review: invoice volume vs DB pool / workers | Tech Owner |
| Update TECHNICAL_DEBT.md priorities after pilot learnings | Tech Owner |

---

## 5. Backup procedures

1. Prefer **managed PITR** (Neon/Supabase continuous backup).  
2. Confirm retention meets customer contract (e.g. 7–30 days).  
3. Document last successful backup timestamp in monthly log.  
4. Never rely on “export table from app” as sole backup.  
5. Migrations are expand-only — backups remain valid across phase2/6/8.

---

## 6. Restore procedures

1. Declare incident; pause non-essential writes if corruption suspected.  
2. Restore to **new** staging instance first when possible.  
3. Point staging `DATABASE_URL` → restored DB; run `/health` + `/health/ready`.  
4. Spot-check: pilot customer, workspace settings, recent invoices.  
5. Production cutover only after Tech Owner approval.  
6. **Do not** DROP enterprise tables as a “restore shortcut.”

---

## 7. Log monitoring

| Signal | Where | Action |
|--------|-------|--------|
| `correlation_id` | API / monitoring events | Trace one invoice end-to-end |
| Secret resolve failures | `zodiac-api.secrets` | Never log values; fix refs |
| Government auth fail | Government connector logs | RB-2 |
| ERP timeout / reject | ERP connector logs | RB-3 |
| CORS errors | Browser + API | RB-6 |
| 5xx rate | Edge / host metrics | Scale or rollback |

**Rule:** Do not paste secrets, FIEL private keys, or bearer tokens into tickets.

---

## 8. Performance monitoring

| Metric | Pilot target | Alert if |
|--------|--------------|----------|
| API p95 latency (non-AI) | Baseline from staging | > 2× baseline sustained |
| Invoice process success rate | ≥ agreed SLA | Drop > 5% day-over-day |
| Government submit failures | Near zero in stable week | Spike |
| ERP update failures / skips | Skips OK if `erp_update_mode=auto` | Unexpected failures |
| DB connections | Under pool max | Saturation |
| Monitoring write errors | Soft-fail; pipeline may continue | Persist errors rising |

AI chat / Adaptive Query latency is **separate** from invoice SLA.

---

## 9. Alert handling

Use severity from [`RUNBOOKS.md`](docs/operations/RUNBOOKS.md):

| Sev | First action | Escalate |
|-----|--------------|----------|
| 1 Isolation leak | Disable exposed APIs; RB-4 | Security + Tech Owner |
| 2 Pilot pipeline down | `ENABLE_PIPELINE_API=false` or workspace `pipeline_enabled=false` | Eng |
| 3 Monitoring lag | Fix DB / RB-5 | DevOps |
| 4 AI Ops noise | `ENABLE_AI_OPS_API=false` | Product |

Always record: time, workspace, correlation_id, flag changes, customer impact.

---

## 10. ERP failures

Follow **RB-3**. Summary:

1. Check workspace ERP `base_url`, `auth_type`, secret refs.  
2. Confirm secret resolves on host (`env:` / vault).  
3. Inspect `erp_push_outbox` for stuck / duplicate keys.  
4. Respect built-in retries; do not hammer manually.  
5. Confirm `erp_update_mode` (avoid double SAP write).  
6. Customer comms: “confirmation delayed; invoices still received.”

---

## 11. Government failures

Follow **RB-2**. Summary:

1. Confirm sandbox vs production URL in adapter config.  
2. Verify auth secret refs.  
3. Pause pipeline for workspace if flood of failures.  
4. Mexico: do not invent SAT HTTP; already-stamped path is expected.  
5. Resume and reprocess failed correlation_ids deliberately.

---

## 12. Workspace failures

| Symptom | Check | Fix |
|---------|-------|-----|
| User cannot open workspace | Assignment / admin | Fix `user_customers` |
| Onboarding not ready | `onboarding-status` | Complete Settings |
| Settings 403 | Non-admin | Admin-only config |
| Wrong customer data | Isolation | Sev-1 RB-4 |
| Pipeline rejected | Flags | Enable only after dry-run |

---

## 13. Recovery procedures (standard)

1. **Stabilize** — flag off or pause workspace pipeline.  
2. **Preserve** — collect correlation_ids, logs (redacted).  
3. **Restore service** — SAT path first if pipeline broken.  
4. **Fix root cause** — config, secret, endpoint, migration.  
5. **Verify** — `/health/ready`, sample invoice, monitoring timeline.  
6. **Re-enable** — one flag at a time.  
7. **Postmortem** — within 5 business days for Sev-1/2.

---

## 14. Feature flags (ops cheat sheet)

| Flag | Safe pilot default |
|------|--------------------|
| `ENABLE_PIPELINE_API` | `false` until dry-run proven |
| Workspace `pipeline_enabled` | `false` then true for pilot only |
| `ENABLE_MONITORING_API` | `true` |
| `ENABLE_AI_OPS_API` | `true` |
| `CORS_ALLOW_ALL` | `false` |
| `API_DEBUG` | `false` |
| `SECRET_RESOLVER` | default (not `literal`) |
| `erp_update_mode` | `auto` |

---

## 15. Release & migration discipline

1. Prefer expand-only SQL; never panic-DROP.  
2. Deploy API → verify health → deploy frontend.  
3. Tag release; keep previous image for rollback.  
4. Change config via env/flags before code when possible.  
5. No production deploys Friday evening without Tech Owner approval (pilot policy).

---

*Handbook version: 1.0 · Aligned with Conditional GO pilot*
