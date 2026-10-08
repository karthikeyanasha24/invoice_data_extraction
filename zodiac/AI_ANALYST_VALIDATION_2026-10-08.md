# AI Analyst validation — 8 October 2026

Local source changes are implemented; production deployment and full live AI verification are pending. Existing uncommitted changes were preserved.

## Changes

- General arithmetic uses a bounded decimal evaluator; no model or database is needed. Handles number words, parentheses, percentages, decimal precision, common question-prefix typos, and undefined calculations. Rounded results are marked approximate.
- Self-contained calculations bypass database follow-up heuristics, preserving chat history. Model keys are no longer required for model-independent capabilities.
- Schema answers read current information_schema metadata. If the database is unavailable, the answer explicitly identifies the saved schema snapshot.
- Explicit total counts use the requested SAP document headers: VBAK for sales orders, VBRK for billing documents. Counts use distinct client/document keys and preserve explicit years. Additional predicates stay with normal planning.
- Monetary rankings remain separate by currency and now state that clearly.
- Unanchored linked-document requests cannot reconstruct an analysis without its prior request.
- Provider failures identify exhausted credits, rate limits, and configuration issues. Cooldown retains the original failure cause.
- The page has a visible New chat control and general-question starter examples.

## Verification

- Backend: 201 tests passed across execution contracts, SQL grain, guardrails, understanding, chat reliability, schema/counts, arithmetic, and provider failures. An additional approximation test was added afterward and the calculator suite rerun.
- Frontend: 19 context, presentation, and progress tests passed.
- TypeScript: noEmit checking passed.
- Git diff whitespace check passed.
- Runtime acceptance: 12/14 passed, 2 blocked, 0 failed. Database queries used read-only transactions; background chat persistence was not executed. Both shared and legacy external model transports were disabled.

| Case | Outcome | Seconds |
| --- | --- | --- |
| numeric arithmetic | PASS | 1.86 |
| mistyped arithmetic | PASS | 0.81 |
| general explanation | BLOCKED | 1.36 |
| coding | BLOCKED | 0.92 |
| topic change after coding | PASS | 0.81 |
| percentage calculation | PASS | 0.81 |
| table count | PASS | 2.78 |
| schema description | PASS | 1.5 |
| sales order count | PASS | 15.81 |
| billed invoice count | PASS | 6.8 |
| customer ranking | PASS | 9.22 |
| database follow-up | PASS | 9.91 |
| arithmetic after database result | PASS | 0.8 |
| division by zero | PASS | 1.06 |

## Remaining work

The latest literal-only model probe returned HTTP 429 with error code credit_balance_exhausted. General explanations, coding, and real model reasoning cannot be fully verified until the configured model service has credits. The database connectivity probe passed.

Automatic approval review rejected the live mixed test because it could send private database result samples to the configured external model service. Specific approval was requested. The local-only alternative completed without sending database results to a model.

After credits and approval are available, run scripts/verify_adaptive_mixed_runtime.py without --local-db-only to complete live verification. Review that report and any failures before deployment.
