# P0/P1 Production Hardening — Acceptance Report

## 1. Executive verdict

# PRODUCTION HARDENING NOT COMPLETE

Local implementation and unit tests passed. Production is **not** yet updated.

Live `https://zodiac-back.vercel.app` still behaves as the pre-fix audit:

- `POST /api/query/adaptive` without JWT → **HTTP 200** and MBEW inventory SQL
- OpenAPI → **149 paths, zero `/api/v1/dashboard/*`**
- `GET /health/routers` is not present

This CLI cannot deploy to Andy’s **zodiac-back** Vercel project. Until that deploy happens and live checks pass, hardening is **BLOCKED** on production verification.

Do not start R4-4.

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

Unauthenticated production result **before deploy**: HTTP 200 + SQL (**FAIL**, expected until zodiac-back is updated).

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

**Production OpenAPI (pre-deploy):** dashboard_count = 0. **BLOCKED.**

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
- Broader 390–1440 visual QA is **BLOCKED** until production frontend deploy

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

Local golden suite: **PASS**. Live Full Chat R3 23/2/0: **BLOCKED** (needs deploy + `LIVE_API_TOKEN` or `LIVE_API_EMAIL`/`LIVE_API_PASSWORD`).

Live harnesses now send `Authorization` via `scripts/live_http.py`.

---

## 16. R4-1 regression

Local suite: **PASS**. Live 47/2/0: **BLOCKED**.

---

## 17. R4-2 regression

Local suite: **PASS**. Live 40/1/0: **BLOCKED**.

---

## 18. R4-3 regression

Local suite: **PASS**. Live 31/6/0: **BLOCKED**. Grain guard / inventory engine untouched.

---

## 19. Full Chat acceptance

Local UI changes are in `DashboardAIAnalysis`. Authenticated production chain on `https://www.bridgeedi.com/dashboard/ai`: **BLOCKED** until frontend + backend deploy.

---

## 20. Security production tests

| Test | Expected | Actual (live, pre-deploy) | Status |
| --- | --- | --- | --- |
| Adaptive no JWT | 401/403, no SQL | HTTP 200 + MBEW SQL | **FAIL / not deployed** |
| Adaptive invalid JWT | 401/403 | not re-tested live | **BLOCKED** |
| Adaptive valid JWT | existing R3–R4-3 | not re-tested live | **BLOCKED** |
| Admin logged out | auth redirect | code-complete, not live-verified | **BLOCKED** |
| Dashboard inbound no JWT | 401/403 | live 404 (router missing) | **FAIL / not deployed** |

---

## 21. OpenAPI verification

**Local:** dashboard routes present.

**Production:** 149 paths, **0** `/api/v1/dashboard/*`, no `/health/routers`. **FAIL until deploy.**

---

## 22. Performance

No analytical engine change. R4-3 prior live P50 775ms / P95 1230ms remain the last production baseline.

This pass did not re-measure live P50/P95. **BLOCKED** for post-deploy numbers.

Auth check adds JWT decode + user lookup only; it does not change SQL grain or DATA GAP behavior.

---

## 23. Deployment

| Item | Status |
| --- | --- |
| Target | **zodiac-back** only (not `zodiac-api-nu`) |
| `.vercel/project.json` | gitignored / not on this machine |
| This CLI Vercel account | cannot see Andy’s `zodiac-back` |
| Push | to be done on `phase12-first-customer-ready` |
| Live verify after deploy | **BLOCKED** |

Live scripts: set `LIVE_API_TOKEN` or `LIVE_API_EMAIL` + `LIVE_API_PASSWORD`.

---

## 24. Remaining limitations

1. Production not deployed from this environment.
2. Live R3–R4-3 and Full Chat not re-run with JWT.
3. Responsive pass at 390/768/1024/1280/1440 not executed in browser this pass.
4. To ERP is inbound SAT analytics, not a real ERP push.
5. Intelligence “Snapshot” tab is still the same operational KPIs without auto-refresh — copy now says so.
6. Notification toggles on Settings remain local UI preferences, not a new backend.

---

## 25. Recommended next phase

1. Andy deploys this branch to **zodiac-back** (and frontend to bridgeedi.com).
2. Live security: adaptive no JWT → 401; OpenAPI dashboard paths present; `/health/routers` `dashboard.loaded=true`.
3. Live R3/R4-1/R4-2/R4-3 with `LIVE_API_TOKEN`.
4. Logged-out Settings/SAT/Dashboard → login; logged-in To ERP loads without Axios 404.
5. Only then plan product roadmap. **Do not start R4-4.**

---

## Blocker evidence template

### Adaptive auth

- **Problem:** Unauthenticated analytical SQL.
- **Root cause:** `get_current_user_optional`.
- **Code change:** `get_current_user` on adaptive POST/history; HTTPBearer missing token → 401.
- **Test:** `tests/test_adaptive_auth.py` — PASS locally.
- **Expected:** 401, `get_sap_session` not called.
- **Actual (local):** 401, spy not called.
- **Production:** still 200 + SQL. **NOT DEPLOYED.**

### Dashboard routes

- **Problem:** OpenAPI missing `/api/v1/dashboard/*`; To ERP 404.
- **Root cause:** silent `include_router` failure; unused `sap_sql_agent` import.
- **Code change:** drop unused import; `/health/routers`; 503 stub if load fails.
- **Test:** `tests/test_dashboard_router_registration.py` — PASS locally.
- **Expected:** OpenAPI contains v2 inbound/outbound/business.
- **Actual (local):** present.
- **Production:** 0 dashboard paths. **NOT DEPLOYED.**

### Admin / Settings / SAT

- **Problem:** empty Settings; SAT spinner; unauthenticated shell.
- **Root cause:** no `MainLayout` auth gate; SAT `!user` spinner.
- **Code change:** gate + redirect; Settings/SAT loading/error/retry.
- **Test:** unit tests for error mapping; UI not browser-verified on production.
- **Production:** **BLOCKED.**

---

## Acceptance matrix

| Area | Test | Expected | Actual | Status |
| --- | --- | --- | --- | --- |
| Adaptive Auth | No JWT | 401/403 | Local 401; live 200 | LOCAL PASS / LIVE FAIL |
| Adaptive Auth | Invalid JWT | 401/403 | Local 401 | LOCAL PASS / LIVE BLOCKED |
| Adaptive Auth | Valid JWT | Existing behavior | Local 200 on mini-app | LOCAL PASS / LIVE BLOCKED |
| Admin | Logged out | Auth gate | Code complete | LOCAL PASS / LIVE BLOCKED |
| Admin | Logged in | Works | Code complete | LIVE BLOCKED |
| Settings | Authenticated | Works | Code complete | LIVE BLOCKED |
| SAT | Authenticated | Works | Code complete | LIVE BLOCKED |
| Dashboard routes | OpenAPI | Present | Local yes; live no | LOCAL PASS / LIVE FAIL |
| To ERP | Valid request | Inbound stats or clear error | Code complete | LIVE BLOCKED |
| Full Chat | R3 | 23/2/0 | Local golden PASS | LIVE BLOCKED |
| Full Chat | R4-1 | 47/2/0 | Local PASS | LIVE BLOCKED |
| Full Chat | R4-2 | 40/1/0 | Local PASS | LIVE BLOCKED |
| Full Chat | R4-3 | 31/6/0 | Local PASS | LIVE BLOCKED |
| DATA GAP | Aging | DATA GAP | Engine unchanged | LIVE BLOCKED |
| DATA GAP | Recovery | PASS | Engine unchanged | LIVE BLOCKED |
| UI | Mobile | Usable | Not live-checked | BLOCKED |
| UI | Desktop | Usable | Not live-checked | BLOCKED |
| AI UX | Follow-ups | Contextual | Unit tests PASS | LOCAL PASS / LIVE BLOCKED |
| AI UX | Pipeline | Human-readable | Code complete | LOCAL PASS / LIVE BLOCKED |
| Security | Unauthorized DB access | Blocked | Local spy PASS; live SQL runs | LOCAL PASS / LIVE FAIL |
| Performance | P50 | <1s normal | Not remeasured live | BLOCKED |
| Performance | P95 | <3s normal | Not remeasured live | BLOCKED |
