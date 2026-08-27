# P0/P1 Production Hardening — Acceptance Report

## 1. Executive verdict

# PRODUCTION HARDENING COMPLETE

Authenticated production acceptance is complete against `https://zodiac-back.vercel.app` and `https://www.bridgeedi.com`. Commit **`7f1f7cd`**. Do not start R4-4.

**R3–R4-3 production baseline fully verified.**

### Live verification (2026-08-27)

| Check | Result |
| --- | --- |
| `POST /api/query/adaptive` no JWT | **401**, no SQL |
| Invalid / malformed / empty / wrong-scheme JWT | **401**, no SQL |
| Expired JWT | **401**, no SQL |
| Valid JWT adaptive | **200** `SUCCESS` / `deep_multidim` (inventory 30 rows, 970ms then 633ms) |
| OpenAPI | **181** paths, **31** `/api/v1/dashboard/*` |
| `/api/v1/dashboard/v2/inbound` in OpenAPI | **Present** |
| `GET /health/routers` | **200**, `status=ok`, `loaded_count=20`, `failed=[]`, `dashboard.loaded=true` |
| Inbound no JWT | **401** |
| Inbound with JWT | **200**, 582ms; schema `summary`, `by_document_type`, `by_source`, `by_period`, `top_suppliers`, `timeline`, `tokens` |
| Frontend | Title **BridgeEDI**; logged-out protected pages → `/?next=…` |
| To ERP (inbound SAT KPIs, not an ERP push) | **14** documents, **4** merges, **4** sent to SAP, **0** pending; charts render; no AxiosError |
| Settings / SAT authenticated | Profile + API key controls; SAT **14** documents; no blank spinner |
| Full Chat | 11-turn chain **PASS**; aging DATA GAP; recovery **PASS**; second gap chain PASS / DATA GAP / PASS |
| R3 live | **23 PASS / 2 DATA GAP / 0 FAIL** |
| R4-1 live | **47 PASS / 2 DATA GAP / 0 FAIL** |
| R4-2 live | **40 PASS / 1 DATA GAP / 0 FAIL** |
| R4-3 live | **31 PASS / 6 DATA GAP / 0 FAIL** |
| Independent SQL | Values match (0.00% on compared metrics); rank ties only |
| Frozen engine | R3–R4-3 analytical files not in `7f1f7cd`; unchanged vs that commit |

Previously production returned HTTP 200 + MBEW SQL without a JWT and OpenAPI had 0 dashboard paths. That old build is gone.

---

## 2. Original blockers

| ID | Blocker | Audit evidence |
| --- | --- | --- |
| B1 | Adaptive API optional auth | `POST /api/query/adaptive` returned 200 and executed inventory SQL with no JWT |
| B2 | Dashboard API routes missing | Live OpenAPI had no `/api/v1/dashboard/*`; To ERP showed raw Axios 404 |
| B3 | Admin shell not auth-gated | `MainLayout` allowed unauthenticated chrome; Settings empty; SAT infinite spinner |

---

## 3. Root causes

### B1 — Adaptive optional JWT

`POST /api/query/adaptive` and `GET /api/query/adaptive/history` used `get_current_user_optional`. Missing/invalid tokens became `current_user=None` and the handler still ran SAP SQL.

### B2 — Dashboard router silent drop

`server.py` wrapped `include_router` in `except Exception: log only`. `dashboard.py` imported unused `answer_with_sap_sql_agent` from the ~5k-line `sap_sql_agent` module at import time. That import is the most likely Vercel registration failure. Failed routers vanished from OpenAPI, so the frontend hit a real 404.

Local proof after removing the unused import: `from app.api import dashboard` succeeds with **31** routes including `/dashboard/v2/inbound`.

### B3 — Admin gate / SAT spinner

`MainLayout` only redirected customer-portal users. Logged-out admins still got the shell. Settings fetched APIs with no user. SAT returned an unlabeled `LoadingSpinner` when `!user`, which never resolved.

---

## 4. Security changes

- `get_current_user` now treats a missing/empty Bearer token as **401** (`Could not validate credentials`) instead of FastAPI HTTPBearer’s default 403.
- Adaptive POST and history require `Depends(get_current_user)`.
- Unauthorized adaptive requests never enter the handler body; tests patch `get_sap_session` and assert it is not called.
- 401 bodies are the existing FastAPI `detail` string — no SQL, stack traces, or secrets.

Unauthenticated production result **after deploy**: HTTP **401**, no SQL. Reconfirmed after authenticated suites.

---

## 5. Admin authentication changes

`MainLayout`:

- While `authLoading`: “Checking your session…”
- If `!user`: redirect to `/?next=<path>` with “Redirecting to sign in…”
- Customer portal users still go to the portal
- Home honors a safe relative `next` (not `//`, not `/customer`)

Session expiry: Axios interceptor already logs out on JWT 401 (`Could not validate credentials`). Adaptive is not on the AI-exception list, so an expired adaptive call clears the session.

---

## 6. Dashboard route restoration

- Removed unused module-level `sap_sql_agent` import from `dashboard.py`.
- Router registration now uses `_register_router` with `logger.exception` and `ROUTER_STATUS`.
- `GET /health/routers` reports loaded/failed routers (`error_type` only, no secrets).
- If dashboard still fails to import, `/api/v1/dashboard/{path}` returns **503**, not silent 404.

Local OpenAPI includes `/api/v1/dashboard/v2/inbound` and related v2 routes.

**Production OpenAPI (post-deploy):** 181 paths, 31 dashboard routes, inbound present. **PASS.**

Expected paths after deploy (router prefix `/dashboard` + app prefix `/api/v1`):

- `/api/v1/dashboard/statistics`
- `/api/v1/dashboard/ai-insights`
- `/api/v1/dashboard/operations`
- `/api/v1/dashboard/v2/inbound`
- `/api/v1/dashboard/v2/inbound/recent`
- `/api/v1/dashboard/v2/outbound`
- `/api/v1/dashboard/v2/failed-invoices-analysis`
- `/api/v1/dashboard/v2/failed-invoices-ai-insights`
- `/api/v1/dashboard/v2/business`
- `/api/v1/dashboard/v2/sap-historical`
- `/api/v1/dashboard/v2/customer-comparison`
- `/api/v1/dashboard/v2/customer-comparison-chat`
- `/api/v1/dashboard/ai-analysis/chat`
- `/api/v1/dashboard/ai-analysis/schema-chat`
- `/api/v1/dashboard/ai-analysis/schema-chat/history`
- `/api/v1/dashboard/ai-analysis/store-query`
- `/api/v1/dashboard/ai-analysis/reject-query`
- `/api/v1/dashboard/ai-analysis/suggest-sql`
- `/api/v1/dashboard/ai-analysis/schema`
- `/api/v1/dashboard/ai-analysis/approve-query`
- `/api/v1/dashboard/ai-analysis-multi-model`
- `/api/v1/dashboard/training-feedback`
- `/api/v1/dashboard/voice-transcribe`
- `/api/v1/dashboard/training-stats`
- `/api/v1/dashboard/auto-fix-details`
- `/api/v1/dashboard/business`
- `/api/v1/dashboard/industry-intelligence`
- `/api/v1/dashboard/revenue-analysis`
- `/api/v1/dashboard/product-demand`
- `/api/v1/dashboard/dashboard-data-stats`
- `/api/v1/dashboard/backfill-invoice-v2-bi`

---

## 7. Settings / SAT fixes

**Settings:** wait for authenticated user before API-key fetch; profile still shows from `user`; error banner + retry; API errors go through `publicApiError`.

**SAT:** removed the logged-out unlabeled spinner. `MainLayout` gates the page. Document fetch failures show copy + Retry. Empty state remains “No Documents”.

---

## 8. To ERP fix

**Problem:** Dashboard tab **To ERP** calls `GET /api/v1/dashboard/v2/inbound` (inbound SAT KPIs, not a live ERP push). Missing router → Axios 404.

**Fix:** restore dashboard registration; map 404/5xx to “This dashboard service is temporarily unavailable. Please try again.”

**Not fabricated:** this tab does not synchronize to an ERP. Success is inbound SAT statistics for the signed-in user. Failure is a human-readable error, not `AxiosError`.

---

## 9. AI UX changes

- Removed fake 15-stage pipeline copy.
- Progress is a single current step: Understanding → Checking business data → Analyzing → Preparing. Slow-load notes after 5s / 20s. Query is not delayed for animation.
- Header: “Business intelligence / Governed answers from your SAP data”.
- Duplicate markdown + summary reduced when they match.

---

## 10. DATA GAP UX

`answer_status === CANNOT_ANSWER` renders a **Data limitation** card (amber), not a red application error.

Copy: the question was understood; required data is unavailable; no unsupported number was calculated; conversation/context continues.

Backend DATA GAP semantics were not changed.

---

## 11. Follow-up UX

Frontend maps semantic drilldown labels to short chips and canonical questions (`Show their customers.`, `Show their regions.`, `Show their inventory.`, …). SAP parentheticals (LAND1, WAVWR, MBEW) are not shown as chip text. Resolver matching is unchanged.

---

## 12. Product identity improvements

Light pass only:

- Metadata title: **BridgeEDI**
- Login: BridgeEDI — invoice ops + governed SAP questions
- Sidebar: BridgeEDI; nav **Intelligence** (`/dashboard/ai` unchanged)
- Account Mapping uses a distinct icon from Settings

No full redesign.

---

## 13. Responsive / accessibility changes

- Password show/hide control has `aria-label`
- Auth-gate and SAT/Settings states have readable text (not a blank spinner)
- Dashboard tabs already hide labels on small screens
- Broader 390–1440 visual QA executed on production (see §16). No critical overflow, AxiosError, or blank-screen issues recorded. At 390px the sidebar is an overlay with Close/Toggle menu; To ERP tabs remain usable.

---

## 14. Automated tests

| Suite | Result |
| --- | --- |
| `tests/test_adaptive_auth.py` | PASS (no JWT, invalid, expired, malformed, empty Bearer, wrong scheme, valid JWT, real endpoint no `get_sap_session`) |
| `tests/test_dashboard_router_registration.py` | PASS (import, OpenAPI paths, `/health/routers`) |
| `tests/test_r3_golden_benchmark.py` | PASS |
| `tests/test_r4_1_month_quarter_trends.py` | PASS |
| `tests/test_r4_2_product_growth_decline.py` | PASS |
| `tests/test_r4_3_inventory_sales.py` | PASS |
| `tests/test_analytical_followup_resolver.py` | PASS |
| Combined above | **85 passed**, then dashboard tests **4/4** after tightening the sap_sql_agent assertion |
| Frontend `test:ux` + `test:adaptive-context` | **13 passed** |

Analytical engine files were not modified.

---

## 15. R3 regression

Local golden suite: **PASS**.

Live (`scripts/r3_post_deploy_live_acceptance.py` against zodiac-back, authenticated):

**23 PASS / 2 DATA GAP / 0 FAIL**

- Canonical `canonical_verdict`: `23 PASS / 2 DATA GAP / 0 FAIL`
- `r3_deployed_evidence=true` (`suppliers_of_selection` + EKPO; `product_group_breakdown` + MATKL)
- Short follow-ups 17/17; data-gap recovery 3 PASS + 2 DATA GAP; supplier-profit safety PASS
- P50 **772ms**, P95 **1087ms**, max **1951ms**

---

## 16. R4-1 regression

Local suite: **PASS**.

Live: **47 PASS / 2 DATA GAP / 0 FAIL** (49 scored turns).

Verified monthly/quarterly revenue, COGS, GP, margin, ASP, MoM, QoQ, 2004/2005 monthly and quarterly, monthly margin decline, DATA GAP recovery, Full Chat / basic-GA non-hijack.

Suite wall-clock P50 **779ms**. Analytical probes P95 **1372ms**. Three `basic_ga` turns (`2004`, `Top 5`) ran 9–13s and pull full-suite P95 to **9163ms**. Those are not normal governed-metric queries; they still **PASS**. Analytical behavior was not changed to chase the 3s target.

---

## 17. R4-2 regression

Local suite: **PASS**.

Live: **40 PASS / 1 DATA GAP / 0 FAIL**.

Verified product growth/decline, absolute and percentage growth, metric-specific growth, MoM, QoQ, YoY, zero prior period, empty period, context, DATA GAP recovery.

P50 **750ms**, P95 **1167ms**.

---

## 18. R4-3 regression

Local suite: **PASS**.

Live: **31 PASS / 6 DATA GAP / 0 FAIL**.

Verified inventory snapshot/value/quantity, highest inventory, inventory vs revenue and quantity, high inventory / low sales, product group, plant, product context, customer/supplier/region follow-ups, inventory aging DATA GAP, unsupported turnover DATA GAP, DATA GAP recovery, grain safety.

P50 **755ms**, P95 **1097ms**. Grain guard / inventory engine files were not modified in `7f1f7cd`.

---

## 19. Full Chat acceptance

Authenticated production: `https://www.bridgeedi.com/dashboard/ai` (Full Chat tab).

| Turn | Question | Intent / heading | Rows | Result |
| --- | --- | --- | ---: | --- |
| 1 | Show the products with the highest profits. | `product_profitability` | 10 | PASS — top Ship Project, revenue 973,700,000 INR |
| 2 | Show their inventory. | `inventory_analysis` / `stock_value_by_material` | 30 | PASS — Fire fighting vehicle 1,741,481,295.73 at valuation area 4110 |
| 3 | Show their sales. | `product_profitability` | 10 | PASS — sales of selected products |
| 4 | Which have high inventory but low sales? | `inventory_risk_analysis` | 9 | PASS |
| 5 | Show their product groups. | `product_group_breakdown` | 12 | PASS |
| 6 | Show their suppliers. | `suppliers_of_selection` | 9 | PASS |
| 7 | Show their customers. | `customers_of_selection` / `customers_of_products` | 30 | PASS |
| 8 | Show their regions. | `country_breakdown` | 18 | PASS |
| 9 | Show inventory by plant. | `inventory_by_plant` | 17 | PASS |
| 10 | Compare their sales with last year. | `period_compare_selection` / `period_compare` | 9 | PASS |
| 11 | Why? | `dimensional_extend` | 9 | PASS |

### AI UX

- Progress: “Working on your question” / **Understanding your question** observed. No fake 15-stage pipeline.
- Follow-up chips: `Show customers`, `Break down by industry`, `Break down by region`, `Compare with last year`, `Show monthly trend`, `Show quarterly trend`, `Show products`, `Show COGS`. No LAND1/MBEW/WAVWR on chip labels.
- Note (non-blocking): the “Available deeper analysis” list still mentions BRSCH, LAND1, VBRK.FKDAT. Chips do not.
- DATA GAP vs application failure: aging rendered an amber **Data limitation** card, not a red Query failed / AxiosError.

### DATA GAP recovery

1. `Show inventory aging.` → **DATA GAP**. Copy: MSEG movement history is not in this extract; billing/creation/expiry dates are not inventory age. No aging buckets fabricated.
2. `Show inventory again.` → **PASS** `inventory_analysis`, 13 rows (selected-product context kept).

### Second DATA GAP recovery (New question)

1. `Show inventory.` → **PASS** `inventory_analysis`, 30 rows
2. `Show net profit.` → **DATA GAP** (amber card; not an application error)
3. `Show inventory.` → **PASS** `inventory_analysis`, 30 rows

---

## 20. Security production tests

Re-run **after** authenticated suites.

| Test | Expected | Actual | Status |
| --- | --- | --- | --- |
| Adaptive no JWT | 401, no SQL | **401**, no SQL | **PASS** |
| Adaptive invalid JWT | 401, no SQL | **401**, no SQL | **PASS** |
| Adaptive expired JWT | 401, no SQL | **401**, no SQL | **PASS** |
| Adaptive valid JWT | existing R3–R4-3 | **200** SUCCESS / inventory 30 rows | **PASS** |
| Admin logged out | auth redirect | Settings/SAT/Dashboard/AI → `/?next=…` | **PASS** |
| Dashboard inbound no JWT | 401 | **401** | **PASS** |
| Unauthorized SQL | Blocked | 401 body has no `sql` / SELECT | **PASS** |

---

## 21. OpenAPI verification

**Production:** 181 paths, **31** `/api/v1/dashboard/*`, `/api/v1/dashboard/v2/inbound` present, `/health/routers` present. **PASS.**

---

## 22. Authenticated inbound / To ERP / Settings / SAT

### Inbound API

```text
Endpoint  GET /api/v1/dashboard/v2/inbound
Status    200
Rows      summary.total_documents=14; merges_total=4; merges_sent_to_sap=4; merges_pending=0
          by_document_type=3 (CREDIT_NOTE 5, INVOICE 4, PAYMENT 5)
          by_source=2 (admin 7, supplier 7); by_period=5; top_suppliers=3; tokens.total=2
Latency   582ms (API); browser XHR ~774ms inbound + ~751ms inbound/recent
Result    PASS
```

### To ERP

Dashboard default tab **To ERP** is the inbound SAT KPI view (`GET /api/v1/dashboard/v2/inbound`), **not** an ERP push.

Authenticated UI: SAT Documents 14, Merges 4, Sent to SAP 4, Pending 0; By Document Type / By Source charts; Supplier Tokens; Top Suppliers; Recently Received Documents. No 404, no raw AxiosError.

### Settings

Session resolved after “Checking your session…”. Profile (username/email), notification toggles, processing preferences, Suspend Key / Regenerate Key rendered. No blank screen, no infinite spinner.

### SAT

SAT Documents (14) table with VALIDATED credit notes, payments, invoices; Filters / Bulk Upload / Details. No raw technical error, no infinite spinner.

---

## 23. Independent SQL

Production database compared to live authenticated adaptive answers. Harness `scripts/r4_3_independent_sql.py` plus plant/revenue spot checks. Credentials were not written into the report.

| Question | Metric | AI | Independent SQL | Difference | Difference % | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Show inventory. | stock_value (rank 1–2 tie) | 25,000,000,000 | 25,000,000,000 | 0 | 0.00 | PASS (tie: ME_4003 vs ME_4002) |
| Show inventory. | stock_qty (same materials) | 50,000 | 50,000 | 0 | 0.00 | PASS |
| Highest profits | revenue | 973,700,000 (SHIP_PROJECT) | 973,700,000 (SHIP_PROJECT) | 0 | 0.00 | PASS |
| Inventory vs sales | stock_value top 5 | ME_4001/4003/4002, IMC_6000/8000 | same keys and values | 0 | 0.00 | PASS |
| Inventory vs sales | revenue on inventory-only top | 0 / null | 0 / null | 0 | 0.00 | PASS |
| Inventory by product group | stock_value | 100,089,299,823.21 (00104) | 100,089,299,823.21 (00104) | 0 | 0.00 | PASS |
| Inventory by plant | plant key | 3000 | 3000 | — | — | PASS (key). AI plant view is unrestricted qty + material count, not MBEW SALK3; not the same metric |

The independent script’s 8 `ok=false` rows are **rank-order ties** at identical stock_value (ME_4003/ME_4002 at 25B; IMC_8000/IMC_6000 at 12.5B). Values match exactly. No unexplained material mismatch.

---

## 24. Performance

Authenticated sample (`Show inventory.`): `plan_ms=0`, `db_ms=200`, `transform_ms=0`, engine `total_ms=201`, HTTP **633ms**.

| Suite | P50 | P95 | Notes |
| --- | ---: | ---: | --- |
| R3 live | 772ms | 1087ms | max 1951ms |
| R4-1 analytical (ex-GA) | 779ms | 1372ms | target met |
| R4-1 full suite | 779ms | 9163ms | 3 basic_ga turns 9–13s |
| R4-2 live | 750ms | 1167ms | |
| R4-3 live | 755ms | 1097ms | |
| Inbound API | 582ms | — | |

Normal governed queries meet P50 &lt; 1s and P95 &lt; 3s. Full R4-1 P95 is outside 3s only because of basic-GA probes. Analytical SQL was not changed.

---

## 25. Production UI / console / frozen engine

### Responsive (390 / 768 / 1024 / 1280 / 1440)

No horizontal overflow (`scrollWidth` ≤ viewport + 8px) on Dashboard, Settings, SAT, Full Chat. Login branding BridgeEDI. No AxiosError. No blank screens after session resolve.

Actual issue recorded: at **390px** the sidebar is a full overlay (Close menu / Toggle menu). Content is reachable after closing the menu. Not treated as a hardening blocker.

### Console

Hooked `console.error` / `window.onerror` on Full Chat: no critical JS errors. Authenticated XHR: `/api/v1/user/auth/fetch_user`, `/api/v1/dashboard/v2/inbound`, `/inbound/recent`, `/outbound`, `/api/query/adaptive/history` succeeded. No unexpected 404/500, no auth loop, no infinite polling observed.

### Frozen engine

`7f1f7cd` did not modify `inventory_sales.py`, `sql_grain_guard.py`, `analytical_followup_resolver.py`, `analytical_deep_dive.py`, or `business_intelligence_inventory.py`. Working tree matches that commit for those files. Live R3–R4-3 scores match the frozen baselines.

---

## 26. Deployment

| Item | Status |
| --- | --- |
| Target | **zodiac-back** only (not `zodiac-api-nu`) |
| Code | `7f1f7cd` live |
| This CLI Vercel account | cannot see Andy’s `zodiac-back`; Andy deployed |
| Live verify | **COMPLETE** |

No further deploy was made from this environment.

---

## 27. Remaining limitations (non-blocking)

1. To ERP is inbound SAT analytics, not a live ERP push.
2. Intelligence Snapshot tab remains operational KPIs without auto-refresh.
3. Settings notification toggles remain local UI preferences.
4. “Available deeper analysis” copy still includes some SAP field names; follow-up chips do not.
5. R4-1 basic-GA probes can take 9–13s; normal analytical P95 stays under 3s.

---

## 28. Next phase

Product roadmap is a **separate decision**. **Do not start R4-4.**

---

## Original blocker close-out

### Adaptive auth

- **Problem:** Unauthenticated analytical SQL.
- **Production:** no JWT / invalid / expired → **401**, no SQL. Valid JWT → SUCCESS. **PASS.**

### Dashboard routes

- **Problem:** OpenAPI missing dashboard paths; To ERP 404.
- **Production:** 31 dashboard paths; authenticated inbound 200; To ERP renders inbound SAT KPIs. **PASS.**

### Admin / Settings / SAT

- **Problem:** empty Settings; SAT spinner; unauthenticated shell.
- **Production:** logged-out redirect; logged-in Settings and SAT render. **PASS.**

---

## Acceptance matrix

| Area | Expected | Actual | Status |
| --- | --- | --- | --- |
| Adaptive no JWT | 401 | 401, no SQL | **PASS** |
| Invalid JWT | 401 | 401, no SQL | **PASS** |
| Expired JWT | 401 | 401, no SQL | **PASS** |
| Unauthorized SQL | Blocked | 401, no SQL in body | **PASS** |
| Authenticated adaptive | PASS | 200 SUCCESS / deep_multidim | **PASS** |
| OpenAPI | 181+ paths | 181 | **PASS** |
| Dashboard routes | 31 | 31 | **PASS** |
| Router health | 0 failed | 20 loaded, `failed=[]`, `dashboard.loaded=true` | **PASS** |
| Inbound API | PASS | 200, 14 documents, 582ms | **PASS** |
| To ERP | PASS | Inbound SAT KPIs rendered; not an ERP push | **PASS** |
| Settings | PASS | Profile + API key UI | **PASS** |
| SAT | PASS | 14 documents table | **PASS** |
| Full Chat | PASS | 11-turn chain | **PASS** |
| DATA GAP | Correct | Aging / net profit amber Data limitation | **PASS** |
| DATA GAP recovery | PASS | Aging→inventory; inventory→net profit→inventory | **PASS** |
| R3 | 23/2/0 | 23/2/0 | **PASS** |
| R4-1 | 47/2/0 | 47/2/0 | **PASS** |
| R4-2 | 40/1/0 | 40/1/0 | **PASS** |
| R4-3 | 31/6/0 | 31/6/0 | **PASS** |
| Independent SQL | PASS | 0.00% value diffs; explained rank ties | **PASS** |
| Performance | Documented | See §24 | **PASS** |
| Console | No critical errors | None observed | **PASS** |
| Responsive | PASS | 390–1440; overlay menu at 390px only | **PASS** |
