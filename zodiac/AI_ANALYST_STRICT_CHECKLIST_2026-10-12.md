# AI Analyst — strict audit and acceptance checklist

Audit date: 12 October 2026 (Asia/Calcutta).

**Assessment: useful guarded analytics, but not yet demonstrated to be reliable end to end for aggregate-to-invoice drill-downs.** Passing SQL and finding a number in tool output are necessary checks; they do not prove the correct business interpretation, entity attribution, completeness, or reconciliation. This audit changes documentation and adds a private synthetic probe script; it does not implement the fixes or deploy anything.

## Evidence and limits

- Re-ran the focused backend suite: **152 passed**. Re-ran six frontend helper test files: **47 passed**. These are local tests, principally deterministic/model-mocked; they are not 199 live production acceptance cases.
- Four synthetic Python probes exercised numeric-evidence checking, alternative relationship paths, plan-filter checking, and the SAP customer assignment boundary. No model call, API key, business record, or live database was used.
- A synthetic JavaScript check of the current table/chart conversion expressions demonstrates different interpretations of an EU-formatted number.
- Prior database/API comparison evidence is documented in `AI_ANALYST_UPGRADE_2026-10-11.md`: 34 comparison rows with deterministic model transport, not a live-model comparison pass. Previous browser smoke and desktop/phone checks are separate from the comparison evidence.
- The reported **4,630,639 in 2001** has not been reproduced. Its original SQL, source result, currency, SAP client, selected dimensions, and filters are not in the supplied complaint. No specific invoice or root cause can be asserted from that amount alone.
- No current production version, deployment, billing, latency under load, or live cross-user access was verified in this audit. The earlier bounded document-level live model permission remains pending.

## What already has evidence

- [x] Tool-using agent with schema inspection, relationship discovery, explicit comparison plans, SQL execution and bounded repair.
- [x] Agent SQL rejects writes/unsafe functions, resolves tables/columns against a filtered schema, applies a 201-row sentinel and displays at most 200 rows.
- [x] Agent execution uses read-only transactions and wraps physical application tables carrying `user_id` with authenticated ownership filters.
- [x] Focused tests reject wrong document keys, missing client keys, duplicate monetary bridges, hidden identities, and unsafe sums across expanded joins.
- [x] Explicit document-enrichment follow-ups can preserve a bounded displayed document cohort and re-read it under current authorization.
- [x] Currency/measure chart protections, calculation-source details, missing-industry warnings, cancellation/outage handling, and bounded retry tests exist.
- [x] Public research uses an isolated vocabulary-only request with cited URLs; it excludes database rows, names, schema and chat history from that research call.

These boxes mean the described mechanism exists with bounded evidence. They do not certify all query shapes, users, providers, or production flows.

## P0 — accuracy and access requirements before relying on drill-downs

### 1. Aggregate row to contributing invoices — missing

`prior_cohort` reconstructs complete base-document keys from previous displayed rows. A grouped country/customer/year total normally has no billing document key. The chat/chart therefore has no general, immutable aggregate selection contract that guarantees a follow-up retrieves the contributors to a particular plotted amount. Chart handlers switch types and export CSV; they do not pass a selected data point to a reconciliation endpoint.

- [ ] Store an authorized server-side result/selection ID containing metric definition, source, date field/range, SAP client, dimensions, currency, filters, joins, and snapshot/version.
- [ ] A click or “show invoices for this row” must resolve that selection, clarify if multiple rows match, and never identify a cohort by amount alone.
- [ ] Build detail SQL from that verified selection in code; preserve the original scope and metric rather than asking the model to reconstruct it.
- [ ] Reconcile an independently calculated full contributor total to the selected aggregate using decimal arithmetic. Show original total, contributor count, reconciled total and any difference.
- [ ] Reproduce 4,630,639 with the original result contract, then prove the drill-down matches it. Treat this as unresolved until that evidence exists.

Evidence: `zodiac-api/app/services/agent_query_contract.py:290`; `zodiac-front/src/components/ai/AIChartRenderer.tsx:987`.

### 2. SAP customer/role authorization — deployment assumption, not assignment enforcement

The endpoint loads assigned customer IDs into trusted scope, but `enforce_agent_user_scope` filters physical tables by `user_id`. SAP tables such as VBRK have no such field; `allowed_customer_ids` is not used there. The trusted-scope module explicitly assumes one customer extract per deployment. A synthetic scope with one permitted customer produced no customer predicate or binding for a VBRK query. This is a confirmed boundary behavior, **not proof that live data was accessed by an unauthorized user**.

- [ ] Decide and document the permitted AI Analyst roles and the SAP isolation contract. Administrative cross-customer analytics and customer-user analytics need explicit different permissions.
- [ ] Enforce the authorized SAP client/customer scope server-side, through authorized views/connection binding or physical-source filtering, including bridges and aggregates.
- [ ] Empty/failed assignment lookup must deny access for restricted roles rather than implicitly mean unrestricted.
- [ ] Test two different restricted users, unassigned users, administrator access, joins, OR, UNION, CTEs and guessed document IDs through the actual API.

Evidence: `zodiac-api/app/api/adaptive_query.py:2909`; `zodiac-api/app/services/analyst_agent_sql.py:112`; `zodiac-api/app/services/adaptive_trusted_scope.py:8`.

### 3. Amount-to-entity attribution — confirmed helper weakness

The numeric-evidence helper checks whether a number occurs anywhere in selected evidence or the question. With Customer A = USD 100 and Customer B = USD 200, “Customer A billed sales were USD 200” returns no unsupported-number error. The general answer-consistency check mainly checks increase/decrease signs. This probe does not prove the full live loop would accept the statement, but the helpers cannot enforce row-specific attribution.

- [ ] Bind factual claims to result ID, row key, measure, period and currency; retain provenance for derived values.
- [ ] Render scalar totals and critical rankings deterministically, using the exact verified values and labels.
- [ ] Reject swapped entities, years/currencies, wrong denominators and claims about rows outside the returned evidence.
- [ ] Replace broad “verified” claims with the specific checks that passed and the checks still unproven.

Evidence: `zodiac-api/app/services/analyst_agent.py:216`; `zodiac-api/app/services/plan_satisfaction.py:906`.

### 4. Complete filter enforcement — partial

Comparison plans hold filters as text. `plan_sql_issues` checks field lineage, ordering and limit, but not those filter declarations. A synthetic plan declaring USD accepts a SQL query omitting that restriction. Separate semantic gates exist for some date/ranking/identity requests; this finding is about an incomplete generic plan contract, not absence of all semantic checking.

- [ ] Represent filters as typed field/operator/value expressions, including exclusion, null and date semantics.
- [ ] Verify every required filter and any unrequested narrowing against executed SQL, after sanitization.
- [ ] Explicitly test calendar versus fiscal year, customer changes, currency changes, “overall,” “same rows,” and compound/conditional questions.

Evidence: `zodiac-api/app/services/agent_query_contract.py:254`; `zodiac-api/app/services/analyst_agent.py:534`.

### 5. Uniform execution boundary — alternate route requires audit

`overrideSql` runs before the agent branch. It has legacy SELECT/keyword and ownership checks, but does not activate the agent's read-only transaction marker or bounded fetch path. Safety properties of the agent cannot be assumed for this reachable alternative route.

- [ ] Apply the same AST validation, safe schema, authorization, read-only transaction, statement timeout, bounded results and audit evidence to every query route.
- [ ] Test the actual authenticated override endpoint without executing destructive queries or reading unauthorized records.

Evidence: `zodiac-api/app/api/adaptive_query.py:3337`; `zodiac-api/app/api/adaptive_query.py:1276`.

## P1 — correctness, completeness and operational gaps

### 6. Alternative relationship meanings — confirmed discovery gap

BFS returns the first shortest path. A synthetic catalog with two direct relationships returns one without an ambiguity warning. A valid key path can still express the wrong role: original order versus subsequent document, sold-to versus payer, current versus historical master data.

- [ ] Preserve distinct relationship roles and enumerate competing paths; select from the user's business intent or clarify.
- [ ] Validate coverage, multiplicity, null links and client/language/effective-date keys, not merely uniqueness and matching column names.
- [ ] Expand numeric oracles to partial billing, multiple orders, cancellations/credits, missing records, document-flow alternatives and historical master changes.

Evidence: `zodiac-api/app/services/agent_query_contract.py:46`.

### 7. Exact money and consistent display — confirmed representation risks

The SQL executor converts Decimal values to float. Table parsing treats commas as grouping characters; chart parsing attempts locale inference. For `1.234,56`, these expressions produce 1.23456 and 1234.56 respectively. This is a latent input-format inconsistency; it does not establish the cause of the reported 4,630,639. Float conversion also prevents an end-to-end exact decimal contract.

- [ ] Keep monetary values as canonical decimal strings plus explicit currency/scale; use decimal arithmetic for reconciliation.
- [ ] Centralize parsing/formatting across table, chart, tooltip, answer and CSV. Do not guess locale from ambiguous strings.
- [ ] Test decimal cents, large amounts, negatives, zero/null, currency-specific scale, locale formats and leading-zero identifiers.
- [ ] Label rounding and chart abbreviations while preserving original exact values in detail/export.

Evidence: `zodiac-api/app/api/adaptive_query.py:1320`; `zodiac-front/src/components/DashboardAIAnalysis.tsx:131`; `zodiac-front/src/components/ai/AIChartRenderer.tsx:172`.

### 8. Bounded rows versus complete evidence — missing full-result workflow

The agent displays at most 200 rows. Table pagination/CSV operate on received rows, not a server cursor over every matching record. A full total cannot be reconciled by summing only that sample. The API additionally overwrites `result_artifact.truncated` with `len(result_rows)>30`, mixing memory sampling with database-result truncation.

- [ ] Separate total matched rows, returned rows, persisted rows, model sample rows and actual truncation flags.
- [ ] Add authorized stable server-side pagination/export with deterministic sorting and snapshot/version handling.
- [ ] Compute full reconciliation totals in the database independently of the page/sample. Label bounded CSV exports accurately.

Evidence: `zodiac-api/app/services/analyst_agent_sql.py:14`; `zodiac-api/app/api/adaptive_query.py:3227`; `zodiac-front/src/components/DashboardAIAnalysis.tsx:398`.

### 9. Freshness and repeatability — insufficient result contract

Stored SQL/rows and schema provenance exist, but a snapshot/version contract for original aggregate versus later detail is not established. Changed data can create a real difference even with correct filters.

- [ ] Show source, extract freshness, execution time and metric version. Record immutable result provenance.
- [ ] Reconcile within the same snapshot or explicitly report intervening data changes.
- [ ] Test refresh, history reload, concurrent tabs, cancellation/retry and changed permissions between turns.

### 10. Business metric definitions — partial

The agent labels net revenue minus invoice cost as a gross-profit proxy. That does not cover every meaning of sales, profit, production cost or accounting revenue. Header and item values, cancellations, tax, exchange rates and document categories need explicit governed definitions.

- [ ] Version metric contracts and require the correct source, grain, date, signed amount, tax/cancellation handling and currency policy.
- [ ] Explain differences between billed sales, sales orders, recognized revenue, gross-profit proxy and actual production cost.
- [ ] Validate definitions against approved business examples; clarify material ambiguities rather than silently choose.

### 11. Token cost and latency — no measured per-answer cost

The Responses transport uses one configured agent model with medium reasoning by default and up to 8,000 output tokens per call. The loop can make 14 decisions/20 tool calls within its budget. It resends accumulated history/tool output; prior SQL and answers can be substantial. Request-local tool caching and output compaction exist. The audited transport does not capture input/output/cached/reasoning usage or calculate per-answer cost; no dollar budget or evaluated cheap/strong routing is established.

- [ ] Capture actual provider usage for each call, model/version, latency, retries and tool stages; aggregate by answer/session with a versioned pricing configuration.
- [ ] Add enforceable per-request/session resource budgets and a visible graceful limit response.
- [ ] Handle drill-down, reconciliation, SQL display and exact values deterministically; avoid model calls for work already specified by a verified result contract.
- [ ] Reduce repeated context/schema payloads, evaluate versioned authorized caches, and measure cache effectiveness.
- [ ] Benchmark easy/complex routing and any local model against identical accuracy/privacy/latency cases before adoption. Fine-tuning is not a substitute for these database controls.

Evidence: `zodiac-api/app/services/analyst_agent_provider.py:34`; `zodiac-api/app/services/analyst_agent.py:685`; `zodiac-api/app/services/analyst_agent.py:904`.

### 12. Evaluation and release evidence — incomplete

- [ ] Establish a maintained acceptance dataset with independent SQL/decimal oracles and adversarial follow-ups, not only mocked model decisions.
- [ ] Measure correct source, correct scope, reconciled totals, false SUCCESS, clarification, latency and cost across repeated live runs.
- [ ] Include multi-user authorization, ambiguous joins, malformed dates/numbers, empty/partial extracts, large cohorts and multilingual/rephrased questions.
- [ ] Complete the authorized live-model comparison test and actual chart-to-invoice UI tests. Existing smoke screenshots do not prove those paths.
- [ ] Verify the deployed build/model/schema/metric versions and roll back if acceptance checks regress; local changes are not evidence of a production fix.
- [ ] Test tablet/mobile/desktop, keyboard/screen-reader interaction, large tables/charts and loading/cancellation under realistic load.

## P2 — requested intelligence still not fully built

- [ ] Derive privacy-reviewed public research topics from internal industry/material characteristics. Current external vocabulary is restricted to 12 sectors, seven regions and five topics.
- [ ] Evaluate source publication date, geography, definitions and conflicting claims; a citation proves a URL was supplied, not that every claim is correct or independently corroborated.
- [ ] Build dedicated competitor/campaign/credit-data workflows with permitted data sources and entity resolution. General industry context cannot certify a specific customer rating.
- [ ] Connect Gemini/Claude only if required, through supported integrations and configured credentials; presently public research uses OpenAI web search. Multiple agreeing models are not independent evidence.
- [ ] Implement numerical forecasting only when sufficient comparable time-series/cost data exists: baseline models, time-based holdouts, prediction intervals, backtesting, drift checks and an insufficient-data response.
- [ ] Keep external facts, internal measured facts and forecasts/scenarios distinct, including methodology and uncertainty.

## Implementation order and release bar

1. Resolve restricted-user scope and alternate execution boundary; establish the authorized result-selection contract.
2. Implement aggregate-to-invoice drill-down with exact reconciliation, complete filter checks and row-specific claims.
3. Resolve relationship ambiguity, decimal/display consistency, paging/truncation and snapshot provenance.
4. Measure and reduce cost/latency; run live acceptance and production-version checks.
5. Expand public intelligence and forecasting using validated data and sources.

**Minimum release bar for the reported issue:** a selected 2001 total produces the correct authorized invoice cohort; all original dimensions/filters/currency/client remain intact; full contributor totals reconcile exactly under the metric's rounding policy; missing links and data changes are disclosed; the same behaviour survives refresh and follow-ups; token usage is measured. Nothing in this audit supports a universal 100% accuracy claim.

Private reproducibility artifact: `artifacts/ai-agent-2026-10-11/strict_audit_probes.py` and its JSON output. These contain synthetic data only and are ignored by Git.
