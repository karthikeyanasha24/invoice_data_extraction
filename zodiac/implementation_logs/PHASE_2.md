# Phase 2 — Customer Workspace

**Status:** Implemented — awaiting review before Phase 3  
**Date:** 2026-08-01  
**Source of truth:** `IMPLEMENTATION_TASKS.md` Phase 2 · `docs/architecture/03_CUSTOMER_ONBOARDING.md`

---

## Review hardening (same phase, pre–Phase 3)

After enterprise review, Phase 2 was strengthened **before** Phase 3:

- Multi-ERP: `UNIQUE(customer_id, connection_key)`
- FKs to `zodiac_customers.customer_id`
- `monitoring_enabled`, adapter `auth_secret_ref` / `auth_type`
- Paginated list; scoped settings/adapter queries
- Secret-ref validation (reject plaintext)
- Non-admin unauthorized → HTTP 404 (hide existence)
- `assert_ai_workspace_scope` extension point
- Isolation unit tests (15 passing)

See [`PHASE_2_REVIEW.md`](PHASE_2_REVIEW.md) for full gate review.

---

## What was implemented

Additive Customer Workspace spine:

1. **Data model** — `workspace_settings`, `workspace_erp_connections`, `workspace_adapter_config` (`workspace_id == customer_id`)
2. **Core guards** — `app/core/workspace/` resolve + membership checks
3. **REST API** — `/api/v1/workspace/*` (new router only)
4. **UI shell** — `/workspace` and `/workspace/[customerId]/*`
5. **Composition** — customer users reuse existing invoice/SAT customer tabs; admin gets deep-links + activity counts
6. **SQL migration script** — expand-only DDL
7. **Unit tests** — access helper mocks (no production pipeline tests required to change)

`pipeline_enabled` defaults **false** — no new invoice processing path is active.

---

## Files created

### Backend

| File | Purpose |
|------|---------|
| `zodiac-api/app/models/workspace.py` | ORM models |
| `zodiac-api/app/core/__init__.py` | Core package |
| `zodiac-api/app/core/workspace/__init__.py` | Workspace package exports |
| `zodiac-api/app/core/workspace/context.py` | Context + access helpers |
| `zodiac-api/app/core/workspace/guards.py` | FastAPI dependency helpers |
| `zodiac-api/app/schemas/workspace.py` | Pydantic DTOs |
| `zodiac-api/app/api/workspace.py` | Workspace router |
| `zodiac-api/app/migrations/phase2_workspace_tables.sql` | Expand-only DDL |
| `zodiac-api/app/tests/__init__.py` | Test package |
| `zodiac-api/app/tests/test_workspace_access.py` | Access unit tests |

### Frontend

| File | Purpose |
|------|---------|
| `zodiac-front/src/lib/api.ts` | Added `workspaceApi` (append only) |
| `zodiac-front/src/components/workspace/WorkspaceShell.tsx` | Tab shell |
| `zodiac-front/src/app/workspace/page.tsx` | Workspace list / enable |
| `zodiac-front/src/app/workspace/[customerId]/page.tsx` | Overview |
| `zodiac-front/src/app/workspace/[customerId]/invoices/page.tsx` | Invoices composition |
| `zodiac-front/src/app/workspace/[customerId]/sat/page.tsx` | SAT composition |
| `zodiac-front/src/app/workspace/[customerId]/settings/page.tsx` | Admin config UI |

### Docs / logs

| File | Purpose |
|------|---------|
| `zodiac/implementation_logs/PHASE_2.md` | This log |

---

## Files modified

| File | Change | Why safe |
|------|--------|----------|
| `zodiac-api/app/server.py` | `include_router(workspace_router)` only | Additive mount; try/except like other routers |
| `zodiac-api/app/database.py` | Import workspace models in `init_models()` | Registers tables for `create_all`; no schema rewrite of old tables |
| `zodiac-front/src/components/Sidebar.tsx` | Optional “Workspaces” nav item | Hide with `NEXT_PUBLIC_WORKSPACE_UI=false`; does not remove existing items |
| `zodiac-front/src/lib/api.ts` | Append `workspaceApi` | No change to existing API clients |

**Intentionally untouched:** invoices, invoices_v2, sat*, dashboard, adaptive_query, auth, process_service, sap_*, customer delivery stub, existing customer-* pages.

---

## API changes (additive)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/workspace` | List visible workspaces |
| POST | `/api/v1/workspace` | Create settings (admin) |
| GET | `/api/v1/workspace/{customer_id}` | Summary |
| PATCH | `/api/v1/workspace/{customer_id}/settings` | Update flags (admin) |
| PUT/GET | `/api/v1/workspace/{customer_id}/erp` | ERP config refs |
| PUT/GET | `/api/v1/workspace/{customer_id}/adapters` | Adapter enablement |
| GET | `/api/v1/workspace/{customer_id}/access-check` | Membership probe |
| GET | `/api/v1/workspace/{customer_id}/activity` | Read-only scoped counts |

---

## Database changes

New tables only (see SQL migration). Apply with:

```bash
psql "$DATABASE_URL" -f app/migrations/phase2_workspace_tables.sql
```

Or rely on `Base.metadata.create_all()` after model registration (creates missing tables only).

---

## UI changes

- New `/workspace` routes
- Sidebar link (feature-flaggable)
- Existing `/customer-invoices`, `/sat-documents`, `/dashboard` unchanged

---

## Impact analysis (regression)

| Area | Impact |
|------|--------|
| Invoice V1/V2 pipelines | **Unaffected** — no code paths changed |
| SAT → SAP | **Unaffected** |
| AI / adaptive query | **Unaffected** |
| Dashboard | **Unaffected** |
| Authentication | **Unaffected** — reuses `get_current_user` |
| Existing customer portal | **Unaffected** |

---

## Testing performed

- Python syntax parse of new modules: OK  
- Import of `WorkspaceContext` with env DB URL: OK (workspace_id property)  
- Unit test file added for access helpers (run when pytest + app import path available): `app/tests/test_workspace_access.py`  
- Manual runtime against live DB: **pending** (requires applying migration + server restart)

Suggested smoke after deploy:

1. `GET /api/v1/health`  
2. Login → `GET /api/v1/workspace`  
3. Admin: `POST /api/v1/workspace` for existing customer  
4. Open `/workspace/{customer_id}`  
5. Confirm `/invoices-v2` and `/sat-documents` still work  

---

## Remaining work (Phase 2 polish / later)

- Live DB migration apply in each environment  
- Optional: stricter single-customer filter inside composed customer tabs when user has multiple assignments  
- Playwright e2e for workspace shell  
- Do **not** start Phase 3 until this phase is approved  

---

## Known limitations

- Workspace activity SAT count depends on `CustomerReceiverRfc` mappings  
- Admin invoice/SAT tabs deep-link to existing tools rather than a new filtered admin list API (avoids touching production list endpoints)  
- Adapter enablement stores config only — no runtime adapter yet (Phase 3)  
- `pipeline_enabled` does nothing until Phase 4 orchestrator  

---

## Rollback

1. Remove workspace router mount from `server.py` (or leave mounted — idle)  
2. Hide UI: `NEXT_PUBLIC_WORKSPACE_UI=false`  
3. Drop new tables only if required (optional; unused tables are harmless)  
4. No changes to reverse on invoice/SAT schemas  

---

## Recommendation for next phase

After approval → **Phase 3: Country Adapter Framework** (`CountryAdapter` protocol + `MxCfdiAdapter` façade). Do not relocate `sat_*` files.
