# Adaptive query engines (System A)

**Status:** documentation of current routing — **not** an engine unification.  
**Follow-up (R2 / consolidation):** keep `universal_adaptive` as the source of truth for SAP NL→SQL guardrails; fold `sql_catalog` templates and `intent_sql_fast` ranking/filter discipline into that path or delete the weaker engines. Do not add a fifth engine.

Entry point: `POST /api/query/adaptive` (`app/api/adaptive_query.py`).

## Turn intent (before any engine)

`contextData` means prior analytical state is available. It does **not** mean the user wants a continuation.

```text
USER MESSAGE → classify_turn() →
  NON_BUSINESS / CLARIFICATION_REQUIRED → CLARIFICATION (no SQL, no charts, no narration)
  FOLLOWUP_DELTA → deterministic_sql_delta (then intent_sql_fast / universal)
  NEW_ANALYTICAL_QUERY / NEW_ANALYTICAL_QUERY_WITH_CONTEXT → fresh SQL engines
```

`classify_turn` lives in `app/services/ai_followup_routing.py`. `_followup_analysis` is not a fallback for unrecognized deltas.

## Order of engines (new analytical question)

| Order | Engine id (`reason` / `pipeline`) | When it wins | LLM SQL? | Guardrails in this pass |
|------|-------------------------------------|--------------|----------|-------------------------|
| 0 | Schema structure | “which tables / columns / data type / shared columns” | No | N/A — catalog lookup only |
| 0b | Intent gate | Non-business / nonsense (`meaning of life`) | No | Clarification payload, empty SQL |
| **1.5** | **`deep_multidim`** | Semantic multi-dim profit/COGS/margin/process/expiry/history (or prior deep context follow-ups) | No | Governed metrics; ≤6 SQL; CANNOT_ANSWER for unavailable metrics; does **not** steal basic sales/Top-N |
| 1 | `period_compare` | Year vs year compare phrases | Orchestrator | Compare router |
| 2 | `operational_*` | EDI / app-ops patterns (failed invoices, SAT, pipeline) | No | Intentionally **not** SAP VBRK counts |
| 3 | `intent_sql_fast` | Deterministic intent planner (billing/revenue, no named customer) | No | `apply_ranking_discipline` (LIMIT N, single currency, skip named customer → universal) |
| 4 | `sql_catalog` | High-score keyword template, no named customer / year / proper noun | No | Same `apply_ranking_discipline` |
| 5 | `universal_adaptive` | Everything else in SAP domain; all follow-ups that need fresh SQL | Yes (target: **one** SQL-gen call) | CTE-local names, netwr rewrite, date-empty only when asked, LPAD repair, charts use `display_question` |

SAP domain lock: if the question is ERP/SAP and engines 2–5 cannot produce valid SAP SQL, the handler **does not** fall through to the EDI analyst pipeline.

## Question-type cheat sheet

| Question type | Typical engine |
|---------------|----------------|
| Highest sales 2004 + customer + industry (client Q) | `intent_sql_fast` or `universal_adaptive` |
| Named customer (`Motomarkt…`, `XYZNOEXIST999`) | Skip catalog/fast → `universal_adaptive` + ILIKE; empty → not-found |
| Top N / “five biggest” | Catalog or fast path, then LIMIT rewritten to N + default EUR |
| Product / line-item / CTE `base` | `universal_adaptive` (CTE aliases are local, not schema tables) |
| Follow-up chain (filter / rank / year / remove filter / metric) | Always `universal_adaptive` with `display_question` = user text |
| Out-of-domain EDI analyst | Refused when SAP-locked |
| Invoice **count** by customer | SAP `VBRK` (not EDI failed-invoice tables) by design |

## Latency

Common case: **one** SQL-generation LLM call; answer summary is **deterministic** unless `ADAPTIVE_SUMMARY_LLM=true`. Stage spans log as `adaptive_stage_timings` (`planner`, `schema`, `sql_llm`, `sql_repair`, `guardrail`, `schema_validate`, `db`, `summary` / `summary_llm`). Live p95 bench: `LIVE_GA_BENCH=1 pytest tests/test_adaptive_live_ga_bench.py`.
