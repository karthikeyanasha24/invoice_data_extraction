# R3 production baseline (updated 2026-08-26)

Do not regress this behavior when expanding multi-dimensional BI (R4-1+).

## Git / deploy

| Item | Value |
|------|--------|
| Branch | `phase12-first-customer-ready` |
| **Current production baseline** | **`9424373`** — Harden R3 latency: inventory query skip, compare LIMIT, split timings |
| Prior behavioral baseline | `036b52a` — Fix R3 product-group follow-up routing and MBEW inventory SQL |
| R3 feature commit | `5bd81a4` |
| Follow-up resolver | `0eefed1` |
| Production API | `https://zodiac-back.vercel.app` |
| Frontend Full Chat | `https://www.bridgeedi.com/dashboard/ai` |
| Live acceptance (behavioral) | **23 PASS / 2 DATA GAP / 0 FAIL** |
| R3 unit / golden | **35/35** · **694+ golden cases** · **17/17 short follow-ups** |

Historical note: `036b52a` remains the accepted R3 capability baseline. `9424373` freezes the performance-hardened release on top of that behavior (do not overwrite historical measurements below).

## Supported dimensions

product, customer, industry, country/region, year, **month (YYYY-MM)**, **quarter (YYYY-Qn)** (R4-1), currency, supplier (PO grain), product_group (MATKL), warehouse/valuation_area (inventory snapshot), process_stage (partial)

## Supported metrics

| Metric | Definition | Grain |
|--------|------------|--------|
| revenue | billing NETWR | billing_item |
| cogs | billing WAVWR | billing_item |
| gross_profit | NETWR − WAVWR | billing_item |
| gross_margin_pct | gross_profit / revenue | billing_item |
| quantity | FKIMG | billing_item |
| avg_selling_price (ASP) | SUM(NETWR) / SUM(FKIMG) | billing_item |
| purchase_value | EKPO.NETWR | PO item — **not** invoice COGS |
| inventory stock_value / stock_qty | MBEW.SALK3 / LBKUM | inventory **snapshot** |
| invoice_count | COUNT(DISTINCT VBELN) | billing_header |

## Grain / fan-out rules

- Never join EKPO / VBFA / KONV / BSEG into billing NETWR/WAVWR aggregations.
- Supplier analysis is PO grain (`purchase_value`), never inferred billing profit.
- Product group uses MARA.MATKL at billing grain without duplicating amounts.
- Inventory is MBEW/MARD snapshot — **not** aging (MSEG absent).
- `sql_grain_guard` rejects unsafe monetary fan-out SQL.
- Month/quarter trends use governed `fkdat_time` SUBSTRING on TEXT FKDAT (never CAST AS DATE).

## Follow-up behavior

Short follow-ups inherit `analytical_context` via `analytical_followup_resolver` (deterministic). Pronouns (`their`, `them`, `those`) preserve product/customer selection. `"by product group"` must not be stolen by bare `"by product"`. Month/quarter TIME_CHANGE preserves selection and metric switches stay on the active time grain.

## DATA GAPs (genuine — do not fabricate)

| Metric | Reason |
|--------|--------|
| Logistics cost amount | LIKP/LIPS activity only; no reliable freight amount |
| Product-level net profit / OPEX | ACDOCA absent; FAGLFLEXA/COEP not at billing grain |
| Certified discount / tax / freight | KONV present; KSCHL uncertified |
| Budget / target | No extract |
| True inventory aging | MSEG absent |

## Performance snapshot (pre-hardening, live acceptance 2026-08-26)

| Metric | Value |
|--------|--------|
| P50 (17-turn / mixed) | ≈ 701–828 ms |
| P95 | ≈ 4.6–5.9 s |
| Max | ≈ 9.4 s (purchase history / cold start suspected) |
| Prior pre-R3 reference | P50 ≈ 646 ms · P95 ≈ 2.7 s |

See `R3_PERFORMANCE_HARDENING.md` for warm-path scenario table and post-`9424373` live probe notes.

## Golden 17-turn chain

Highest profits → customers → industry → regions → 2004/2005 → COGS → margins → margin decline → why → components → purchase history → buy/sell/delivery process → logistics DATA GAP → net profit DATA GAP → COGS again PASS.

## R3 extended chain

Highest profits → suppliers (EKPO) → purchase history → product group (MATKL) → ASP → inventory (MBEW) → highest inventory → suppliers associated → purchase-cost / margin drivers → regions / YoY.

## Status

**R3 PRODUCTION COMPLETE** (behavioral `036b52a` + performance freeze `9424373`). Protect this baseline when shipping R4-1.
