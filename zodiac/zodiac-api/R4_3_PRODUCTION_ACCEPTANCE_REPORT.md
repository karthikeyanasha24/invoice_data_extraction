# R4-3 Production Acceptance Report

**Date:** 2026-08-27  
**Branch:** `phase12-first-customer-ready`  
**Implementation commit:** `dbc1913` (rebased onto `170e644`)  
**R4-4:** not started

---

## Final verdict

```text
R4-3 PRODUCTION COMPLETE
```

Live `zodiac-back` now serves R4-3 intents. Harness 0 FAIL. Frozen R3 / R4-1 / R4-2 baselines held. Independent comparison values match SQL. Full Chat shows snapshot-vs-sales ranking, governed aging DATA GAP, and recovery.

---

## 1. Deployment

| Item | Value |
|------|--------|
| Required project | `zodiac-back` only |
| Production URL | https://zodiac-back.vercel.app |
| Full Chat | https://www.bridgeedi.com/dashboard/ai |
| GitHub | `dbc1913` on `phase12-first-customer-ready` |
| Deployed this session | **Yes — by Andy** to `zodiac-back`. This machine still cannot see that Vercel project and did not deploy `zodiac-api-nu`. |

Fingerprint after deploy:

`Show inventory versus sales.` → `pipeline=deep_multidim`, `intent=inventory_sales_comparison`, independent `inventory_agg` + `sales_agg` joined on `MATNR`. Keys include `stock_value`, `revenue`, `billed_qty`, ratios, `data_availability`.

---

## 2. Implementation

New module `app/services/inventory_sales.py` plus routing in `analytical_deep_dive.py` / `analytical_followup_resolver.py`, grain-guard contracts, semantic metrics, tests, and live scripts.

| Intent | Meaning |
|--------|---------|
| `inventory_analysis` | Current MBEW snapshot (R3 frozen) |
| `inventory_sales_comparison` | Snapshot vs billed activity |
| `inventory_risk_analysis` | High inv / low sales or low inv / high sales via `PERCENT_RANK` |
| `inventory_by_plant` | `MARD.WERKS` codes (`T001W` absent) |
| `inventory_aging_gap` | DATA GAP (no MSEG) |
| `inventory_turnover_gap` | DATA GAP (no dated snapshots) |
| `inventory_trend_gap` | DATA GAP (no historical inventory) |

Architecture: independent `inventory_agg` and `sales_agg`, then join on `MATNR` / `MATKL`. Never `FROM vbrp JOIN MARD/MBEW SUM(NETWR)`.

Language: current inventory snapshot vs sales activity. No stock-out prediction. No invented 2004 inventory.

---

## 3. Schema audit

| Table | Grain | Fields | Notes |
|-------|-------|--------|-------|
| MBEW | MATNR + BWKEY + BWTAR | SALK3 value, LBKUM valuated qty | Current snapshot only |
| MARD | MATNR + WERKS + LGORT | LABST unrestricted qty | Plant = WERKS **code** |
| MARA | MATNR | MATKL | Product group |
| MAKT | MATNR + SPRAS | MAKTX | |
| VBRP | billing item | NETWR, WAVWR, FKIMG, MATNR, WERKS | Sales facts |
| VBRK | billing header | FKDAT, KUNAG, WAERK | Sales period only |
| MSEG | — | — | Absent → aging DATA GAP |
| T001W | — | — | Absent → plant text DATA GAP |

Governed inventory (unchanged from R3): `stock_value = SUM(MBEW.SALK3)`, `stock_qty = SUM(MBEW.LBKUM)`. Distinct from billed qty `VBRP.FKIMG` and PO qty `EKPO.MENGE`.

Sales (unchanged): Revenue `SUM(NETWR)`, COGS `SUM(WAVWR)`, GP = Rev−COGS, Qty `SUM(FKIMG)`, ASP = Rev/Qty.

---

## 4. Local tests

```text
91 passed
```

Suites: `test_r4_3_inventory_sales.py`, R3 grain/golden, R4-1, R4-2, follow-up resolver, deep dive.

---

## 5. Live R4-3 harness

Artifact: `r4_3_live_acceptance.json`

```text
31 PASS / 6 DATA_GAP / 0 FAIL
P50 775ms / P95 1230ms / Max 1664ms
```

Meets P50 < 1s and P95 < 3s.

| Question | Intent | Result |
|----------|--------|--------|
| Show inventory. (standalone) | `inventory_analysis` | PASS |
| Show inventory versus sales. | `inventory_sales_comparison` | PASS |
| High inventory but low sales | `inventory_risk_analysis` | PASS |
| Low inventory but high sales | `inventory_risk_analysis` | PASS |
| Show inventory by plant. | `inventory_by_plant` | PASS |
| Show inventory aging / turnover / trend | DATA GAP intents | DATA_GAP (governed) |

Product context chain (API): profits → inventory → sales → high inv/low sales → product groups → suppliers → customers → regions → plant → compare last year → Why? → aging DATA GAP → inventory again **all PASS / governed DATA_GAP**.

---

## 6. Independent accuracy

Artifact: `r4_3_independent_sql.json`

Script printed `total_mismatches: 8` across 5 cases. **Not a value error.**

| Case | Result |
|------|--------|
| Snapshot ranking (`Show inventory.` / highest inventory) | 8 rank-key swaps, **0% value diff** |
| Inventory vs sales `stock_value` | **0 mismatches** |
| Inventory vs sales `revenue` | **0 mismatches** |
| Product group MATKL `00104` | stock_value `100089299823.21` vs revenue `1385630.00` **exact match** |

Snapshot grain is MATNR + BWKEY. Tied stock values (`ME_4003` / `ME_4002` both `25000000000`; `IMC_8000` / `IMC_6000` both `12500000000`) can swap order when the helper compares by product key. Treat as **no unexplained material mismatch**.

---

## 7. Performance

| Suite | P50 | P95 | Max |
|-------|-----|-----|-----|
| R4-3 | 775ms | 1230ms | 1664ms |
| R3 post-deploy | 731ms | 1018ms | 1365ms |
| R4-2 | 755ms | 1161ms | 1826ms |

R4-3 P50 < 1s, P95 < 3s: **PASS**.

---

## 8. Context / Full Chat

Authenticated session: https://www.bridgeedi.com/dashboard/ai

| Turn | Observed | Result |
|------|----------|--------|
| Highest profits | `product_profitability`, Ship Project, 10 rows | PASS |
| Show their inventory | `inventory_analysis`, 30 rows, Fire fighting vehicle, snapshot caveat | PASS |
| Show their sales | `product_profitability`, Ship Project preserved | PASS |
| High inventory but low sales | `inventory_risk_analysis`, 9 rows, Tires; ranking, not stock-out | PASS |
| Show their product groups | `product_group_breakdown`, 12 rows | PASS |
| Show inventory aging. | DATA GAP: MSEG absent; billing/creation/expiry are not age | DATA_GAP |
| Show inventory again. | `inventory_analysis`, 30 rows | PASS |
| Show inventory by plant. | `inventory_by_plant`, 40 rows, plant `3000`, LABST, T001W caveat | PASS |

Suppliers / customers / regions / YoY / Why were not re-typed in this UI pass; the **same sequence passed on the live API** context chain (0 FAIL).

---

## 9. DATA GAPs (governed, must remain)

| Topic | Status |
|-------|--------|
| Inventory aging (MSEG) | DATA GAP — live + Full Chat refuse; do not use billing/creation/expiry as age |
| True inventory turnover | DATA GAP — no temporally aligned snapshots |
| Inventory trend | DATA GAP — only current MBEW/MARD snapshot |
| Net profit / OPEX / logistics cost | DATA GAP (R3 frozen) |

---

## 10. Regression (frozen baselines, re-run live after deploy)

| Suite | Required | This session |
|-------|----------|--------------|
| R3 | 23 PASS / 2 DATA GAP / 0 FAIL | **23 PASS / 2 DATA GAP / 0 FAIL** (short follow-ups 17/17; supplier safety true) |
| R4-1 | 47 PASS / 2 DATA GAP / 0 FAIL | **47 PASS / 2 DATA GAP / 0 FAIL** |
| R4-2 | 40 PASS / 1 DATA GAP / 0 FAIL | **40 PASS / 1 DATA GAP / 0 FAIL** |

Artifacts: `r3_post_deploy_live_results.json`, `r4_1_live_acceptance.json`, `r4_2_live_acceptance.json`.

---

## 11. Acceptance matrix

| Capability | Status |
|---|---|
| Inventory snapshot (standalone + follow-up) | PASS |
| Inventory value / qty / highest | PASS (live + SQL; ranking ties only) |
| Inventory vs sales | PASS |
| High inventory / low sales | PASS (`inventory_risk_analysis`, `overstock_score`) |
| Low inventory / high sales | PASS (`undersupply_score`) |
| Product group | PASS (MATKL independent aggs, exact SQL match) |
| Plant | PASS (`MARD.WERKS` codes) |
| Product context | PASS |
| Customer / supplier / region follow-up | PASS (live API chain) |
| Inventory aging | DATA_GAP (governed) |
| DATA GAP recovery | PASS |
| R3 / R4-1 / R4-2 regression | PASS (frozen counts) |
| Full Chat | PASS |
| Latency | PASS |

---

## 12. Remaining limitations (not blockers)

- Inventory is a **current snapshot**, not a dated time series
- Do not call sales_qty/stock_qty **inventory turnover**
- Plant labels are codes only (`T001W` absent)
- Inventory is not customer-owned; region is a **sales** dimension
- Aging / true turnover / inventory trend remain DATA GAP

---

## 13. What is frozen and must not regress

R3, R4-1, R4-2, follow-up resolver, analytical context, SQL grain guard, governed metrics, DATA GAP behavior, basic GA routing.

Do **not** start R4-4 from this report.
