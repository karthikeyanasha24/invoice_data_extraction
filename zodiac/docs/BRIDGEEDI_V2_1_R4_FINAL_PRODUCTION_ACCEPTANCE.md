# BridgeEDI V2.1 + R4 — Final Production Acceptance

**Date:** 2026-08-28  
**Branch:** `phase12-first-customer-ready`  
**Canonical frontend:** `https://www.bridgeedi.com`  
**Canonical backend:** `https://zodiac-back.vercel.app`  
**Forbidden target:** `zodiac-api-nu` (not used, not deployed)

---

## Executive verdict

**NOT COMPLETE — PRODUCTION DEPLOYMENT BLOCKED**

Local implementation, unit tests, compiled independent SQL, and GitHub push are done. This CLI cannot deploy to the canonical Vercel projects, so live first-question R4-4, live independent SQL vs AI, and live Full Chat / Overview chip acceptance remain unverified on production.

Do not declare `BRIDGEEDI V2.1 + R4 — COMPLETE` until `zodiac-back` and `www.bridgeedi.com` are redeployed from this branch and the live matrix below is re-run.

---

## Implementation

This pass fixed the remaining first-question R4-4 routing hole: `Show the top 3 suppliers by purchase value.` (and similar) was classified as a basic-engine `top N` query, so `try_deep_multidim_analysis` returned `None` and production fell through to `COUNT(*)` on `invoice_business_data` (~22s).

Actual changes:

- `wants_supplier_concentration` now recognizes semantic paraphrases (concentration, PO share/value, top-N suppliers, concentrated suppliers, account-for-most, etc.) and still excludes R3 `Show their suppliers.`
- `is_deep_analysis_candidate` returns true for concentration **before** the basic-engine `top N` steal
- Adaptive path still enters deep analysis when concentration is recognized even if `classify_turn` is conservative
- Top-N LIMIT honored on standalone concentration (`LIMIT 3` / `LIMIT 1` / default display 20)
- Follow-ups stay in concentration: highest one / highest supplier / percentage / top 3 / PO value / largest / why-highest
- R3 `Show their suppliers.` remains `suppliers_of_selection`
- Share is `NULL` when total PO value is zero (no divide-by-zero)
- Concentration SQL ranks with a supplier tie-break; grain is EKPO/EKKO/LFA1 only
- Human headings (`Supplier concentration`, `Top 3 suppliers by purchase value`) — no intent slugs
- Trust panel: Source → Definition → Aggregation → Period → Grain → Result size → Limitations, with PO provenance
- Follow-up chips no longer remap concentration questions to `Show their suppliers.`
- Unused `sap_sql_agent` import removed from `dashboard.py` so router load cannot fail on that module
- Intent-gate tests no longer crash when the handler is invoked without a user object (HTTP JWT gate unchanged)

---

## Backend

### Auth

HTTP `Depends(get_current_user)` still runs before SQL. Adaptive without JWT / empty Bearer / wrong scheme / malformed / invalid token → 401, no SQL. Direct-function tests may pass `current_user=None`; that path no longer AttributeErrors and still does not execute SAP SQL for gated nonsense.

### Routing

Standalone first-question concentration is a deep-analysis candidate. It no longer loses to the generic `top N` basic engine. Clarification/non-business turns still short-circuit unless the question is concentration.

### R4-4

Intent `supplier_concentration`. Metric = supplier PO value / total PO value × 100 at PO-item grain. Tables: EKPO, EKKO, LFA1. Not VBRP/VBRK, not supplier profit, not HHI.

### Grain safety

Compiled concentration SQL contains no VBRP. Unit tests still reject VBRP⋈EKPO, VBRP⋈MBEW/MARD, and EKPO⋈MBEW monetary fan-out.

### DATA GAP

Aging, true turnover, net profit, logistics cost, budget remain unavailable. Recovery chips still point at current inventory / inventory vs sales / highest inventory / gross profit — not aging or fabricated profit.

### Performance

Wrong-engine ~22s path is removed in this branch because concentration no longer falls through to invoice `COUNT(*)`. Normal analytical P50/P95 baseline is unchanged (no new cache). Live R4-4 latency cannot be re-measured until `zodiac-back` is redeployed.

---

## Frontend

### Overview

Supplier concentration remains a first-click investigation chip (`Show supplier concentration.`). EDI invoice total is not labeled as SAP P&L. Empty pending is honest.

### AI Analyst

Question → What we found → Results (business heading) → How this was calculated → Next investigation. View SQL hidden by default. Saved analyses labeled **Saved on this device**. `?q=` deep-link preserved. No EDI Operations tabs inside the analyst.

### Trust

Source, Definition, Aggregation, Period, Grain, Result size, Limitations. Concentration definition states PO share of total PO value and NULL-if-zero.

### Follow-ups

Concentration chips: highest supplier, percentage, top 3. Generic `/supplier/` map no longer steals those chips into R3 listing.

### SAT / Settings / responsive / accessibility

Unchanged from the prior V2.1 pass: human SAT statuses, no raw AxiosError, inbound SAT is not a fake ERP push, Settings Profile/Security/API/Account, skip-to-content, keyboard controls. Live responsive QA was previously done on www; this CLI did not re-deploy frontend, so later heading/chip copy is **locally verified** only.

---

## Test matrix

| Suite | Result | Notes |
| --- | --- | --- |
| R3 unit (`test_r3_bi_expansion` + golden benchmark) | PASS | Local. Live golden 23/2/0 last verified on production in the prior pass; not re-run this pass |
| R4-1 unit | PASS | Local. Live 47/2/0 last verified prior pass |
| R4-2 unit | PASS | Local. Live 40/1/0 last verified prior pass |
| R4-3 unit | PASS | Local. Live 31/6/0 last verified prior pass |
| R4-4 unit | PASS (21 tests) | Standalone paraphrases, top-N, R3 distinction, grain, headings, follow-ups, zero-total SQL |
| Combined governed pytest this pass | **135 passed** | R3–R4-4 + follow-up + deep dive + auth + dashboard + Andy cases |
| Intent-gate nonsense + dashboard registration | **9 passed** | After null-user and unused-import fixes |
| Adaptive auth | PASS | 401 before SQL |
| Independent SQL (compiled vs DB) | **PASS locally** | `0000005557` ≈ 49.86%, `0000001095` ≈ 42.45%, top-3 row count 3 |
| Independent SQL (live AI vs DB) | **blocked by credentials/access** | Requires `zodiac-back` on this commit |
| Frontend `test:ux` | **18 passed** | Concentration heading/trust/chips included |
| Frontend `test:adaptive-context` | **8 passed** | |

R3/R4-1/R4-2/R4-3 **golden live scores were not silently updated**. Local unit tests did not require changing those expected scores.

---

## Live matrix

| Check | Status |
| --- | --- |
| Frozen live R3 23/2/0 | verified live in prior same-day pass — **not re-run after this commit** |
| Frozen live R4-1 47/2/0 | verified live prior pass — **not re-run after this commit** |
| Frozen live R4-2 40/1/0 | verified live prior pass — **not re-run after this commit** |
| Frozen live R4-3 31/6/0 | verified live prior pass — **not re-run after this commit** |
| Live first-question `Show supplier concentration.` | **blocked by credentials/access** (still the old engine on current production) |
| Live top-3 standalone | **blocked by credentials/access** |
| Live concentration follow-ups | **blocked by credentials/access** for this commit; follow-up-after-profits was live on the previous backend |
| Live R3 `Show their suppliers.` | verified live prior pass (`suppliers_of_selection`) |
| Live independent SQL vs AI (global 49.86 / 42.45) | **blocked by credentials/access** |
| Local compiled SQL vs DB (global 49.86 / 42.45) | **locally verified** |
| Live Full Chat 15-turn | **not re-run this pass** |
| Live Overview / AI / SAT / Settings | Product V2.1 **verified live** earlier; this commit’s analyst heading/chip mapping is **locally verified** only |
| Live responsive QA | **verified live** earlier on www; no frontend deploy this pass |
| Canonical production deploy | **blocked by credentials/access** |

Never treat local pytest or compiled-SQL DB checks as production verification.

---

## Deployment

| Item | Value |
| --- | --- |
| Frontend deployment target | Existing BridgeEDI Vercel project serving `www.bridgeedi.com` |
| Backend deployment target | Existing `zodiac-back` project serving `zodiac-back.vercel.app` |
| Commit SHA | `90e6106` on `phase12-first-customer-ready` |
| Deployment status | **No deployment occurred** |
| This CLI Vercel account | `karthikeyanasha24` / team `ashas-projects-a0fae821` |
| Visible projects | `zodiac-api` → `zodiac-api-nu`, `hrm53v1`, `banyanqi-react` |
| Not visible | `zodiac-back`, BridgeEDI frontend |

**No deploy to `zodiac-api-nu`. No new Vercel project. No DNS change.**

### Owner deploy (canonical projects only)

From a CLI that can see `zodiac-back` and the BridgeEDI frontend project, on this branch:

```text
# backend — existing zodiac-back only
cd zodiac/zodiac-api
vercel --prod --yes
# confirm the production URL is https://zodiac-back.vercel.app

# frontend — existing www.bridgeedi.com project only
cd zodiac/zodiac-front
vercel --prod --yes
# confirm the production URL is https://www.bridgeedi.com
```

Then:

```text
cd zodiac/zodiac-api
python scripts/r4_4_live_acceptance.py
python scripts/r4_4_independent_sql.py
```

Required live probes after deploy:

1. Fresh session: `Show supplier concentration.` → intent `supplier_concentration`, EKPO SQL, share %, no `COUNT(*)` invoice fallback
2. Fresh session: `Show top 3 suppliers by purchase value.` → exactly 3 rows
3. Follow-up: `Show the highest one.` / `Show the percentage.` stay in concentration
4. After product analysis: `Show their suppliers.` remains `suppliers_of_selection`
5. Independent SQL: `0000005557` ≈ 49.86% and `0000001095` ≈ 42.45% vs AI, not rank-only

---

## Known DATA GAPs

- Inventory aging (no historical stock movements)
- True inventory turnover (required movement fields absent)
- Net profit / EBIT / opex
- Logistics / freight cost
- Budget
- Supplier profit / HHI / supplier risk thresholds (not fabricated)
- Cloud/team saved analyses (device-local only)

---

## Remaining blockers

1. **This CLI cannot deploy canonical production.** Vercel account does not see `zodiac-back` or the BridgeEDI frontend project.
2. Until that deploy, live first-question R4-4 on `zodiac-back` still uses the generic fallback (`intent` empty, `COUNT(*)` on `invoice_business_data`).
3. Live independent SQL vs AI (global shares) and live Full Chat / Overview-chip acceptance for **this commit** cannot be claimed.

No other product blockers remain in local code for V2.1 + R4-4 first-question concentration.

---

## What must not be claimed

This is **not** `BRIDGEEDI V2.1 + R4 — COMPLETE`.

Local tests passing is not production verification.
