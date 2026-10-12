# Vercel Basic: LLM, RAG, and teaching

Basic can run in the existing Vercel Python API. Retrieval uses a small standard-library BM25 index over verified examples stored in the existing application database. New investigations can call a hosted Groq model; Vercel does not load model weights, run an Ollama daemon, or require a writable local model cache. The frontend remains the existing Next.js application.

## Vercel environment variables

Set these **server-side** variables on the backend project and redeploy:

```dotenv
BASIC_LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-free-plan-key
BASIC_GROQ_FREE_PLAN=true
BASIC_GROQ_MODEL=openai/gpt-oss-20b
BASIC_MAX_MODEL_CALLS=6
BASIC_MAX_PROMPT_BYTES=24000
AI_ANALYST_DATASET_VERSION=your-current-extract-version
```

`BASIC_GROQ_FREE_PLAN=true` declares that the configured Groq account uses the free plan; the API cannot independently verify that account's billing tier. Do not set it for a paid account and assume calls become free. Groq publishes [free-plan quotas](https://console.groq.com/docs/rate-limits), including token and request limits. Basic still consumes those tokens for new questions. Quota exhaustion stops the investigation, with no retry loop or automatic paid-provider fallback. The key stays on the backend and is never exposed as a `NEXT_PUBLIC_` variable.

The existing `DATABASE_URL`/SAP connection and authenticated-user permission settings remain required. Training memory lives in `ai_basic_query_memory`, verified cross-source plans in `ai_basic_query_plans`, and teaching references in the existing `ai_analyst_results` artifact table. These tables are created using SQLAlchemy like the existing analyst artifacts. Cold starts do not erase training. Change the dataset version when switching extracts. Users cannot read or teach another user's result, or reuse memory after its authorization scope changes.

On Vercel, local Ollama inference and embedding calls are disabled. Local development can still select `BASIC_LLM_PROVIDER=ollama`; see [the local setup guide](BASIC_FREE_RAG.md). No additional Python package, large ML framework, or model download is required for the Vercel path. The existing `httpx` dependency supplies the transport.

The API's normal deadline still bounds a request. Set the Vercel function duration above that deadline using your project's supported configuration. The repository currently uses the legacy `builds` configuration: do not mix it with a second `functions` configuration without migrating that setup. [Vercel's function configuration](https://vercel.com/docs/functions/configuring-functions) explains the supported duration settings. This change adds no background training process that must survive an HTTP response.

## What Andy can train

1. Run a complex question once with the configured Basic model or Agentic.
2. Check its SQL, filters, currencies, and returned values.
3. Open **Teach Basic this checked answer** below the result.
4. Save the question wording to remember. Keep the same named filters, year, amounts, ranking, and grouping.
5. Ask that taught question again in Basic. It reruns the checked SQL against current data with **zero model calls**.

Successful single-query results are also remembered automatically. The explicit teaching action saves a human-reviewed wording, including a paraphrase the conservative automatic matcher would otherwise decline. Cross-source comparison queries retain their verified relationship/analysis plan; the normal execution tool rechecks it against the connected catalog when reused. Compound investigations with several result queries are not cached as if one SQL statement answered the whole request.

An administrator who already knows the SQL can also use the existing authenticated `POST /api/query/adaptive` request with `question`, `overrideSql`, and `analysisMode: "basic"`. The read-only SQL validator and normal user-scope rules run before execution. A successful custom query now produces the teaching reference too, so this path needs no model call. Non-administrators cannot submit SQL overrides. The teaching endpoint, `POST /api/query/adaptive/basic/teach`, accepts a server-owned `result_id` and the question wording; it does not accept client-supplied SQL.

This teaches query memory and domain examples. It does **not** fine-tune neural network weights. Even a fine-tuned model still needs computation for inference. An unseen complex question may need the hosted model and consume free quota; training does not make unlimited cloud inference free. Similarity supplies examples to the model, but cannot silently change a cached query's year, customer, metric, currency, or ranking.

## Validation and limits of this environment

The tests exercise the hosted tool-call transport with scripted replies and real SQLite execution, teaching/cold-start persistence, permission isolation, quotas, and no paid fallback. They do not establish real Groq reasoning quality. There is no configured Groq key in the inspected environment.

`scripts/verify_basic_history.py --live-db` replays Andy's 25 questions from `andy_live_verify_results.json`, plus three billing questions, with every model transport blocked. The current configured database connection failed, so the report explicitly labels SQL-only validation instead of claiming live results. The report is in `scripts/basic_history_report.json`; unsupported untrained questions are marked `NEEDS_TAUGHT_QUERY_OR_MODEL`.

After setting the key and database connectivity, repeat representative complex questions through the deployed API, check the result, teach it, and repeat in Basic. The repeated request should show zero model calls; an invoice drill-down should reconcile to the selected row's exact amount.
