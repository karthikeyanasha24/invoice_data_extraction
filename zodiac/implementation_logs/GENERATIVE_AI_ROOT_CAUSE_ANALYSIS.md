# Generative AI / Adaptive Query — Root Cause Analysis

**Status:** AUDIT COMPLETE — no production business-logic changes in this step  
**Date:** 2026-08-16  
**Scope:** System A only (Generative AI / Adaptive Query). System B (AI Ops) and System C (pipeline/adapters) are out of scope unless noted.  
**Database used for profiling:** Local `.env` `DATABASE_URL` (Neon Postgres hosting SAP-replica tables).  
**UI under complaint:** Sidebar **Generative AI** → `/dashboard/ai`

---

## 1. Current architecture

### Systems (do not confuse)

| System | What it is | Client complaint? |
|--------|------------|-------------------|
| **A — Generative AI / Adaptive Query** | NL→SQL against ERP/SAP tables in Postgres; charts; follow-up; history | **YES** |
| **B — Phase 9 AI Ops** | Monitoring-fact explanations | No |
| **C — Pipeline / adapters / monitoring** | Invoice processing | No |

### Live user path (shipping UI)

```
User question
  → /dashboard/ai (IntelligencePage + DashboardAIAnalysis Full Chat)
  → dashboardApi.postAdaptiveQuery({ question, contextData?, threadId })
  → POST /api/query/adaptive  (app/api/adaptive_query.py :: post_query_adaptive)
  → cascade (below)
  → rows + summary + charts → UI (AIChartRenderer)
```

Legacy path still exists in API + `.bak` UI but is **not** what Full Chat calls today:

- `POST /api/v1/dashboard/ai-analysis/chat` → LangGraph `multi_stage_planner`
- Approve / store / suggest-SQL → `ai_query_memory`
- Client helpers in `sapGenerativeAIRouting.ts` (imported by `.bak` only)

### Backend cascade for `POST /api/query/adaptive`

1. **overrideSql** — execute user SQL (SELECT-only guard)
2. **contextData follow-up**
   - if `follow_up_requires_fresh_sql(q)` → compose drill-down message → `_universal_query`
   - else → `_followup_analysis` (**narrative only on prior ~20 rows — no new SQL**)
3. **Period-compare fast path** → `ai_analysis_orchestrator`
4. **`run_dashboard_query`** (scalable router)
   - operational Zodiac resolver
   - intent billing fast path
   - `sql_catalog.json` keyword templates (`sap_sql_agent._lookup_sql_catalog`)
   - `_universal_query`
5. **`run_analyst_pipeline`** (15-stage analyst)
6. **`_universal_query`** again (GPT SQL + up to 3 retries)
7. **`run_ai_analysis_orchestrator`** final fallback (may consult `ai_query_memory`, LangGraph-style hand-rolled loop, `sap_sql_agent`)

**Implication:** One user question can take radically different engines depending on routing. Behavior is not a single adaptive planner; it is a **pipeline of competing paths**.

---

## 2. Current AI flow (detailed)

| Stage | Implementation | Notes |
|-------|----------------|-------|
| Frontend | `dashboard/ai/page.tsx` → `IntelligencePage.tsx` / `DashboardAIAnalysis.tsx` | Follow-up sends `contextData: { previousQuestion, previousSQL, data[:20] }` |
| API | `POST /api/query/adaptive` | Mounted without `/api/v1` prefix |
| Intent | Mixed: regex (`ai_intent_classifier`), catalog keywords, LLM action decide in orchestrator | Not a single semantic planner |
| Schema | `schema_full.json` / `tables_columns.csv` (121 tables) + `_TABLE_CONTEXT` + domain maps | Huge prompt; casing inconsistencies |
| Prompt | `_SYSTEM_PROMPT_CORE` in `adaptive_query.py` | Strong SAP casting/join rules documented in prompt |
| LLM SQL | `_universal_query` → `OPENAI_MODEL` (default `gpt-4o`; local env set to `gpt-5`) | Direct prompt→SQL |
| Validation | `_sql_guardrail_violations`, `_schema_reference_violations`, SELECT-only bans | Strong on zero/negative invoice; weaker on join inflation / currency |
| Repair | Up to 3 retries with PG error / guardrail feedback | Empty results often **not** diagnosed |
| Execution | Same Neon `DATABASE_URL` (SAP tables live there). `USE_SAP_DB_FOR_AI` only if `AI_CONTEXT_SOURCE=sap` | Default `AI_CONTEXT_SOURCE=zodiac` still hits SAP tables via primary DB |
| Answer | Fast model summarises first rows | Risk of LLM paraphrasing; usually grounded in returned rows |
| Charts | `_auto_charts` / orchestrator chart planners / `AIChartRenderer` | Derived from result columns when present |
| History | `ada_*` threads via `chat_thread_store` | Separate from `ai_query_memory` |
| Saved SQL | `ai_query_memory` (137 rows in profiled DB) | Used heavily by orchestrator / suggest-sql; poison gates exist |

---

## 3. Current AI stack inventory

| Concern | Provider / mechanism |
|---------|----------------------|
| Primary LLM | **OpenAI** (`OPEN_AI_KEY` / `OPENAI_API_KEY`) |
| Adaptive SQL model | `OPENAI_MODEL` (env: `gpt-5`; code default `gpt-4o`) |
| Summaries | `OPENAI_FAST_MODEL` / `AI_FAST_MODEL` (env includes `gpt-5-mini`) |
| LangGraph planner models | `LANGGRAPH_OPENAI_MODEL`, `LANGGRAPH_SQL_MODEL`, `LANGGRAPH_ANSWER_MODEL` |
| Multi-model optional | Google / Anthropic / OpenRouter when `ENABLE_MULTI_MODEL=true` |
| Deterministic templates | **Yes** — large `sql_catalog.json` keyword/priority matcher |
| Hard-coded classifiers | **Yes** — follow-up regex, intent tags, nationality/year catalog bypasses, analyst domain hard SQL |
| LangChain/LangGraph | Real LangGraph in `multi_stage_planner`; **hand-rolled** loop in `langgraph_orchestrator` |
| Semantic layer | Partial (`semantic_sql_resolver`, domain maps) — not the primary adaptive path |
| SQL validation / repair / retry | Yes (guardrails + 3 retries) |
| Saved SQL reuse | Exact normalized match + fuzzy score **≥ 24** + poison checks |
| Conversation context | Thread history + follow-up heuristics; **not** a full semantic query graph |

---

## 4. Current database / schema strategy

- **One Postgres DB** (Neon in local config) containing:
  - Zodiac app tables
  - SAP-shaped replicas: `"VBRK"` (35,057), `vbrp` (53,158), `"KNA1"` (20,030), `"T016T"` (60), `"MARA"`, `"MAKT"`, …
- **Casing trap:** `"VBRK"` must be quoted uppercase; `vbrp` is lowercase. Unquoted `VBRK` → `relation "vbrk" does not exist`.
- **Type trap:** `"VBRK"."netwr"` is **text**; `vbrp."netwr"` is **numeric**. Templates that `TRIM(v.netwr)` without cast fail.
- Schema prompt claims “121 tables / 9,352 columns” — LLM must invent joins under heavy load.
- Billing year must use `SUBSTRING(TRIM(fkdat),1,4)` — **not** `gjahr`.

---

## 5. Current data-quality issues (proven on live DB)

| Issue | Evidence | Business impact |
|-------|----------|-----------------|
| `VBRK.gjahr` useless | **All 35,057 rows = `'0000'`** | Any SQL using `gjahr` for year → empty/wrong; poison check exists for this |
| Header vs line sales disagree | 2004 header Σ netwr ≈ **90.79M**; line Σ via `vbrp` ≈ **69.66M** | Catalog templates that sum `vbrp.netwr` disagree with header totals; “total sales” is ambiguous |
| Missing customer master link | **251** of 2004 `VBRK` rows have `kunag` not in `KNA1` | Top result can be `(NULL, NULL, 17.5M USD)` |
| Industry sparsely populated | **17,638 / 20,030** `KNA1` rows have empty `brsch` | Industry questions often NULL / incomplete |
| Multi-currency | 2004: EUR 604 docs / USD 552 docs | Ranking across currencies without FX is misleading |
| Orphan / empty keys | 810 empty `kunag` overall | Inflates “unknown customer” buckets |
| Cached wrong SQL | `ai_query_memory` **137** rows; top reuse includes product/industry confusions and raw SQL-as-question | Wrong SQL can be reused if score ≥ 24 |

**Ground truth for the client’s 2004 + customer + industry question (header grain, verified manually):**

| Customer | Industry | Sales | Curr |
|----------|----------|-------|------|
| Motomarkt Stuttgart GmbH | Trading & Distribution | **6,099,225.00** | EUR |
| Motomarkt Heidelberg GmbH | Trading & Distribution | 5,947,880.00 | EUR |
| HTG Komponente GMBH | High Technology & Electronics | 4,643,837.40 | EUR |
| … | … | … | … |

So the **data exists**. Failures are not “empty database”; they are planning / path / reuse / follow-up / grain / join issues.

---

## 6. Screenshot / client failure patterns — reproduced at the routing layer

Client-style questions (exact family):

1. “Show me highest sales for the year 2004 with customer and industry”
2. “Show me highest sales for 2004 with customer”
3. “Show me highest sales for the year 2004”
4. Follow-ups: “Show me the industry” / “Only the Trading industry” / “Now show the top 5”

### Follow-up heuristic results (`follow_up_requires_fresh_sql`)

| Question | Fresh SQL? | What happens if Follow-up is on |
|----------|------------|----------------------------------|
| …2004 with customer and industry | True (year) | Full `_universal_query` |
| …2004 with customer | True | Full SQL |
| …2004 | True | Full SQL |
| **Show me the industry** | **False** | **Narrative on prior 20 rows only** |
| **Only the Trading industry** | **False** | Narrative only |
| **Now show the top 5** | **False** | Narrative only |
| What is the currency? | False | Narrative only |
| How many invoices? | False | Narrative only |
| Show sales by industry | False | Narrative only (unless “highest…by industry”) |

This matches the client complaint that **intent flips / follow-ups stop being adaptive**: after a good first answer, “show me the industry” does **not** rewrite SQL to add `T016T`; it chatters over a truncated prior result set.

### Catalog / year behavior

- Concrete years **bypass** `sql_catalog` (good for 2004 questions → LLM).
- Generic questions can still hit **keyword templates** that hard-code `vbrp` line sums → different totals than header.

### Saved SQL / “SQL saved — will be reused”

- Mechanism: `ai_query_memory_service.find_similar_stored_query`
  - Exact normalized question match, else fuzzy score ≥ **24**
  - Poison gates for T016T leakage, `gjahr`, year mismatch, etc.
- Observed DB: high `use_count` on unrelated / contaminated patterns (e.g. industry explained via `MARA.mbrsh`, raw SELECT stored as “question”).
- Live Full Chat primary path prefers fresh engines, but **orchestrator fallback + legacy approve/suggest paths still reuse memory**.
- Any UI copy about “SQL saved — will be reused for similar questions” is tied to this memory store / approve flow — **correctness can lose to reuse**.

---

## 7. Root cause of each failure class

| Class | Verdict | Exact layer |
|-------|---------|-------------|
| **A. Intent failure** | **Confirmed** | Competing paths + keyword catalog + weak follow-up intent; underspecified follow-ups treated as commentary |
| **B. Schema failure** | **Confirmed** | 121-table dump; casing (`VBRK` vs `vbrp`); wrong year column (`gjahr`) historically; industry via wrong table in memory |
| **C. Join failure** | **Confirmed / risk** | Header vs item grain; orphan `kunag`; industry LEFT JOIN → NULL industries; risk of fan-out if `vbrp` joined for “invoice count” |
| **D. Data-quality failure** | **Confirmed** | `gjahr=0000`; sparse `brsch`; orphans; dual currency; text vs numeric netwr |
| **E. SQL-generation failure** | **Confirmed (intermittent)** | Prompt→SQL under huge schema; catalog templates may be wrong grain |
| **F. SQL-execution failure** | **Confirmed (intermittent)** | TRIM on numeric `vbrp.netwr`; unquoted table names |
| **G. Result-interpretation** | **Partial** | Summary LLM usually uses rows but can mis-scale numbers; empty result → thin message |
| **H. Visualization** | **Secondary** | Charts follow whatever rows the wrong SQL returned |
| **I. Query-memory failure** | **Confirmed** | Fuzzy reuse ≥ 24; poisoned entries still present; can override fresh reasoning on orchestrator path |
| **J. Follow-up-context failure** | **Confirmed (primary UX bug)** | `follow_up_requires_fresh_sql` too narrow → narrative-only for “show industry / top 5 / filter Trading” |

**Primary client-facing root causes (ordered):**

1. **Follow-up routing treats many business refinements as chat-over-rows (J).**  
2. **No single semantic planner** — catalog + universal + analyst + orchestrator disagree (A/E).  
3. **ERP data quality + ambiguous sales grain** (D/C) — header vs line, currency, industry sparsity.  
4. **Saved SQL reuse can still poison answers** on fallback/legacy paths (I).  
5. **Empty / wrong results lack diagnosis** (G) — user sees “no results” instead of “wrong year column / wrong grain”.

---

## 8. Existing strengths

- Real DB connectivity with substantial SAP history (1995–2018 billing dates).
- Strong prompt documentation of SAP text→numeric and `fkdat` year filters.
- Guardrails already target known invoice zero/negative and some poison patterns.
- Retry-on-error for SQL repair exists.
- Charts auto-derived from result schemas in several paths.
- Destructive SQL blocked (SELECT-only).
- Some regression scripts already exist (`verify_memory_filter_guard.py`, adaptive guardrail tests).
- Manual SQL proves Motomarkt / Trading 2004 answers are recoverable.

---

## 9. Weaknesses

- Adaptive experience is a **fallback cascade**, not one planner.
- Follow-up is **not semantic** (add dimension / change filter / re-rank).
- Catalog is effectively a **hard-coded question dictionary** for non-year queries.
- Schema prompt is oversized; table selection is fragile.
- No business-aware result validation (inflation / currency mix / null-heavy industry).
- Memory store contains contaminated high-use entries.
- Live UI vs legacy approve-loop diverge — client screenshots may mix both eras.
- Answer path can still soft-hallucinate scale when summarising.

---

## 10. Proposed remediation (do not implement until approved)

**Principle:** smallest architecture-consistent fix; keep System A separate from AI Ops; no canned question dictionary expansion.

### Phase R1 — Fix follow-up (highest ROI)

- Expand `follow_up_requires_fresh_sql` **or replace** with a semantic delta planner:
  - detect add/remove dimension (industry, customer, product), filter (Trading, year), rank (top N), metric change
- Always generate **new SQL** for those deltas using previous SQL as constraint context (already partially done in drill-down composer).
- Never answer “show the industry” from 20 preview rows alone when industry was not in the prior SELECT.

### Phase R2 — Single query plan contract

Introduce an explicit intermediate object before SQL:

`{ metric, dimensions[], filters[], grain: header|line, operation, compare? }`

Then: schema select → join plan → SQL → validate → execute → answer/charts.

Wire **one** primary path for `/api/query/adaptive`; demote catalog to optional hints, not hard overrides.

### Phase R3 — Sales grain + currency rules

- Default **sales/revenue** to **VBRK header** unless user asks line/product.
- Never mix EUR+USD into one “highest” without FX or separate ranking per currency.
- Prefer `fkdat` year; reject `gjahr` (already partially poisoned).

### Phase R4 — Data-quality / semantic layer (non-destructive)

- Canonical views e.g. `vw_billing_header_enriched` (VBRK ⋈ KNA1 ⋈ T016T) with clean casts.
- Document null industry / orphan customers in answers.
- Do **not** rewrite raw ERP rows.

### Phase R5 — Memory correctness > reuse

- Raise / redesign similarity threshold; require matching plan fingerprint (metric+dims+years).
- Re-score or purge poisoned `ai_query_memory` rows.
- Never reuse SQL when new question plan differs.
- Keep poison checks; extend for header/line grain mismatches.

### Phase R6 — Empty-result diagnosis

- On 0 rows: check year availability, sample date range, whether filter entity exists, whether join eliminated rows; repair or explain.

### Phase R7 — Evaluation harness

- Offline suite: question → expected plan → SQL validity → numeric gold (Motomarkt 2004 etc.) → follow-up chains.
- Unit tests for follow-up routing, memory guards, guardrails, grain rules.

---

## 11. Files that must change (when implementing)

| Area | Files |
|------|-------|
| Follow-up | `app/services/ai_followup_routing.py`, `app/api/adaptive_query.py` |
| Primary adaptive path | `app/api/adaptive_query.py`, `app/services/dashboard_query_router.py` |
| Memory | `app/services/ai_query_memory_service.py` (+ optional DB cleanup script) |
| Planner (new or extend) | prefer extend `analyst_pipeline` / semantic resolver rather than new parallel stack |
| Guardrails / grain | `adaptive_query._sql_guardrail_violations`, catalog SQL entries that force line grain |
| Tests | new `tests/test_generative_ai_*.py`, expand adaptive guardrail tests |
| Docs | this RCA + later `GENERATIVE_AI_FINAL_VALIDATION.md` |

Frontend: only if follow-up UX needs to send richer context (prior plan) — `DashboardAIAnalysis.tsx`.

---

## 12. Files that must NOT change

- Customer portal / customer login
- Workspace / country adapter / pipeline / ERP / government / monitoring
- AI Ops (`app/api/ai_ops.py`, monitoring consumers)
- SAT V1/V2 invoice processing (unless shared SQL sanitizers are proven required)
- Do not replace Generative AI with AI Ops

---

## 13. Testing strategy

1. **Routing unit tests** — follow-up matrix (industry / Trading / top 5 / year change).  
2. **SQL plan tests** — 2004 customer+industry must include VBRK+KNA1+T016T, `fkdat` year, header grain.  
3. **Gold numeric tests** — Motomarkt Stuttgart 6,099,225 EUR (header).  
4. **Data-quality tests** — `gjahr` rejection; currency split; orphan handling.  
5. **Memory tests** — dissimilar question must not reuse high-score contaminated SQL.  
6. **Security** — injection / DDL still blocked.  
7. **Regression** — existing adaptive guardrail + memory filter scripts.  
8. **Eval dataset** — ≥30 NL variants + ≥10 multi-turn conversations (per client requirement).

Do **not** declare success on HTTP 200 alone.

---

## 14. Expected improvement

| Before | After (target) |
|--------|----------------|
| Follow-up often narrative-only | Follow-ups rewrite SQL with preserved filters |
| Competing engines | One plan→SQL path for adaptive UI |
| Line vs header confusion | Explicit grain; consistent totals |
| Memory can poison | Reuse only on matching plan fingerprint |
| “No results” opaque | Diagnosed empty results / auto-repair |
| Industry often wrong/missing | Correct joins + honest NULL/orphan messaging |

---

## 15. Risks

- Tightening follow-up → more LLM SQL calls (latency/cost).
- Changing default grain (header vs line) may shift totals users previously saw from catalog.
- Purging memory may remove some good approved SQL — need curated re-approval.
- `gpt-5` vs `gpt-4o` env drift between local and production must be verified.
- Over-scoping into AI Ops / portal must be avoided.

---

## 16. Production readiness of Generative AI (current)

| Dimension | Score (0–10) | Note |
|-----------|--------------|------|
| DB connectivity | 8 | Real SAP tables present |
| Broad adaptive NL | 4 | Catalog + fragile follow-up |
| SQL correctness | 5 | Guardrails help; grain/joins weak |
| Follow-up | 2 | Heuristic miss on industry/top-N |
| Data-quality handling | 3 | Issues known; not surfaced well |
| Memory safety | 4 | Poison gates exist; store dirty |
| Trustworthy answers | 4 | Gold cases recoverable but not reliable |
| **Overall** | **~4 / 10** | Not client-ready as “adaptive ERP AI” |

---

## 17. Audit method notes

- Code traced: frontend Generative AI → `postAdaptiveQuery` → `adaptive_query.py` cascade → router / analyst / universal / orchestrator / memory / follow-up.
- DB profiled with read-only SQL against Neon (counts, year histogram, 2004 rankings, inflation, nulls, memory).
- Follow-up heuristic exercised programmatically for client phrasing.
- **Full live LLM e2e suite not executed in this audit step** (cost/latency); routing + data evidence already prove primary root causes. E2E gold-query runs belong in the implementation + validation phase.

---

## 18. Decision gate

**No production Generative AI business-logic changes have been made in this step.**

Next step after stakeholder approval of this RCA:

1. Implement R1 (follow-up) + R3 (sales grain) + R5 (memory) first.  
2. Add evaluation harness with Motomarkt/2004 gold.  
3. Then R2 planner consolidation.  
4. Publish `implementation_logs/GENERATIVE_AI_FINAL_VALIDATION.md`.

---

*Document: `zodiac/implementation_logs/GENERATIVE_AI_ROOT_CAUSE_ANALYSIS.md`*  
*System A audit only — Generative AI / Adaptive Query*
