# AI Analyst comparison and public-context upgrade — 11 October 2026

The active path is the existing Responses agent in `zodiac-api/app/services/analyst_agent.py`, reached through `/api/query/adaptive`. The frontend's same-origin proxy forwards to the local backend configured in `BACKEND_URL`. Legacy structured-query paths remain present; this upgrade does not introduce a second agent or change the funded model/provider.

## Failure and correction

The prior monetary fanout gate rejected a valid non-additive document-pair listing through a deduplicated link. Its generic repair message led to repeated equivalent failures. Successful billing-only queries could also pass existing analytical checks without supplying an order value.

The existing loop now exposes `find_relationships` and `prepare_analysis`. Request-local discovery combines actual foreign-key constraints with governed business relationships, retains composite keys, discovers intermediate tables, and checks connected uniqueness/null coverage before trusting imported document identities. Imported SAP tables have no declared PK/FK constraints. Business relationship evidence and connected key checks are labelled separately.

A validated comparison plan records required sources, physical fields, output aliases, strategy, grain, filters, currencies, sort, bound, missing handling, assumptions and key evidence. The original request supplies an independent source/value coverage gate. A billing-only result cannot complete a billing/order net-value comparison.

The structural proof follows physical field and key lineage through CTEs. Identified document pairs display header values without summing duplicated headers. Link projections are deduplicated to the full pair. Every monetary identity and composite join is checked. Nullable target IDs cannot hide an unmatched originating reference. Independent aggregates must be computed before their join; summing again across that join is rejected. This machinery is tested with arbitrary names and a four-table relationship path, not only SAP templates.

Failed SQL is fingerprinted independently of aliases, whitespace and comments. Equivalent failed shapes are blocked; materially revised SQL has a bounded repair budget. A newly validated plan can resolve a missing-plan failure. Successful query caches are invalidated on plan changes. Read-only execution, authenticated ownership filters, row bounds, deadline and cancellation remain in the shared executor.

Explicit document-enrichment follow-ups re-read the previous base-document cohort under current authorization. A self-contained request such as “identify billing documents and compare them” does not inherit a previous customer's filters. This is a document-cohort guarantee; arbitrary entity-cohort and ambiguous-path scenarios still require wider acceptance evaluation.

## Industry coverage and presentation

The connected customer master contains 20,030 rows: 2,392 have industry codes, 2,383 match an industry text. The industry text table has 60 unique codes. Nine populated customer codes lack matching text. The remaining customers have no industry assignment. These are extract limitations, not permission to fabricate an industry.

The agent reports missing industry fields in its returned rows. Calculation details expose the validated sources, bridge, fields, filters, grain and limitations. Charts keep quantities and diagnostic row counts off a monetary axis, including `billed_net`/`item_net` aliases. Incompatible or missing source currencies retain a verified comparison table rather than implying a common money axis. New tools have readable step labels.

## Public industry research

`research_public_context` uses the existing OpenAI credential and Responses web search in a fresh isolated request. Only approved generic sector, region and topic terms enter it. SQL, database metadata, rows, document IDs, customer/product names and chat history are excluded by construction. An explicit external-research request is required. Private free-text tool arguments are rejected.

The result must have actual URL citation evidence. The agent distinguishes public context and scenarios from connected database facts. It cannot claim a customer credit rating or guaranteed future price from general sector research. Gemini and Claude have not been connected; no provider accounts, keys, billing settings or deployments were changed. Search capabilities follow the [official OpenAI web-search documentation](https://developers.openai.com/api/docs/guides/tools-web-search).

## Verification

- Focused backend suite: 152 tests passed, covering existing agent behavior/security, new plans/proofs/recovery, arbitrary-schema multi-hop joins, numeric fixture oracles, date bounds, follow-up context, public-research isolation, industry coverage and charts.
- Frontend: 39 tests passed for conversation context, trust details, agent diagnostics and SQL evidence; TypeScript check passed.
- Actual connected database and real local API function, with deterministic model transport: 34 billing/order pairs, independently reconstructed from separately read billing headers, item links and order headers. Nineteen rows lack matching order headers; an additional standard-order document-flow check found no links for these selected missing bills. Missing order values remain null.
- Actual API follow-up, with deterministic model transport: the same 34-row cohort and numeric oracle match.
- Real OpenAI public research: generic motorcycle-parts input-cost context for India returned three cited primary/industry sources. No database session or private payload was used.
- Local running backend health confirmed `agent_enabled=true`, `agent_runtime_version=tool_loop_v2_sources`.
- Live in-app browser smoke checks passed: `Hi`, `How many tables are there?` (129), and `What can you do?`. Jump-to-top worked. Desktop and 390 × 844 phone layouts were inspected; screenshots are `live-smoke-catalog.jpg`, `live-smoke-desktop.jpg` and `live-smoke-phone.jpg` in the private artifact directory. The temporary browser tab was closed and the viewport restored.

Private QA artifacts live under the ignored `artifacts/ai-agent-2026-10-11/` directory. They are not public application assets.

The new comparison has **not yet been replayed through the live model or visibly tested in the chat UI**. The pending approval specifies a bounded document-level financial payload; the earlier aggregate-only approval does not cover it. The database/API checks above must not be described as a live-model or screenshot pass. No production deployment was performed. These tests establish specific invariants, not universal 100% accuracy or arbitrary forecasting capability.
