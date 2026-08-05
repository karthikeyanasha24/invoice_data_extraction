# Rollback Guide

**Goal:** Restore a known-good production posture in minutes without data loss where possible.

---

## 1. Instant feature-flag rollback (preferred)

No redeploy required if env/config can be flipped at the host:

| Symptom | Action |
|---------|--------|
| New pipeline causing errors | Set `ENABLE_PIPELINE_API=false` |
| Single workspace pipeline issues | Set workspace `pipeline_enabled=false` |
| AI Ops noise / abuse | Set `ENABLE_AI_OPS_API=false` |
| Monitoring API issues | Set `ENABLE_MONITORING_API=false` (pipeline still soft-fails sinks) |
| CORS misconfig locking out UI | Fix `CORS_ORIGINS` or emergency `CORS_ALLOW_ALL=true` **temporarily**, then correct |

SAT / legacy invoice routes do **not** depend on `ENABLE_PIPELINE_API`.

---

## 2. Application rollback

1. Redeploy previous known-good API image/commit.  
2. Redeploy previous frontend if UI broke.  
3. Re-verify health endpoints and pilot login.  
4. Leave DB migrations in place (expand-only) unless a migration was destructive (Phase migrations are additive — **do not drop tables** in panic).

---

## 3. Data / migration rollback

Phase 2/6/8 scripts are **expand-only** (`CREATE TABLE IF NOT EXISTS`).

| Situation | Action |
|-----------|--------|
| New tables unused | Leave tables; disable features via flags |
| Bad rows in monitoring | Delete by `customer_id` / `correlation_id` (ops SQL); do not truncate shared tables blindly |
| ERP outbox stuck | Inspect `erp_push_outbox` status; mark/replay per ERP runbook |

**Never** run `DROP TABLE` on `zodiac_invoice_*` or customer tables as a rollback step.

---

## 4. Communication template

```text
INCIDENT: BridgeEDI rollback
Impact: <pipeline | monitoring | AI Ops | UI>
Action: <flag flipped | image reverted>
Pilot customer: <id>
Next update: <time>
```

---

## 5. Validation after rollback

- [ ] `GET /` healthy  
- [ ] Pilot can login  
- [ ] SAT invoice path works (if Mexico pilot)  
- [ ] New pipeline returns 404 when disabled  
- [ ] On-call acknowledges close
