# R4-3 Inventory ↔ Sales Snapshot

Status: **implemented locally** — not production-complete until live + independent SQL + Full Chat acceptance pass.

Prerequisite: R4-2 production baseline (**40 PASS / 1 DATA GAP / 0 FAIL**) on `zodiac-back`.

## Schema audit (schema_full.json)

| Table | Grain | Fields used | Notes |
|-------|-------|-------------|-------|
| MBEW | MATNR + BWKEY + BWTAR | SALK3 (value), LBKUM (valuated qty) | Current snapshot. LFGJA/LFMON are last-movement stamps, not a snapshot series. |
| MARD | MATNR + WERKS + LGORT | LABST (unrestricted qty) | Plant = WERKS code. T001W absent. |
| MARA | MATNR | MATKL (product group) | |
| MAKT | MATNR + SPRAS | MAKTX | |
| VBRP | billing item | NETWR, WAVWR, FKIMG, MATNR, WERKS | Sales facts. |
| VBRK | billing header | FKDAT, KUNAG, WAERK | Period for sales only. |
| MSEG | — | — | **Absent** → aging DATA GAP |
| T001W | — | — | **Absent** → plant text DATA GAP |

Aggregation rule:

- Material inventory: `SUM(MBEW.SALK3)`, `SUM(MBEW.LBKUM)` `GROUP BY MATNR` (snapshot view also keeps BWKEY).
- Plant inventory: `SUM(MARD.LABST)` `GROUP BY WERKS` or `MATNR+WERKS+LGORT`.
- Sales: `SUM(NETWR/WAVWR/FKIMG)` `GROUP BY MATNR` from `VBRP→VBRK`.
- Compare: **independent aggregations joined on MATNR** (or MATKL). Never `FROM vbrp JOIN MARD/MBEW SUM(NETWR)`.

## Intents

| Intent | Meaning |
|--------|---------|
| `inventory_analysis` | Current snapshot (R3, frozen) |
| `inventory_sales_comparison` | Snapshot vs billed activity |
| `inventory_risk_analysis` | High inv / low sales or low inv / high sales via `PERCENT_RANK` |
| `inventory_by_plant` | MARD.WERKS codes |
| `inventory_aging_gap` | DATA GAP (no MSEG) |
| `inventory_turnover_gap` | DATA GAP (no dated snapshots) |
| `inventory_trend_gap` | DATA GAP (no historical inventory) |

Risk ranking uses percentile difference (`overstock_score` / `undersupply_score`). No hardcoded inventory > X / sales < Y.

Ratios (`sales_qty_to_stock_qty`, `inventory_value_to_revenue`) are **not** inventory turnover. NULL when the denominator is 0/NULL.

Language: "current inventory snapshot vs sales activity". Do not say stock will run out. Do not invent inventory in 2004.

## Frozen baselines

Do not regress R3 23/2/0, R4-1 47/2/0, R4-2 40/1/0.
