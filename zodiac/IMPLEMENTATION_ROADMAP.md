> **Superseded for v1.0 release:** Historical planning. Use [`RELEASE_NOTES_v1.0.md`](RELEASE_NOTES_v1.0.md), [`FINAL_GO_LIVE_VALIDATION.md`](FINAL_GO_LIVE_VALIDATION.md), [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md).

# BridgeEDI — Implementation Roadmap  
## Multi-Customer Workspace + Country Adapter Framework

**Document type:** Enterprise architecture roadmap (planning only — no production code changes)  
**Platform:** BridgeEDI (`zodiac/zodiac-api` + `zodiac/zodiac-front`)  
**Audience:** Engineering, delivery leads, client technical stakeholders  
**Governing constraint:** Existing customers and pipelines must keep working exactly as today  

---

## Executive Summary

BridgeEDI already runs production invoice / EDI / tax-document middleware for existing customers. The business goal is **not** a rewrite. It is to make the current platform **reusable** for:

1. **Many customers** — each with an **isolated workspace** (ERP, credentials, endpoints, config, adapters, monitoring, AI, transaction history).
2. **Many countries** — each with a **country adapter** that owns only mapping, validation, business rules, formatting, government/endpoint integration, and country configuration.
3. **One shared core** — auth, orchestration, storage, audit, retries/monitoring, notifications, portal shell, and AI analytics scoped to workspace data.

**Non-negotiable rules**

| Rule | Meaning |
|------|---------|
| Do not break | Existing V1, V2, SAT→SAP, PeppolSoft, dashboards, AI, certs continue unchanged |
| Do not replace | No swap of live routers/services for a new stack |
| Do not remove | APIs, tables, models, business logic stay |
| Prefer add | New folders and wrappers alongside existing code |
| Extract later | Mexico CFDI becomes **Adapter #1** by wrapping first; move code only when safe |

**Strategy in one line:** Introduce Core + Workspace + Adapter Framework **next to** today’s pipelines; route *new* customer/country traffic through the framework; keep *existing* traffic on current paths until explicitly migrated behind a thin façade.

---

## Existing Architecture

### High-level topology (as implemented)

```text
Clients (Admin / Customer users / ERP / Suppliers)
    │  JWT · API Key · Supplier Token · Customer Token · mTLS
    ▼
┌─────────────────────┐
│  zodiac-front       │  Next.js portal (role-split admin vs customer-*)
└──────────┬──────────┘
           │ REST
           ▼
┌─────────────────────┐
│  zodiac-api         │  FastAPI (app/server.py)
│  Auth · Invoices    │
│  V1 / V2 · SAT      │
│  Dashboard · AI     │
│  Certificates       │
└────┬───────┬────┬───┘
     │       │    │
     ▼       ▼    ▼
 PostgreSQL  Storage  Externals
 (app +      local /  · SAP billing HTTP
  SAP-shaped Blob)    · PeppolSoft DBNA
  AI tables)          · LLM providers
```

### What the shared platform already provides

| Layer | Reality today |
|-------|---------------|
| Auth | JWT, API keys, supplier/customer tokens, mTLS certificates |
| Portal | Admin ops UI + narrow customer-user routes |
| Pipelines | Three parallel paths: V1 EDI, V2 validate/convert, Mexico SAT/CFDI |
| Storage | Local `uploads/` / `converted/` or Vercel Blob in PROD |
| Monitoring | Dashboard V2 inbound/outbound/business/failed |
| AI | Adaptive NL→SQL, charts, chat threads, schema-chat |
| Customer master | `Customer`, `UserCustomer`, `target_format`, RFC allow-lists |

### What is missing (product architecture)

| Concept | Status |
|---------|--------|
| Formal `CountryAdapter` interface | **Not present** |
| Formal `Workspace` / `tenant_id` | **Not present** (isolation via `customer_id` + `user_id` + RFCs) |
| Durable job queue | **Not present** (BackgroundTasks + in-memory `status_tracker`) |
| Generic ERP confirmation push | **Partial** (SAP response stored; V2 delivery stub) |
| Live SAT.gov / PAC timbrado APIs | **Not found** |

---

## Current Invoice Pipeline

Three **independent** production paths (FACT from code). They must all remain callable.

### Path A — Legacy V1 (EDI / PeppolSoft)

| Item | Detail |
|------|--------|
| Entry | `POST /api/v1/invoices/process`, `/sap/process`, `/api/process` |
| Core | `process_service` → `format_router` → converters/validators → optional AI correction |
| Status | In-memory `status_tracker` + poll by `tracking_id` |
| DB | `zodiac_invoice_success_edi`, `zodiac_invoice_failed_edi` |
| Outbound | `external_api_service` → PeppolSoft when path needs third party |

**Formats:** XML, X12, EDIFACT, embed variants (`format_router.PROCESSING_PATHS`).

### Path B — Invoices V2

| Item | Detail |
|------|--------|
| Entry | `POST /api/v1/invoices-v2/upload`, `/sap/receive` |
| Core | Validate → correct/cache → convert (`InvoiceConversionService`) → send |
| DB | `v2_invoice_documents` → validated → `converted_invoices` |
| Outbound | `customer_delivery_service` — **stub** (“not yet configured”) |

### Path C — Mexico SAT / CFDI (de facto country implementation)

| Item | Detail |
|------|--------|
| Entry | `POST /api/v1/sat/intake`, supplier intake |
| Core | `sat_processor` → simple/canonical merge → `sap_transformer` |
| DB | `sat_documents`, merge tables, supplier account mapping |
| Outbound | `sap_api_client` / `sap_send_all` → SAP billing HTTP |

**Implication for adapters:** Path C is the **reference country vertical**. Adapter #1 wraps this path; Paths A/B stay as shared platform capabilities (format conversion / multi-format EDI), not “countries.”

---

## Existing ERP Integration

| Direction | Implementation | Notes |
|-----------|----------------|-------|
| Inbound XML from SAP | V1 `/invoices/sap/process`, V2 `/invoices-v2/sap/receive` | Multipart / process pipeline |
| Outbound billing to SAP | `SAPAPIClient.send_json_to_sap_with_session` | CSRF + session POST |
| CFDI → SAP JSON | `sap_transformer.py` | MX-specific transform + GL mapping |
| Bulk send | `sap_send_all.py` | Pending merges |
| AI over SAP-shaped tables | `sap_sql_agent`, `table_mapping/*`, adaptive query | Same Postgres `DATABASE_URL` (config); not live RFC for invoices |

**Security FACT (plan later, do not “fix in place” during framework intro):** outbound SAP credentials historically hardcoded / TLS verify issues in client — move to env/vault via **new config layer** used by adapters; leave current client behavior until a dedicated hardening task.

---

## Existing Government Integration

| Finding | Detail |
|---------|--------|
| “Government-adjacent” stack today | Mexico CFDI intake + RFC mapping + merge + post to SAP |
| Live SAT.gov / PAC / timbrado | **Not in codebase** |
| Confirmation semantics today | Practically = SAP accept/reject + portal document status |
| PeppolSoft | Partner/EDI network (V1), not a tax authority portal |

**New customer requirement (from meeting):** different HTTP/REST government endpoint, 3–4 document types, confirmation returned to BridgeEDI then pushed to customer ERP. That endpoint **is not in the repo** — it arrives as integration inputs (OpenAPI, auth, samples).

---

## Existing CFDI Adapter

Even without an interface, Mexico is already a **module-shaped** vertical:

| Adapter concern | Where it lives today |
|-----------------|----------------------|
| Mapping | `sap_transformer`, supplier/GL mapping, RFC tables |
| Validation | `CFDIParser`, `sat_processor`, receiver RFC allow-lists |
| Business rules | Simple/canonical merge, duplicates, fiscal grouping |
| Formatting | CFDI parse; SAP JSON output |
| Endpoint | `sap_api_client`, `sap_send_all` |
| Configuration | Customer RFCs, supplier account mappings, SAP URL/creds |

**Everything else** (auth, UI shell, DB engine, dashboards, AI, certificates) is shared platform and must stay shared.

**Extraction policy (safe):**

1. Phase A: Define `CountryAdapter` protocol + `MxCfdiAdapter` that **delegates** to existing services (zero behavior change).
2. Phase B: New pipeline entry uses adapter registry (new routes or opt-in flag).
3. Phase C (optional, later): Physically move modules under `adapters/mx_cfdi/` only after golden tests — **not** required to start new countries.

---

## Existing AI Integration

| Surface | Role |
|---------|------|
| `POST /api/query/adaptive` | NL analytics over DB |
| Dashboard AI (`/ai-analysis/chat`, schema-chat) | Ops / training / multi-model |
| Charts | `ai_chart_generator`, Recharts UI |
| Threads | `chat_thread_store` (`ada_*` / schema-chat) |
| Scope today | Often user-scoped; not strict workspace/tenant SQL enforcement |

**Meeting intent:** AI shows realtime analysis of **that customer’s** transaction data.  
**Roadmap approach:** Reuse adaptive pipeline; add **workspace filter middleware / SQL guard** as an additive layer for workspace-mode sessions — do not rewrite the SQL agent.

---

## Current Folder Structure

### Repository (relevant)

| Path | Role | Status |
|------|------|--------|
| `zodiac/zodiac-api/` | Production FastAPI backend | **Production — leave intact** |
| `zodiac/zodiac-front/` | Production Next.js portal | **Production — leave intact** |
| `zodiac/*.md` | Architecture / proposals | Documentation |

### `zodiac-api/app/` (production layout — do not reorganize)

| Folder | Purpose |
|--------|---------|
| `api/` | Routers: auth, invoices, V2, SAT, dashboard, certificates, customers, adaptive_query |
| `services/` | Process, SAT, SAP, AI, delivery stub, file storage, status tracker |
| `models/` | SQLAlchemy ORM |
| `schemas/` | Pydantic DTOs |
| `utils/` | Formatters, CFDI parser, crypto |
| `config/` | Env, blob, LLM |
| `middleware/` | mTLS helpers |
| `tasks/` | Cert expiration monitor (CLI) |
| `analysis/` | Metrics/charts helpers |
| `table_mapping/` | SAP column metadata for AI |

### `zodiac-front/src/` (production layout — do not reorganize)

| Area | Purpose |
|------|---------|
| `app/` | Routes: dashboard, AI, invoices-v2, sat-documents, customers, `customer-*` |
| `components/` | InvoicesV2, SAT*, Dashboard*, Intelligence/AI |
| `lib/api.ts` | Axios client |
| `contexts/AuthContext.tsx` | JWT session |

**Customer isolation today (UI):** `is_customer_user` + assigned `customer_ids` + `*ForCustomerUser` APIs — **not** a workspace product shell yet.

---

## Current Data Flow

### Mexico SAT → SAP (closest to meeting flow)

```text
Supplier/Admin CFDI upload
  → sat_processor (parse / validate / store)
  → simple or canonical merge
  → sap_transformer (CFDI → SAP JSON + GL map)
  → sap_api_client POST
  → store sap_document_number / sap_response on merge
```

**Gap vs meeting:** confirmation is stored on BridgeEDI; **generic push of confirmation into customer ERP** is not a reusable service. V2 “send to customer” is unfinished.

### V1 partner path

```text
Upload → process_invoice_internal → format_router → PeppolSoft → success/failed EDI tables
```

### Target flow (new customers / new countries)

```text
Customer ERP → BridgeEDI Core (auth · workspace · audit · retry)
  → Country Adapter (map · validate · rules · format · send)
  → Government / Partner Endpoint
  → Confirmation → Core → push ERP → monitor + AI
```

---

## Problems With Current Architecture

| Problem | Impact | Constraint on solution |
|---------|--------|------------------------|
| Country logic embedded in SAT/SAP services | Hard to add India/UAE without copy-paste risk | Wrap with adapter; don’t delete SAT APIs |
| No first-class workspace | Demo/ops data can mix with customer scenario | Add workspace **alongside** `Customer` |
| Three pipelines, no unified orchestration | New country unclear which path to extend | New core pipeline for **new** traffic only |
| In-memory status / no broker | Fragile at 1k–10k invoices multi-instance | Additive durable outbox — don’t rip V1 tracker yet |
| Delivery stub | ERP round-trip incomplete for V2 | New ERP connector service |
| Secrets mixed in code | Go-live risk | New vault/env for adapter configs |
| AI not strictly tenant-scoped | Cross-customer leak risk | Additive SQL/workspace guards |

---

## Proposed Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                     BridgeEDI Core                          │
│  Auth · Workspace context · Intake · Orchestration          │
│  Storage · Audit · Retry/Outbox · Notify · Monitor · AI     │
└────────────────────────────┬────────────────────────────────┘
                             │ resolve adapter(country_code)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Country Adapter Framework                       │
│  Protocol: parse_and_validate · apply_mappings · rules       │
│            format_outbound · send · handle_confirmation      │
│            push_to_erp (or core ERP connector)               │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  mx_cfdi     │  india       │  germany     │  uae / …       │
│  (Adapter#1) │  (new)       │  (new)       │  (new)         │
│  wraps SAT   │  own rules   │  own rules   │  own rules     │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

### Design patterns (mandatory)

| Pattern | Use |
|---------|-----|
| **Adapter** | Country-specific mapping/validation/rules/format/endpoint |
| **Strategy** | Select adapter by `country_code` + workspace enablement |
| **DI / Registry** | `AdapterRegistry` maps code → adapter instance; core depends on protocol only |
| **Façade** | `MxCfdiAdapter` calls existing SAT/SAP services — no rewrite |
| **Decorator / Guard** | Workspace scoping on queries and AI (additive) |

### Compatibility mode

| Traffic | Behavior |
|---------|----------|
| Existing SAT URLs / V1 / V2 | **Unchanged** handlers |
| New workspace pipeline API | Uses Core + Adapter registry |
| Optional later | Feature flag to run MX SAT through façade (same services) |

---

## Customer Workspace Design

### Meeting requirement

> Exclusive space for the customer to run their own transactions; not mixed with other demo/scenario data.

### Proposed model (additive)

```text
Workspace (seeded from existing Customer)
  ├── Users & roles (reuse UserCustomer + RBAC extensions)
  ├── ERP connection config (base URL, auth, callback)
  ├── Enabled country adapters [MX, IN, …]
  ├── Credentials / certificates (reuse cert model; scope by workspace)
  ├── Endpoint configs (government + ERP) — secrets in env/vault refs
  └── Transaction + audit data (scoped by workspace_id / customer_id)
```

### Isolation properties

| Concern | Design |
|---------|--------|
| Own ERP | `workspace_erp_connections` (new table) |
| Own credentials | Vault/env refs per workspace; certs already per customer |
| Own API endpoints | Config rows — adapters read config, not hardcoded URLs |
| Own adapters | `workspace_enabled_adapters` |
| Own monitoring | Dashboard filters / new workspace dashboard routes |
| Own AI | Adaptive sessions with forced `customer_id` / `workspace_id` predicate |
| Own history | Transaction/outbox tables keyed by workspace |

**Reuse seed:** Existing `Customer` + `UserCustomer` become the workspace spine. Prefer `workspace_id == customer_id` initially to avoid dual keys — or add nullable `workspace_id` that defaults to `customer_id`.

**Frontend:** New routes under `app/workspace/[customerId]/` **or** harden existing `customer-*` pages — prefer **new routes** that compose existing components to avoid breaking admin UX.

---

## Country Adapter Design

### Protocol (proposed — new module only)

Each adapter implements:

| Hook | Responsibility | MX reference (delegate to) |
|------|----------------|----------------------------|
| `parse_and_validate(payload)` | Schema + tax-id rules | `CFDIParser` + `sat_processor` |
| `apply_mappings(ctx)` | Field / GL / party mapping | supplier mapping + transformer |
| `apply_business_rules(ctx)` | Accept/reject/merge | merge services |
| `format_outbound(ctx)` | Government/ERP payload | SAP JSON |
| `send(ctx)` | Call endpoint | `SAPAPIClient` |
| `handle_confirmation(ctx)` | Normalize response | sap_response fields |
| `get_config_schema()` | Country configuration | RFCs, mappings |

`push_to_erp` may live in **Core ERP connector** (shared) with adapter providing payload mapping only — avoids duplicating HTTP retry logic.

### Adapter isolation rule (from meeting)

- Adapter **rules/mappings/formats/endpoints** are **not** shared across countries.
- Shared utilities (HTTP client, retry, audit writer, storage) stay in **Core**.
- Do **not** import `india` rules from `mx_cfdi`.

### Adapter packaging

```text
adapters/
  base.py              # Protocol / ABC + context types
  registry.py          # Strategy registration / DI
  mx_cfdi/             # Adapter #1 — thin wrappers over existing SAT/SAP
    adapter.py
    config.py
  <country_code>/      # Future — clone layout only
    mapping/
    validation/
    rules/
    formatting/
    connector/
    config.py
```

---

## Folder Structure For New Components

**Principle:** Add under new trees; do not move production folders in early phases.

### Backend (new)

```text
zodiac-api/app/
  core/                          # NEW — thin orchestration only
    __init__.py
    workspace/
      context.py                 # resolve workspace from auth + customer_id
      guards.py                  # query filter helpers
    pipeline/
      orchestrator.py            # intake → adapter hooks → audit
      outbox.py                  # durable transaction events (later phase)
    erp/
      connector.py               # generic confirmation push (new)
    adapters/                    # OR keep adapters at app/adapters — pick one root
      base.py
      registry.py

  adapters/                      # NEW — country packages
    mx_cfdi/
      adapter.py                 # façade over sat_* + sap_*
      config.py
    # india/, germany/, uae/, singapore/ — later

  api/
    workspace.py                 # NEW router — workspace CRUD / pipeline entry
    # existing routers UNTOUCHED
```

### Frontend (new)

```text
zodiac-front/src/
  app/workspace/[customerId]/   # NEW customer exclusive space
    page.tsx
    transactions/
    monitoring/
    ai/
  lib/workspaceApi.ts            # NEW client module
  components/workspace/          # NEW — compose existing tabs where possible
```

---

## Files To Be Added

| New file / package | Purpose |
|--------------------|---------|
| `app/core/**` | Workspace context, pipeline orchestrator, ERP connector interfaces |
| `app/adapters/base.py` | CountryAdapter protocol |
| `app/adapters/registry.py` | Strategy registry / DI |
| `app/adapters/mx_cfdi/adapter.py` | Adapter #1 façade |
| `app/api/workspace.py` | New workspace + pipeline APIs |
| `app/models/workspace*.py` | Workspace config / outbox / adapter enablement (additive tables) |
| `app/schemas/workspace.py` | DTOs for new APIs |
| `zodiac-front/.../workspace/**` | Customer exclusive UI shell |
| Tests: `tests/adapters/`, `tests/workspace/` | Golden path + isolation tests |
| Docs: this roadmap + `IMPLEMENTATION_TASKS.md` | Planning |

---

## Existing Files That Must Remain Untouched

Treat as **frozen production surface** unless a later reviewed task explicitly allows a one-line extension point.

### Backend routers / entry

- `app/server.py` — only additive `include_router` for new workspace router (minimal allowed extension; see next section)
- `app/api/invoices.py`, `invoices_v2.py`, `converted_invoices.py`
- `app/api/sat.py`, `sat_canonical.py`, `sat_simple_merge.py`, `sat_supplier_mapping.py`
- `app/api/dashboard.py`, `adaptive_query.py`, `auth.py`, `certificates.py`, `customers.py`

### Backend services (behavior)

- `process_service.py`, `format_router.py`, `external_api_service.py`, `status_tracker.py`
- `sat_processor.py`, merge services, `sap_transformer.py`, `sap_api_client.py`, `sap_send_all.py`
- AI stack (`sap_sql_agent.py`, orchestrators, chart generators) — no rewrite
- `customer_delivery_service.py` — leave stub; new ERP connector is separate

### Models / utils in active use

- All existing `app/models/*` tables remain
- `utils/cfdi_parser.py` and converters remain

### Frontend

- Existing admin and `customer-*` routes/components continue to work
- Prefer composing rather than editing shared tabs until workspace UI is proven

---

## Files That Require Small Extension Points

**Only when unavoidable; prefer new files.** Each extension must be reviewed, tiny, and backward compatible.

| File | Allowed extension | Forbidden |
|------|-------------------|-----------|
| `app/server.py` | `include_router(workspace_router)` | Changing existing mounts |
| `app/models/customer.py` | Optional nullable link fields **or** prefer separate workspace table keyed by `customer_id` | Renaming columns / breaking serializers |
| `app/api/customers.py` | Optional read-only fields for workspace status | Changing create/update contracts for existing clients |
| Dashboard / adaptive query | Optional `workspace_id` query param (ignored if absent = legacy behavior) | Forcing workspace for admin global views |
| `Sidebar.tsx` / nav | Add workspace link behind role/flag | Removing admin menu items |

**Rule of thumb:** If behavior can be achieved with a **new route**, do that instead of extending an old one.

---

## APIs To Reuse

| API family | Reuse how |
|------------|-----------|
| `/api/v1/sat/*` | Called internally by `MxCfdiAdapter` / remain public for existing clients |
| `/api/v1/invoices*`, `/invoices-v2/*` | Unchanged for current customers |
| `/api/v1/customers`, `/customer-users` | Seed workspace membership |
| `/api/v1/certificates/*` | Per-customer secure channels |
| `/api/v1/dashboard/*` | Filter/reuse for workspace monitoring views |
| `/api/query/adaptive` | Workspace-scoped sessions (additive params) |
| Auth (`/user/auth`) | Unchanged JWT issuance |

**New APIs (additive only):** e.g. `/api/v1/workspace/...`, `/api/v1/pipeline/...` — never replace old URLs.

---

## Services To Reuse

| Service | Role in new architecture |
|---------|--------------------------|
| `sat_processor`, merge services | MX adapter internals |
| `sap_transformer`, `sap_api_client` | MX send/format |
| `file_service` | Storage for all adapters |
| `certificate_*` | mTLS / customer channels |
| Adaptive / chart / thread store | Workspace AI |
| `format_router` / V2 conversion | Shared multi-format utilities (not country adapters) |
| Auth helpers | Workspace context resolution |

---

## Components To Reuse

| Frontend | Reuse |
|----------|-------|
| `MainLayout`, `Sidebar`, `AuthContext`, `api.ts` patterns | Shell |
| InvoicesV2 / SAT tabs | Embed inside workspace with scoped API calls |
| `IntelligencePage` / chart renderer | Workspace AI page |
| Dashboard V2 panels | Workspace monitoring with forced customer filter |

---

## Database Changes (if any)

**Principle:** Additive tables/columns only. No drops. No renames of production tables.

| Change | Type | Purpose |
|--------|------|---------|
| `workspace_settings` (or equivalent) | **New table** | ERP endpoints, enabled adapters, feature flags per `customer_id` |
| `workspace_erp_connections` | **New table** | Callback URL, auth type, secret ref |
| `workspace_adapter_config` | **New table** | Per-country config JSON / secret refs |
| `pipeline_transactions` / outbox | **New tables** | Durable status, correlation ID, retries |
| Optional `workspace_id` on new txn tables | **New** | Prefer new tables over altering SAT/V1/V2 rows initially |
| Existing SAT/V1/V2 tables | **Untouched** | Continue as today |

**Migration strategy:** Expand-only Alembic/SQL migrations; deploy with app that ignores new tables until features enabled.

---

## Security Considerations

| Topic | Action |
|-------|--------|
| Isolation | Every workspace query must filter by `customer_id` / `workspace_id`; add automated leak tests |
| Secrets | Adapter/ERP/gov credentials via env or vault refs — **not** new hardcoding |
| Existing hardcoded SAP/Peppol | Do not “drive-by rewrite”; schedule dedicated hardening task that swaps config source behind client |
| TLS | New connectors verify TLS by default; legacy client unchanged until hardening task |
| AuthZ | Workspace APIs enforce membership via `UserCustomer` / admin |
| Audit | New pipeline writes immutable event log (who/what/when/correlation_id) |
| AI | Prevent unconstrained SQL across tenants in workspace mode |

---

## Scalability

| Concern | Current | Target (additive) |
|---------|---------|-------------------|
| Status tracking | In-memory | DB outbox + correlation ID |
| Background work | BackgroundTasks / asyncio | Optional Redis/SQS/Service Bus worker — **new** path |
| Volume (1k–10k) | Risk under multi-instance | Durable queue before claiming scale |
| Horizontal scale | Sticky in-memory state | Stateless API + shared DB/queue |

**Do not** force Celery into V1 on day one; introduce durable processing for **new pipeline** first.

---

## Deployment Strategy

1. Deploy **docs + new empty packages** (no behavior change).
2. Deploy **new tables** (idle).
3. Deploy **new workspace APIs** behind feature flag / admin-only.
4. Enable **one pilot workspace** (non-production customer or sandbox).
5. Register **MxCfdiAdapter** façade (existing SAT still direct).
6. Add **new country adapter** when API specs arrive.
7. Only after soak: optional flag to prefer façade for MX — still calling same services.

Rollback = disable feature flag / stop routing to new APIs; old paths untouched.

---

## Backward Compatibility Strategy

| Guarantee | How |
|-----------|-----|
| Same URLs | Existing routers remain mounted |
| Same payloads | No breaking schema changes on old DTOs |
| Same DB rows | No destructive migrations |
| Same UI for admins | New workspace UI additive |
| Same MX behavior | Façade delegates 1:1 to current services |
| Feature flags | New pipeline off by default |

**Compatibility tests:** Snapshot/golden CFDI → SAP fixtures; V1 process smoke; V2 upload smoke; adaptive query smoke; customer-user route smoke.

---

## Migration Strategy

```text
Phase M0  Document + interfaces (this roadmap)
Phase M1  Workspace tables + APIs (idle for existing traffic)
Phase M2  MxCfdiAdapter façade (delegate only)
Phase M3  Pilot workspace UI using existing SAT/V2 data scoped
Phase M4  Durable outbox for NEW pipeline only
Phase M5  New country adapter (gov API) + ERP push
Phase M6  Optional: dual-run MX via façade; never delete SAT routers
Phase M7  Hardening (secrets, TLS, load test)
```

**Non-goal:** Big-bang move of `sat_*` files into `adapters/mx_cfdi/` before golden tests and customer sign-off.

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Rewriting MX instead of wrapping | High | Façade-first policy; code review gate |
| Cross-customer data exposure | Critical | Isolation tests; AI SQL guards |
| Timeline inflation vs ~10-day direct integrations | Medium | Platform investment once; new country = adapter + config |
| Spec unknown for new government API | High | Block country adapter coding until OpenAPI/samples |
| Touching too many production files | High | “New file first” rule |
| In-memory queues under load | High | Outbox before volume claims |
| Secrets / SSL issues | Critical | Dedicated hardening phase |
| Confusing V1/V2 with “country adapters” | Medium | Document: formats ≠ countries; MX is Adapter #1 |

---

## Step-by-Step Implementation Plan

### Step 0 — Freeze understanding (docs only) ✅ this document + tasks

- Confirm three pipelines and MX as reference adapter.
- List frozen files vs additive targets.
- Collect missing inputs (country, gov API, ERP callbacks, document types).

### Step 1 — Core scaffolding (new folders only)

- Add `app/core/` and `app/adapters/` with protocols + empty registry.
- No calls from `server.py` yet (or mount health-only stub).

### Step 2 — Customer workspace MVP (additive)

- New tables + `/api/v1/workspace/*`.
- Portal shell for one customer; data scoped via existing filters + new guards.
- Demo: “exclusive space” without changing SAT send behavior.

### Step 3 — Adapter #1 façade (MX)

- `MxCfdiAdapter` delegates to existing SAT/SAP services.
- Registry resolves `mx` / `mx_cfdi`.
- Existing `/api/v1/sat/*` still primary for current clients.

### Step 4 — New pipeline entry (opt-in)

- Core orchestrator invokes adapter hooks for **flagged** workspaces only.
- Correlation ID + audit events on new tables.

### Step 5 — Durable processing (new path)

- Outbox/retry for new pipeline; leave V1 `status_tracker` as-is.

### Step 6 — New country adapter

- Clone adapter package layout; implement mapping/validation/rules/format/connector from client specs.
- No reuse of MX business rules.

### Step 7 — ERP confirmation round-trip

- Core ERP connector + per-workspace config; replace need for V2 stub for **new** flow (stub file remains).

### Step 8 — Workspace monitoring + AI

- Scoped dashboards + adaptive workspace mode.

### Step 9 — Hardening & go-live

- Secrets, TLS, load test, runbooks; still no removal of legacy APIs.

---

## Inputs Still Required (blocked for Phase 5+)

1. Target **country** code and government OpenAPI / auth / callbacks  
2. **3–4 document type** schemas and samples  
3. Customer **ERP** submit + confirmation update APIs  
4. Latency / SLA expectations vs direct integration  
5. Sync confirmation vs async webhook  
6. Whether PeppolSoft remains in scope for the new customer  

---

## Success Criteria

1. Existing customers’ V1 / V2 / SAT→SAP / AI / dashboards behave as today.  
2. New customer can use an **isolated workspace**.  
3. Mexico is usable as **Adapter #1** (façade) without rewriting SAT.  
4. A new country can be added primarily as `adapters/<cc>/` + config.  
5. Demonstrable flow: **ERP → BridgeEDI → Endpoint → Confirmation → ERP**.  
6. Monitoring + AI show **that workspace’s** data.  
7. Volume path does not rely solely on single-process memory for the **new** pipeline.

---

## Closing

The repository already contains a working middleware — especially a complete **Mexico CFDI → SAP** vertical and shared portal/AI/security. The multi-country, multi-customer program must **formalize Mexico as Adapter #1 by wrapping**, **add Customer Workspaces beside existing Customer isolation**, and **plug future countries into Core** without deleting or replacing production paths.

**Next artifact:** `IMPLEMENTATION_TASKS.md` (phased engineering tasks).  
**Code generation:** blocked until roadmap + tasks are reviewed and approved.

---

*Document: IMPLEMENTATION_ROADMAP.md*  
*Platform: BridgeEDI / Zodiac*  
*Status: Planning only — no production code modified*
