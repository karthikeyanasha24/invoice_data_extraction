# BridgeEDI — Product Excellence Audit

**Date:** 2026-08-28  
**Branch:** `phase12-first-customer-ready`  
**Live frontend:** `https://www.bridgeedi.com` (V2.1)  
**Live backend:** `https://zodiac-back.vercel.app` (R3–R4-3 + R4-4 follow-up)  
**Verdict:** not production-complete until first-question R4-4 is live.

This is a product review, not a test dump. Frozen analytical contracts are treated as already proven on live (R3 23/2/0, R4-1 47/2/0, R4-2 40/1/0, R4-3 31/6/0).

---

## 1. Architecture (current)

Next.js App Router frontend + FastAPI backend on Vercel. AI Analyst calls `POST /api/query/adaptive` with JWT. Governed deep analysis: semantic candidate gate → follow-up resolver → `AnalyticalPlan` → compiled SQL → `sql_grain_guard` → execute → human summary / DATA GAP.

Sales grain: billing item (`vbrp`/`VBRK`). Inventory: MBEW/MARD snapshot. Purchase concentration: EKPO⋈EKKO⋈LFA1 at PO-item grain. Independent aggregation before any cross-domain join.

---

## 2. Product map

| IA group | Route | Purpose |
| --- | --- | --- |
| Auth | `/` | Sign in / sign up |
| Understand | `/overview` | What is happening, what needs attention, what to ask |
| Ask | `/dashboard/ai` | Governed SAP questions |
| Operate | `/dashboard` | Inbound SAT / From ERP / Business / Comparison |
| Operate | `/sat-documents` | CFDI intake, merge, send to SAP |
| Operate | `/invoices-v2` | Invoice convert/validate |
| Manage | `/settings` | Profile, session, API keys, account |
| Manage | `/customers`, `/admin/*` | EDI customers, RFC→G/L, supplier API access |
| Other | `/workspace/*`, customer portal | Not the primary demo path; still gated |

AI Analyst does not host EDI tabs.

---

## 3. Page-by-page (enterprise buyer)

**Login.** Brand present. Purpose could be stronger on cached live copy; branch tagline states governed SAP intelligence and data limitations. Password visibility and human errors exist.

**Overview.** Answers the four executive questions. EDI totals are labeled not SAP P&L. Empty pending merges are not celebrated as “healthy.” Supplier concentration chip is useful **only after** backend first-question deploy — today it fails as a first click.

**AI Analyst.** Clear workspace. View SQL hidden. Trust panel: Source / Definition / Aggregation / Period / Grain / Result size / Limitations. Branch strips `Deep analysis — intent <slug>` and shows an investigation breadcrumb. Live backend still dumps intent slugs in summaries until redeploy.

**SAT / EDI.** Counts, filters, loading, send-to-SAP vs inbound SAT. Residual live subtitle “To ERP tab” on EDI operations; tab itself is Inbound SAT. Branch removes the leftover phrase.

**Settings.** Profile read-only. Security uses session language. API keys are real. No fake toggles observed.

---

## 4. UX / UI findings

| Finding | Severity | Status |
| --- | --- | --- |
| Overview concentration chip does not run R4-4 on live | Blocker | Code on branch; not on `zodiac-back` |
| Intent slugs in live summaries | Medium | Fixed on branch |
| EDI “To ERP tab” leftover | Low | Fixed on branch |
| Mobile Close-menu still in a11y tree | Low | Residual |
| Saved analyses are local | Info | Labeled “this device” |
| Session flash when no cached user | Acceptable | Cached user keeps shell |

---

## 5. Accessibility

Skip-to-content, main landmark, headings, labeled password toggle, tab names. No critical contrast failure observed at 390 / 768 / 1440. Keyboard: skip link exists. Residual: overlay control in tree when visually closed.

---

## 6. Security

Adaptive without JWT / empty Bearer / wrong scheme / malformed / invalid: **401**, no SQL. Dashboard inbound requires bearer. JWT not shown in Settings Security. This CLI does not commit secrets. Do not put production credentials in reports.

---

## 7. API

`GET /health/routers`: ok, failed=[], dashboard loaded. OpenAPI includes `/api/v1/dashboard/v2/inbound`. Failed routers become 503, not silent 404.

---

## 8. Analytical engine / semantic routing

First-question concentration is a deep candidate locally (`is_deep_analysis_candidate` +3). Paraphrases covered: dominate purchases, largest PO share, compare suppliers by PO value. R3 “Show their suppliers.” remains listing.

Live first question still uses a row-count fallback. That is the remaining routing hole.

---

## 9. Follow-up context

Long R4-3 Full Chat holds on live. After concentration, branch keeps: which supplier is highest, what percentage, show top 3, PO value. “Show their suppliers.” still R3 listing.

Context survives DATA GAP (aging → inventory, net profit → inventory).

---

## 10. DATA GAP

Aging and net profit are limitations, not errors. Alternatives do not re-ask aging. Recovery works.

---

## 11. Inventory governance

Snapshot only. SALK3 / LBKUM / LABST. Not 2004 stock. Not aging. Not true turnover. Plant uses WERKS codes. Inventory is not customer-owned.

---

## 12. Supplier concentration

PO share, rank, LOEKZ filter, NULL share if total ≤ 0. No HHI, no risk language, no supplier profit, no VBRP join. Follow-up path live and independently matched (0.00). Standalone not live.

---

## 13. Grain safety

Guard rejects billing×inventory, billing×purchase, purchase×inventory monetary joins. Unit tests pass. Live follow-up SQL has no VBRP.

---

## 14. Independent SQL

Product-filtered chain: 98.57 / 1.35 / 0.06 vs AI, diff 0.00. Global reference 0000005557 ≈ 49.86%, 0000001095 ≈ 42.45% cannot be compared until standalone AI returns concentration.

---

## 15. Performance

Normal analytical P50 ~0.6–0.7s, P95 < 3s. Basic-GA ~9s outliers accepted. Standalone concentration 22s is the wrong engine.

---

## 16. Responsive

390, 768, 1280, 1440: no horizontal overflow in prior live QA. Tables may scroll internally.

---

## 17. Production deployment

Frontend V2.1 live. Backend R4-4 follow-up live. Remaining commits need owner deploy to **existing** `zodiac-back` and www. This CLI cannot see those projects. `zodiac-api-nu` must not be used.

---

## 18. Full Chat / R3–R4-4

Live Full Chat (R4-3 chain) PASS. Live R3–R4-3 frozen contracts PASS. R4-4 follow-up PASS. R4-4 first question FAIL on live. Local R4-4 golden **PASS** (86 pytest including new follow-up/limit tests).

---

## 19. Remaining limitations

No MSEG aging, no true turnover, no net profit, no logistics cost, no HHI, no forecasts. Inventory vs sales is snapshot-vs-activity. Saved analyses are device-local.

---

## 20. Recommended next improvements

Ranked by customer value × frequency × severity ÷ implementation risk:

1. **Deploy first-question R4-4 to `zodiac-back`** — Overview chip is currently a false promise.
2. **Deploy human headings / trust copy** — stop intent slugs on live.
3. **Investigation workspace / history in the cloud** — only if multi-device is a real need.
4. **Reduce ~9s basic-GA cold path** without changing answers.
5. **Mobile drawer a11y (inert when closed)**.
6. **Evidence-first comparison visuals** for YoY / inventory vs sales.
7. **CSV export of the current result table** (already partly present).
8. **Authenticated share of an investigation** — later; needs permissions.
9. **Executive one-paragraph narrative** from the same governed numbers.
10. **Connection reuse / plan cache** for warm analytical P95.

Do not implement fake aging, turnover, risk scores, or P&L.

---

## 21. Honest product score (/10)

| Dimension | Score |
| --- | --- |
| Product clarity | 8 |
| Information architecture | 8 |
| UI | 8 |
| UX | 7 |
| Analytical intelligence | 9 |
| Trust | 7 |
| Security | 9 |
| Reliability | 8 |
| Performance | 8 |
| Accessibility | 8 |
| Responsiveness | 8 |
| Enterprise readiness | 6 |
| Customer-demo readiness | 6 |
| Differentiation | 9 |

**Overall: 7.6 / 10.**

The engine is a serious governed SAP analyst. The first-click supplier-concentration hole and deploy-access gap are what keep it from feeling finished for a first customer.

---

# BRIDGEEDI V2.1 + R4 — NOT COMPLETE
