# PHASE 2 REVIEW — Customer Workspace

**Document type:** Enterprise architecture validation (pre–Phase 3 gate)  
**Status:** **READY FOR APPROVAL** (with documented residual risks)  
**Date:** 2026-08-01  
**Companion logs:** [`PHASE_2.md`](PHASE_2.md) · [`IMPLEMENTATION_TASKS.md`](../IMPLEMENTATION_TASKS.md) Phase 2  

**Do not start Phase 3 until this review is approved.**

---

## Executive verdict

Phase 2 now provides a **solid, additive foundation** for multi-customer workspaces with:

- N customers  
- N ERP connections per customer (`connection_key`)  
- N country adapters per customer (`country_code`)  
- Secret **references only** (plaintext rejected)  
- Authorization + IDOR-hardened 404 for non-admins  
- Paginated workspace listing  
- Extension points for adapters, ERP, government, AI scope, monitoring  

Production invoice / SAT / AI / dashboard / auth pipelines were **not rewritten**. Only minimal mounts/nav/append changes exist.

**Approval status:** Pending stakeholder sign-off — technical gate **PASS** after hardening below.

---

## 1. Architecture review

### What Phase 2 delivers

```text
Customer (existing)
  └── WorkspaceSettings (1:1, optional until enabled)
        ├── WorkspaceErpConnection (1:N via connection_key)
        └── WorkspaceAdapterConfig (1:N via country_code)
```

`workspace_id == customer_id` seeds from existing `zodiac_customers` — no dual identity system.

### Patterns used

| Pattern | Where |
|---------|--------|
| Composition | UI reuses customer invoice/SAT tabs |
| DI / guards | `require_workspace_access`, `resolve_workspace` |
| Strategy-ready | Adapter rows keyed by `country_code` (Phase 3 registry will resolve) |
| Config-driven | Flags: `pipeline_enabled`, `ai_scoped`, `monitoring_enabled` |

### Independence

| Surface | Relationship to Workspace UI |
|---------|------------------------------|
| Admin portal | Unchanged; Workspaces is additive nav |
| Customer portal (`/customer-*`) | Unchanged; workspace composes same APIs |
| SAT / Dashboard / AI pages | Untouched routes |

---

## 2. Database review

### `workspace_settings`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Feature flags + display for one customer workspace |
| **Relationships** | 1:1 with `zodiac_customers.customer_id` |
| **FK** | `customer_id → zodiac_customers(customer_id) ON DELETE CASCADE` |
| **Uniqueness** | `UNIQUE(customer_id)` |
| **Indexes** | PK `id`; unique/index on `customer_id` |
| **Scalability** | O(customers) rows — fine to 10k+ |

**Supports:** 1 or many customers. One settings row per customer.

### `workspace_erp_connections`

| Aspect | Detail |
|--------|--------|
| **Purpose** | ERP endpoint + auth **refs** per workspace |
| **Relationships** | N:1 customer |
| **FK** | `customer_id → zodiac_customers(customer_id) ON DELETE CASCADE` |
| **Uniqueness** | `UNIQUE(customer_id, connection_key)` — **multi-ERP** |
| **Indexes** | `customer_id`, `connection_key` |
| **Scalability** | Small N per customer (primary, billing, …) |

**Supports:** one ERP (`connection_key=primary`) **or** multiple ERP connections without redesign.

**Hardening done in this review:** replaced earlier 1:1 unique-on-`customer_id` with `(customer_id, connection_key)`.

### `workspace_adapter_config`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Per-country adapter enablement + gov endpoint/auth refs |
| **Relationships** | N:1 customer |
| **FK** | `customer_id → zodiac_customers(customer_id) ON DELETE CASCADE` |
| **Uniqueness** | `UNIQUE(customer_id, country_code)` |
| **Indexes** | `customer_id`, `country_code`, `(customer_id, enabled)` |
| **Scalability** | ~1–20 adapters per customer typical |

**Supports:** Mexico + future countries (`india`, `germany`, `uae`, …) without schema redesign.

**Hardening done:** added `auth_type`, `auth_secret_ref` for government connector readiness.

### Migration / rollback

- DDL: `app/migrations/phase2_workspace_tables.sql` (expand-only + DO blocks for upgrades)  
- Rollback: `DROP TABLE` the three workspace tables only — **never** touches invoice/SAT tables  

---

## 3. Customer isolation review

| Asset | Enforcement point |
|-------|-------------------|
| Workspace config / ERP / adapters | `require_workspace_access` on every `/{customer_id}/*` mutating+read route; queries always `filter(customer_id=…)` |
| Activity / monitoring counts | `workspace_activity` filters V2 by `invoice_data.customer_id` and SAT via **that customer’s** RFCs only |
| List API | Customer users: `UserCustomer` assignment only; admins see all |
| Cross-customer probe | Non-admin denied access → **HTTP 404** (hides existence) |
| Invoices (composed UI) | Existing `*ForCustomerUser` APIs (assignment-scoped) — unchanged |
| AI | Flag `ai_scoped` + `assert_ai_workspace_scope()` extension point — **runtime SQL guard is Phase 9** (flag ready) |
| Dashboard global | Untouched — workspace does not open global AI/dashboard to customer users |

**Cannot access each other’s ERP/adapters/config:** yes, at API guard + query filter.  
**AI runtime isolation:** prepared, not fully wired into adaptive_query yet (by design — Phase 9).

---

## 4. API review

Auth for all: JWT via `get_current_user`.

| Endpoint | Purpose | AuthZ | Validation | Returns | Future | Rate limit |
|----------|---------|-------|------------|---------|--------|------------|
| `GET /workspace` | List visible workspaces | Admin all / customer assigned | `skip`/`limit` | Paginated list | Add search | Recommend 60/min |
| `POST /workspace` | Create settings | Admin | Customer must exist; no dup | Settings | Idempotent upsert optional | 10/min |
| `GET /workspace/{id}` | Summary | Membership | Path id | Settings+erps+adapters | Add health | 120/min |
| `PATCH …/settings` | Update flags | Admin + membership | Partial body | Settings | Feature flags JSON | 30/min |
| `PUT …/erp` | Upsert ERP by key | Admin + membership | Secret-ref validators | ERP row | N connections | 30/min |
| `GET …/erp` | List ERPs | Membership | — | ERP[] | — | 120/min |
| `GET …/erp/{key}` | Get one ERP | Membership | — | ERP\|null | — | 120/min |
| `PUT …/adapters` | Upsert country adapter | Admin + membership | country normalize; refs | Adapter | Gov auth fields | 30/min |
| `GET …/adapters` | List adapters | Membership | — | Adapter[] | — | 120/min |
| `GET …/access-check` | UI probe | Any authed | Does not leak ids if denied | `{allowed}` | — | 120/min |
| `GET …/activity` | Scoped counts | Membership | — | Counts for **this** id only | Feed monitoring | 60/min |

**Rate limiting:** not implemented platform-wide yet — **recommended** at gateway/API middleware before go-live; not a Phase 2 blocker for scaffolding.

**Compatibility:** Additive paths under `/api/v1/workspace`; no replacement of `/customers` or invoice routes.

---

## 5. UI review

| Check | Result |
|-------|--------|
| Independent routes under `/workspace` | Yes |
| Does not replace admin / customer / SAT / dashboard / AI pages | Yes |
| Composition | Customer users: `CustomerInvoicesDocumentsTab`, `CustomerSATDocumentsTab`; Admin: deep-links + activity |
| Duplication of pipeline logic | None |
| Nav flag | `NEXT_PUBLIC_WORKSPACE_UI=false` hides link |

---

## 6. Security review

| Control | Status |
|---------|--------|
| No plaintext secrets in DB fields | **Enforced** — Pydantic rejects non-`vault:`/`env:`/`secret:`/`arn:`/`kms:`/`ref:` |
| Customer data leakage via workspace APIs | Mitigated by membership + scoped queries + 404 hide |
| Permissions | Admin for writes; membership for reads |
| Guessable `customer_id` | Business key by design; **authorization** is the control; non-admin gets 404 on probe |
| HTTPS government URL allowed | Yes (non-secret); auth still ref-only |

**Residual:** Gateway rate limits; Phase 9 must enforce AI SQL tenancy when `ai_scoped=true`.

---

## 7. Scalability review

| Scale | Assessment |
|-------|------------|
| 100 customers | Comfortable |
| 1,000 customers | Paginated list + indexed FKs — OK |
| 10,000 customers | OK if list stays paginated; avoid loading all adapters globally (fixed: filter by page `cids`) |

**Future bottlenecks**

| Bottleneck | Mitigation |
|------------|------------|
| Admin list without search | Add `search=` query (Phase 2.x polish) |
| Activity count on huge SAT tables | Materialized counters / Phase 8 timeline |
| Many ERP keys | Already keyed; no redesign |
| In-process BackgroundTasks | Unrelated to workspace tables — Phase 10 outbox |

---

## 8. Integration readiness for later phases

| Later phase | Phase 2 provides | Gap |
|-------------|------------------|-----|
| **3 Adapter Framework** | `workspace_adapter_config` + country codes | Registry/protocol code (Phase 3) |
| **4 Pipeline** | `pipeline_enabled` flag | Orchestrator (Phase 4) |
| **5 New country** | N adapters / customer | Specs + package |
| **6 ERP connector** | Multi ERP refs + callback_url | Connector service |
| **7 Government** | `endpoint_url_ref`, `auth_secret_ref` | Connector impl |
| **8 Monitoring** | `monitoring_enabled` + `/activity` | Event/outbox tables |
| **9 AI** | `ai_scoped` + `assert_ai_workspace_scope` | Wire into adaptive_query |

**Nothing blocking Phase 3** after approval.

---

## 9. Regression review — production files modified

| File | Why required | Risk |
|------|--------------|------|
| `zodiac-api/app/server.py` | `include_router(workspace_router)` only | Low |
| `zodiac-api/app/database.py` | Register workspace models in `init_models()` | Low |
| `zodiac-front/src/components/Sidebar.tsx` | Additive Workspaces nav (flaggable) | Low |
| `zodiac-front/src/lib/api.ts` | Append `workspaceApi` only | Low |

### Verified untouched (no intentional edits)

Invoices V1/V2 routers & services · SAT/SAP services · Dashboard · Adaptive query · Auth · Customer portal pages · Peppol/delivery stub.

---

## 10. Testing

### Executed (2026-08-01)

```text
python -m unittest app.tests.test_workspace_access app.tests.test_workspace_isolation -v
Ran 15 tests in 0.307s
OK
```

Coverage includes:

- Secret-ref accept/reject  
- Customer A ↛ Customer B  
- 404 hide-existence  
- AI scope guard  
- Multi-ERP key normalization  
- Filter helpers  

### Pending in each environment (ops)

| Test | How |
|------|-----|
| Migration validation | Apply `phase2_workspace_tables.sql`; `\d workspace_*` |
| Rollback validation | Drop three tables in a **dev** DB; confirm invoices/SAT intact |
| Live API authz | Two customer users; cross GET `/workspace/{other}` → 404 |
| UI smoke | `/workspace` list → enable → settings save with `vault:` refs |

---

## 11. Performance review

| Item | Notes |
|------|-------|
| List query | Paginated; settings/adapters loaded **only for page customer_ids** |
| Activity | Count queries scoped — acceptable for MVP; optimize in Phase 8 |
| No N+1 on summary | Single customer load of erps+adapters |

---

## 12. Remaining issues / recommended improvements

| Priority | Item | When |
|----------|------|------|
| P1 | Apply SQL migration in staging/prod | Before any workspace write usage |
| P1 | Gateway rate limits on `/api/v1/workspace*` | Before external customer exposure |
| P2 | Optional opaque UUID alias for URLs | Nice-to-have; authZ already required |
| P2 | Search on workspace list | 1k+ customers UX |
| P2 | Wire `assert_ai_workspace_scope` into adaptive query | Phase 9 |
| P3 | Single-assignment hard filter inside composed customer tabs when user has multiple customers | Polish |

---

## 13. Approval status

| Gate | Result |
|------|--------|
| Multi-customer / multi-country / multi-ERP schema | **PASS** (after hardening) |
| Isolation model | **PASS** (API); AI runtime deferred to Phase 9 intentionally |
| Additive / no production pipeline rewrite | **PASS** |
| Tests (unit/isolation) | **PASS** (15/15) |
| Live migration in all envs | **PENDING ops** |
| **Phase 3 start** | **BLOCKED until explicit approval** |

**Recommendation:** Approve Phase 2 for merge/staging after migration applied; then authorize Phase 3 (Country Adapter Framework — façade only).

---

*Document: `implementation_logs/PHASE_2_REVIEW.md`*
