# Basic with free retrieval and a local agent

For Vercel deployment with a separate self-hosted model server, use [Basic on Vercel](BASIC_VERCEL_RAG.md). The instructions below describe the local Ollama path.

The dashboard tries checked SQL reuse and deterministic templates first. For an untaught question, it uses the configured free provider (including this local Ollama adapter). When no free provider is configured, it can use the existing Agentic route, which may consume credits. A configured free provider failure does not silently retry with a paid provider.

Basic now retrieves verified question/SQL examples without calling OpenAI embeddings. It first reuses an equivalent query with matching intent and filters, then tries deterministic billing templates. It always executes SQL against the current database; stored totals are never used as new answers.

For questions outside those paths, configure a self-hosted Ollama model. Basic then uses the same bounded tool loop as Agentic: discover schema, inspect relationships, execute read-only SQL, repair rejected queries, and validate the result. The model cannot authorize access, invent database figures, or fall back to paid APIs. Public research tools are unavailable in this mode. Agentic retains its existing provider.

## Enable the local model

Install and run Ollama on the backend machine, or an accessible self-hosted server. Download models with:

```powershell
ollama pull qwen3:4b
ollama pull embeddinggemma
ollama serve
```

If Ollama is already running, another `ollama serve` is unnecessary. Choose a locally installed model with tool-call support that fits the server's hardware. These commands download models; the application does not install or download them automatically.

Set backend environment variables and restart the API:

```dotenv
BASIC_LLM_PROVIDER=ollama
BASIC_LOCAL_MODEL=qwen3:4b
BASIC_EMBED_MODEL=embeddinggemma
BASIC_OLLAMA_URL=http://127.0.0.1:11434
BASIC_ALLOW_PAID_FALLBACK=false
AI_ANALYST_DATASET_VERSION=erp-extract-2026-10-12
```

Select **Basic** on the AI Analyst page. No OpenAI key is needed for this path. `BASIC_LOCAL_MODEL` enables tool-based investigations; `BASIC_EMBED_MODEL` independently enables semantic example retrieval. With both unset, offline query reuse and templates still work. The setup uses Ollama's [chat/tool-call API](https://docs.ollama.com/capabilities/tool-calling) and [embedding API](https://docs.ollama.com/api/embed).

`127.0.0.1` refers to the API's host or container. A backend hosted on Vercel cannot reach your laptop through that address. Use an authenticated HTTPS reverse proxy on a separate self-hosted model server and set `BASIC_OLLAMA_API_KEY` to its bearer token. Hosted Ollama cloud endpoints and cloud model names are rejected. No per-token provider fee applies to this configured self-hosted path; hardware, hosting, and electricity still cost money.

## What improves over time

Use the teaching button on a checked answer to save its wording and executed SQL in `ai_basic_query_memory`. Eligible independent multi-query answers retain every checked query; conditional or result-dependent investigations that cannot be safely replayed are excluded. A successful execution alone is not user approval. Memory is bound to the authenticated user, their permissions, the data source, and dataset version. Failed queries are excluded. Change `AI_ANALYST_DATASET_VERSION` when switching extracts or datasets. Old chat entries are not blindly imported because they lack this verification and scope metadata.

Equivalent questions bypass model calls and rerun their verified SQL. Related examples can guide a local model on new questions. Embeddings are batched and cached in memory, and only requested when the query/template path cannot answer. Similarity alone never authorizes executing an old query: years, amounts, currency, named entities, grouping, ranking, and conditions must retain their meaning. New scopes require a template or freshly generated, validated SQL.

The AI Analyst header has a **How Basic works** button explaining the routes and how to teach a checked result. The answer also labels whether it came from checked SQL replay, a supported SQL pattern, or a Basic model investigation. Legacy direct billed-sales totals that sum multiple currencies into one number are omitted from Basic's saved-question suggestions and replay, and new examples with that SQL are rejected. The database records remain intact for review. Basic instead uses per-currency billing patterns where supported.

This is retrieval memory, not automatic fine-tuning. Model weights do not change and speed/accuracy improvement is not guaranteed for every new question. Local token usage is reported separately with zero estimated provider cost.

## Invoice traceability

Basic now uses the durable result follow-up handler too. After a billed-sales query, ask “Show related billing documents for 2001 current displayed data,” or select a row's **Billing documents** action. The original row, measure, currency, client, and filters drive invoice selection and exact decimal reconciliation. A typed amount can select its matching row, including a value rounded for display. An ambiguous row requires selection. A requested year, currency, or amount outside the saved result cannot open another row silently. Mismatches remain visible instead of being reported as successful reconciliation.

## Verification

```powershell
python -m pytest tests/test_basic_rag.py tests/test_basic_local_provider.py tests/test_basic_followups.py tests/test_basic_sql_answer.py tests/test_analyst_agent.py tests/test_analyst_reliability_upgrade.py -q
```

Tests use scripted Ollama replies and a real SQLite fixture to verify the complete local tool loop. They do not establish the quality or latency of a particular installed model on production SAP data. Smoke-test that separately after enabling the runtime.
