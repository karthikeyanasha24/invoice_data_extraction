# Deep multi-dimensional analysis — production validation notes

**Branch:** `phase12-first-customer-ready`  
**Module:** `analytical_deep_dive` + `business_semantic_layer`  
**Path:** after `classify_turn`, before FOLLOWUP_DELTA / intent_sql / catalog / universal

## What is proven in automated tests

| Area | Evidence |
|------|----------|
| Semantic (not phrase) gating | Paraphrases like “making us the most money”; basic “highest sales 2004…” not stolen |
| Andy exact intents | `tests/test_andy_deep_dive_cases.py` |
| Conversational product → customer → industry → region → YoY → COGS → margin decline | Mock-exec chain in Andy tests |
| Purchase history (“how long”) | Compiles first/last FKDAT + duration days |
| Lowest margin | `HAVING` min revenue ≥ 1000 |
| Net profit / logistics cost | `CANNOT_ANSWER`, no SQL |
| Adaptive hardening | Guardrail + NL hardening suites still green with deep path |

## Governed metrics (must match live)

| Metric | Formula |
|--------|---------|
| Revenue | `SUM(vbrp.NETWR)` |
| COGS | `SUM(vbrp.WAVWR)` |
| Gross profit | Revenue − COGS |
| Gross margin % | Gross profit / Revenue (NULL if revenue ≤ 0) |

Not net profit. Not logistics cost amounts.

## Grain

Billing item (`vbrp` ⋈ `VBRK`) is the monetary fact grain. Dimension joins group by dimension keys so amounts are not fan-out multiplied.

PostgreSQL requires quoted uppercase SAP tables (`"VBRK"`, `"KNA1"`, …). Adaptive `_execute_sql` applies `_quote_catalog_sql_tables`; deep SQL also emits quoted identifiers and TEXT casts for numeric-or-text amounts (`wavwr`/`netwr`).

## Data gaps (honest)

| Request | Status |
|---------|--------|
| Net profit / EBIT | DATA GAP |
| Logistics **cost** | DATA GAP (delivery activity available) |
| Budget / target | DATA GAP |
| Expiry by industry | PARTIAL (MARA shelf-life + billing industry bridge) |
| Purchase duration | PARTIAL — billing history only (`VBRK.FKDAT`) |
| Compare 2024 vs 2025 | **Empty on current extract** — billing years ≈ through 2018; answer explains and suggests 2004/2005 |

## Local SAP DB acceptance (this branch, real Postgres)

| Scenario | Pipeline | SQL | Real Data | Accuracy | Context | UI | Status |
|----------|----------|-----|-----------|----------|---------|-----|--------|
| Highest profit products | deep_multidim | PASS | PASS | PASS (indep. GP match) | PASS | — | PASS |
| Lowest margins | deep_multidim | PASS + HAVING | PASS | PASS | PASS | — | PASS |
| COGS | deep_multidim | PASS WAVWR | PASS | PASS | PASS | — | PASS |
| Cost components | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| Product → customer | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| Customer → industry | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| Industry → region | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| 2024 → 2025 | deep_multidim | PASS | empty | explained | PASS | — | PARTIAL |
| 2004 → 2005 | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| Margin decline | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| Margin explanation | deep_multidim | PASS | PASS | drivers from data | PASS | — | PASS |
| Purchase history | deep_multidim | PASS | PASS | FKDAT duration | PASS | — | PASS |
| Expiry | deep_multidim | PASS | PASS | PARTIAL schema | preserved | — | PARTIAL |
| Logistics cost | deep_multidim | none | — | — | kept | — | DATA GAP |
| Net profit | deep_multidim | none | — | — | kept | — | DATA GAP |
| Buying / selling process | deep_multidim | PASS | stage counts | counts only | PASS | — | PARTIAL |
| Full chained analysis | deep_multidim | PASS | PASS | PASS | PASS | — | PASS |
| Basic 2004 regression | intent_sql_fast | PASS | PASS | PASS | PASS | — | PASS |

Latency (16-step local chain): **p50 ≈ 1.6s**, **max ≈ 6.5s** (cold first call).

## Follow-up resolver (deterministic)

Short follow-ups (`Show COGS`, `Show the regions`, `How long have they been buying them?`) are resolved by `analytical_followup_resolver.py` against persisted `query_plan.analytical_context` **before** the NL clarification gate.

| Follow-up class | Example | Resolved intent |
|-----------------|---------|-----------------|
| METRIC_CHANGE | Show COGS / Show margins | `cogs_by_product` / `margin_by_product` |
| DIMENSION_EXPANSION | Show regions / Break by industry | `country_breakdown` / `industry_breakdown` |
| HISTORY_EXPANSION | How long have they been buying them? | `purchase_history` |
| CAUSE_ANALYSIS | Why did margins fall? | `margin_decline_drivers` |
| DATA_GAP_REQUEST | Logistics cost / net profit | `CANNOT_ANSWER` (context preserved) |

Local Andy verify (25 scenarios): **23 PASS / 2 DATA GAP / 0 FAIL** including full 17-step chain.

## Live Full Chat / zodiac-back deploy

**Status (2026-08-24, post-deploy):** Andy deployed follow-up resolver to `zodiac-back`. Live acceptance:

| Check | Result |
|-------|--------|
| Gate *highest profits* | `deep_multidim` SUCCESS, 10 rows |
| `VERIFY_MODE=live andy_live_verify.py` | **23 PASS / 2 DATA GAP / 0 FAIL** |
| 17-turn live chain | **15 PASS + 2 DATA GAP + COGS after gap PASS** |
| Data-gap chain (logistics → COGS) | DATA GAP then SUCCESS |
| Basic 2004 regression (live API) | preserved |
| Live perf (17-turn) | p50 ≈ 646ms, max ≈ 2.7s |

**Previous blocker (resolved):** Vercel CLI here cannot inspect `zodiac-back` metadata, but live API behavior confirms deploy contains `0eefed1` resolver changes.

```bash
cd zodiac/zodiac-api
npx vercel link --scope <andy-team> --project zodiac-back
npx vercel --prod
VERIFY_MODE=live python scripts/andy_live_verify.py
# expected: 23 PASS / 2 DATA GAP / 0 FAIL
```

Then re-run Full Chat on https://www.bridgeedi.com/dashboard.
