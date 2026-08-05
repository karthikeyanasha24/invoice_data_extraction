# BridgeEDI Enterprise — Release Notes v1.0

**Release:** v1.0 Enterprise Release Candidate  
**Date:** 2026-08-02  
**Verdict:** CONDITIONAL GO — single-customer pilot (see [`FINAL_GO_LIVE_VALIDATION.md`](FINAL_GO_LIVE_VALIDATION.md))  
**Related:** [`CHANGELOG.md`](CHANGELOG.md) · [`REPOSITORY_AUDIT.md`](REPOSITORY_AUDIT.md)

---

## Features

- Multi-customer **Workspace** with isolation and admin settings  
- Opt-in **Shared Invoice Pipeline** (`ENABLE_PIPELINE_API` + per-workspace flag)  
- **Country Adapter Framework** with registry bootstrap  
- **Mexico CFDI** adapter (production façade; SAT/V1/V2 unchanged)  
- **Sample GST** adapter (scaffold / non-customer-facing)  
- **ERP connector** with outbox idempotency and `erp_update_mode` policy  
- **Government connector** (HTTP + already-stamped MX path, retries, idempotency)  
- **Secret resolver** (`env:`, `vault:`, literal mode for legacy)  
- **Monitoring** timelines, events, metrics, alerts (log + optional webhook)  
- **AI Ops** operational analytics over monitoring only  
- **Onboarding readiness** API + Settings UX checklist  
- **Health / readiness** probes and startup initialization  
- Ops pack: handbooks, runbooks, deployment checklists, demo package  

---

## Architecture

Additive enterprise layer beside existing Mexico SAT / invoice engines:

```
Workspace → Pipeline (opt-in) → Country Adapter → Government
  → Confirmation → ERP → Monitoring → AI Ops
```

Legacy SAT/V1/V2 remain the primary production path when the pipeline is off.

Canonical diagrams: [`docs/architecture/`](docs/architecture/)

---

## Customer Workspace

- `workspace_id == customer_id`  
- Settings, ERP connections (multi `connection_key`), adapters  
- Access: admin all; customer users via assignments  
- UI: `/workspace` shell (overview, invoices, SAT, monitoring, AI Ops, settings)  

---

## Pipeline

- Orchestrated stages with transport retries  
- Feature-flagged API; per-workspace `pipeline_enabled`  
- Platform services DI: workspace, adapter, ERP, monitoring sinks  

---

## Adapters

- Builtin registration: `mx_cfdi`, `sample_gst` (startup + lazy)  
- Contract-based stages; no country hardcoding in core framework  

---

## ERP

- Workspace-configured HTTP connector  
- Secret refs only in config  
- Skip policy when submit already fulfilled ERP (`erp_update_mode=auto|always|never`)  

---

## Government

- Workspace endpoint + auth refs  
- Retries / idempotency headers  
- Mexico already-stamped path without inventing SAT HTTP  

---

## Monitoring

- Pipeline timelines, events, metrics, alert history  
- Soft-fail persistence preference for invoice success  
- Optional `ALERT_WEBHOOK_URL`  

---

## AI Ops

- Consumes monitoring aggregates only  
- Does not join invoice processing or query invoice/ERP tables  
- Distinct from global Adaptive Query / dashboard AI  

---

## Deployment

- Migrations: `phase2` / `phase6` / `phase8` (+ `scripts/apply_enterprise_migrations.py`)  
- Optional `AUTO_APPLY_ENTERPRISE_SCHEMA`  
- `/health`, `/health/ready`  
- Startup: adapters + config posture  
- Example env: [`zodiac-api/.env.example`](zodiac-api/.env.example)  
- Ops: [`docs/operations/`](docs/operations/)  

---

## Security

- JWT auth; workspace guards  
- Secret-ref validation (no plaintext in workspace ERP/adapter secrets)  
- CORS origin allowlist; `CORS_ALLOW_ALL` emergency only  
- AI Ops isolation tests  

---

## Known limitations

1. Dual processing worlds (legacy vs pipeline) — intentional  
2. No in-app rate limit / circuit breaker / durable pipeline DLQ  
3. Email/Slack alert channels stubbed (log + webhook OK)  
4. Customer file delivery service incomplete (non-blocking for MX pilot)  
5. `arn:`/`kms:`/`ref:` secret schemes not wired  
6. sample_gst not for production customers  
7. Live ERP/Gov sandbox proof is an **ops** gate, not a code gap  

---

## Upgrade / pilot stance

v1.0 is the **baseline** for the first customer pilot under Conditional GO.  
Complete target-host migrations, secrets hardening, and sandbox connectivity before production traffic.
