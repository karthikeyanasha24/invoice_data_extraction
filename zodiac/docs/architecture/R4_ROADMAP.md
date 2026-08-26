# R4 roadmap (post-R3) — schema-backed only

Frozen R3 baseline: commit `9424373` (perf) on `036b52a` (behavior) · live 23/2/0 · Full Chat verified.

Status: **R4-1 in implementation / deploy gate**. Do not declare R4-1 production complete until live + UI acceptance.

## Principles

1. Extend existing architecture (classify → resolve → plan → compile → grain guard → execute → explain → drill-downs).
2. Use only `schema_full.json` tables/columns.
3. Prefer business questions over table expansion.
4. Keep DATA GAPs honest (logistics cost, net profit, discount/tax/freight, budget, inventory aging).
5. No monetary fan-out through EKPO / VBFA / KONV / BSEG into billing NETWR/WAVWR.

## Schema inventory (relevant)

| Present | Absent |
|---------|--------|
| VBRK/VBRP, KNA1, T016T, MARA/MAKT, VBAK/VBAP, LIKP/LIPS, VBFA, EKKO/EKPO, LFA1, MBEW/MARD, KONV, BKPF/BSEG, FAGLFLEXA, COEP, MKPF | ACDOCA, MSEG, COBK, KONP, T001W, TVKOT |

## Capability ranking

| Capability | Business value | Tables | Grain | Confidence | Complexity | Status |
|---|---|---|---|---|---|---|
| Month / quarter trends (billing) | High — seasonality & growth | VBRK.FKDAT | billing_item by period | High | Low | **R4-1 implemented** (local; live acceptance pending) |
| Product growth / decline ranking | High | VBRP/VBRK YoY | billing_item | High | Medium | **R4-2 ready** |
| Inventory vs sales (snapshot×velocity) | High | MBEW + VBRP | snapshot ⋈ product (no fan-out of NETWR) | Medium | Medium | **R4-3 ready** (velocity already conditional) |
| Supplier concentration by product | High | EKPO/EKKO/LFA1 | PO item | Medium | Medium | **R4-4 ready** (association only; no supplier profit) |
| Delivery cycle times (order→delivery→billing) | High | VBAK/LIKP/VBRK/VBFA | document-flow counts/dates | Medium | High | **R4-5 careful** |
| Customer value change / mix shift | High | VBRP/KNA1 | billing_item | High | Medium | **R4-6 ready** |
| Plant / warehouse (beyond MBEW.BWKEY) | Medium | needs T001W | — | Low | Blocked | **blocked** (T001W absent) |
| True inventory aging | High | MSEG | — | — | Blocked | **DATA GAP** |
| Logistics freight amount | High | — | — | — | Blocked | **DATA GAP** |
| Product net profit / OPEX | High | ACDOCA | — | — | Blocked | **DATA GAP** |
| Certified discount/tax/freight | Medium | KONV+KSCHL | — | Low | Blocked until KSCHL certified | **DATA GAP** |
| Budget / target | Medium | — | — | — | Blocked | **DATA GAP** |

## Ranked R4 sequence

1. **R4-1 Month/quarter** — complete period dimensions; low risk; high UX value.
2. **R4-2 Product growth/decline** — reuse YoY pattern from margin decline; governed metrics only.
3. **R4-3 Inventory↔sales** — explicit snapshot vs billed-qty proxy; never call it aging.
4. **R4-4 Supplier concentration** — PO grain; refuse supplier profit attribution.
5. **R4-6 Customer mix shift** — before delivery cycle (easier grain).
6. **R4-5 Delivery cycle** — only after VBFA grain audits and golden cases.

## Acceptance framework (required before each R4 slice)

For every new capability add golden cases covering:

Intent × Metric × Dimension × Follow-up × Data status × Grain risk

Verify: routing, SQL tables/joins, grain guard, context inheritance, DATA GAP honesty, Full Chat suggestions from current context only.

## Explore-further (UX)

Suggestions must come from `available_drilldowns` + current selection. After highest-profit products, prefer: customers, industry, regions, product groups, suppliers, ASP, inventory — only if schema-supported.
