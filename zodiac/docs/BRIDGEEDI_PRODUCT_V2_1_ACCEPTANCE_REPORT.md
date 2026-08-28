# BridgeEDI Product V2.1 + R4 — Acceptance Report

**Date:** 2026-08-28  
**Branch:** `phase12-first-customer-ready`  
**Baseline:** Product V2 live on `https://www.bridgeedi.com`; engine freeze R3–R4-3 on `https://zodiac-back.vercel.app`  
**Credentials:** not included.

---

## Executive result

```text
WHAT WAS AUDITED
  Live V2 product (login → Overview → AI Analyst → SAT → Settings),
  nav/IA, session flash, Axios leaks, trust panel, R4 roadmap vs engine,
  grain guard, DATA GAP, auth, /health/routers, Vercel project access.

WHAT WAS IMPROVED
  Session restore without wiping the shell when a cached user exists.
  Overview next-actions + EDI vs SAP P&L labeling.
  Trust panel: source/definition/aggregation/period/result size by intent.
  DATA GAP try-instead is intent-aware (net profit ≠ inventory chips).
  SAT counts loading/error/retry; human status labels; publicApiError.
  Settings security copy without JWT jargon.
  AI Analyst route no longer embeds Operations/Snapshot EDI tabs
  (those remain under Operate → EDI operations). Overview ?q= still works.

WHAT WAS IMPLEMENTED
  R4-4 supplier_concentration: EKPO/EKKO/LFA1, share_of_po_value_pct,
  no VBRP join, no supplier profit. R3 "Show their suppliers." unchanged.
  See R4_4_PRODUCTION_ACCEPTANCE_REPORT.md.

WHAT WAS FIXED
  Operator-facing Axios error strings on SAT upload/merge/send.
  Overview celebrating a "clear pipeline" on an empty account.
  Inventory results showing billing NETWR/WAVWR as the definition.

WHAT WAS DEPLOYED
  Nothing from this CLI. Vercel account karthikeyanasha24 / team
  ashas-projects-a0fae821 sees zodiac-api → zodiac-api-nu, hrm53v1,
  banyanqi-react. BridgeEDI frontend and zodiac-back are not visible.
  No new Vercel project. No DNS change. Not deployed to zodiac-api-nu.

R3 RESULT
  23 PASS / 2 DATA GAP / 0 FAIL (p50 582ms, p95 1519ms, max 11145ms)

R4-1 RESULT
  47 PASS / 2 DATA GAP / 0 FAIL

R4-2 RESULT
  40 PASS / 1 DATA GAP / 0 FAIL (p50 746ms, p95 1147ms, max 11392ms)

R4-3 RESULT
  31 PASS / 6 DATA GAP / 0 FAIL (p50 598ms, p95 1276ms, max 11049ms)

R4-4 RESULT
  Local: implemented + goldens PASS.
  Live: NOT_DEPLOYED (concentration still suppliers_of_selection).
  Independent SQL vs AI: BLOCKED.

INDEPENDENT SQL RESULT
  PO-grain shares computed (top supplier 49.35%). AI compare BLOCKED.

SECURITY RESULT
  Live POST /api/query/adaptive: no JWT / empty Bearer / wrong scheme /
  invalid JWT / malformed JWT / expired-shaped JWT → HTTP 401, no SQL.
  GET /health/routers: status=ok, dashboard.loaded=true, failed=[], loaded_count=20.

PERFORMANCE RESULT
  Normal analytical p50 < 1s, p95 < 3s on R3/R4-2/R4-3.
  Known cold/outlier path ~11s on first deep_multidim of a suite.

UI/UX RESULT
  Live www is still Product V2 (not V2.1). V2 journey works:
  Overview, AI Analyst (How this was calculated, View SQL hidden),
  SAT counts, Settings. 390px viewport usable. Session flash still
  shows "Checking your session…" on route change (fixed in V2.1, not live).
  Duplicate Ask/Operations/Snapshot tabs still on live AI Analyst
  (removed in this branch, not live).

FULL CHAT RESULT
  Live 15-turn chain PASS: profits → inventory → sales → high inv/low sales
  → groups → suppliers → customers → regions → plant → YoY compare → Why?
  → aging DATA GAP → inventory PASS → net profit DATA GAP → inventory PASS.

FINAL PRODUCT SCORE
  Previous V2 score: 7/10 (later V2 go-live report: 8/10).
  V2.1 implemented quality: 8/10. Production remains V2 until deploy.

REMAINING LIMITATIONS
  Aging / true turnover / net profit / logistics cost / budget — DATA GAP.
  R4-4 share % not on zodiac-back. V2.1 frontend not on www.
  Saved analyses device-local. No HHI / invented risk flags.
  "Show supplier profit" still lists PO suppliers (no billing fan-out).
  Overview EDI invoice totals can be 0 (not fabricated SAP P&L).

FINAL VERDICT
  BRIDGEEDI V2.1 + R4 — NOT COMPLETE
```

---

## Architecture (unchanged path)

```text
classify_turn → resolve follow-up → governed plan → compile SQL
→ grain guard → execute → explain → drill-downs
```

Monetary billing stays on `vbrp`/`VBRK`. Purchase concentration stays on `EKPO`/`EKKO`/`LFA1`. Inventory stays snapshot (`MBEW`/`MARD`). No ACDOCA/MSEG metrics.

---

## Page inventory (live V2 vs this branch)

| Page | Route | Purpose | Live www | This branch |
| --- | --- | --- | --- | --- |
| Overview | `/overview` | What happened / what to ask | V2 snapshot + 6 chips | Next-actions, EDI invoice total, supplier concentration chip |
| AI Analyst | `/dashboard/ai` | Governed NL analysis | IntelligencePage + Ask/Operations/Snapshot | Analyst only; `?q=` preserved |
| EDI operations | `/dashboard` | Inbound/outbound/business | Unchanged | Unchanged |
| SAT | `/sat-documents` | CFDI intake | Counts + tabs | Loading/error/retry + human labels |
| Settings | `/settings` | Profile / security / API | JWT jargon in Security | Human session copy |
| Login | `/` | Auth | Protected routes redirect | Same JWT requirement |

---

## Live customer journey (2026-08-28, www.bridgeedi.com)

Viewport during this pass: **390×844**.

| Step | Observation |
| --- | --- |
| Login | Existing session; Overview loaded as home |
| Overview | Understand/Ask/Operate/Manage. Needs attention 0 pending / 14 SAT. Period revenue 0 (EDI invoices, not SAP P&L). Six investigation chips. No V2.1 "What to do next". No supplier concentration chip. Labels still "Account mapping" / "Supplier tokens". |
| AI Analyst | Question → analysis → How this was calculated → View SQL. Duplicate Ask/Operations/Snapshot still present. Session flash on navigation. |
| SAT | 14 documents, 0 waiting, 4 sent. Table + filters. |
| Settings | Profile / Security / API / Account. Security still mentions JWT. |

Could a business user complete a demo on live V2 without a developer? **Yes, for V2.** V2.1 copy and IA are not on the domain yet.

---

## Tests

| Suite | Result |
| --- | --- |
| Frontend `test:ux` | **15 PASS** |
| Frontend `test:adaptive-context` | **8 PASS** |
| Pytest R3 + R4-1 + R4-2 + R4-3 + R4-4 unit/golden | **76 PASS** |
| Pytest `test_adaptive_auth` | PASS |
| `test_dashboard_does_not_import_sap_sql_agent_at_module_level` | Pre-existing FAIL (module-level import). Production `/health/routers` still `dashboard.loaded=true`. Not changed in this work. |

---

## Production

| Surface | Target | This environment |
| --- | --- | --- |
| Frontend | `https://www.bridgeedi.com` | V2 live; V2.1 needs frontend deploy of this branch |
| Backend | `https://zodiac-back.vercel.app` | R3–R4-3 live; R4-4 not live |
| Not used | `zodiac-api-nu` | Not deployed |

---

## Live regression (production backend)

| Suite | Required | Actual | Status |
| --- | --- | --- | --- |
| R3 | 23/2/0 | **23 PASS / 2 DATA GAP / 0 FAIL** (p50 582ms, p95 1519ms, max 11145ms) | PASS |
| R4-1 | 47/2/0 | **47 / 2 / 0** | PASS |
| R4-2 | 40/1/0 | **40 / 1 / 0** | PASS |
| R4-3 | 31/6/0 | **31 / 6 / 0** | PASS |
| R4-4 live | `supplier_concentration` + share % | NOT_DEPLOYED | BLOCKED |
| Independent SQL | share % match | DB computed; AI compare requires live intent | BLOCKED |
| Adaptive no JWT | 401, no SQL | 401, no SQL | PASS |
| `/health/routers` | dashboard.loaded=true, failed=[] | Confirmed | PASS |
| Full Chat | Context + DATA GAP recovery | 15 turns as specified | PASS |

---

## Final acceptance matrix

| Area | Expected | Actual | Status |
| --- | --- | --- | --- |
| V2.1 product UX | Complete on www | Implemented on branch; www is V2 | BLOCKED |
| Overview | PASS | Live V2 PASS; V2.1 not live | BLOCKED (V2.1) |
| Understand | PASS | Live nav PASS | PASS (V2) |
| Ask | PASS | Live AI Analyst PASS | PASS (V2) |
| Operate | PASS | SAT + EDI PASS | PASS (V2) |
| Manage | PASS | Settings/admin links PASS | PASS (V2) |
| AI Analyst | PASS | Live analysis + trust panel V2 | PASS (V2) |
| Context | PASS | Full Chat + suites | PASS |
| Follow-ups | PASS | Full Chat | PASS |
| DATA GAP | PASS | Aging + net profit + recovery | PASS |
| SAT | PASS | Live counts/table | PASS (V2) |
| Settings | PASS | Live profile/API | PASS (V2) |
| Authentication | PASS | 401 probes | PASS |
| API security | PASS | No SQL without JWT | PASS |
| Responsive | PASS | 390px Overview/AI/SAT usable | PASS (V2) |
| Accessibility | PASS | Skip link, buttons, labels; no critical blocker | PASS |
| Performance | P50&lt;1s P95&lt;3s | Met except known ~11s first deep query | PASS |
| R3 | 23/2/0 | 23/2/0 | PASS |
| R4-1 | 47/2/0 | 47/2/0 | PASS |
| R4-2 | 40/1/0 | 40/1/0 | PASS |
| R4-3 | 31/6/0 | 31/6/0 | PASS |
| R4-4 | Governed acceptance | Local PASS; live NOT_DEPLOYED | BLOCKED |
| Independent SQL | PASS | BLOCKED | BLOCKED |
| Grain safety | PASS | Guard + live no VBRP⋈EKPO on supplier probes | PASS |
| Full Chat | PASS | 15-turn live chain | PASS |
| Production V2.1 | PASS | V2 only | BLOCKED |

---

## Final product score

Previous V2 score: **7/10** (production V2 go-live later scored **8/10**).

| Category | Score |
| --- | --- |
| Product clarity | 8 |
| UI | 8 |
| UX | 8 |
| Analytical intelligence | 8 (R4-4 local; live still R4-3) |
| Trust | 8 |
| Security | 8 |
| Reliability | 8 |
| Performance | 8 (p50 &lt; 1s; rare outlier ~11s) |
| Responsiveness | 8 |
| Accessibility | 7 |
| Enterprise readiness | 7 |
| Customer-demo readiness | 8 (V2 demo path works) |
| Differentiation | 8 |
| **Overall V2.1 (implemented)** | **8/10** |

Not 9: saved analyses remain local; R4-4 is not on live `zodiac-back`; V2.1 is not on `www.bridgeedi.com`; Overview EDI totals can be 0; cold session flash still exists on live V2.

---

## Remaining limitations

1. Inventory aging, true turnover, net profit, logistics cost, budget — DATA GAP.
2. R4-4 share % is not on production until `zodiac-back` is deployed from this branch.
3. This CLI cannot deploy `www.bridgeedi.com` or `zodiac-back`.
4. Saved analyses are device-local.
5. No HHI / automated single-source risk threshold (would be invented policy).
6. R4-5 delivery cycle and R4-6 customer mix were inspected and **not** implemented (insufficient governed schema / would be a new roadmap, not this assignment's freeze).

---

## Blocker policy

| Item | Class | Evidence | Fix | Production safe as-is? |
| --- | --- | --- | --- | --- |
| V2.1 frontend not on www | BLOCKED | Live Overview lacks next-actions / concentration chip / friendlier admin labels; Settings still says JWT; AI still has Operations/Snapshot tabs | Deploy existing BridgeEDI frontend project from this branch | Yes — leave V2 |
| R4-4 share % not on zodiac-back | BLOCKED | Live intent `suppliers_of_selection` for concentration | Andy deploys `zodiac-back` only | Yes — leave R4-3 |
| Independent SQL vs AI | BLOCKED | No live `supplier_concentration` | After backend deploy, re-run independent script | Yes |
| Aging / net profit | DATA GAP | Schema (MSEG/ACDOCA absent) | Do not fabricate | Yes |
| Dashboard unit import test | FAIL (pre-existing, local only) | `dashboard.py` imports sap_sql_agent at module level | Separate hardening; live routers healthy | Yes |

---

## Final verdict

# BRIDGEEDI V2.1 + R4 — NOT COMPLETE

1. **Blocker:** this environment cannot deploy the existing BridgeEDI frontend or `zodiac-back`.  
2. **Evidence:** `npx vercel project ls` shows only `zodiac-api` → `zodiac-api-nu`, `hrm53v1`, `banyanqi-react`. Live www still serves V2 chrome. Live concentration intent is still `suppliers_of_selection`.  
3. **Affected area:** V2.1 UX on `www.bridgeedi.com`; R4-4 on `zodiac-back`.  
4. **Exact required fix:** From the account that already owns those Vercel projects, deploy **frontend** to the existing BridgeEDI project and **backend** to `zodiac-back` only. Then re-run this report's live matrix.  
5. **Production is safe to leave as-is:** live V2 + R3/R4-1/R4-2/R4-3 baselines held; auth 401; routers healthy.

Do not declare completion from GitHub push or local tests.
