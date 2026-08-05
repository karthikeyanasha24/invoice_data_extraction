# Customer Onboarding Implementation

**Platform:** BridgeEDI / Zodiac  
**Scope:** First production customer using the **existing** architecture  
**Status:** Implemented — awaiting review  

---

## 1. Current capability (verified from source)

The platform already supports onboarding without redesign:

| Capability | How it works today |
|------------|--------------------|
| Create customer | Existing admin `POST /api/v1/customers` + Customers UI |
| Create workspace | `POST /api/v1/workspace` or Workspaces UI → Enable settings (`workspace_id == customer_id`) |
| Configure ERP | `PUT /api/v1/workspace/{id}/erp` — Settings UI (secret refs only) |
| Configure adapter | `PUT /api/v1/workspace/{id}/adapters` — e.g. `mx_cfdi` |
| Secrets | Prefixed refs (`vault:`, `env:`, …); `app/core/secrets` resolver at runtime |
| Monitoring | `monitoring_enabled` + `/api/v1/monitoring/*` + workspace Monitoring tab |
| AI Ops | `ai_scoped` + `/api/v1/ai/*` + workspace AI Ops tab (ops data only) |
| Pipeline | Workspace `pipeline_enabled` + process `ENABLE_PIPELINE_API` |
| Access | Admin all customers; customer users only assigned IDs |
| ERP double-update policy | `flags.erp_update_mode` = `auto` \| `always` \| `never` (PR1) |

**Answer: Can a customer be onboarded today?**  
**Yes, for configuration and workspace use** — once SQL migrations are applied and secret refs resolve in the target environment. The remaining gaps were UX/readiness visibility (now addressed below), not a missing architecture.

---

## 2. Missing functionality (before this work)

Verified gaps that blocked a smooth first-customer experience:

| Gap | Impact |
|-----|--------|
| No onboarding readiness checklist API | Admins could not see “ready vs incomplete” in one place |
| Settings UI outdated (“Phase 3 façade”) | Misleading; adapter registry already exists |
| No `erp_update_mode` in UI | Flag existed in code (PR1) but was not configurable in Settings |
| No `bearer` ERP auth option in UI | Supported path incomplete in forms |
| Weak client-side secret-ref validation | Bad UX; API already rejected plaintext |
| No `/health/ready` table probe | PR3 readiness not visible to ops |
| No packaged demo / E2E checklist script | Demo prep was ad hoc |

Not missing (do not rebuild):

- Workspace / pipeline / adapters / government / ERP connectors  
- SAT / V1 / V2 (frozen; unchanged)  
- Monitoring and AI Ops backends  

---

## 3. Implemented functionality (this delivery)

### Backend

1. **`GET /api/v1/workspace/{customer_id}/onboarding-status`**  
   Checklist: customer, settings, ERP, secrets, adapter, government endpoint, monitoring, AI Ops, pipeline, plus advisory `ENABLE_PIPELINE_API` and `erp_update_mode`.  
   Implementation: `app/core/workspace/onboarding.py` + route in `app/api/workspace.py`.

2. **`GET /health/ready`** (PR3 readiness)  
   Checks DB connectivity and enterprise tables (`workspace_*`, `erp_push_outbox`, monitoring tables). Returns **503** if missing.

3. **Flags merge on settings PATCH**  
   Partial `flags` updates (e.g. `erp_update_mode`) no longer wipe other flags.

### Frontend

1. Settings: onboarding checklist, `erp_update_mode`, ERP `bearer`, government auth type, client-side secret-ref validation, updated copy.  
2. Overview: readiness banner + ERP mode display.  
3. Workspaces index: clearer onboarding copy; enable sets `monitoring_enabled` + default `erp_update_mode=auto`.  
4. `workspaceApi.getOnboardingStatus`.

### Demo / tests

- `zodiac/scripts/demo_first_customer_e2e.py` — simulated path + checklist  
- `app/tests/test_customer_onboarding.py`

---

## 4. Implementation checklist (admin flow)

```
Administrator creates customer          →  /customers
        ↓
Workspace settings created              →  /workspace → Enable
        ↓
ERP configured (base URL + auth)        →  Settings → ERP
        ↓
Secrets configured (vault:/env: refs)   →  Settings + env/vault
        ↓
Country adapter enabled (mx_cfdi)       →  Settings → Adapter
        ↓
Government endpoint configured          →  endpoint_url_ref
        ↓
Monitoring enabled                      →  monitoring_enabled
        ↓
AI Ops enabled (scoped)                 →  ai_scoped
        ↓
Pipeline enabled (platform path)        →  pipeline_enabled + ENABLE_PIPELINE_API
        ↓
Customer ready                          →  onboarding-status.ready == true
```

---

## 5. Configuration guide

### 5.1 Create customer

Use existing Customers admin UI or:

```http
POST /api/v1/customers
Authorization: Bearer <admin>
```

### 5.2 Enable workspace

UI: **Workspaces** → Enable settings for customer  

API:

```http
POST /api/v1/workspace
{
  "customer_id": "ACME_MX",
  "display_name": "ACME Mexico",
  "pipeline_enabled": true,
  "ai_scoped": true,
  "monitoring_enabled": true,
  "flags": { "erp_update_mode": "auto" }
}
```

### 5.3 ERP + secrets

```http
PUT /api/v1/workspace/ACME_MX/erp
{
  "connection_key": "primary",
  "base_url": "https://erp.acme.example/api",
  "auth_type": "bearer",
  "client_secret_ref": "env:ACME_ERP_TOKEN",
  "is_active": true
}
```

Set `ACME_ERP_TOKEN` (or vault path) in the API runtime.  
`SECRET_RESOLVER=literal` only for local/legacy tests.

### 5.4 Adapter + government

```http
PUT /api/v1/workspace/ACME_MX/adapters
{
  "country_code": "mx_cfdi",
  "enabled": true,
  "endpoint_url_ref": "https://gov.example/cfdi",
  "auth_type": "bearer",
  "auth_secret_ref": "env:ACME_GOV_TOKEN"
}
```

### 5.5 Process flags (API host)

| Variable | Purpose |
|----------|---------|
| `ENABLE_PIPELINE_API=true` | Opt-in shared pipeline API |
| `SECRET_RESOLVER` | `default` (env+vault) or `literal` (dev) |
| `CORS_ORIGINS` | Production frontend origins |
| `DATABASE_URL` | PostgreSQL |

### 5.6 Migrations (required before ready)

Apply expand-only SQL from `zodiac-api/app/migrations/`:

- `phase2_workspace_tables.sql`  
- `phase6_erp_outbox.sql`  
- `phase8_monitoring_tables.sql`  

See `docs/operations/MIGRATION_GUIDE.md`. Confirm with `GET /health/ready`.

### 5.7 Verify readiness

```http
GET /api/v1/workspace/ACME_MX/onboarding-status
GET /health/ready
```

---

## 6. Testing

### Automated

```bash
cd zodiac/zodiac-api
python -m unittest app.tests.test_customer_onboarding -v
python zodiac/../scripts/demo_first_customer_e2e.py
# or from zodiac:
python scripts/demo_first_customer_e2e.py
```

### End-to-end (documented stages)

| Step | Action | Evidence |
|------|--------|----------|
| 1 | Create customer | Customers list / DB `zodiac_customers` |
| 2 | Enable workspace | `has_settings=true` |
| 3–6 | Save Settings (ERP, secrets, adapter, gov) | onboarding steps OK |
| 7–8 | Monitoring + AI tabs | Workspace UI |
| 9 | Enable pipeline + `ENABLE_PIPELINE_API` | `ready=true` |
| 10 | Process sample invoice (sandbox) | Existing invoice/SAT or pipeline path |
| 11 | Government submit (sandbox endpoint) | Adapter/government connector logs |
| 12 | ERP confirmation | Respect `erp_update_mode`; outbox if used |
| 13 | Monitoring timeline | `/api/v1/monitoring/*` |
| 14 | AI Ops | Reads monitoring only — never invoice pipeline |

**Demo script** prints the same stage list and a simulated complete checklist.

---

## 7. Known limitations

1. **Customer creation** remains on legacy `/customers` — workspace does not replace it (by design).  
2. **Live government / ERP** still require real endpoints and resolvable secrets; this delivery does not mock them in production.  
3. **PR4** (monitoring soft-fail / circuit breaker) is optional and not included.  
4. **`ENABLE_PIPELINE_API`** is process-wide; per-workspace `pipeline_enabled` still required.  
5. **MX submit path** may still fulfill SAP inside the adapter; use `erp_update_mode=auto` to avoid double ERP update (PR1).  
6. **Adaptive Query / dashboard AI** is separate from AI Ops — do not conflate for demos.  
7. Migrations are **manual** (no auto-migrate in app startup).

---

## 8. Production readiness (first customer)

| Gate | Status |
|------|--------|
| Architecture redesign needed? | No |
| Workspace / adapter / pipeline / connectors | Existing |
| Onboarding UX + readiness API | Done (this delivery) |
| `/health/ready` | Done |
| SQL migrations applied in target env | **Ops must confirm** |
| Secrets resolvable in target env | **Ops must confirm** |
| Sandbox gov + ERP endpoints | **Customer-specific** |
| SAT / V1 / V2 unchanged | Yes |
| Pilot GO | Conditional on migrations + secrets + sandbox connectivity |

**Recommendation:** Proceed with pilot customer configuration in staging using this guide; treat first production invoice through sandbox government/ERP before flipping production endpoints.

---

## 9. Files touched

| Area | Path |
|------|------|
| Onboarding logic | `zodiac-api/app/core/workspace/onboarding.py` |
| API | `zodiac-api/app/api/workspace.py`, `schemas/workspace.py` |
| Ready probe | `zodiac-api/app/server.py` |
| UI | `zodiac-front/src/app/workspace/**`, `lib/api.ts` |
| Tests | `zodiac-api/app/tests/test_customer_onboarding.py` |
| Demo | `zodiac/scripts/demo_first_customer_e2e.py` |
| This doc | `zodiac/CUSTOMER_ONBOARDING_IMPLEMENTATION.md` |

---

*Stop here for review. No architecture redesign. No SAT/V1/V2 changes. No new frameworks.*
