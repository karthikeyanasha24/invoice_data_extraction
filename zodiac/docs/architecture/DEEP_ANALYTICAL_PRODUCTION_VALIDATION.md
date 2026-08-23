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

## Data gaps (honest)

| Request | Status |
|---------|--------|
| Net profit / EBIT | DATA GAP |
| Logistics **cost** | DATA GAP (delivery activity available) |
| Budget / target | DATA GAP |
| Expiry by industry | PARTIAL (MARA shelf-life + billing industry bridge) |
| Purchase duration | PARTIAL — billing history only (`VBRK.FKDAT`) |

## Live / Full Chat / deploy checklist (operator)

Run against API with SAP session (`USE_SAP_DB_FOR_AI`) and Full Chat UI:

1. Andy exact question list (verbatim)
2. 13-step chained drill-down
3. GA regression: `2004 → Meaning of life → Top 5` and `2004 → Meaning of life → Show sales for 2005 → Top 3`
4. Capture plan, SQL, row samples, explanation, suggested follow-ups per turn
5. Measure p50/p95/max for basic / deep single / deep multi / multi-turn
6. Confirm deployed commit matches git HEAD after push

**Script (when API is up):**

```bash
# Local
set ADAPTIVE_API=http://127.0.0.1:8000/api/query/adaptive
python zodiac/zodiac-api/scripts/live_deep_dive_chain.py

# Production backend (if authorized)
set ADAPTIVE_API=https://zodiac-back.vercel.app/api/query/adaptive
python zodiac/zodiac-api/scripts/live_deep_dive_chain.py
```

## Acceptance matrix status (closure pass)

Statuses below reflect **code + automated chain**. Cells marked *UNVERIFIED LIVE* need a DB-backed API run before claiming production DONE.

| Scenario | Plan | SQL | Data | Accuracy | Follow-up | Status |
|----------|------|-----|------|----------|-----------|--------|
| Highest profit products | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| Lowest margins | PASS | PASS (HAVING) | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| COGS | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| Cost breakdown | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| Product → customer | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| Customer → industry | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| Industry → region | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| 2024 → 2025 | PASS | PASS | UNVERIFIED LIVE | UNVERIFIED LIVE | PASS | PARTIAL |
| Expiry | PASS | PASS | UNVERIFIED LIVE | PARTIAL schema | — | PARTIAL |
| Buying process | PASS | PASS | UNVERIFIED LIVE | counts only | — | PARTIAL |
| Selling process | PASS | PASS | UNVERIFIED LIVE | counts only | — | PARTIAL |
| Logistics | PASS | no fake SQL | — | — | context kept | DATA GAP |
| Net profit | PASS | no fake SQL | — | — | context kept | DATA GAP |
