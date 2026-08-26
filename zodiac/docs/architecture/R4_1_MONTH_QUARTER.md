# R4-1 Month / Quarter Trends

Status: **implemented locally** — not production-complete until Andy deploys to `zodiac-back` and live + Full Chat acceptance pass.

Prerequisite production baseline after performance hardening: commit **`9424373`**.

## Scope

- Month labels: `YYYY-MM` from `VBRK.FKDAT` (TEXT YYYYMMDD) via governed `fkdat_time`
- Quarter labels: `YYYY-Q1`…`YYYY-Q4` (year-aware chronological order)
- MoM / QoQ / YoY monthly / YoY quarterly comparisons
- Metrics: revenue, COGS, GP, margin %, quantity, invoice_count, ASP only
- Grain: billing_item `VBRP → VBRK` only (no EKPO/VBFA/KONV/BSEG/MBEW fan-out)

## Out of scope (later R4)

product growth, supplier concentration, customer mix, delivery analytics, net profit/OPEX/logistics/budget

## Key modules

| Module | Role |
|--------|------|
| `app/services/fkdat_time.py` | Single governed FKDAT normalization |
| `analytical_deep_dive.py` | `monthly_trend` / `quarterly_trend` intents + SQL |
| `analytical_followup_resolver.py` | TIME_CHANGE + metric preserve on trends |
| `business_intelligence_inventory.py` | month/quarter dimensions + compose_intent |
| `tests/test_r4_1_month_quarter_trends.py` | Dedicated R4-1 suite |

## Acceptance gate

Local R4-1 tests PASS + R3 regression green → push branch → Andy `npx vercel --prod` on **zodiac-back only** → live R3 23/2/0 + R4-1 live probes + Full Chat → then `R4-1 PRODUCTION COMPLETE`.
