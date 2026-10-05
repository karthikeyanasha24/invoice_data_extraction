# Local AI Analyst browser verification — 2026-10-05

Target: http://localhost:3000/dashboard/ai. No deployment was performed.

## Actual browser runs

The frontend proxies `/api/query` to the API on port 8000. Its original worker predated the source fixes and had a dead reload parent. Only this local API was restarted; the frontend and separate API on port 8002 were preserved. A subsequent automatic reload stalled, so the final test API was started without reload (PID 24352).

1. The original four-turn conversation was exercised before the restart. It repeated clarification, then executed a linked-order query and returned no matching records. Its existing chat carried posting-date preferences from earlier turns. Evidence: `localhost_before_restart.txt` and `.jpg`.
2. A fresh chat after restarting returned seven customer/currency rows. Four had zero in 2000 and negative amounts only in 2001. This exposed an additional baseline eligibility bug. Evidence: `localhost_baseline_bug.txt`.
3. Generic period comparison generation now requires baseline facts for baseline rankings and applies the requested numeric predicate to the baseline aggregate. Result validation also rejects baseline values that violate the predicate. The next actual browser run returned only three eligible customers. Its executed SQL has `HAVING COUNT(CASE WHEN ... = '2000' THEN 1 END) > 0` and a negative baseline aggregate. Evidence: `localhost_baseline_fixed.txt` and `.jpg`.
4. The exact follow-up asking to compare invoices and their linked sales orders incorrectly reused two previous rows and subtracted their `change` values. The overly broad `compare with` match in the in-memory difference shortcut caused this. Evidence: `localhost_followup_shortcut_bug.txt`.
5. Removed that broad match. Actual difference questions remain supported; requests needing additional facts go to the planner. Four regressions cover invoice/order, delivery, purchase-order, and inventory follow-ups. No production question, answer, year, customer, or amount was hardcoded.
6. A fresh browser run on the final API again executed the original question successfully and returned the same three rows below. Evidence: `localhost_current_verified.txt` and `.jpg`.

| Customer | Currency | Negative billed amounts, 2000 | Negative billed amounts, 2001 | Difference |
|---|---|---:|---:|---:|
| R111 | DEM | -12.19 | -10.19 | 2.00 |
| R110 | DEM | -2.63 | -14.98 | -12.35 |
| R112 | DEM | -0.28 | 0.00 | 0.28 |

These are customer aggregates of negative invoice-header amounts. The zero is a CASE aggregation default when no qualifying negative amount is present in the comparison period; it does not establish that all net billed sales were zero. This browser result does not itself verify invoice-level or linked-order analysis.

## Latest automated verification

302 selected tests passed in 66.63 seconds, with two existing deprecation warnings. The suites cover local SQL execution, multilingual lookup cardinality, document-period identity, comparison structure, SQL generation/repair, four-stage execution, result validation, measure/currency semantics, pending-request continuity, grain, follow-up routing, chat reliability, native execution, and guardrails. Earlier focused runs passed 34 and 75 tests. Local fixtures include multiple year pairs and comparison-only entities.

## Remaining browser verification

Automatic approval review rejected submission of the follow-up after the final first-question run. It stated that this application workflow may send internal schema and prior results to OpenAI, and requested explicit authorization for that payload and destination. No workaround or indirect submission was used after this rejection. A specific approval request was presented to the user.

The revised follow-up is **offline-tested, browser verification pending**. The third and fourth turns on the revised final code are also pending. Do not claim the whole conversation or live deployment is fixed based on the initial successful query.

The local browser is left open at the successful first result; the final API remains running. Provider calls in the successful browser runs were real, and the database queries executed against the configured connection. Fixture tests use controlled planner outputs and must not be described as real-model acceptance.
