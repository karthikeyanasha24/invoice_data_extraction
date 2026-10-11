# AI Analyst reported-issue validation — 10 October 2026

The fixes are in the local repository. They have not been deployed.

## Reported issues and changes

- **Inventory versus sales:** connected a schema-gated comparison to the existing four-stage pipeline. Stock and billing aggregate independently at client/material/base-unit grain. Source identities are checked before execution. Exact duplicates are collapsed, split-valued stock is not counted twice, missing matches stay NULL, and amounts remain separate by currency. Stock is an undated extract snapshot; its as-of date is not claimed.
- **Supplier concentration:** computes supplier purchase-order value shares within each SAP client and currency. Deleted orders/items are excluded. The full eligible denominator is calculated before selecting the top suppliers. It is purchase-order association, not supplier profit or a verified single-source risk score. Additional unsupported constraints remain with normal planning.
- **False data limitations:** failed schema mapping no longer claims that the requested data is absent.
- **Year-filter failures:** valid SAP date prefixes such as LIKE '2004%' are recognized. A missing billing date filter is inserted in the billing SELECT scope, preserving the stock snapshot and OR conditions. Complete comparisons start with their own schema context rather than patching stale context.
- **Incorrect repairs:** inventory comparisons must include both inventory and billing sources and output measures. A sales-only total cannot become a successful inventory comparison. Unbound table qualifiers and raw billing-to-stock fanout are rejected.
- **Monthly revenue:** charts retain the complete time series and show one selected currency at a time. Monthly labels use YYYY-MM; the initial time-series range covers the latest 24 observations. Every currency remains available in the selector and table. Stock quantity charts do not put money on the same quantity axis.
- **General-question failure display:** removed the unrelated SQL-generation notice. Model service failures have an AI-service heading and their actual cause.

## Verification

- **322 backend tests passed**, including duplicate/cross-client fixtures, supplier denominator checks, base-unit comparisons, missing matches, date predicates, SQL scopes, grain guards, chat understanding, and execution contracts.
- **20 frontend tests passed** for chart selection, conversation context, answer presentation, and progress.
- TypeScript noEmit checking and the optimized Next.js production build passed.
- Git whitespace checks passed.
- **19 mixed runtime cases: 17 passed, 2 blocked, 0 failed.** External model HTTP transports were disabled; background chat persistence was not executed.
- The five reported/filtered cases were rerun after the stricter source-quality gate: **5 passed, 0 failed**.

| Runtime case | Outcome | Seconds |
| --- | --- | --- |
| numeric arithmetic | PASS | 0.84 |
| mistyped arithmetic | PASS | 0.95 |
| general explanation | BLOCKED | 1.42 |
| coding | BLOCKED | 0.77 |
| topic change after coding | PASS | 0.72 |
| percentage calculation | PASS | 0.72 |
| table count | PASS | 2.73 |
| schema description | PASS | 1.31 |
| sales order count | PASS | 9.76 |
| billed invoice count | PASS | 3.86 |
| customer ranking | PASS | 8.05 |
| database follow-up | PASS | 5.74 |
| arithmetic after database result | PASS | 0.7 |
| division by zero | PASS | 0.7 |
| reported inventory comparison | PASS | 7.09 |
| reported supplier concentration | PASS | 4.64 |
| supplier year and currency | PASS | 5.3 |
| inventory billing period | PASS | 6.5 |
| reported monthly revenue | PASS | 7.14 |

## Remaining external requirements

The latest literal-only model probe returned HTTP 429, code credit_balance_exhausted. General explanations and coding cannot be verified through the configured model service until its credits are restored. There is no canned replacement for general AI reasoning.

The earlier automatic approval review blocked sending private database result samples to the configured external model service. The database acceptance runs instead kept all results local, with both shared and legacy HTTP model transports disabled. Full live model summaries/follow-ups require the previously requested data-sharing approval as well as funded model access.

Deployment is pending.
