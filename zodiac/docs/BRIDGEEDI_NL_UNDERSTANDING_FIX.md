# BridgeEDI — Natural-Language Understanding + Failure-UX Fix

**Date:** 2026-08-31 · **Branch:** `phase12-first-customer-ready` · **Scope:** AI Analyst / Adaptive Query only
**Status:** LOCAL — implemented, tested, **not yet committed or deployed** (deploy is owner-run).
**Frozen R3–R4-4 analytical contracts:** untouched and still green.

---

## ROOT CAUSE

The client asked: *"Can you show me which customer and country and industry the highest sales reflected?"* and got a "Please rephrase as a business question" fallback with three internal states leaking to the UI (`too_short`, `-1 rows returned`, and a contradictory "Limitations: None reported").

Two independent defects:

**1. Language understanding (backend).** The failure is **not** about the missing year, as the fallback example ("highest sales in 2004 by customer") implied. Reproduced against live production:

| Phrasing | Result |
| --- | --- |
| `top customers by sales` | ✅ SUCCESS |
| `top 5 customers by sales` | ✅ SUCCESS |
| `Show total sales by customer` | ✅ SUCCESS |
| `who had the highest sales` | ✅ SUCCESS |
| `Which customer had the highest sales?` | ❌ CANNOT_ANSWER |
| `Which customer had the highest sales in 2004?` | ❌ CANNOT_ANSWER (year present, still fails) |
| `Which customer generated the most sales` | ❌ CANNOT_ANSWER |
| `Which customer and country and industry had the highest sales?` | ❌ CANNOT_ANSWER |

The classifier/planner fails to map the **interrogative phrasing "which customer … the highest/most sales"** onto the top-customers intent, even though the SQL engine answers the canonical form perfectly. It is a classification gap, not an engine defect — so the fix belongs in language normalization, not in SQL.

**2. Failure-state UX (frontend).** The `CANNOT_ANSWER` path already renders a clean data-gap card, but the **`CLARIFICATION`** path fell through to the *success* renderer, which is why the screenshot showed the raw reason code `too_short` in Key Findings, `Result size: -1 rows returned`, and a full "How this was calculated" panel claiming "Limitations: None reported" on a response that produced no result.

---

## FILES CHANGED

| File | Change | Δ |
| --- | --- | --- |
| `zodiac-api/app/services/ranking_question_normalizer.py` | **New.** Deterministic normalizer for interrogative sales/revenue ranking questions. | new |
| `zodiac-api/app/api/adaptive_query.py` | Call the normalizer once, before routing; preserve the user's original wording for stored history. | +14 / −1 |
| `zodiac-api/tests/test_ranking_question_normalizer.py` | **New.** 7 governed tests (rewrite + must-not-touch). | new |
| `zodiac-front/src/components/DashboardAIAnalysis.tsx` | Humanize Key Findings (drop internal reason codes); dedicated Clarification card; no trust panel on clarification. | +58 / −3 |
| `zodiac-front/src/lib/analysisTrust.ts` | Never render a negative row count as "Result size". | +1 / −1 |

No changes to the SQL compiler, intent registry, grain model, governance, security, or any R3–R4-4 logic.

---

## LANGUAGE FIX

A single deterministic pre-classification step. It fires **only** on interrogative sales/revenue ranking questions and rewrites them into the governed canonical form the engine already answers. It is intentionally narrow — it ignores anything containing profit / margin / COGS / cost / count / quantity / inventory / supplier / concentration / aging so it can never touch a different governed intent or a frozen contract question. Primary dimension is limited to **customers** and **countries** (whose canonical form returns the correct dimension); industry/product-primary rankings are left unchanged rather than risk a wrong-dimension answer.

```
which customer had the highest sales?                  -> top customers by sales
who generated the most revenue?                        -> top customers by revenue
which customer had the highest sales in 2004?          -> top customers by sales in 2004
which country had the highest sales?                   -> top countries by sales
Can you show me which customer and country and         -> top customers by sales
   industry the highest sales reflected?                  with countries and industries
```

Every rewrite target was verified to return SUCCESS on live production before shipping, and every R3–R4-4 / deep-dive / other-intent phrasing tested returns **unchanged** (verified: 0 of 15 working questions altered).

## EXACT CLIENT QUESTION

```
input:            Can you show me which customer and country and industry the highest sales reflected?
normalized:       top customers by sales with countries and industries
selected intent:  top customers (governed sales ranking)
metric:           sales (VBRK header)
dimensions:       customer (primary) + country
result (live on canonical form): SUCCESS, customer + country + total_sales, real rows
```

Known residual (pre-existing engine limitation, not caused by this fix): the industry *attribute column* is not always emitted, and "top industries by sales" as a primary currently routes to products — which is exactly why industry-primary rankings are deliberately left unchanged here. A proper industry-ranking intent is a separate, governed follow-up.

## UX FIX

| Symptom | Fix |
| --- | --- |
| `too_short` shown in Key Findings | Internal reason codes and internal SQL-exhaustion notes are filtered out of Key Findings; bare snake_case codes never render. |
| `Result size: -1 rows returned` | Negative / non-finite counts are treated as unknown and omitted. |
| `Limitations: None reported` on a failed response | `CLARIFICATION` now renders a dedicated, human-readable card with example questions and **no** "How this was calculated" panel. `CANNOT_ANSWER` keeps its honest data-gap card. |

## REGRESSION RESULTS (local)

| Suite | Result |
| --- | --- |
| New normalizer tests | **7 / 7 PASS** |
| Backend governed suite (tests + app/tests, excl. live-AI bench) | **603 passed / 2 failed** — the 2 failures are the **same pre-existing** ones (operational-routing edge case; stale onboarding test), unchanged by this fix. **No new failures.** |
| `adaptive_query` import | OK |
| Frontend `test:ux` | **43 / 43 PASS** |
| Frontend `test:adaptive-context` | **8 / 8 PASS** |
| Frontend `next build` | **✓ Compiled successfully, 0 errors** |

Not regressed and re-confirmed unchanged by the normalizer: supplier concentration, Top-3 = 3, `suppliers_of_selection`, DATA-GAP honesty (aging / net profit / logistics), context isolation, and the 8-turn deep-dive chain (none of those phrasings match the normalizer's trigger).

## PRODUCTION STATUS

- Local only. **Not committed. Not pushed. Not deployed. Not live-verified.**
- Evidence the client question will work after deploy: (a) the normalizer deterministically rewrites it to `top customers by sales with countries and industries`, and (b) that exact string already returns SUCCESS on the current production engine, which this change does not modify.
- Final live verification must be done after the owner deploys the branch to the canonical `zodiac-back` (backend) and `www.bridgeedi.com` (frontend) Vercel projects. Do **not** deploy to `zodiac-api-nu`.
