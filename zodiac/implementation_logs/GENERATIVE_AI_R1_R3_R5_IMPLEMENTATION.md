# Generative AI — R1 / R3 / R5 Implementation

**Date:** 2026-08-16  
**Based on:** `GENERATIVE_AI_ROOT_CAUSE_ANALYSIS.md`  
**Scope:** System A (Adaptive Query / Generative AI) only  
**Not done:** R2 (single planner consolidation) — deferred per instructions

---

## Summary

Implemented the highest-impact corrections without redesigning the AI stack:

| Track | What changed |
|-------|----------------|
| **R1** | Semantic `QueryPlan` + follow-up deltas → fresh SQL for industry / Trading / top-N / compare |
| **R3** | Header sales grain default, `fkdat` (reject `gjahr`), currency grouping, KNA1→T016T industry |
| **R5** | Plan fingerprints gate memory reuse; suspicious entries classified/rejected |
| **Eval** | 32 single-turn + 10 multi-turn cases + unit tests + Motomarkt gold SQL |

---

## Exact behavior changes

### R1 — Adaptive follow-ups

**Before:** `follow_up_requires_fresh_sql("Show me the industry")` → `False` → narrative over prior 20 rows.

**After:**

1. Extract / merge `QueryPlan` (`metric`, `dimensions[]`, `filters`, `grain`, `operation`, `limit`).
2. Follow-up applies a **semantic delta** (add dimension, filter, ranking, year, metric, grain).
3. If plan changes → compose plan-aware prompt → `_universal_query` with fresh SQL.
4. Narrative reserved for thanks/explain-style turns.

Client chain now plans as:

| Turn | Fresh SQL | Plan effect |
|------|-----------|-------------|
| highest sales 2004 | yes | sales, customer, year=2004, header, top |
| Show me the industry | yes | +industry |
| Only Trading | yes | +industry filter |
| top 5 | yes | limit=5 |
| Compare with 2003 | yes | years={2003,2004}, compare |

### R3 — Sales grain / date / currency / industry

- Default sales/revenue → **VBRK header `netwr`** unless line/product cues.
- Guardrail rejects `SUM(vbrp.netwr)` for header sales questions.
- Guardrail rejects `gjahr` whenever calendar year + sales/billing intent.
- Guardrail rejects `MARA.mbrsh` for customer industry; requires KNA1→T016T.
- Monetary aggregates must include currency + `GROUP BY` currency.
- Prompt directives: `COALESCE(name1,'Unknown / unmapped')`, `COALESCE(brtxt,'Not available')`.

### R5 — Safe SQL memory reuse

- Build plan fingerprint: `metric|dimensions|years|industry|currency|grain|operation|limit`.
- Reuse only if fingerprints compatible **and** score ≥ 24 **and** not poisoned/suspicious.
- `classify_memory_entry()` → `valid | suspicious | incompatible | raw_sql` (non-destructive).
- Rejects raw-SQL-as-question and MARA industry contamination.

### Empty results

`_diagnose_empty_result` probes year availability on `fkdat` and explains join/filter/grain likely causes instead of a bare “no rows”.

---

## Files changed

| File | Role |
|------|------|
| `app/services/ai_query_plan.py` | **NEW** — plan extract / delta / fingerprint / prompt directive |
| `app/services/ai_followup_routing.py` | Semantic resolve + legacy safety net |
| `app/api/adaptive_query.py` | Follow-up path, plan in universal SQL, R3 guards, empty diagnosis |
| `app/services/ai_query_memory_service.py` | Fingerprint gate + classify_memory_entry |
| `app/tests/generative_ai_eval_cases.json` | **NEW** — eval dataset |
| `app/tests/test_generative_ai_r1_r3_r5.py` | **NEW** — unit + eval harness tests |

**Not modified:** Customer Portal, Workspace, Pipeline, Adapters, Monitoring, AI Ops, SAT V1/V2.

---

## Before / after (routing)

| Question (as follow-up after 2004 sales) | Before | After |
|------------------------------------------|--------|-------|
| Show me the industry | narrative | fresh SQL + industry dim |
| Only the Trading industry | narrative | fresh SQL + industry filter |
| Now show the top 5 | narrative | fresh SQL + limit 5 |
| Compare with 2003 | year token → SQL (partial) | compare plan years 2003+2004 |
| thanks | narrative | narrative (unchanged) |

---

## Database validation

Gold header query (EUR, 2004) still returns:

- Motomarkt Stuttgart GmbH  
- Trading & Distribution  
- **6,099,225.00**  
- EUR  

Covered by `test_ground_truth_header_sql_against_database`.

---

## Remaining limitations (honest)

- R2 not done — catalog / analyst / universal / orchestrator still compete on first-turn path.
- Live LLM e2e in browser not automated in this pass (unit + DB gold + routing eval done).
- Contaminated `ai_query_memory` rows are **rejected on reuse**, not bulk-deleted.
- Cross-currency ranking still requires per-currency grouping (no FX invented) — correct, but rankings are multi-series.
- `tests/test_adaptive_query_schema_mode.py` fails collection due to **pre-existing** missing `_build_schema_structure_payload` (unrelated to this change).

---

## Next step (only after review)

**R2** — consolidate competing engines behind one semantic planner, keeping this plan contract.
