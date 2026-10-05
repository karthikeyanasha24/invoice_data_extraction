# Comparison SQL regression verification — 2026-10-04

The live SQL supplied by the user combined scalar projections with SUM expressions without GROUP BY, retained single-year restrictions alongside a two-year comparison, and contained unquoted physical identifiers and undeclared nested expression scopes. No database exception text was supplied, so these are confirmed structural defects rather than a claim about the exact server exception.

The later SQL successfully executed but joined the same uniquely dated billing document to itself in another year and joined unrestricted multilingual material descriptions. The first condition makes the comparison impossible; the second multiplies item rows and consumes the ranking limit. A synthetic fixture reproduces the reported ten copies of one item, independently of the user's actual business values.

## Local changes

- Aggregate projections and period comparisons override the row-list classification in both rendering and aggregation pruning.
- Comparison rewrites widen restrictions on the compared date's year while retaining customer, currency, other-date, and month predicates. Equivalent numeric year wrappers are recognized. Year projections/groupings that split a side-by-side comparison are removed.
- Verified physical expression identifiers are quoted using the schema catalog. Structured expressions cannot introduce undeclared nested query scopes.
- PostgreSQL syntax-tree checks reject ungrouped aggregate projections and WHERE restrictions that exclude a CASE comparison period. Checks run during SQL acceptance, analytical intent validation, and before each main execution/repair attempt.
- Base-period rankings sort by the base-period measure; change rankings retain change ordering.
- The date precision validator recognizes actual WHERE year operands, including IN, instead of matching nearby literals in SQL text.
- An unanswered request retains its intent until model understanding distinguishes a clarification answer from a new request. Short choices containing verbs such as “compare” no longer erase the pending request through an early lexical route.
- The tested sqlglot version is declared in requirements.txt.
- Catalog-defined language text lookups select one deterministic label per complete joined entity key before joining facts. Explicit language filters, language facets, and joined client keys are preserved. This runs in both SQL sanitization paths, before four-stage validation and before shared execution.
- Mandatory identity joins across disjoint document-date periods and grouped comparisons at unique dated-document grain are rejected. Different documents compared using a stable entity remain valid.
- Native SQL repairs are sanitized and revalidated before execution, including database-error repairs. Repairs that drop the requested comparison are rejected.
- Comparison fallback retains the requested numeric predicate and base-period ranking. It does not silently rank the difference or drop the negative filter.
- Understanding instructions distinguish separate dated-document cohorts from stable entity comparisons. Context retention alone is not evidence that the proposed comparison is sound.

All production year values come from the query plan. There is no special-case branch for the reported question, replies, or year pair.

## Verification

The latest combined selected suite passed **279 tests in 48.37 seconds**, with two existing deprecation warnings. `git diff --check` passed. These are local regression and fixture acceptance tests; they do not verify the live deployment.

Suites: local comparison execution, text lookup and period identity, period comparison structure, adaptive structured SQL, adaptive query repair, four-stage DB pipeline, plan satisfaction live gates, measure comparison semantics, currency strategy, pending analysis continuation, AI Analyst SQL grain, AI Analyst live regressions, analyst chat reliability, AI native pipeline, and adaptive query guardrails.

Synthetic SQL execution covered 2000/2001, 2012/2015, and 2022/2023 with known signed amounts. It confirmed both comparison totals and retained customer restrictions. Linked-invoice/order execution covered duplicate document-flow rows, out-of-cohort invoices, currency mismatches, percentage calculations, and missing comparison periods. SQLite adapters emulate PostgreSQL decimal division and ordered string aggregation; these tests do not prove PostgreSQL runtime compatibility.

Six additional acceptance cases cover both native and primary four-stage paths for those three year pairs. Controlled planner outputs first propose invalid document-grain SQL and then a valid material/currency comparison. Production sanitizers, schema/analytical validators, the shared `_execute_sql`, SQLAlchemy result handling, and actual local database execution run normally. The tests assert the invalid draft never executes, only one repaired SELECT executes, labels do not inflate sums, unrelated-period amounts are excluded, missing comparison values remain NULL, and result narration receives the executed rows. The fixture has baseline -2.76 and comparison -1.00 for one material (difference +1.76), and a second material with no comparison-period rows. No real SAP rows or external providers are used.

To rerun the execution acceptance cases locally:

```powershell
python -m pytest tests/test_local_comparison_execution.py -q -p no:cacheprovider
```

## Remaining verification

**Update 2026-10-05:** Actual localhost browser tests subsequently ran and executed database queries after restarting a stale API. They exposed and fixed additional baseline-ranking and follow-up shortcut defects. The latest selected suite passes 302 tests. The first browser question passes on the final code; final follow-up submission was rejected by automatic approval review and explicit approval was requested. See [the local browser report](localhost_browser_verification_20261005.md) for exact outcomes and remaining checks. The notes below describe earlier verification attempts, not the current database availability.

`scripts/verify_comparison_database.py --base-year 2000 --comparison-year 2001` attempted read-only EXPLAIN and SELECT against the app's configured PostgreSQL connection. It failed with **connection_timeout** before compilation/execution could be verified. Only sanitized diagnostics were saved in `comparison_database_verification.json`; no AI APIs were called.

The full model/database acceptance test remains awaiting the previously requested user approval. Automatic approval review rejected that test because it would send internal SAP schema and limited business-result evidence to configured OpenAI/Gemini services. That rejection was not bypassed.

The latest understanding-only rerun explicitly excluded internal schema and rows, but automatic approval review also rejected it because it would transmit conversation text to a configured external AI provider. The prior understanding report records continuity checks only; its first resolved query still proposed a same-invoice cross-year match. It is not evidence of analytical correctness. The new planning instruction has passed offline routing regressions, but its real-model behavior remains unverified.

**No deployment was performed in this work. The live site is not verified as fixed.** Other existing/shared workspace edits were preserved; this report does not attribute those unrelated changes to this repair.
