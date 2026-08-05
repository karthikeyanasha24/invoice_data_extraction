# BridgeEDI — Production Readiness Checklist

**Status:** Official production gate (Phase 10)  
**Audience:** Engineering leads, DevOps, security reviewers  
**Rule:** Do not enable new enterprise surfaces in production until every **P0** item is checked.

Use this document as the go-live gate. Supporting detail lives in:

- [`docs/operations/`](docs/operations/) — runbooks and guides  
- [`implementation_logs/PHASE_10.md`](implementation_logs/PHASE_10.md) — full review report  

Legend: `[ ]` open · `[x]` done · **P0** blocker · **P1** strong recommend · **P2** follow-up

---

## 0. Pre-flight (architecture freeze)

| ID | Item | Pri | Owner |
|----|------|-----|-------|
| A0 | No redesign of Workspace / Pipeline / Adapters / ERP / Government / Monitoring / AI Ops | P0 | Arch |
| A1 | Feature flags documented and understood (`ENABLE_*`, workspace gates) | P0 | Eng |
| A2 | Phase 2–9 implementation logs reviewed | P0 | Eng |
| A3 | Contracts reviewed (ERP, Government, AI Ops data) | P0 | Arch |

---

## 1. Security

| ID | Item | Pri | Status note |
|----|------|-----|-------------|
| S1 | Production `SECRET_KEY` set (not default) | P0 | |
| S2 | Production `API_HASH_KEY` set | P0 | |
| S3 | JWT expiry appropriate for deployment threat model | P1 | Default ~30d — tighten for prod |
| S4 | `CORS_ORIGINS` set to exact frontends; `CORS_ALLOW_ALL` **false** | P0 | |
| S5 | Workspace isolation verified (A cannot read B) | P0 | Tests: workspace + AI Ops |
| S6 | Pipeline / Monitoring / AI Ops require auth | P0 | |
| S7 | Secret refs only in workspace ERP/adapter config (`vault:`/`env:`) | P0 | |
| S8 | Runtime secret resolver wired for ERP + Government (no plaintext in config) | P0 | **Gap until Task 10.5 complete** |
| S9 | TLS verify on outbound ERP/Government connectors | P0 | Confirm in staging |
| S10 | Certificate private keys never logged | P0 | |
| S11 | SQL injection controls on adaptive query remain enabled | P0 | Existing guardrails |
| S12 | AI Ops does not query invoice tables / does not join pipeline | P0 | Contract + tests |
| S13 | Prompt-injection: ops AI is rule-based; global LLM paths stay admin-controlled | P1 | |
| S14 | API input validation (Pydantic) on new endpoints | P0 | |
| S15 | Rate limiting at edge (WAF/API gateway) or app | P1 | **App-level absent — use edge** |
| S16 | Dependency vulnerability scan (`pip-audit` / `npm audit`) clean or waived | P0 | |
| S17 | Audit logging for AI Ops + pipeline correlation IDs enabled in log drain | P1 | |

---

## 2. Database & migrations

| ID | Item | Pri |
|----|------|-----|
| D1 | `phase2_workspace_tables.sql` applied | P0 |
| D2 | `phase6_erp_outbox.sql` applied | P0 |
| D3 | `phase8_monitoring_tables.sql` applied | P0 |
| D4 | Backup / PITR enabled on PostgreSQL | P0 |
| D5 | Connection pool sized for worker count | P1 |
| D6 | Indexes verified (customer_id, correlation_id, idempotency_key) | P0 |

---

## 3. Configuration & feature flags

| ID | Item | Pri |
|----|------|-----|
| C1 | `DATABASE_URL` production DSN | P0 |
| C2 | `ENABLE_PIPELINE_API=false` until pilot workspace ready | P0 |
| C3 | Pilot workspace: `pipeline_enabled=true` only after dry-run | P0 |
| C4 | `ENABLE_MONITORING_API` / `ENABLE_AI_OPS_API` set deliberately | P1 |
| C5 | ERP/Government endpoint refs point to sandbox first | P0 |
| C6 | `API_DEBUG=false` in production | P0 |

---

## 4. Reliability

| ID | Item | Pri |
|----|------|-----|
| R1 | ERP outbox uniqueness verified in staging | P0 |
| R2 | Government idempotency key behavior verified | P1 |
| R3 | Pipeline ERP transport retries observed under fault injection | P1 |
| R4 | Timeouts (30s ERP/Gov) acceptable for customer SLAs | P1 |
| R5 | Circuit breakers at edge or future connector work — risk accepted or mitigated | P1 | **Not in app** |
| R6 | DLQ / failed-job strategy documented (manual replay via outbox/monitoring) | P1 | **No durable pipeline DLQ yet** |
| R7 | Rollback plan rehearsed (flags + migration reverse notes) | P0 |
| R8 | Multi-instance: in-memory V1 status_tracker limitation acknowledged | P0 | Scale SAT carefully |

---

## 5. Performance

| ID | Item | Pri |
|----|------|-----|
| P1 | Staging load smoke: pipeline dry-run latency baseline recorded | P1 |
| P2 | Monitoring write path does not fail pipeline on DB blip | P0 | Soft-fail sinks |
| P3 | DB pool / worker count match expected concurrency | P1 |
| P4 | No synchronous LLM inside invoice pipeline | P0 | Architecture invariant |

---

## 6. Testing (must pass before go-live)

| ID | Suite | Pri |
|----|-------|-----|
| T1 | `app/tests` enterprise suite (workspace, adapters, pipeline, ERP, gov, monitoring, AI Ops) | P0 |
| T2 | MX CFDI adapter parity | P0 |
| T3 | Workspace isolation + AI Ops isolation | P0 |
| T4 | Adaptive query guardrails (existing `tests/`) | P1 |
| T5 | Staging integration: SAT upload + SAP path (Mexico pilot) | P0 |
| T6 | Staging integration: pipeline dry-run for pilot workspace | P0 |
| T7 | Dependency scans | P0 |

---

## 7. Operations

| ID | Item | Pri |
|----|------|-----|
| O1 | Deployment guide followed | P0 |
| O2 | Rollback guide available on-call | P0 |
| O3 | Migration guide executed and recorded | P0 |
| O4 | Configuration guide applied per env | P0 |
| O5 | Monitoring guide — dashboards/alerts subscribed | P0 |
| O6 | Runbooks for pipeline failure / gov down / ERP down | P0 |
| O7 | On-call roster + escalation | P0 |
| O8 | Log aggregation + correlation_id search | P1 |

---

## 8. Pilot scope (recommended first production)

| ID | Item | Pri |
|----|------|-----|
| L1 | Single pilot customer workspace | P0 |
| L2 | Mexico SAT path remains primary (unchanged) | P0 |
| L3 | New pipeline API opt-in only | P0 |
| L4 | Sample GST adapter **not** customer-facing in prod | P0 |
| L5 | AI Ops read-only; no automated remediations | P0 |

---

## 9. Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Engineering Lead | | | |
| Security | | | |
| DevOps | | | |
| Product / Customer Success | | | |

**Gate result:** ☐ GO (full) · ☐ CONDITIONAL GO (pilot) · ☐ NO-GO

**Conditions (if conditional):** _______________________________________________

---

## Quick flag reference

| Variable | Safe prod default |
|----------|-------------------|
| `ENABLE_PIPELINE_API` | `false` until pilot |
| `ENABLE_MONITORING_API` | `true` |
| `ENABLE_AI_OPS_API` | `true` (read-only ops) |
| `CORS_ALLOW_ALL` | `false` |
| `API_DEBUG` | `false` |
| Workspace `pipeline_enabled` | `false` except pilot |
