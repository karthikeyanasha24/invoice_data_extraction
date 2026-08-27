# R4-3 Production Acceptance Report

**Date:** 2026-08-27  
**Branch:** `phase12-first-customer-ready`  
**Implementation commit:** `dbc1913` (rebased onto `170e644`)  
**R4-4:** not started

---

## Final verdict

```text
R4-3 NOT PRODUCTION COMPLETE
```

**Exact blocker:** `zodiac-back` was not deployed from this machine. Live production still runs the pre-R4-3 build. Local implementation and tests are green; live inventory↔sales comparison, high-inventory/low-sales ranking, independent AI-vs-SQL, live R3/R4-1/R4-2 re-runs, and Full Chat R4-3 acceptance cannot be claimed until Andy deploys `dbc1913` to **zodiac-back only**.

---

## 1. Deployment

| Item | Value |
|------|--------|
| Required project | `zodiac-back` only |
| Production URL | https://zodiac-back.vercel.app |
| Full Chat | https://www.bridgeedi.com/dashboard/ai |
| GitHub | `dbc1913` on `phase12-first-customer-ready` (pushed) |
| `.vercel/project.json` | **absent** (gitignored; not created) |
| Vercel CLI whoami | `karthikeyanasha24` |
| Visible team | `Asha's projects` (`ashas-projects-a0fae821`) only |
| Visible projects | `zodiac-api` → **zodiac-api-nu**, `hrm53v1`, `banyanqi-react` |
| `npx vercel inspect https://zodiac-back.vercel.app` | **FAIL** — deployment not in this team |
| `VERCEL_TOKEN` / org / project env | **absent** |
| Deployed this session | **No.** Refused `zodiac-api-nu`. Did not create another project. |

### Deploy steps (Andy / zodiac-back owner)

```bash
git pull origin phase12-first-customer-ready
cd zodiac/zodiac-api
npx vercel link --scope <andy-team> --project zodiac-back
# verify .vercel/project.json project name is zodiac-back, never zodiac-api-nu
npx vercel --prod
```

Then:

```bash
python scripts/r4_3_live_acceptance.py
python scripts/r4_3_independent_sql.py
python scripts/r3_post_deploy_live_acceptance.py
python scripts/r4_1_live_acceptance.py   # if present
python scripts/r4_2_live_acceptance.py
```

First live fingerprint that must appear after deploy:

`Show inventory versus sales.` → `pipeline=deep_multidim`, `intent=inventory_sales_comparison`, independent `inventory_agg` + `sales_agg` joined on `MATNR`, **not** catalog yearly sales.

---

## 2. Implementation (local, pushed)

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

## 5. Live probes (pre-deploy, current zodiac-back)

| Question | Pipeline | Intent | Result |
|----------|----------|--------|--------|
| Highest profits | `deep_multidim` | `product_profitability` | PASS (R3 frozen) |
| Show their inventory | `deep_multidim` | `inventory_analysis` | PASS (R3 frozen; MBEW; 30 rows) |
| Which products grew the most? | `deep_multidim` | `product_growth_decline` | PASS (R4-2 frozen) |
| Show inventory. (standalone) | catalog fallback | none | FAIL path (MARA count); follow-up inventory still works |
| Show inventory versus sales. | `sql_catalog` | none | **FAIL vs R4-3** — yearly `total_sales`, no MBEW |
| High inventory but low sales (API) | `sql_catalog` | none | **FAIL vs R4-3** — billed `total_sales` |
| High inventory but low sales (Full Chat follow-up) | `deep_multidim` | `inventory_analysis` | **FAIL vs R4-3** — old `billing_velocity_proxy`, not `inventory_risk_analysis` / `overstock_score` |

Live R4-3 harness (`r4_3_live_acceptance.py`) was **not** run to completion against production because the new intents are not on the deployed build. Running it now would only count expected FAILs.

---

## 6. Independent accuracy

Independent SQL against `DATABASE_URL` (Neon SAP extract) **runs**. Ground-truth samples:

| Query | Top row |
|-------|---------|
| Inventory snapshot (MATNR+BWKEY) | `ME_4002` / BWKEY `3000` / stock_value `25000000000.00` / stock_qty `50000` |
| Inventory vs sales (MATNR) | `ME_4001` stock_value `25000000000.00`, **revenue NULL** (inventory-only) |
| Product group | MATKL `00104` stock_value `100089299823.21` vs revenue `1385630.00` |

**AI vs independent SQL:** **BLOCKED** — live AI does not yet emit R4-3 comparison rows. Do not claim PASS.

---

## 7. Performance

Local unit tests only. Live P50/P95 for R4-3 intents: **not measured** (not deployed). Do not claim the &lt;1s / &lt;3s targets.

Existing live R3 inventory follow-up: **814 ms**. R4-2 growth probe: **720 ms**. Highest profits: **1600 ms**.

---

## 8. Context / Full Chat

Authenticated session: https://www.bridgeedi.com/dashboard/ai

| Turn | Observed | R4-3 expected |
|------|----------|----------------|
| Highest profits | `product_profitability`, Ship Project, 10 rows | PASS (R3) |
| Show their inventory | `inventory_analysis`, 30 rows, stock_value/qty | PASS (R3) |
| Show their sales | `product_profitability` replay | PASS-ish (existing sales of selection) |
| High inventory but low sales | `inventory_analysis` + `billing_velocity_proxy` | **FAIL** — need `inventory_risk_analysis` |
| Remaining chain (groups, suppliers, customers, regions, plant, YoY, Why, aging, inventory again) | not completed | blocked by missing R4-3 risk/compare |

No console SQL crash on the turns that ran. Context product selection survived inventory follow-up.

---

## 9. DATA GAPs (governed, must remain)

| Topic | Status |
|-------|--------|
| Inventory aging (MSEG) | DATA GAP — do not use billing/creation/expiry as age |
| True inventory turnover | DATA GAP — no temporally aligned snapshots |
| Inventory trend | DATA GAP — only current MBEW/MARD snapshot |
| Net profit / OPEX / logistics cost | DATA GAP (R3 frozen) |

---

## 10. Regression (frozen baselines — not re-run live this session)

Prior accepted live baselines (must be re-proven after `zodiac-back` deploy):

| Suite | Required |
|-------|----------|
| R3 | 23 PASS / 2 DATA GAP / 0 FAIL |
| R4-1 | 47 PASS / 2 DATA GAP / 0 FAIL |
| R4-2 | 40 PASS / 1 DATA GAP / 0 FAIL |

Spot-check this session: highest profits, inventory follow-up, and product growth still succeed on live. That does **not** replace the full harnesses.

---

## 11. Acceptance matrix

| Capability | Pipeline | SQL | Data | Accuracy | Context | UI | Latency | Status |
|---|---|---|---|---|---|---|---|---|
| Inventory snapshot | live follow-up PASS | MBEW | yes | local only | yes | Full Chat yes | ~814ms follow-up | PARTIAL (standalone catalog miss) |
| Inventory value | local | MBEW.SALK3 | SQL yes | BLOCKED live | — | — | — | NOT LIVE |
| Inventory quantity | local | MBEW.LBKUM | SQL yes | BLOCKED live | — | — | — | NOT LIVE |
| Highest inventory | local | yes | — | BLOCKED live | — | — | — | NOT LIVE |
| Inventory vs sales | **catalog on live** | independent SQL ready | SQL yes | BLOCKED | — | FAIL | — | **NOT LIVE** |
| High inventory / low sales | live = old proxy | — | — | BLOCKED | yes | FAIL vs R4-3 | — | **NOT LIVE** |
| Low inventory / high sales | not deployed | — | — | BLOCKED | — | — | — | **NOT LIVE** |
| Product group | SQL ready | MATKL independent aggs | SQL yes | BLOCKED live | — | — | — | NOT LIVE |
| Plant | local | MARD.WERKS | — | BLOCKED live | — | — | — | NOT LIVE |
| Product context | live profits→inventory | yes | yes | — | PASS | PASS | — | PASS (R3) |
| Customer follow-up | not re-run | — | — | — | — | — | — | UNVERIFIED |
| Supplier follow-up | not re-run | — | — | — | — | — | — | UNVERIFIED |
| Region follow-up | not re-run | — | — | — | — | — | — | UNVERIFIED |
| Inventory aging | intended DATA GAP | no SQL | — | — | — | — | — | UNVERIFIED live |
| DATA GAP recovery | local tests | — | — | — | local | — | — | UNVERIFIED live |
| R3 regression | spot-check only | — | — | — | — | — | — | UNVERIFIED full harness |
| R4-1 regression | not re-run | — | — | — | — | — | — | UNVERIFIED this session |
| R4-2 regression | growth spot-check | — | — | — | — | — | — | UNVERIFIED full harness |
| Full Chat | authenticated | — | — | — | partial | R4-3 miss | — | **NOT PASS** |

---

## 12. Remaining limitations (even after deploy)

- Inventory is a **current snapshot**, not a dated time series
- Do not call sales_qty/stock_qty **inventory turnover**
- Plant labels are codes only (`T001W` absent)
- Inventory is not customer-owned; region is a **sales** dimension
- Aging / true turnover / inventory trend remain DATA GAP

---

## 13. What is frozen and must not regress after deploy

R3, R4-1, R4-2, follow-up resolver, analytical context, SQL grain guard, governed metrics, DATA GAP behavior, basic GA routing.
