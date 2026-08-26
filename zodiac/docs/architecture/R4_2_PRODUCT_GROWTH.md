# R4-2 Product Growth / Decline

Status: **implemented locally** — not production-complete until Andy deploys to `zodiac-back` and live + Full Chat acceptance pass.

Prerequisite: R4-1 production baseline (**47 PASS / 2 DATA GAP / 0 FAIL**) on commit family `e8c945e`.

## Scope

- Intent: `product_growth_decline`
- Governed helpers: `app/services/product_growth.py`
  - `absolute_change = current − previous`
  - `growth_pct` NULL when previous = 0 (no infinity)
  - `NEW_NO_PRIOR_BASE` / `FULL_DECLINE_NO_CURRENT` / `CONTINUING`
  - Absolute vs percentage ranking (semantic)
- Metrics: revenue, COGS, GP, margin pp, quantity, ASP, invoice_count
- Period grains: YoY (default 2004/2005), MoM (LAG on `YYYY-MM`), QoQ (LAG on `YYYY-Qn`)
- Grain: billing_item `VBRP → VBRK` only
- Observed-driver language (not causal certainty)
- Customer-mix companion query: `product_change_customer_drivers`

## Routing order (must preserve)

1. Month/quarter **margin** ranking → R4-1 `monthly_trend` / `quarterly_trend`
2. Product margin YoY → R3 `margin_decline_drivers`
3. Product growth/decline → R4-2 `product_growth_decline`
4. Generic period compare

## Key modules

| Module | Role |
|--------|------|
| `product_growth.py` | Canonical change formulas + semantic resolvers |
| `analytical_deep_dive.py` | Plan + SQL + interpret + empty period |
| `analytical_followup_resolver.py` | Why / metric / dimension follow-ups |
| `tests/test_r4_2_product_growth_decline.py` | Dedicated suite |
| `scripts/r4_2_live_acceptance.py` | Live probes after deploy |
| `scripts/r4_2_independent_sql.py` | Independent SQL accuracy |

## Out of scope

R4-3+, logistics cost, net profit/OPEX, budget, certified discount/tax/freight.

## Acceptance gate

Local R4-2 + R4-1 + R3 green → push → Andy `npx vercel --prod` on **zodiac-back only** → live R3 23/2/0 + R4-1 47/2/0 + R4-2 live + Full Chat → then `R4-2 PRODUCTION COMPLETE`.
