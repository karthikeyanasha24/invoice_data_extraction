# Annual order and invoice comparison audit

Request: "Identify the difference in the sales amount for order value and invoice value from the year 2000 and 2001."

## Changes

- Distinguish a comparison of different document values within a year scope from explicit year-over-year growth.
- Preserve explicit growth, decline, and period-to-period comparison requests.
- Require the complete year scope on each requested document source's own date.
- Permit independent aggregate plans without a document relationship. SQL still needs independently aggregated inputs and a complete compatible grouping-key join.
- Require a requested monetary difference in the executed output rather than accepting only side-by-side amounts.
- Reject shifted year/date expressions as proof of the original calendar scope.
- Reject missing executed SQL with a validation message instead of a parser exception.

## Verification

343 offline tests passed with two existing SQLAlchemy/Pydantic deprecation warnings.

The full Agentic tool-loop regression scripts the model's decisions and uses the actual plan validation, SQL validation, local SQLite execution, and final answer validation. Its synthetic fixture returns order-minus-invoice differences of 100 in 2000 and 20 in 2001. It does not call an external AI provider or use production records.

Other checks cover multi-year scopes, unmatched periods/clients/currencies, independent fact grain, document keys, price/quantity diagnostics, provider failure handling, saved context, ranking, and chart semantics.

Test command (from zodiac/zodiac-api):

```text
python -m pytest tests/test_cross_source_annual_intent.py tests/test_agent_query_contract.py tests/test_analyst_year_filters.py tests/test_analyst_comparison_failures.py tests/test_analyst_agent.py tests/test_analyst_chat_reliability.py tests/test_analyst_reliability_upgrade.py tests/test_agentic_diagnostic_expressions.py tests/test_ai_analyst_sql_grain.py tests/test_ai_analyst_live_regressions.py tests/test_semantic_reliability_gates.py tests/test_measure_comparison_semantics.py tests/test_agent_chart_semantics.py tests/test_agent_ranking_contracts.py -q
```

## Release status

These are backend changes. Deploy the latest fix/ai-analyst-live revision to the production backend, then repeat the exact question in a new live Agentic chat.

No live authenticated or real-model test was performed in this audit. Passing these regressions establishes no known failures in the covered cases; it does not prove that every possible user question will succeed or that unavailable data, exchange rates, or provider capacity exist.
