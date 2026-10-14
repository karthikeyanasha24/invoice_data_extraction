# Basic saved-query reuse on Vercel

The Andy Generative AI page keeps its existing Agentic execution path. Basic first retrieves a checked question and reruns its saved read-only SQL. If no safe match or billing template exists, or execution rejects the saved SQL, Basic uses its configured free model when available. Without a configured free model, Basic calls the existing Agentic entry point automatically. Agentic fallback may consume credits; the UI and response metadata identify that route. A successful empty query is a valid result and does not trigger a paid investigation.

## User flow

1. Ask Agentic a question and check the returned data, filters, currency, and SQL.
2. Click **Reuse it in Basic Model** under an eligible answer.
3. Open **Questions** at the top right. Search all **Verified saved questions** and **Predefined questions** from either mode.
4. Select a saved question to switch to Basic and fill the message box, then send it. You can also type an equivalent question with the same filters. Predefined questions keep the currently selected method.
5. Basic reruns the checked SQL against current data and renders a summary directly from the new rows, with zero model calls. It never serves the old answer as a current total.

Clicking a suggestion starts a standalone question so an unrelated previous conversation cannot add filters. Typed follow-ups retain the existing conversation context. Invoice drill-down continues using the existing result references and reconciliation path.

Execution alone does not approve a new query for memory. The button saves it after human review. Existing permission-bound Basic memory remains usable. The authenticated teaching endpoint accepts only a server-owned result reference and a compatible question, never SQL supplied by the browser. The authenticated suggestions endpoint returns question text only.

## Retrieval and safeguards

- Persistent memory uses the existing `ai_basic_query_memory` and `ai_basic_query_plans` tables. Teaching references use `ai_analyst_results`.
- Memory is bound to the authenticated owner, current permission scope, data source, and `AI_ANALYST_DATASET_VERSION`.
- Canonical wording matches preserve metric, entity, year, currency, grouping, ranking, negation, and numeric constraints. A merely similar question cannot authorize execution of an old query. Changed parameters require a new validated query; this feature does not substitute arbitrary values into SQL.
- Existing BM25 retrieval and optional embedding utilities remain available. Direct reuse and the dashboard's fallback routing require no embedding service.
- The existing SQL tool rechecks read-only safety, live schema, permissions, and saved analysis plans on each run. Validation failure goes to Agentic with the original question and context.
- Independent multi-query results retain all queries, their sources, analysis plans, and the primary result. Partial replay failure is not displayed as a complete answer.
- Conditional investigations are not saved as fixed outcomes. Follow-on filters absent from the question are conservatively rejected for multi-query reuse: for example, yesterday's top product ID cannot be reused as today's winner. Such work requires Agentic, or a validated SQL query that computes the dependency with a subquery/CTE.

The audit found older `ai_query_memory` approvals, `ai_training_data`, chat SQL history, and the OpenAI embedding store. Their historical rows do not establish the current owner/permission/dataset binding and complete execution plan required here, so they are not silently imported as checked answers. Recheck those questions through Agentic and save the result with the new button. Existing scoped Basic records are retained.

## Deployment

Use the existing Vercel Python API, Next.js frontend, application database, SAP connection, and Agentic provider configuration. SQLAlchemy creates the memory/artifact tables in the application database using the existing mechanism. The deployment database role must permit that creation, or the tables must be provisioned before rollout.

Set `AI_ANALYST_DATASET_VERSION` to the deployed extract/schema version and change it when switching datasets or changing business definitions. Cold starts do not erase memory. Keep the existing request deadline and Vercel function duration configuration.

For a downloaded model with no inference-provider token bill, run Ollama on a separate always-on server. Pull a tool-capable model there, such as `qwen3:4b`, and put an authenticated HTTPS reverse proxy in front of its API. On the Vercel **backend API project**, set `BASIC_LLM_PROVIDER=ollama`, `BASIC_LOCAL_MODEL=qwen3:4b`, `BASIC_OLLAMA_URL=https://<your-model-host>`, `BASIC_OLLAMA_API_KEY=<proxy bearer token>`, and `BASIC_ALLOW_PAID_FALLBACK=false`. Optionally pull `embeddinggemma` on the same server and set `BASIC_EMBED_MODEL=embeddinggemma` for semantic example retrieval; the checked-query memory also works without it. The Vercel function rejects localhost, plain HTTP, unauthenticated remote endpoints, and Ollama's hosted cloud domains. Your proxy must validate the bearer token before forwarding requests to Ollama. Keep the Ollama port private; do not expose it directly to the internet. The model host has hardware, hosting, and electricity costs. A Vercel deployment does not run the model weights itself.

For a hosted free-tier pilot instead, set server-side `BASIC_LLM_PROVIDER=groq`, `GROQ_API_KEY`, and `BASIC_GROQ_FREE_PLAN=true` only for a verified free-plan account. The flag is an operator declaration, not a billing-tier check. Basic uses that provider only after checked reuse and deterministic templates cannot answer. Free-provider quota failures stop without a paid retry. Set `BASIC_ALLOW_PAID_FALLBACK=false` if untaught Basic questions must never call paid Agentic. The Agentic button retains its own route.

The top-right question picker also includes 50 database-tested questions in `basic_question_catalog.py`. `scripts/verify_basic_catalog.py --live-db` checks their execution and result shape through the existing SQL tool with HTTP/model transports disabled. Its report contains SQL hashes, row counts, and column names, not cached row values. Test results apply to the configured extract; the normal permission and schema checks still apply on every user request. This library is separate from answers a user explicitly checked and saved.

Short follow-ups retain the previous question. An explicit year comparison preserves the prior metric and filters; a comparison without a target year asks for clarification instead of assuming the following year. Teaching stores the resolved full question.

This is reviewed query memory, not neural-network fine-tuning. Repeated safe queries require no model tokens. New reasoning uses the configured Basic model when available. Fine-tuning model weights would be a separate training job and would not remove the need to run the model for new questions.

## Validation

`tests/test_basic_reuse_flow.py` exercises the save endpoint, suggestions, owner isolation, persistence across a new database engine, changed live SQLite values, per-currency output, zero-model replay, failed-SQL fallback, new-question fallback, accurate credit metadata, and bypassing Basic when Agentic is selected. Existing teaching, SQL, retrieval, invoice reconciliation, provider, and Agentic regression suites also apply.

`scripts/verify_basic_history.py --live-db` runs the historical question fixture with model transport blocked. Without taught SQL, unsupported questions are marked as needing a taught query or model. If the configured database cannot be reached, the report explicitly records SQL-only validation; it is not proof of live answer correctness. The fallback tests use a stubbed Agentic response rather than spending production credits.
