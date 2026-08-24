# R3 production baseline (frozen 2026-08-24)

Do not regress this behavior when expanding multi-dimensional BI.

## Git / deploy

| Item | Value |
|------|--------|
| Branch | `phase12-first-customer-ready` |
| Resolver commit | `0eefed1` |
| Production API | `https://zodiac-back.vercel.app` |
| Frontend | `https://www.bridgeedi.com/dashboard` |
| Live acceptance | **23 PASS / 2 DATA GAP / 0 FAIL** |

## Supported dimensions (baseline)

product, customer, industry, country/region, year, month, currency, process_stage (partial)

## Supported metrics (baseline)

revenue (NETWR), cogs (WAVWR), gross_profit, gross_margin_pct, quantity, invoice_count

## DATA GAPs (genuine)

| Metric | Reason |
|--------|--------|
| Logistics cost | LIKP/LIPS activity only; no reliable freight amount |
| Net profit | No product-level opex allocation (ACDOCA absent; FAGLFLEXA/COEP not at billing grain) |

## Performance (live 17-turn)

P50 ≈ 646 ms · P95 ≈ 2.7 s · max ≈ 2.7 s

## Golden chain

Highest profits → customers → industry → regions → 2004/2005 → COGS → margins → margin decline → why → components → purchase history → buy/sell/delivery process → logistics DATA GAP → net profit DATA GAP → COGS again PASS.
