# Environment Diagnostic Report — Workspace QA Blockers

**Date:** 2026-08-03  
**Scope:** Read-only investigation only. No code, database, migration, or role changes were made.  
**Goal:** Establish why Workspace Overview / Workspace APIs fail before resuming manual QA.

---

## Executive summary

| Symptom | Verified cause |
|---------|----------------|
| `GET /api/v1/workspace` → **403** | Logged-in user is neither `is_admin` nor `is_customer_user` |
| `GET /api/v1/workspace/{id}` (+ activity / onboarding) → **404** “Workspace not found” | Same user fails `user_can_access_customer`; guard intentionally maps deny → **404** (IDOR hardening) |
| Workspace Overview UI cannot load | Those three GETs fail; page shows error (and still shows loading spinner because `!data`) |
| Enterprise tables “appear missing” | **Confirmed:** all 8 required platform tables are **MISSING** on the connected Neon `neondb` / `public` schema |
| Migrations “may not have been applied” | **Confirmed:** no migration tracker tables; SQL files exist but were never applied to this DB; `AUTO_APPLY_ENTERPRISE_SCHEMA` is unset |

**Classification:** primarily **environment / deployment / user-role**, with two small **frontend UX code** gaps. Workspace **routing and auth guards are working as designed**.

---

## 1. Current environment

| Item | Value |
|------|--------|
| Frontend | `localhost:3000` (Zodiac Next.js) |
| API | `localhost:8000` |
| `DEPLOY_ENV` | `DEV` |
| `API_DEBUG` | `True` |
| `AUTO_APPLY_ENTERPRISE_SCHEMA` | **unset / null** (defaults to off) |
| Liveness `GET /health` | **200** `{"status":"healthy",...}` |
| Readiness `GET /health/ready` | **503** (expected when enterprise tables missing) |
| Logged-in QA user (UI) | `ashakarthikeyan24` / `ashakarthikeyan24@gmail.com` |

---

## 2. Connected database

### DATABASE_URL source

- Loaded from: `zodiac/zodiac-api/.env` via `python-dotenv` (`app/database.py` → `load_dotenv()`).
- Same source used by the running API process and by this diagnostic.

### Connection (credentials redacted)

| Field | Verified value |
|-------|----------------|
| Scheme | `postgresql` |
| Host | `ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech` |
| Database name | `neondb` |
| DB user | `neondb_owner` |
| Query | `sslmode=require` |
| Redacted URL | `postgresql://neondb_owner:***@ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require` |

### Live session

| Field | Verified value |
|-------|----------------|
| `current_database()` | `neondb` |
| `current_schema()` | `public` |
| `current_user` | `neondb_owner` |
| Public tables present | **121** (legacy Zodiac schema is present) |
| `zodiac_customers` count | **11** |

**Conclusion:** Backend is on the intended Neon DEV database / `public` schema. This is **not** a “wrong empty database” problem — legacy tables exist; **enterprise Phase 2/6/8 tables were never created on this DB**.

---

## 3. Existing vs missing tables

### Required platform tables (readiness set)

| Table | Status |
|-------|--------|
| `workspace_settings` | **MISSING** |
| `workspace_erp_connections` | **MISSING** |
| `workspace_adapter_config` | **MISSING** |
| `erp_push_outbox` | **MISSING** |
| `pipeline_timelines` | **MISSING** |
| `pipeline_events` | **MISSING** |
| `pipeline_metrics` | **MISSING** |
| `alert_history` | **MISSING** |

Also verified:

- `workspace_like_tables` = `[]`
- `pipeline_like_tables` = `[]`
- Migration tracker tables (`alembic_version`, `schema_migrations`, `flyway_schema_history`) = **none**

### Why missing (verified, not guessed)

1. Migration SQL files exist under `zodiac-api/app/migrations/` but are **manual / expand-only**.
2. Helper `zodiac/scripts/apply_enterprise_migrations.py` applies them only when **explicitly run**.
3. Startup `apply_enterprise_schema_if_enabled()` only runs SQLAlchemy `create_all` when `AUTO_APPLY_ENTERPRISE_SCHEMA` is truthy — **currently unset**, so startup **does not** create tables.
4. `init_models()` only **registers ORM metadata**; it does **not** create tables by itself.
5. No Alembic (or similar) history table exists → there is no applied-version ledger; absence of tables is the evidence they were never applied here.

---

## 4. Migration status

### Files that exist

| Order | File | Creates |
|-------|------|---------|
| 1 | `app/migrations/phase2_workspace_tables.sql` | `workspace_settings`, `workspace_erp_connections`, `workspace_adapter_config` |
| 2 | `app/migrations/phase6_erp_outbox.sql` | `erp_push_outbox` |
| 3 | `app/migrations/phase8_monitoring_tables.sql` | `pipeline_timelines`, `pipeline_events`, `pipeline_metrics`, `alert_history` |

Documented in: `app/migrations/README.md`, `docs/operations/MIGRATION_GUIDE.md`.

### Executed vs unapplied

| Migration | Applied on connected Neon `neondb`? |
|-----------|-------------------------------------|
| phase2 | **No** (all three workspace tables missing) |
| phase6 | **No** (`erp_push_outbox` missing) |
| phase8 | **No** (all four monitoring tables missing) |

### Correct apply command (do **not** run until approved)

From repo docs / script:

```powershell
cd c:\Users\karth\Downloads\ANDY\invoice_data_extraction\zodiac\zodiac-api
# DATABASE_URL already in .env — ensure it is loaded, or set explicitly
python ../scripts/apply_enterprise_migrations.py
```

Alternative (ops guide):

```powershell
psql "$env:DATABASE_URL" -f app/migrations/phase2_workspace_tables.sql
psql "$env:DATABASE_URL" -f app/migrations/phase6_erp_outbox.sql
psql "$env:DATABASE_URL" -f app/migrations/phase8_monitoring_tables.sql
```

Optional DEV convenience (not currently enabled): set `AUTO_APPLY_ENTERPRISE_SCHEMA=true` and restart API (SQLAlchemy `create_all`; prefer SQL files for index/constraint parity).

**Verify after apply (when approved):**

```text
GET http://127.0.0.1:8000/health/ready
→ 200 { "status": "ready", "missing_tables": [] }
```

---

## 5. Startup trace

```
server.py
  → @app.on_event("startup") _bridgeedi_startup()
    → core.startup.run_startup()
      → ensure_adapters_registered()     # always (mx_cfdi + builtins)
      → apply_enterprise_schema_if_enabled()
          # ONLY if AUTO_APPLY_ENTERPRISE_SCHEMA in {1,true,yes,on}
          # else returns False — NO table creation
      → validate_production_config()     # logs warnings; does not refuse start
```

Also at import time:

```
database.py
  → load_dotenv()
  → engine / SessionLocal
  → init_models()   # imports Workspace*/Outbox/Monitoring models into Base.metadata
  → does NOT call create_all unless create_all_tables() is invoked
```

Routers (including workspace) are registered at module load with prefix `/api/v1`.

**Should startup have created tables automatically?**  
**No.** By design: SQL migrations are opt-in / ops-applied; auto-create is behind an env flag that is **off**. Startup skipped schema creation because the flag is unset — this is expected behavior, not a crashed hook.

---

## 6. Authentication — current user

### JWT (browser `localStorage.access_token`)

| Claim | Value |
|-------|--------|
| `sub` | `"11"` |
| `exp` | present (long-lived relative to session) |

Auth route: `GET /api/v1/user/auth/fetch_user` (router prefix `/user/auth` under `/api/v1`).

### Database row `zodiac_users.id = 11`

| Field | Value |
|-------|--------|
| id | 11 |
| username | `ashakarthikeyan24` |
| email | `ashakarthikeyan24@gmail.com` |
| is_admin | **false** |
| is_customer_user | **false** |
| is_active | true |
| is_verified | false |
| assigned customers (`user_customers`) | **[]** (none) |

### Admins present in DB

| id | username | is_admin |
|----|----------|----------|
| 1 | `puspesh` | true |

### Why Workspaces are inaccessible

Workspace list requires:

```text
is_admin OR is_customer_user
```

User 11 has **neither** → `list_workspaces` raises **403**  
`Workspace access requires admin or customer-user role`.

Detail endpoints use `require_workspace_access` → `user_can_access_customer` returns **False** for non-admin / non-customer-user → **404** (see below).

---

## 7. Authorization flow (403 vs 404)

```
Workspace Overview page
  → workspace/[customerId]/page.tsx
  → workspaceApi.getWorkspace / getActivity / getOnboardingStatus
  → GET /api/v1/workspace/{id}
  → GET /api/v1/workspace/{id}/activity
  → GET /api/v1/workspace/{id}/onboarding-status
  → app/api/workspace.py handlers
  → require_workspace_access / resolve_workspace
  → user_can_access_customer()
       admin? → no
       customer_user? → no
       else → False
  → require_workspace_access(hide_existence=True)
       not admin → HTTP 404 "Workspace not found"
```

### Why list is 403 but Overview is 404

| Endpoint | Guard | Outcome for user 11 |
|----------|-------|---------------------|
| `GET /api/v1/workspace` | Explicit role check in `list_workspaces` | **403** role message |
| `GET /api/v1/workspace/{id}` (and activity / onboarding) | `require_workspace_access` with `hide_existence=True` | **404** to avoid IDOR probing |

This is **intentional code behavior**, not a routing bug.

**Note:** With tables still missing, even after fixing roles an admin Overview call would next hit SQL against missing `workspace_*` tables (likely **500**) until migrations are applied. Current session never reached that layer because access failed first.

---

## 8. Routing verification

| Client call | Mounted route | Status |
|-------------|---------------|--------|
| `GET /api/v1/workspace` | `APIRouter(prefix="/workspace")` + `app.include_router(..., prefix="/api/v1")` → `GET ""` | **Correct** |
| `GET /api/v1/workspace/{id}` | `GET /{customer_id}` | **Correct** |
| `GET /api/v1/workspace/{id}/activity` | `GET /{customer_id}/activity` | **Correct** |
| `GET /api/v1/workspace/{id}/onboarding-status` | `GET /{customer_id}/onboarding-status` | **Correct** |

Frontend `workspaceApi` paths in `src/lib/api.ts` match these routes.

**Routing is not broken.** Failures are authz + schema readiness.

---

## 9. Frontend findings (inspection only — no changes)

### Sidebar / Workspaces visibility

`Sidebar.tsx`:

- Workspaces menu item is shown when `NEXT_PUBLIC_WORKSPACE_UI !== 'false'` (default **on**).
- Menu set: if `is_customer_user && !is_admin` → customer menu; **else → full admin menu**.
- Therefore a user with `is_admin=false` **and** `is_customer_user=false` still gets the **admin** sidebar (Customers, SAT, Workspaces, etc.).

**Implication:** Workspaces is **not** hidden for users who cannot call Workspace APIs. That is a **UX / permission-gating gap** (code), separate from the API correctly denying access.

### Overview error vs spinner

`workspace/[customerId]/page.tsx`:

- On failure: `setError(...)`.
- Render: shows error banner **and** `{!data ? <Loader/> : ...}`.
- So after a failed load, **error + perpetual spinner** can appear together.

Prefer an access-denied / failed state without continued loading (`!data && !error`). **Code UX issue**; not the root cause of 403/404.

---

## 10. Root cause (stacked)

1. **Database / deployment:** Phase 2/6/8 SQL never applied to Neon `neondb` → all enterprise tables missing; `/health/ready` cannot be ready.
2. **User / role:** QA login `ashakarthikeyan24` (id 11) is not admin and not customer-user → Workspace APIs deny access (403 / 404).
3. **Configuration:** `AUTO_APPLY_ENTERPRISE_SCHEMA` off by design → startup did not create tables.
4. **Code (secondary UX):** Sidebar shows Workspaces without role check; Overview keeps spinner after error.

Wrong-database theory: **rejected** (121 public tables, 11 customers, known users present).

---

## 11. Issue taxonomy

| Category | Issue | Severity |
|----------|-------|----------|
| **Database issue** | All 8 enterprise tables missing on connected Neon DB | Critical — pilot blocker for Workspace / Monitoring / Outbox |
| **Deployment issue** | Migrations never applied; no auto-apply on startup | Critical — same |
| **User/Role issue** | User 11 not `is_admin` / `is_customer_user`; no `user_customers` rows | High — blocks this QA account from Workspace APIs |
| **Configuration issue** | `AUTO_APPLY_ENTERPRISE_SCHEMA` unset (expected default) | Informational — explains why startup skipped create |
| **Code issue** | Sidebar shows Workspaces to non-privileged users | Medium — UX / confusion |
| **Code issue** | Overview spinner remains when `error` is set | Medium — cosmetic / UX |
| **Code issue** | 403 list vs 404 detail | Not a bug — intentional IDOR hardening |

---

## 12. What is broken / why / what must be done

### What is broken

- Workspace list and Overview cannot be QA’d under the current login against this DB.
- Platform readiness (`/health/ready`) fails.
- Enterprise Workspace / ERP outbox / Monitoring schema is absent.

### Why

- Environment never received Phase 2/6/8 DDL.
- Current user lacks Workspace API roles.
- Startup correctly does not invent schema without an explicit flag.

### Exactly what must be done (when you approve — not done yet)

1. **Apply enterprise migrations** to the Neon DB in `.env` (phase2 → phase6 → phase8).
2. **Confirm** `GET /health/ready` → **200**, `missing_tables: []`.
3. **Grant Workspace access** for the QA/pilot user, e.g.:
   - set `is_admin = true` for id 11, **or**
   - set `is_customer_user = true` and insert `user_customers` for pilot `customer_id`s, **or**
   - log in as existing admin `puspesh` for QA.
4. **Re-login** (new JWT / AuthContext) after any role change.
5. **Optionally** (separate, after env works): fix Sidebar gating + Overview error/spinner UX.
6. **Then** resume Step 5 Workspace Overview QA.

### Code vs environment?

| Layer | Verdict |
|-------|---------|
| Workspace API routing / guards | Environment-ready **code is correct** |
| Missing tables | **Environment / deployment** |
| User 11 roles | **Environment / data** |
| Sidebar + spinner | Minor **code** UX (optional after env repair) |

### Safest fix order

1. Apply SQL migrations (expand-only, `IF NOT EXISTS`) → verify `/health/ready`.  
2. Fix QA user role **or** use known admin account → verify `GET /api/v1/workspace` **200**.  
3. Re-run Workspace Overview read-only QA.  
4. Only then consider frontend permission/spinner polish.  
5. Do **not** enable `AUTO_APPLY_ENTERPRISE_SCHEMA` in production; optional for local DEV only after deliberate decision.

---

## 13. Stop criteria (this report)

- [x] Database identified and tables verified  
- [x] Migrations inventoried; apply command documented (not executed)  
- [x] Startup path traced  
- [x] User / JWT / roles verified  
- [x] 403→404 explained  
- [x] Routing verified  
- [x] Frontend inspected without modification  
- [x] No code / DB / role / migration changes performed  
- [x] Manual QA not continued  

**Awaiting your explicit approval** before applying migrations, changing roles, or resuming Workspace QA.
