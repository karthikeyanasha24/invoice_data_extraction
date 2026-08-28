# BridgeEDI V2.1 + R4 — System Audit

**Date:** 2026-08-28  
**Branch:** `phase12-first-customer-ready`  
**Auditor:** production completion pass (code + live `www.bridgeedi.com` + `zodiac-back.vercel.app`)  
**Credentials:** not included.

This audit maps the product as it exists in the repository and on the canonical production hosts. It does not claim production completion.

---

## 1. Product snapshot

BridgeEDI is two products sharing one authenticated shell:

1. **Governed SAP intelligence** (AI Analyst + Overview investigations) over a SAP extract (billing, inventory snapshot, purchase orders).
2. **EDI / SAT operations** (CFDI intake, merge, send to SAP, invoices).

Information architecture on production:

| Group | Purpose | Primary routes |
| --- | --- | --- |
| Understand | Orientation | `/overview` |
| Ask | Governed analysis | `/dashboard/ai` |
| Operate | EDI / SAT / invoices | `/dashboard`, `/invoices-v2`, `/sat-documents` |
| Manage | Accounts and settings | `/customers`, `/admin/*`, `/settings` |

AI Analyst does **not** contain EDI operation tabs. Operations stay under Operate.

---

## 2. Frontend architecture

**App:** Next.js (`zodiac/zodiac-front`), App Router under `src/app`.

**Shell:** `MainLayout` + `Sidebar` from `navConfig.adminNavGroups`. Skip-to-content link `#main-content`. Session restore: cached user keeps the shell; full-page gate only when there is no user.

**Auth:** `AuthContext` stores JWT in `localStorage` (`access_token`). Login at `/`. Customer portal is a separate login (`/customer/login`) and is redirected away from the admin shell.

**API client:** `src/lib/api.ts` Axios. Browser uses `NEXT_PUBLIC_API_URL` when set (production: `https://zodiac-back.vercel.app`). Human errors go through `publicApiError` (no raw `AxiosError`).

**AI Analyst:** `src/app/dashboard/ai/page.tsx` → `DashboardAIAnalysis`. Reads `?q=` from Overview chips. Trust panel: `analysisTrustFromResult`. SQL behind **View SQL**. Saved analyses: **this device** only (`savedAnalyses`).

**Overview:** `OverviewCommandCenter` loads `GET /api/v1/dashboard/v2/inbound` and `GET /api/v1/dashboard/v2/business`. Distinguishes EDI invoice totals from SAP P&L. Does not celebrate an empty pipeline as “healthy”.

---

## 3. Frontend route inventory

### Admin / operator (MainLayout)

| Route | Page | Notes |
| --- | --- | --- |
| `/` | Login / signup | Public |
| `/overview` | Command center | Home |
| `/dashboard/ai` | AI Analyst | Strategic core |
| `/dashboard` | EDI operations | Inbound SAT / From ERP / Business / Comparison |
| `/invoices-v2` | Invoice convert/validate | Operate |
| `/invoices-v2/processing` | Processing tracker | |
| `/invoices` | Legacy invoices | Still routed |
| `/sat-documents` | SAT list / merge / send | |
| `/sat-documents/upload` | Upload | |
| `/sat-documents/[id]` | Document detail | |
| `/sat-documents/canonical/[id]` | Canonical merge | |
| `/sat-documents/simple-merge/[id]` | Simple merge | |
| `/upload` | Invoice upload | |
| `/invoice/[id]` | Invoice detail | |
| `/failed-invoice/[id]` | Failed invoice | |
| `/quotations` | Quotations | |
| `/export` | Export | |
| `/customers` | EDI customers | |
| `/customer-users` | Admin users | |
| `/admin/account-mapping` | RFC to G/L | Human label, not “Account mapping” |
| `/admin/supplier-tokens` | Supplier API access | |
| `/settings` | Profile / Security / API / Account | |
| `/workspace` | Workspace list | Feature-flagged |
| `/workspace/[customerId]/*` | Per-customer workspace | overview, ai, sat, invoices, monitoring, settings |

### Customer portal (separate)

`/customer`, `/customer/login`, `/customer/(portal)/{overview,ai,invoices,sat,monitoring,settings}`, plus `/customer-dashboard`, `/customer-invoices`, `/customer-sat-documents`.

Customers hitting admin `MainLayout` are redirected to the portal home.

---

## 4. Backend architecture

**App:** FastAPI (`zodiac/zodiac-api/app/server.py`), Vercel serverless.

**Router registration:** failures are recorded on `GET /health/routers` (not silent 404). Live 2026-08-28: `status=ok`, `loaded_count=20`, `failed=[]`, `dashboard.loaded=true`.

**Registered routers:** auth, invoices, invoices_v2, converted_invoices, customers, corrections, dashboard, adaptive_query, admin, sat, sat_canonical, sat_supplier_mapping, sat_simple_merge, supplier_tokens, customer_users, certificates, workspace, pipeline, monitoring, ai_ops.

**Adaptive path (AI Analyst):**

```text
POST /api/query/adaptive
  → JWT (get_current_user) before any SQL
  → classify_turn / follow-up resolver
  → is_deep_analysis_candidate
  → try_deep_multidim_analysis
       build_analytical_plan → compile_queries
       sql_grain_guard
       execute
       interpret / data gaps / follow-ups
  → else existing engines (intent SQL, catalog, universal)
```

**Auth:** `HTTPBearer(auto_error=False)` so missing Authorization is **401**, not 403. JWT decode failures 401. Adaptive never reaches SQL without a valid user.

**OpenAPI:** live spec exposes 31 dashboard paths including `/api/v1/dashboard/v2/inbound`.

---

## 5. Data architecture (governed)

| Domain | Tables | Grain | Metrics | Must not |
| --- | --- | --- | --- | --- |
| Sales | `vbrp` / `VBRK` (+ KNA1/MAKT/MARA N:1) | billing_item | Revenue NETWR, COGS WAVWR, GP, margin, qty, ASP, MoM/QoQ/YoY | Net profit, opex |
| Inventory | `MBEW` / `MARD` | snapshot | SALK3 value, LBKUM qty, LABST unrestricted | Aging, historical stock, true turnover |
| Purchase / R3 suppliers | `EKPO` / `EKKO` / `LFA1` | po_item | PO NETWR association | Supplier profit |
| Purchase / R4-4 | same | po_item → supplier | rank, PO value, share_of_po_value_pct | HHI, risk thresholds, VBRP⋈EKPO |

Independent aggregation then join at safe grain. `sql_grain_guard.sql_has_unsafe_monetary_fanout` rejects billing×inventory, billing×purchase, and purchase×inventory monetary joins.

**LOEKZ:** deleted PO header/item rows excluded (`TRIM(COALESCE(loekz,'')) = ''`).

**Zero total:** `share_of_po_value_pct` is NULL when the denominator is ≤ 0.

---

## 6. AI architecture

| Layer | Role |
| --- | --- |
| Semantic candidate gate | `is_deep_analysis_candidate` — meaning signals, not phrase patches |
| Follow-up resolver | `analytical_followup_resolver` — entity / metric / time / dimension / DATA GAP kinds |
| Plan | `AnalyticalPlan` intent, selected products, metrics, dimensions, period |
| SQL compiler | Intent-specific CTE SQL (no LLM SQL for governed intents) |
| Grain guard | Reject unsafe monetary fan-out |
| DATA GAP | First-class `CANNOT_ANSWER` with alternatives (no aging retry) |
| Trust | Source / definition / aggregation / period / grain / result size / limitations |

R3 “Show their suppliers.” remains `suppliers_of_selection`. R4-4 “Show supplier concentration.” is a separate intent.

**Live gap:** first-question concentration is not a deep candidate on the currently deployed backend (`score` lacked supplier-concentration signals). Fix is on this branch (`wants_supplier_concentration` → score += 3) and is **not live** until `zodiac-back` is redeployed.

---

## 7. Authentication architecture

| Surface | Rule |
| --- | --- |
| Login | Email + password, show/hide password, human error copy |
| Session | JWT in localStorage; shell restore without wiping chrome when user is cached |
| Adaptive | 401 without JWT / empty Bearer / wrong scheme / malformed / invalid signature |
| Dashboard APIs | Same bearer via Axios interceptor |
| Logout | Clears token and returns to `/` |
| Direct URL | Unauthenticated users redirected to `/?next=` |
| Customer vs admin | Portal users cannot use the operator shell |

JWT is not shown in Settings Security copy on production (session language). API keys remain on the API tab by design.

---

## 8. Production dependencies and Vercel

| Host | Role | Canonical? |
| --- | --- | --- |
| `https://www.bridgeedi.com` | Frontend Product V2.1 | Yes |
| `https://zodiac-back.vercel.app` | Backend R3–R4-3 + R4-4 follow-up | Yes |
| `https://zodiac-api-nu.vercel.app` | Unrelated project on this CLI account | **Never deploy here** |

This CLI (`karthikeyanasha24` / team `ashas-projects-a0fae821`) can only see:

- `zodiac-api` → `zodiac-api-nu.vercel.app`
- `hrm53v1`
- `banyanqi-react`

It cannot inspect or deploy the BridgeEDI frontend project or `zodiac-back`. `VERCEL_TOKEN` is unset. No DNS change. No replacement project.

---

## 9. Environment variables (names only)

### Backend (representative)

`DATABASE_URL` / `POSTGRES_URL`, `SECRET_KEY`, `ALGORITHM`, `CORS_ORIGINS`, `CORS_ALLOW_ALL`, `OPENAI_API_KEY` / `OPEN_AI_KEY`, model selectors (`OPENAI_MODEL`, `AI_FAST_MODEL`, …), `LIVE_API_EMAIL` / `LIVE_API_PASSWORD` (local live scripts only, not committed).

### Frontend

`NEXT_PUBLIC_API_URL` (production backend origin), optional `INTERNAL_API_URL` for SSR.

Secrets must not appear in git, reports, or the UI.

---

## 10. API contracts (AI)

`POST /api/query/adaptive`

Body: `{ question, contextData?, threadId?, tableHint?, overrideSql? }`

Response (governed): `answer_status` (`SUCCESS` | `CANNOT_ANSWER`), `sql`, `data`, `query_plan.analytical_context` (intent, selected_products, metrics, data_gaps), `summary`, `suggested_followups`, `meta`.

Without Authorization: **401** `Could not validate credentials`. Body contains no SQL.

---

## 11. Known limitations

- No MSEG → no inventory aging or true turnover.
- No ACDOCA / FI → no net profit, opex, logistics cost.
- Inventory is a **current snapshot**, not time-aligned to billing FKDAT.
- R4-4 is purchase **share**, not supplier risk / HHI / profit.
- Saved analyses are device-local.
- Workspace / pipeline ERP write is a separate operator surface; inbound SAT KPIs are not an ERP push.
- Cold / basic-GA turns can take ~9s (observed on live R4-1 `2004` / `Top 5`).

---

## 12. Technical debt

- Live summaries still say `Deep analysis — intent <slug>` until backend heading helper is deployed.
- EDI operations subtitle still says “To ERP tab” on www; tab itself is already “Inbound SAT”.
- Mobile a11y tree still exposes a Close-menu control while the overlay is visually closed.
- `live_acceptance_chain.py` does not attach JWT (do not use it for production probes).
- Duplicate Windows path untracked copies in git status (`zodiac\zodiac-front\...`) — ignore; they are the same tree.
- CORS_ALLOW_ALL in local `.env` must not be production posture (production CORS is origin-restricted on the live service).

---

## 13. Product / UX / security / performance gaps

| Area | Gap | Severity |
| --- | --- | --- |
| R4-4 first question | Overview / welcome chip “Show supplier concentration.” does not enter `deep_multidim` on live | **Blocker** for R4-4 production complete |
| Deploy access | This CLI cannot deploy `zodiac-back` or www | **Blocker** |
| Trust copy | Intent slugs in live result headings | Medium (fixed on branch) |
| EDI subtitle | “To ERP tab” leftover | Low (fixed on branch) |
| Login tagline | Local copy stronger than some live cache; V2.1 branding is live | Low |
| GA latency | ~9s on some basic-engine turns | Accepted outlier; do not weaken correctness |
| Independent SQL standalone | BLOCKED until first-question path is live | **Blocker** for that comparison |
| Independent SQL chained | PASS, 0.00 share difference | Closed |

---

## 14. Feature inventory (governed, shippable)

- R3 profitability, customers, industry, region, suppliers-of-selection, product group, ASP, process DATA GAPs, net profit DATA GAP, recovery
- R4-1 month/quarter trends, MoM/QoQ, 2004/2005
- R4-2 product growth/decline
- R4-3 inventory snapshot vs sales, plant, selected-product context
- R4-4 supplier concentration (follow-up live; first question on branch only)
- SAT CFDI intake / merge / send
- Settings profile, session security, API keys
- Adaptive JWT gate
- Grain guard
