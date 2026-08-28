# BridgeEDI V2.1 + R4 — Final Production Acceptance

**Date:** 2026-08-28  
**Branch:** `phase12-first-customer-ready`  
**Canonical frontend:** `https://www.bridgeedi.com`  
**Canonical backend:** `https://zodiac-back.vercel.app`  
**Forbidden target:** `zodiac-api-nu` (not used)

# BRIDGEEDI V2.1 + R4 — NOT COMPLETE

---

## 1. Executive verdict

Product V2.1 is **live** on `www.bridgeedi.com`. Frozen analytical contracts R3 / R4-1 / R4-2 / R4-3 **still hold on live** with **0 FAIL**. R4-4 supplier concentration is **live as a follow-up** after product context, and independent SQL matches those shares at **0.00 difference**.

R4-4 is **not** live as a first question. Overview and AI welcome chips that send `Show supplier concentration.` do not enter the governed engine on the currently deployed backend. This CLI cannot deploy `zodiac-back` or the BridgeEDI frontend project.

Until that backend commit is on `zodiac-back` and first-question concentration independently matches global PO share, production completion cannot be declared.

---

## 2. Current production state

| Surface | Live now |
| --- | --- |
| Frontend | Product V2.1 (Understand / Ask / Operate / Manage; Overview command center; analyst-only AI route; Settings session language; SAT inbound-not-ERP copy) |
| Backend | R3 + R4-1 + R4-2 + R4-3 + **R4-4 follow-up** + adaptive JWT + dashboard routers |
| R4-4 first question | Count / non-deep fallback (`intent` empty, `query_plan={}`) |
| This CLI deploy | No access to canonical projects |

---

## 3. Architecture

See `zodiac/docs/BRIDGEEDI_V2_1_R4_SYSTEM_AUDIT.md`.

Governed path: question → semantic candidate → plan → SQL compiler → grain guard → execute → explain → follow-ups.

Sales = billing item. Inventory = MBEW/MARD snapshot. Purchase concentration = EKPO⋈EKKO⋈LFA1 at PO-item grain, then supplier. No VBRP⋈EKPO / VBRP⋈MBEW monetary joins.

---

## 4. Page-by-page audit (live www)

### Login (`/`)

Not re-run logged-out in this pass (session already authenticated). Code + prior live: BridgeEDI branding, purpose line, password visibility, `publicApiError`, loading, redirect with `?next=`. Customer-org link to portal login.

### Overview (`/overview`) — PASS (product)

Live at **390×844**: What to do next, Needs attention (“No merges are waiting to send.” — not “healthy because empty”), EDI invoice total **not SAP P&L**, 14 inbound documents labeled as SAT not ERP push, investigation chips including **Supplier concentration**, skip-to-content, no horizontal overflow.

**Caveat:** the Supplier concentration chip navigates to `/dashboard/ai?q=Show supplier concentration.` which currently **does not** run R4-4 on live.

### AI Analyst (`/dashboard/ai`) — PASS (shell) / FAIL (first-question concentration)

Question → verified analysis → next investigation. No EDI tabs. Welcome chips. Inventory aging disclaimer. View SQL. How this was calculated. DATA GAP card with Show current inventory / Compare with sales / Highest inventory (does **not** suggest aging). Follow-up / New question. Cancel. Saved on this device.

Live chat still shows **`Deep analysis — intent inventory_analysis`** headings. Branch replaces this with `_analysis_heading()`; not on `zodiac-back` yet.

### Settings — PASS

Profile (read-only username/email). Security: session language, **no JWT jargon**, no fake self-serve password reset. API keys. Account. Skip link. Loading/retry exist in code.

### SAT documents — PASS

14 documents, 0 waiting, 4 sent. Subtitle: inbound SAT activity, not a live ERP push. Tabs: Documents / Merge / Merged invoices / Send to SAP. Filters. Details/Delete. Loading then list. No AxiosError in UI.

### EDI operations (`/dashboard`) — PASS with copy nits

Tab **Inbound SAT** (not labeled as a push). Tooltip/title on inbound: not a live ERP push. Subtitle still says **“To ERP tab”** on www; branch removes that phrase. From ERP / Business / Customer Comparison remain.

---

## 5. UX improvements on this branch (not all live)

- First-question concentration candidate gate (`is_deep_analysis_candidate` +3)
- Follow-up regex `account for (the )?most purchas`
- Force `supplier_concentration` after follow-up merge so paraphrases do not steal R3 suppliers incorrectly
- Trust panel order: Source, Definition, Aggregation, Period, Grain, Result size, Limitations
- Hide intent slug from meta strip
- EDI subtitle without “To ERP tab”
- Login purpose line (governed SAP intelligence + data limitations)

---

## 6. Product improvements

Differentiator preserved: governed SAP semantics, DATA GAP as a feature, adaptive context, explainability, grain safety. Did not add forecasting, aging, HHI, supplier risk, net profit, or fake turnover.

---

## 7. Security

Live `POST /api/query/adaptive` with `Show inventory.`:

| Case | HTTP | SQL leak |
| --- | --- | --- |
| No Authorization | 401 | No |
| Empty Bearer | 401 | No |
| Wrong scheme (Basic) | 401 | No |
| Malformed token | 401 | No |
| Invalid JWT | 401 | No |

`get_current_user` runs before SQL. Dashboard inbound requires the same Axios bearer. Frontend: unauthenticated protected routes redirect to sign-in. JWT not shown in Settings Security.

**Status: PASS**

---

## 8. AI Analyst

Shell and follow-up R4-4: PASS. First-question concentration: FAIL on live until backend deploy.

---

## 9. Adaptive context

R3 live chain 10/10. R4-1 context chain PASS. R4-3 product context chain 13 turns including aging DATA GAP + inventory recovery: included in **31/6/0**. R3 “Show their suppliers.” remains `suppliers_of_selection` (live R4-4 suite).

---

## 10. DATA GAP

Aging and net profit return `CANNOT_ANSWER` with alternatives that do not re-ask aging. Recovery to inventory PASS (R3 3 PASS / 2 GAP recovery block; R4-3 recovery section; R4-4 suite aging → inventory).

---

## 11. R4-3 inventory

Live **31 PASS / 6 DATA GAP / 0 FAIL**. Snapshot only. SALK3 / LABST / LBKUM. No aging. Ratios not labeled turnover. Grain: independent sales agg ⋈ inventory agg.

---

## 12. R4-4 supplier concentration

| Path | Live |
| --- | --- |
| After highest-profit products → Show supplier concentration. | PASS, intent `supplier_concentration`, EKPO, share %, no VBRP |
| Show their suppliers. | PASS, `suppliers_of_selection` |
| Show supplier profit. | PASS (no billing fan-out; listing, not profit) |
| Standalone Show supplier concentration. | **FAIL(intent empty)** — 22049 ms count fallback |
| Independent SQL (product-filtered chain) | **PASS**, diffs 0.00 |
| Independent SQL (global standalone) | **BLOCKED** (AI intent null) |

Governed definition (branch + follow-up live):

- `supplier_rank` = `ROW_NUMBER() OVER (ORDER BY purchase_value DESC)`
- `share_of_po_value_pct` = supplier EKPO.NETWR / total × 100, NULL if total ≤ 0
- LOEKZ empty on EKPO and EKKO
- Missing LFA1 name → supplier code
- No HHI / risk thresholds / supplier profit

---

## 13. Grain safety

Unit tests reject VBRP⋈MARD, VBRP⋈EKPO, EKPO⋈MBEW with NETWR. Compiled concentration SQL has no VBRP. Live follow-up SQL has EKPO, not VBRP. **PASS** (unit + live follow-up). Adversarial suite in `tests/test_r4_4_supplier_concentration.py`.

---

## 14. Independent SQL

Product-filtered (selected top-profit materials):

| Supplier | Independent share % | AI share % | Diff | Status |
| --- | --- | --- | --- | --- |
| 0000001011 | 98.57 | 98.57 | 0.00 | PASS |
| 0000003902 | 1.35 | 1.35 | 0.00 | PASS |
| 0000003000 | 0.06 | 0.06 | 0.00 | PASS |

Global PO share (LOEKZ filter, no product filter) from the same DB, **not** comparable to the chained AI result:

0000005557 49.86 · 0000001095 42.45 · 0000001075 1.84 · 0000000300 1.26 · 0000003511 0.69

Standalone AI vs global SQL: **BLOCKED**.

**Matrix status: BLOCKED** (standalone required for Overview chip / production-complete rule).

---

## 15–18. Frozen live regression (re-run 2026-08-28 after R4-4 follow-up was live)

| Suite | Required | Actual | Evidence |
| --- | --- | --- | --- |
| R3 | 23 / 2 / 0 | **23 / 2 / 0** | `r3_post_deploy_live_results.json` |
| R4-1 | 47 / 2 / 0 | **47 / 2 / 0** | `r4_1_live_acceptance.json` |
| R4-2 | 40 / 1 / 0 | **40 / 1 / 0** | `r4_2_live_acceptance.json` |
| R4-3 | 31 / 6 / 0 | **31 / 6 / 0** | `r4_3_live_acceptance.json` |

Local pytest goldens this pass: **83 passed** (R3–R4-4 + follow-up) plus **23** additional deep-dive tests. Frontend `test:ux` 15 PASS, `test:adaptive-context` 8 PASS.

---

## 19. R4-4 acceptance

Follow-up: PASS. First question: FAIL on live. Golden unit: PASS on branch. **Not production-complete.**

---

## 20. Full Chat

R4-3 live `product_context_chain` + `data_gap_recovery` covers:

highest profits → inventory → sales → high inventory / low sales → product groups → suppliers → customers → regions → inventory by plant → compare last year → why → aging (DATA GAP) → inventory again → net profit (DATA GAP) → inventory.

**PASS** on live (inside 31/6/0). Additional R4-4 concentration turn after profits: **PASS**.

---

## 21. SAT — PASS (live)

14 / 0 waiting / 4 sent. Inbound vs send-to-SAP distinguished. Loading then rows.

---

## 22. Settings — PASS (live)

---

## 23. Responsive QA

| Viewport | Overflow | Notes |
| --- | --- | --- |
| 390×844 | None | Overview + AI Analyst |
| 768×1024 | None | EDI operations loaded |
| 1280×800 | None | Dashboard |
| 1440×900 | None | SAT documents |

430 and 1024×768 not separately captured; 390 and 768 bracket those widths. Mobile tables may scroll internally by design. Sidebar hamburger on <1024.

**PASS** for captured viewports. Residual: live EDI subtitle “To ERP tab”.

---

## 24. Accessibility

Skip to content, `main#main-content`, section headings, tab names, password show/hide aria-labels, trust panel `aria-expanded` (branch), Settings field labels. Keyboard: skip link present. No critical contrast failure observed.

Mobile a11y tree still lists Close menu when overlay is visually closed — not a blocker.

**PASS** (no critical blocker).

---

## 25. Performance

| Suite | P50 | P95 | Max |
| --- | --- | --- | --- |
| R3 live | 715 ms | 1082 ms | 1779 ms |
| R4-2 live | 698 ms | 946 ms | 1393 ms |
| R4-3 live | 616 ms | 1178 ms | 2680 ms |
| R4-4 follow-up concentration | 984 ms | — | — |
| R4-1 basic GA `2004` / `Top 5` | — | — | ~9.3 s |

Normal analytical queries meet **P50 < 1s** and **P95 < 3s**. Basic-engine ~9s turns are **explicitly accepted** as cold/deep outliers; correctness was not weakened.

Standalone concentration 22 s is the **wrong engine**, not a performance target.

**PASS** with documented GA outliers.

---

## 26. Console

Installed error collector on live session: no `console.error` / `window.onerror` events during Overview / AI / SAT / Dashboard. No blank screen after load. SAT and Overview loading copy is intentional.

**PASS** for this session.

---

## 27. Deployment

| Action | Result |
| --- | --- |
| `npx vercel whoami` | `karthikeyanasha24` |
| `npx vercel project ls` | `zodiac-api` → **zodiac-api-nu**, `hrm53v1`, `banyanqi-react` only |
| Inspect `www.bridgeedi.com` / `zodiac-back` | Not visible to this account |
| Deploy to zodiac-api-nu | **Not done** |
| New Vercel project | **Not created** |
| DNS | **Unchanged** |

V2.1 frontend and R4-4 follow-up reached production via an account that **can** see those projects (not this CLI).

### Handoff (required)

1. Owner of **zodiac-back** deploys this branch (`phase12-first-customer-ready`) to the **existing** `zodiac-back` project only.  
2. Re-run `python scripts/r4_4_live_acceptance.py` — standalone must be PASS with `supplier_concentration`.  
3. Re-run `python scripts/r4_4_independent_sql.py` — standalone comparisons vs global shares must PASS.  
4. Owner of the **www.bridgeedi.com** project deploys the same branch for trust-panel / EDI subtitle / login tagline polish.  
5. Hard-refresh Overview → Supplier concentration chip and confirm share % (not a row-count card).

---

## 28. Remaining limitations

No inventory aging, true turnover, net profit, logistics cost, HHI, supplier risk, forecasting. Inventory vs sales is snapshot-vs-activity. Saved analyses are local. First-question R4-4 not live.

---

## 29. Technical debt

See system audit §12. Do not start R4-5.

---

## 30. Product roadmap recommendations (after this scope is accepted)

- Persist saved analyses server-side only if there is a real multi-device need.
- Reduce basic-GA ~9s cold path without changing answers.
- Tighten mobile drawer a11y (inert when closed).
- Optional: cloud sync of analyses — deferred, not required for V2.1.

---

## 31. Final score (/10)

| Dimension | Score | Note |
| --- | --- | --- |
| Product clarity | 8 | Overview explains what/why/next |
| UI | 8 | Coherent V2.1 shell |
| UX | 7 | Concentration chip does not work first-click |
| Analytical intelligence | 9 | Frozen suites + exact PO share match |
| Trust | 7 | Panel exists; live headings still dump intent slugs |
| Security | 9 | Adaptive 401, no SQL leak |
| Reliability | 8 | 0 FAIL on frozen live suites |
| Performance | 8 | P50/P95 met; GA outliers accepted |
| Responsiveness | 8 | 390–1440 no overflow |
| Accessibility | 8 | Skip, headings, labels |
| Enterprise readiness | 6 | Deploy access + first-question hole |
| Customer-demo readiness | 6 | Demo chip for concentration fails |
| Differentiation | 9 | Governed + DATA GAP + context |

**Overall: 7.6 / 10.** A production blocker prevents a higher score and prevents completion.

---

## 32. Final verdict

# BRIDGEEDI V2.1 + R4 — NOT COMPLETE

### Exact blockers

**1. R4-4 first question is not live on `zodiac-back`**

- Evidence: `Show supplier concentration. [standalone]` → `FAIL(intent=)` · 22049 ms · `standalone_intent: null` in `r4_4_independent_sql.json`.
- Cause: live `is_deep_analysis_candidate` does not score supplier concentration, so the Overview/AI chip never reaches the R4-4 SQL.
- Required action: deploy this branch to **existing** `zodiac-back` (never `zodiac-api-nu`), then re-run standalone live + independent SQL.

**2. This CLI cannot deploy canonical production**

- Evidence: Vercel project list is only `zodiac-api-nu`, `hrm53v1`, `banyanqi-react`.
- Required action: project-owner deploy as in §27.

---

## Acceptance matrix

| Area | Expected | Actual | Evidence | Status |
| --- | --- | --- | --- | --- |
| Login | PASS | Session language / branding live | www Settings + AuthForm | PASS |
| Overview | PASS | V2.1 live; concentration chip misfires on backend | www `/overview` 390px | PASS* |
| AI Analyst | PASS | Shell PASS; first-question R4-4 FAIL | www `/dashboard/ai` | FAIL |
| Trust panel | PASS | Live panel + View SQL; slug headings remain | www AI chat | PASS* |
| Follow-ups | PASS | R3/R4 chains | live JSON | PASS |
| DATA GAP | PASS | Aging / net profit | R4-3 / R4-4 live | PASS |
| DATA GAP recovery | PASS | Inventory after gap | R3 + R4-3 + R4-4 | PASS |
| SAT | PASS | 14 / 0 / 4 | www `/sat-documents` | PASS |
| Settings | PASS | No JWT jargon | www `/settings` | PASS |
| Security | PASS | 401 × 5, no SQL | live probes | PASS |
| Router health | PASS | `failed=[]`, dashboard loaded, inbound in OpenAPI | `/health/routers` | PASS |
| R3 | 23/2/0 | 23/2/0 | `r3_post_deploy_live_results.json` | PASS |
| R4-1 | 47/2/0 | 47/2/0 | `r4_1_live_acceptance.json` | PASS |
| R4-2 | 40/1/0 | 40/1/0 | `r4_2_live_acceptance.json` | PASS |
| R4-3 | 31/6/0 | 31/6/0 | `r4_3_live_acceptance.json` | PASS |
| R4-4 | PASS | Follow-up PASS; standalone FAIL | `r4_4_live_acceptance.json` | FAIL |
| Independent SQL | PASS | Chained 0.00; standalone BLOCKED | `r4_4_independent_sql.json` | BLOCKED |
| Grain safety | PASS | Guard + no VBRP in follow-up SQL | tests + live | PASS |
| Full Chat | PASS | R4-3 chain + R4-4 after profits | live JSON | PASS |
| Responsive | PASS | 390 / 768 / 1280 / 1440 | browser | PASS |
| Accessibility | PASS | Skip, headings; no critical blocker | browser | PASS |
| Performance | PASS | P50/P95 met; GA ~9s accepted | live JSON | PASS |
| Console | PASS | No critical errors this session | CDP | PASS |
| Production deployment | PASS | V2.1 + R4-4 follow-up live; this CLI cannot ship remaining commits | Vercel ls | BLOCKED |

\*Overview and trust panel pass as product surfaces; they are marked with a caveat because the concentration chip and heading copy depend on the blocked backend deploy.

---

# BRIDGEEDI V2.1 + R4 — NOT COMPLETE
