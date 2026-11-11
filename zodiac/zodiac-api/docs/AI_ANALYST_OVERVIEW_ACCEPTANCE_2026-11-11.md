# AI Analyst and Overview local acceptance — 11 November 2026

The original 39 API workflows were rerun against the patched local API and configured SAP extract. Two ambiguous-period saved questions were subsequently blocked and retested against the final code. All 39 now meet the expected behavior, including four deliberate stale or incomplete-query rejections.

## Changes

- Basic computes individual billing-line minima/maxima by industry, SAP client, year, and currency without model calls. Unknown industry groups stay visible.
- Saved questions requesting unspecified specific years require review; typed Basic requests ask for the period before running SQL or a model.
- Overview compares equal 90-day windows, keeps currencies separate, retains genuine 100% declines, and shows unavailable inbound data instead of zeros.
- Overview loads without automatic model insights or BI backfill. Its customer investigation link is self-contained.

## Verification

- Backend regression suite: 145 passed (three existing dependency deprecation warnings).
- Frontend suites: 74 passed. Production build and TypeScript checks passed.
- Basic industry minima: nine groups exactly match an independent source query; zero model calls.
- Agentic industry minima: all nine groups match the same independent query.
- Basic and Agentic customer/country comparisons return the requested years; all returned monetary differences match exact decimal subtraction in matching currencies.
- Independent annual order/invoice controls: all seven order groups and eight invoice groups match. The SQL Training year-range checks accept those valid controls.
- Document drill-down: 537 unique documents across seven pages, with exact reconciliation and zero model calls.
- Both invoice investigations finish with the missing-order-item explanation instead of a repair loop or invented cause.
- Overview inbound and business APIs: HTTP 200; three separate currency groups; no model insights requested.
- The 39-workflow matrix used 45 model calls in total. The new Basic and Overview checks use zero model calls.

## Limits

- The referenced SAP order item remains absent from the extract. Its pricing/quantity cause needs the original source item and relevant pricing/document-flow records; application code cannot reconstruct those facts.
- Fresh browser automation was unavailable because browser control was disabled in Work settings. These final checks are API, unit, TypeScript, and production-build checks.
- Delivery is the GitHub fix branch, as requested. Production deployment was excluded by the user.
- Raw responses stay outside Git because they contain business records. Business SQL is read-only; ordinary test conversations and SQL Training run logs may be persisted by the application.

## Original workflow matrix

| Workflow | Result | Status | Rows | Model calls |
| --- | --- | --- | ---: | ---: |
| 01_stale_saved_2000 | PASS — expected block | 409 | — | 0 |
| 02_basic_2000_offer | PASS | SUCCESS | 61 | 0 |
| 03_basic_2000_run | PASS | SUCCESS | 61 | 0 |
| 04_basic_2000_2004_offer | PASS | CLARIFICATION | 0 | 0 |
| 05_basic_2000_2004_run | PASS | SUCCESS | 200 | 0 |
| 06_saved_1999 | PASS | SUCCESS | 200 | 0 |
| 07_typed_1999 | PASS | SUCCESS | 200 | 0 |
| 08_agent_2000_2001 | PASS | SUCCESS | 9 | 5 |
| 09_agent_2000 | PASS | SUCCESS | 61 | 0 |
| 10_agent_2000_2004 | PASS | SUCCESS | 200 | 0 |
| saved_02 | PASS | SUCCESS | 10 | 0 |
| saved_03 | PASS | SUCCESS | 200 | 0 |
| saved_04 | PASS | SUCCESS | 200 | 0 |
| saved_05 | PASS | SUCCESS | 86 | 0 |
| saved_06 | PASS | SUCCESS | 87 | 0 |
| saved_07 | PASS — expected block | 409 | — | 0 |
| saved_08 | PASS | SUCCESS | 86 | 0 |
| saved_09 | PASS — expected block | 409 | — | 0 |
| saved_10 | PASS — expected block | 409 | — | 0 |
| saved_11 | PASS | SUCCESS | 10 | 0 |
| saved_12 | PASS | SUCCESS | 200 | 0 |
| filter_count_1999_category | PASS | SUCCESS | 1 | 4 |
| filter_empty_2099 | PASS | SUCCESS_EMPTY | 0 | 4 |
| filter_lowest_industry_1999 | PASS | SUCCESS | 9 | 4 |
| filter_negative_1999 | PASS | SUCCESS_EMPTY | 0 | 3 |
| filter_sum_1999_category | PASS | SUCCESS | 1 | 4 |
| filter_sum_1999_usd | PASS | SUCCESS | 1 | 4 |
| clarify_category | PASS | SUCCESS | 16 | 3 |
| clarify_type | PASS | SUCCESS | 81 | 3 |
| ranking_00 | PASS | SUCCESS | 20 | 3 |
| ranking_01 | PASS | SUCCESS | 20 | 1 |
| ranking_02 | PASS | SUCCESS | 10 | 1 |
| ranking_03 | PASS | SUCCESS | 7 | 1 |
| ranking_04 | PASS | SUCCESS | 7 | 2 |
| ranking_05 | PASS | SUCCESS | 10 | 2 |
| ranking_06 | PASS | SUCCESS | 10 | 1 |
| diagnosis_00 | PASS | SUCCESS | 1 | 0 |
| diagnosis_01 | PASS | SUCCESS | 1 | 0 |
| drilldown_2001_dem | PASS | SUCCESS | 25 | 0 |
