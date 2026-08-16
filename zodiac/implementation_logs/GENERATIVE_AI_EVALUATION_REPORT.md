# Generative AI — Evaluation Report (R1 / R3 / R5)

**Date:** 2026-08-16  
**Harness:** `app/tests/generative_ai_eval_cases.json` + `app/tests/test_generative_ai_r1_r3_r5.py`  
**Stop point:** R1/R3/R5 only — R2 not started

---

## Test counts

| Suite | Result |
|-------|--------|
| Generative AI R1/R3/R5 unit + eval | **22/22 passed** (in `test_generative_ai_r1_r3_r5.py`) |
| Adaptive Query guardrails | **37/37 passed** |
| Combined above | **59/59 passed** |
| Memory filter guard script | **OK** |
| Adaptive schema_mode test | **ERROR (pre-existing import)** — missing `_build_schema_structure_payload` |
| Full enterprise regression (portal/SAT/pipeline) | Not re-run end-to-end in this pass; **no files in those areas were modified** |

---

## Evaluation dataset coverage

| Category | Count | Status |
|----------|-------|--------|
| Single-turn questions | **32** (≥30 required) | Plan assertions PASS |
| Multi-turn conversations | **10** (≥10 required) | Follow-up SQL need + plan PASS |
| Ground-truth Motomarkt 2004 EUR | 1 DB SQL | PASS (6,099,225.00) |

### Single-turn intent families covered

Sales/revenue, customer ranking, industry, year filters, compare years, counts, top/bottom N, currency, products (line grain), NL paraphrases of “top customer 2004”.

### Multi-turn chains covered

Industry add → Trading filter → top 5 → compare; currency; year switch; metric switch to invoice count; filter phrasing variants.

---

## Client screenshot scenarios (routing layer)

| # | Scenario | Expected | Result |
|---|----------|----------|--------|
| 1 | Highest sales 2004 + customer + industry | Plan: header, customer+industry, year 2004 | **PASS** (plan + gold SQL) |
| 2 | Follow-up: Show me the industry | Fresh SQL | **PASS** |
| 3 | Only the Trading industry | Fresh SQL + filter | **PASS** |
| 4 | Now show the top 5 | Fresh SQL + limit 5 | **PASS** |
| 5 | Compare with 2003 | Fresh SQL + years {2003,2004} | **PASS** |

**Note:** Full live UI LLM execution at `localhost:3000/dashboard/ai` was **not** recorded in this automated pass. Routing, guardrails, fingerprints, and DB gold are validated. Live UI confirmation remains a manual/ops step after API restart.

---

## Guardrail / memory checks

| Check | Result |
|-------|--------|
| Reject `gjahr` for year sales | PASS |
| Reject `vbrp` sum for header sales | PASS |
| Reject MARA industry for customer industry | PASS |
| Require currency on monetary aggregates | PASS |
| Fingerprint blocks dimension/year/grain mismatch reuse | PASS |
| Year-mismatched similarity below reuse threshold | PASS |
| Classify raw SQL / MARA contamination | PASS |

---

## Before vs after (product claim)

| Capability | Before RCA | After R1/R3/R5 |
|------------|------------|----------------|
| Follow-up “show industry” | Narrative on 20 rows | Fresh SQL with industry dim |
| Sales grain | Ambiguous header/line | Header default + guardrail |
| Year field | `gjahr` risk | `fkdat` enforced |
| Memory reuse | Score ≥ 24 only | Score + **plan fingerprint** |
| Empty results | Thin message | Diagnosed (year probe / join hints) |
| Eval harness | Ad hoc | 32 + 10 automated plan cases |

---

## Production readiness (this slice)

| Dimension | Score | Note |
|-----------|-------|------|
| Follow-up adaptivity (routing) | 8/10 | Semantic deltas work; LLM still generates SQL |
| Grain / date / industry guards | 8/10 | Guardrails + plan directives |
| Memory safety | 7/10 | Fingerprints; store not purged |
| End-to-end LLM UI proof | 4/10 | Pending live browser session |
| Overall System A after R1/R3/R5 | **~6.5/10** | Better; not “all questions work” |

Do **not** claim full production readiness for Generative AI until live UI chains pass and R2 reduces engine conflict.

---

## How to re-run

```powershell
cd zodiac\zodiac-api
python -m pytest app/tests/test_generative_ai_r1_r3_r5.py tests/test_adaptive_query_guardrails.py -q
python scripts/verify_memory_filter_guard.py
```

---

*Generated after R1/R3/R5 implementation. R2 deferred pending review.*
