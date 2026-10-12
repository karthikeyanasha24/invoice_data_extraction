# Basic with free retrieval and a local agent

For Vercel deployment use [Basic on Vercel](BASIC_VERCEL_RAG.md). The instructions below describe the optional local-development Ollama path.

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
BASIC_LOCAL_MODEL=qwen3:4b
BASIC_EMBED_MODEL=embeddinggemma
BASIC_OLLAMA_URL=http://127.0.0.1:11434
AI_ANALYST_DATASET_VERSION=erp-extract-2026-10-12
```

Select **Basic** on the AI Analyst page. No OpenAI key is needed for this path. `BASIC_LOCAL_MODEL` enables tool-based investigations; `BASIC_EMBED_MODEL` independently enables semantic example retrieval. With both unset, offline query reuse and templates still work. The setup uses Ollama's [chat/tool-call API](https://docs.ollama.com/capabilities/tool-calling) and [embedding API](https://docs.ollama.com/api/embed).

`127.0.0.1` refers to the API's host or container. A backend hosted on Vercel cannot reach your laptop through that address. Host the API alongside Ollama, or set the URL to a self-hosted Ollama service reachable from the backend. Hosted Ollama cloud endpoints and cloud model names are rejected. No per-token provider fee applies to this configured self-hosted path; hardware, hosting, and electricity still cost money.

## What improves over time

Successful, executed single-query Basic and Agentic answers populate `ai_basic_query_memory` in the application database. Compound and conditional investigations are excluded so one SQL statement cannot be reused as a complete answer to a multipart question. The table is created automatically using the same approach as existing analyst result artifacts. Memory is bound to the authenticated user, their permissions, the data source, and dataset version. Failed queries are excluded. Change `AI_ANALYST_DATASET_VERSION` when switching extracts or datasets. Old chat entries are not blindly imported because they lack this verification and scope metadata.

Equivalent questions bypass model calls and rerun their verified SQL. Related examples can guide a local model on new questions. Embeddings are batched and cached in memory, and only requested when the query/template path cannot answer. Similarity alone never authorizes executing an old query: years, amounts, currency, named entities, grouping, ranking, and conditions must retain their meaning. New scopes require a template or freshly generated, validated SQL.

This is retrieval memory, not automatic fine-tuning. Model weights do not change and speed/accuracy improvement is not guaranteed for every new question. Local token usage is reported separately with zero estimated provider cost.

## Invoice traceability

Basic now uses the durable result follow-up handler too. After a billed-sales query, ask “Show related billing documents for 2001 current displayed data,” or select a row's **Billing documents** action. The original row, measure, currency, client, and filters drive invoice selection and exact decimal reconciliation. A typed amount can select its matching row, including a value rounded for display. An ambiguous row requires selection. A requested year, currency, or amount outside the saved result cannot open another row silently. Mismatches remain visible instead of being reported as successful reconciliation.

## Verification

```powershell
python -m pytest tests/test_basic_rag.py tests/test_basic_local_provider.py tests/test_basic_followups.py tests/test_basic_sql_answer.py tests/test_analyst_agent.py tests/test_analyst_reliability_upgrade.py -q
```

Tests use scripted Ollama replies and a real SQLite fixture to verify the complete local tool loop. They do not establish the quality or latency of a particular installed model on production SAP data. Smoke-test that separately after enabling the runtime.
