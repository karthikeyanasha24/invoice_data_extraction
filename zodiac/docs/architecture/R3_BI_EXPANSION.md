# R3 — Multi-dimensional BI expansion

## What changed

The deep engine is no longer a closed list of profit intents. R3 adds a **schema-backed business graph**, **dimension composition**, **supplier/PO analytics at PO grain**, **product group**, **ASP**, **inventory snapshots**, and **grain safety** — without claiming net profit, logistics cost, discount, or budget.

## Schema facts (schema_full.json, 121 tables)

Present: VBRK/vbrp, KNA1, T016T, MARA/MAKT, VBAK/VBAP, LIKP/LIPS, VBFA, EKKO/EKPO, LFA1, MBEW/MARD, KONV, BKPF/BSEG, FAGLFLEXA, COEP, MKPF.

**Absent:** ACDOCA, MSEG, COBK, KONP, T001W/TVKOT.

## New supported / partial capabilities

| Capability | Status | Grain |
|------------|--------|--------|
| Average selling price | SUPPORTED | billing_item (NETWR/FKIMG) |
| Product group (MATKL) | PARTIAL | billing_item ⋈ MARA |
| Supplier / PO value | PARTIAL | PO item (EKPO.NETWR) — **not** WAVWR |
| Inventory value/qty | PARTIAL | MBEW/MARD snapshot |
| Delivery count | PARTIAL | LIKP — **not** freight cost |
| Discount / tax | DATA GAP | KONV exists; KSCHL uncertified |
| Net profit / opex | DATA GAP | FAGLFLEXA/COEP not product-allocated |
| Logistics cost | DATA GAP | unchanged |
| Budget / EBITDA | DATA GAP | no extract |

## Relationship rule

Never join EKPO/VBFA/KONV into billing NETWR/WAVWR queries. Grain guard rejects that SQL.

## Root cause

Margin decline still compares two years of revenue, COGS, margin, quantity, and ASP. Output is **observed drivers**, not proven causation.

## Benchmark

`tests/test_r3_golden_benchmark.py` expands 500+ structured cases (intent/metric/dimension/status). Target is **supported-benchmark** accuracy, not arbitrary language.

## Production

Do not deploy from the Asha Vercel team. Live `zodiac-back` remains Andy-owned. Baseline 23/2/0 must not regress.
