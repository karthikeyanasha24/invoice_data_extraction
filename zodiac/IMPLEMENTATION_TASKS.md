# BridgeEDI — Implementation Tasks

**Companion to:** `IMPLEMENTATION_ROADMAP.md`  
**Rule:** No production code changes until this plan is reviewed and approved.  
**Style:** Prefer **new files**; existing APIs/services/tables stay; additive only.

---

## How to read this plan

Each task includes:

| Field | Meaning |
|-------|---------|
| **Purpose** | Why the task exists |
| **Files** | Touch list (new vs frozen) |
| **Dependencies** | What must be done first |
| **Estimated effort** | Engineering calendar estimate |
| **Regression risk** | Impact if done wrong |
| **Priority** | P0 blocker / P1 must / P2 should / P3 later |

**Regression risk scale:** None · Low · Medium · High · Critical  

---

# Phase 0 — Discovery Freeze & Inventory

### Task 0.1 — Confirm current invoice pipelines (read-only)

| | |
|--|--|
| **Purpose** | Lock shared understanding of V1, V2, SAT paths before any coding |
| **Files** | Read only: `api/invoices.py`, `api/invoices_v2.py`, `api/sat*.py`, `services/process_service.py`, `format_router.py`, `sat_processor.py`, `server.py` |
| **Dependencies** | None |
| **Estimated effort** | 1–2 days |
| **Regression risk** | None |
| **Priority** | P0 |

**Expected outcome:** Written inventory (can live in roadmap) listing entry URLs, services, outbound systems.

---

### Task 0.2 — Map MX/CFDI as de facto Adapter #1

| | |
|--|--|
| **Purpose** | Identify mapping/validation/rules/format/endpoint boundaries for façade |
| **Files** | Read only: `sat_processor.py`, merge services, `sap_transformer.py`, `sap_api_client.py`, `cfdi_parser.py`, SAT models |
| **Dependencies** | 0.1 |
| **Estimated effort** | 1–2 days |
| **Regression risk** | None |
| **Priority** | P0 |

**Expected outcome:** Hook → existing function map for `MxCfdiAdapter`.

---

### Task 0.3 — Collect external integration inputs

| | |
|--|--|
| **Purpose** | Unblock future country + ERP work |
| **Files** | Docs only (checklist) |
| **Dependencies** | Meeting / client |
| **Estimated effort** | Ongoing until samples arrive |
| **Regression risk** | None |
| **Priority** | P0 |

**Required inputs:** country code, government OpenAPI/auth, 3–4 document schemas, ERP confirmation API, sync vs webhook.

**Expected outcome:** Signed input pack; Phase 5 coding gated on this.

---

### Task 0.4 — Frozen surface checklist

| | |
|--|--|
| **Purpose** | Prevent accidental edits to production routers/services |
| **Files** | Docs: list in roadmap “Must Remain Untouched” |
| **Dependencies** | 0.1 |
| **Estimated effort** | 0.5 day |
| **Regression risk** | None |
| **Priority** | P0 |

**Expected outcome:** PR checklist / CODEOWNERS-style review rule for frozen paths.

---

# Phase 1 — Understand & Document Current Pipeline (Engineering Onboarding)

### Task 1.1 — End-to-end MX smoke (staging)

| | |
|--|--|
| **Purpose** | Baseline behavior before façade |
| **Files** | No code — run intake → merge → send-to-SAP on staging; capture fixtures |
| **Dependencies** | 0.2 |
| **Estimated effort** | 1–2 days |
| **Regression risk** | None (read/execute only) |
| **Priority** | P0 |

**Expected outcome:** Golden CFDI fixtures + expected SAP payload/response snapshots.

---

### Task 1.2 — End-to-end V1 / V2 smoke

| | |
|--|--|
| **Purpose** | Ensure later work never silently breaks EDI/V2 |
| **Files** | No production edits — test scripts under `tests/` or `zodiac/scripts/` (new) |
| **Dependencies** | 0.1 |
| **Estimated effort** | 1 day |
| **Regression risk** | None |
| **Priority** | P1 |

**Expected outcome:** Smoke checklist + optional automated smoke tests (new files).

---

# Phase 2 — Create Customer Workspace (Additive)

### Task 2.1 — Workspace data model (new tables)

| | |
|--|--|
| **Purpose** | Persist workspace settings without altering SAT/V1/V2 schemas |
| **Files** | **New:** `app/models/workspace.py` (or split), migration SQL/Alembic; **Avoid** changing existing model columns |
| **Dependencies** | Phase 0 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Low (expand-only migration) |
| **Priority** | P0 |

**Tables (indicative):** `workspace_settings`, `workspace_erp_connections`, `workspace_adapter_config` keyed by `customer_id`.

---

### Task 2.2 — Workspace context & guards (new core)

| | |
|--|--|
| **Purpose** | Resolve workspace from auth + customer membership; filter helpers |
| **Files** | **New:** `app/core/workspace/context.py`, `guards.py` |
| **Dependencies** | 2.1 |
| **Estimated effort** | 2 days |
| **Regression risk** | None until wired |
| **Priority** | P0 |

---

### Task 2.3 — Workspace API router (new)

| | |
|--|--|
| **Purpose** | CRUD/read workspace config; list enabled adapters; membership check |
| **Files** | **New:** `app/api/workspace.py`, `app/schemas/workspace.py`; **Tiny extension:** `server.py` `include_router` only |
| **Dependencies** | 2.1, 2.2 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Low (new routes) |
| **Priority** | P0 |

---

### Task 2.4 — Workspace portal shell (frontend, new routes)

| | |
|--|--|
| **Purpose** | Exclusive customer space in UI without removing admin/`customer-*` |
| **Files** | **New:** `src/app/workspace/[customerId]/**`, `components/workspace/**`, `lib/workspaceApi.ts`; **Optional tiny:** Sidebar link behind flag |
| **Dependencies** | 2.3 |
| **Estimated effort** | 3–5 days |
| **Regression risk** | Low–Medium (nav only if Sidebar touched) |
| **Priority** | P0 |

**Expected outcome:** Demo-able isolated workspace UI for one customer.

---

### Task 2.5 — Scope existing lists to workspace (compose, don’t fork forever)

| | |
|--|--|
| **Purpose** | Show that customer’s invoices/SAT/history inside workspace |
| **Files** | Prefer calling existing `*ForCustomerUser` / filtered APIs from **new** workspace pages; avoid rewriting `InvoicesV2` internals |
| **Dependencies** | 2.4 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Low if composition-only |
| **Priority** | P1 |

---

# Phase 3 — Extract CFDI into Adapter #1 (Façade First)

### Task 3.1 — Define CountryAdapter protocol

| | |
|--|--|
| **Purpose** | Stable contract for all countries |
| **Files** | **New:** `app/adapters/base.py` (Protocol/ABC + context types) |
| **Dependencies** | 0.2 |
| **Estimated effort** | 1 day |
| **Regression risk** | None |
| **Priority** | P0 |

---

### Task 3.2 — Implement MxCfdiAdapter façade

| | |
|--|--|
| **Purpose** | Adapter #1 delegates to existing SAT/SAP services — **no logic rewrite** |
| **Files** | **New:** `app/adapters/mx_cfdi/adapter.py`, `config.py`; **Import only** existing services (do not move files yet) |
| **Dependencies** | 3.1, 1.1 |
| **Estimated effort** | 3–4 days |
| **Regression risk** | Low if unused by production routes initially; Medium once pipeline calls it |
| **Priority** | P0 |

**Expected outcome:** Unit tests prove façade outputs match direct service calls on golden fixtures.

---

### Task 3.3 — Do **not** relocate `sat_*` packages yet

| | |
|--|--|
| **Purpose** | Avoid high-regression physical move |
| **Files** | None — explicit non-task / hold |
| **Dependencies** | 3.2 soak |
| **Estimated effort** | 0 (deferred) |
| **Regression risk** | Critical if done early — **forbidden until Phase 10 + sign-off** |
| **Priority** | P3 (optional later) |

---

# Phase 4 — Create Generic Adapter Interface + Registry + Core Pipeline

### Task 4.1 — Adapter registry (Strategy + DI)

| | |
|--|--|
| **Purpose** | Resolve `country_code` → adapter instance |
| **Files** | **New:** `app/adapters/registry.py` |
| **Dependencies** | 3.1, 3.2 |
| **Estimated effort** | 1 day |
| **Regression risk** | None |
| **Priority** | P0 |

---

### Task 4.2 — Core pipeline orchestrator

| | |
|--|--|
| **Purpose** | Shared flow: auth → workspace → adapter hooks → audit → (notify) |
| **Files** | **New:** `app/core/pipeline/orchestrator.py`, event/audit helpers |
| **Dependencies** | 2.2, 4.1 |
| **Estimated effort** | 3–5 days |
| **Regression risk** | None until exposed |
| **Priority** | P0 |

---

### Task 4.3 — Opt-in pipeline API

| | |
|--|--|
| **Purpose** | New entry for workspace transactions without replacing `/sat/*` |
| **Files** | **New** routes under `api/workspace.py` or `api/pipeline.py`; feature flag |
| **Dependencies** | 4.2, 2.3 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Low |
| **Priority** | P1 |

**Expected outcome:** Flagged workspace can run MX via façade; default customers unchanged.

---

# Phase 5 — Implement New Country Adapter

> **Gate:** Task 0.3 inputs must be complete.

### Task 5.1 — Scaffold `adapters/<country_code>/`

| | |
|--|--|
| **Purpose** | Empty package layout: mapping, validation, rules, formatting, connector, config |
| **Files** | **New:** `app/adapters/<cc>/**` only |
| **Dependencies** | 4.1, 0.3 |
| **Estimated effort** | 1 day |
| **Regression risk** | None |
| **Priority** | P0 (when unblocked) |

---

### Task 5.2 — Country validation + mapping + rules

| | |
|--|--|
| **Purpose** | Country-specific logic only; no imports from `mx_cfdi` rules |
| **Files** | **New** under `adapters/<cc>/` |
| **Dependencies** | 5.1, document schemas |
| **Estimated effort** | 1–3 weeks (spec-bound) |
| **Regression risk** | Low to existing (isolated package) |
| **Priority** | P0 |

---

### Task 5.3 — Formatting + government connector

| | |
|--|--|
| **Purpose** | Build payloads; call government/partner HTTP API; normalize confirmation |
| **Files** | **New** connector module; workspace adapter config for URL/auth secret refs |
| **Dependencies** | 5.2, OpenAPI |
| **Estimated effort** | 1–2 weeks |
| **Regression risk** | Low to existing |
| **Priority** | P0 |

---

### Task 5.4 — Enable adapter on pilot workspace

| | |
|--|--|
| **Purpose** | Config-only enablement for one customer |
| **Files** | Workspace adapter config rows; registry registration |
| **Dependencies** | 5.3, 2.1 |
| **Estimated effort** | 1–2 days |
| **Regression risk** | Low |
| **Priority** | P0 |

---

# Phase 6 — ERP Integration (Confirmation Round-Trip)

### Task 6.1 — Generic ERP connector (Core)

| | |
|--|--|
| **Purpose** | Push confirmation back to customer ERP using per-workspace HTTP config |
| **Files** | **New:** `app/core/erp/connector.py`; **Do not** rewrite `customer_delivery_service.py` stub |
| **Dependencies** | 2.1, ERP API spec |
| **Estimated effort** | 3–5 days |
| **Regression risk** | Low (new path) |
| **Priority** | P0 |

---

### Task 6.2 — Wire confirmation → ERP after adapter `handle_confirmation`

| | |
|--|--|
| **Purpose** | Close meeting flow: Endpoint confirm → BridgeEDI → ERP |
| **Files** | Orchestrator only (+ adapter mapping helpers) |
| **Dependencies** | 6.1, 4.2, 5.3 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Medium for pilot workspace only |
| **Priority** | P0 |

---

### Task 6.3 — Idempotency & duplicate protection

| | |
|--|--|
| **Purpose** | Safe retries without double-posting to ERP |
| **Files** | **New** outbox/idempotency keys on pipeline tables |
| **Dependencies** | 6.2, Phase 7 outbox preferred |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Medium |
| **Priority** | P1 |

---

# Phase 7 — Government API Integration (Hardening of Phase 5 connector)

### Task 7.1 — Auth variants (OAuth / API key / mTLS)

| | |
|--|--|
| **Purpose** | Support client endpoint auth without hardcoding |
| **Files** | **New** shared HTTP helper in `core/` + country connector config |
| **Dependencies** | 5.3, certs reuse where mTLS |
| **Estimated effort** | 3–5 days |
| **Regression risk** | Low |
| **Priority** | P1 |

---

### Task 7.2 — Multi document-type support (3–4 types)

| | |
|--|--|
| **Purpose** | Route document type → mapping/format strategies inside **one** country adapter |
| **Files** | **New** strategy classes under `adapters/<cc>/` |
| **Dependencies** | 5.2 |
| **Estimated effort** | 3–7 days |
| **Regression risk** | Low |
| **Priority** | P0 |

---

# Phase 8 — Monitoring

### Task 8.1 — Pipeline transaction timeline (new)

| | |
|--|--|
| **Purpose** | Correlation ID, stage timestamps, failure reasons for new pipeline |
| **Files** | **New** models + API; workspace monitoring UI section |
| **Dependencies** | 4.2 |
| **Estimated effort** | 3–5 days |
| **Regression risk** | Low |
| **Priority** | P1 |

---

### Task 8.2 — Workspace-scoped dashboard views

| | |
|--|--|
| **Purpose** | Reuse Dashboard V2 metrics with forced customer/workspace filter |
| **Files** | **New** workspace monitoring page; **optional** additive query param on dashboard APIs (legacy default unchanged) |
| **Dependencies** | 2.4, 8.1 |
| **Estimated effort** | 3–4 days |
| **Regression risk** | Medium if dashboard API extended — keep optional |
| **Priority** | P1 |

---

### Task 8.3 — Alerts hooks (email/Slack) for pipeline failures

| | |
|--|--|
| **Purpose** | Ops visibility for pilot customer |
| **Files** | **New** notifier module; reuse patterns from cert monitor TODOs without breaking cert task |
| **Dependencies** | 8.1 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Low |
| **Priority** | P2 |

---

# Phase 9 — AI Integration (Workspace-Scoped)

### Task 9.1 — Workspace mode for adaptive query

| | |
|--|--|
| **Purpose** | AI analyzes **only** that workspace’s operational facts |
| **Files** | Prefer **new** wrapper endpoint or optional `workspace_id` (ignored = legacy); avoid rewriting `sap_sql_agent` core |
| **Dependencies** | 2.2 |
| **Estimated effort** | 3–5 days |
| **Regression risk** | Medium — must not break global admin AI |
| **Priority** | P1 |

---

### Task 9.2 — Feed pipeline events into AI-readable store

| | |
|--|--|
| **Purpose** | Realtime transactional analysis (“what is already there”) |
| **Files** | **New** event writers from orchestrator; optional BI projection tables |
| **Dependencies** | 8.1, 9.1 |
| **Estimated effort** | 3–5 days |
| **Regression risk** | Low |
| **Priority** | P2 |

---

### Task 9.3 — Workspace AI UI

| | |
|--|--|
| **Purpose** | Embed Intelligence experience inside workspace shell |
| **Files** | **New** workspace AI page composing existing `IntelligencePage` / chart components |
| **Dependencies** | 9.1, 2.4 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | Low |
| **Priority** | P1 |

---

# Phase 10 — Testing, Hardening & Go-Live

### Task 10.1 — Regression suite (frozen paths)

| | |
|--|--|
| **Purpose** | Prove V1, V2, SAT, dashboard, auth, customer-user routes still work |
| **Files** | **New** tests only |
| **Dependencies** | After each major phase |
| **Estimated effort** | 3–5 days initial + ongoing |
| **Regression risk** | None |
| **Priority** | P0 |

---

### Task 10.2 — Adapter contract tests + MX golden parity

| | |
|--|--|
| **Purpose** | Façade == direct SAT/SAP behavior |
| **Files** | **New** `tests/adapters/test_mx_cfdi_facade.py` |
| **Dependencies** | 3.2, 1.1 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | None |
| **Priority** | P0 |

---

### Task 10.3 — Isolation / leak tests

| | |
|--|--|
| **Purpose** | Workspace A cannot read Workspace B (API + AI) |
| **Files** | **New** security tests |
| **Dependencies** | 2.3, 9.1 |
| **Estimated effort** | 2–3 days |
| **Regression risk** | None |
| **Priority** | P0 |

---

### Task 10.4 — Durable outbox for new pipeline (scale)

| | |
|--|--|
| **Purpose** | Handle 1k–10k smoothly without relying on in-memory V1 tracker |
| **Files** | **New** `core/pipeline/outbox.py`, worker entrypoint; **do not** remove `status_tracker` |
| **Dependencies** | 4.2; infra choice (Redis/SQS/Service Bus) |
| **Estimated effort** | 1–2 weeks |
| **Regression risk** | Medium for new path only |
| **Priority** | P1 |

---

### Task 10.5 — Secrets & TLS hardening (dedicated)

| | |
|--|--|
| **Purpose** | Env/vault for outbound creds; TLS verify on **new** connectors; plan safe swap for SAP client config source |
| **Files** | Prefer adapter/core config first; any change to `sap_api_client.py` requires explicit review + dual-read fallback |
| **Dependencies** | Before customer prod |
| **Estimated effort** | 3–5 days |
| **Regression risk** | High if SAP client changed carelessly — use dual-read |
| **Priority** | P0 (before go-live) |

---

### Task 10.6 — Load test & runbooks

| | |
|--|--|
| **Purpose** | Prove platform adds value without delay vs direct integration |
| **Files** | **New** scripts/docs |
| **Dependencies** | 10.4, staging |
| **Estimated effort** | 3–5 days |
| **Regression risk** | None |
| **Priority** | P1 |

---

### Task 10.7 — Go-live checklist & feature flags

| | |
|--|--|
| **Purpose** | Controlled enablement; instant rollback by flag |
| **Files** | Config/flags docs; ops runbook |
| **Dependencies** | 10.1–10.6 |
| **Estimated effort** | 1–2 days |
| **Regression risk** | Low |
| **Priority** | P0 |

---

# Phase Summary (timeline guide)

| Phase | Focus | Rough duration | Production code touch |
|-------|--------|----------------|------------------------|
| 0 | Discovery | 1–2 weeks | **None** |
| 1 | Pipeline understanding + fixtures | 2–4 days | **None** (tests/scripts only) |
| 2 | Customer workspace | 2–3 weeks | Additive + tiny `server.py` / optional Sidebar |
| 3 | MX Adapter façade | 1 week | **New files only** |
| 4 | Registry + core pipeline | 1–2 weeks | New + opt-in APIs |
| 5 | New country adapter | 3–6 weeks | **New adapter package** (gated on specs) |
| 6 | ERP confirmation | 2–3 weeks | New core ERP connector |
| 7 | Gov API hardening | Overlaps 5–6 | New |
| 8 | Monitoring | 2–3 weeks | New + optional dashboard params |
| 9 | AI workspace scope | 2–3 weeks | Additive wrappers |
| 10 | Testing / hardening | 2+ weeks | Minimal, reviewed |

**Client narrative:** Phases 2–4 are platform investment (show workspace + MX-via-adapter early). Phase 5+ is the variable integration path and should approach historical ~10-day speed **once** scaffolding exists.

---

# Explicit Non-Goals (until further approval)

| Non-goal | Reason |
|----------|--------|
| Delete or replace `/api/v1/sat/*` | Breaks existing customers |
| Move all `sat_*` services into `adapters/mx_cfdi` in first release | High regression |
| Replace V1 `status_tracker` globally | Fragile; add outbox for new pipeline instead |
| Rewrite AI SQL agent | Scope with guards/wrappers |
| One mega-PR touching many production files | Violates additive strategy |

---

# Review Gate

Before any production PR:

1. [ ] `IMPLEMENTATION_ROADMAP.md` reviewed  
2. [ ] This task plan reviewed  
3. [ ] Frozen-file list acknowledged  
4. [ ] Pilot customer / sandbox identified  
5. [ ] Feature flag strategy agreed  

**Only then** open Phase 2 implementation PRs (new files first).

---

*Document: IMPLEMENTATION_TASKS.md*  
*Platform: BridgeEDI / Zodiac*  
*Status: **Historical / superseded** for v1.0 go-live — use [`FINAL_GO_LIVE_VALIDATION.md`](FINAL_GO_LIVE_VALIDATION.md), [`RELEASE_NOTES_v1.0.md`](RELEASE_NOTES_v1.0.md), and [`docs/operations/`](docs/operations/)*
