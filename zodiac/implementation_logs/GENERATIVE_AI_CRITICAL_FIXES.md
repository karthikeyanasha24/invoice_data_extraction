# Generative AI — Critical Fixes (Post Live Validation Failure)

**Date:** 2026-08-16  
**Trigger:** `GENERATIVE_AI_LIVE_UI_VALIDATION.md` → **LIVE UI VALIDATION FAILED**  
**Scope:** Generative AI / Adaptive Query only  
**Not started:** R2 engine consolidation  

---

## Problems found (live)

1. **CRITICAL — T016T `spras` deadlock**  
   Guardrail required `T016T.spras = 'E'`; live schema has only `brsch`/`brtxt`. Schema validation then rejected invented `spras` → universal failed → EDI fallback count (59).

2. **CRITICAL — SAP → EDI contamination**  
   After universal failure, analyst chose `zodiac_edi` / `invoice_v2_business_data` COUNT(*) and returned it as a soft “answer” (HTTP 200).

3. **CRITICAL — Follow-ups did not execute fresh SQL**  
   R1 planned deltas, but guardrail false-positives + analysis_fallback narrated prior rows / suggested EDI SQL.

4. **HIGH — False-positive zero/negative NETWR guardrail**  
   Follow-up prompt boilerplate contained “zero/negative” instructions; intent detection treated normal sales as exception queries.

5. **HIGH — LIMIT 1 + mixed currency**  
   “Highest … with customer and industry” used LIMIT 1 and ranked unmapped USD above Motomarkt EUR.

---

## Root causes

| Issue | Cause |
|-------|--------|
| spras | Language filter applied unconditionally; not schema-aware |
| EDI fallback | Adaptive cascade after `no_match` always ran analyst pipeline |
| Follow-up narrative | On universal failure, `_followup_analysis` returned suggested SQL |
| NETWR FP | `_sql_guardrail_violations` scanned full augmented prompt, not user intent |
| Ranking | `_extract_limit` returned 1 for “highest”, unsafe across currencies |

---

## Files changed

| File | Change |
|------|--------|
| `zodiac-api/app/api/adaptive_query.py` | Schema-aware spras; intent-text guardrails; SAP domain lock; cannot_answer contract; follow-up fails closed; header-grain unquoted vbrp; prompts |
| `zodiac-api/app/services/ai_query_plan.py` | Safer limits for customer+industry; mapped-customer directive; explicit top-N always needs fresh SQL |
| `zodiac-api/app/services/dashboard_query_router.py` | Broader SAP skip-operational signals |
| `zodiac-front/src/components/DashboardAIAnalysis.tsx` | Pass previous user question + plan + answer_status; hide fake EDI rows on CANNOT_ANSWER |
| `zodiac-api/app/tests/test_generative_ai_critical_fixes.py` | New regression suite |

---

## Architecture flow (after)

```
UI Full Chat
  → POST /api/query/adaptive
  → (follow-up?) resolve_follow_up_sql_need → QueryPlan delta
  → dashboard router / universal SQL
  → guardrails (schema-aware + intent-cleaned)
  → schema validation
  → execute SAP SQL
  → summary + charts
  → answer_status: SUCCESS | PARTIAL | CANNOT_ANSWER | ERROR

If SAP-domain question and generation fails:
  → CANNOT_ANSWER (explicit)
  → NEVER invoice_v2_business_data count fallback
```

---

## Tests

```
app/tests/test_generative_ai_critical_fixes.py
app/tests/test_generative_ai_r1_r3_r5.py
tests/test_adaptive_query_guardrails.py
```

**Result:** **74 passed** (critical + R1/R3/R5 + guardrails)

Coverage includes: T016T ± spras, client industry SQL, NETWR FP, header/line grain, currency, gjahr, SAP lock, cannot_answer contract, follow-up fingerprints.

---

## Before / after (client question)

| | Before | After |
|--|--------|-------|
| SQL | `COUNT(*) FROM invoice_v2_business_data` | VBRK + KNA1 + T016T, `fkdat` 2004, LIMIT 10 |
| Result | 59 | Motomarkt Stuttgart GmbH / Trading & Distribution / EUR / **6,099,225** |
| spras | Required → deadlock | Not required (column absent) |
| Domain | EDI fallback | SAP locked |

---

## Known limitations

- Follow-up “Show me the industry” may re-run ranking SQL with industry (correct domain) rather than a minimal DISTINCT industries query.
- “Invoice count by customer” as a standalone question may route to SAP VBRK (intent path) rather than EDI — intentional SAP routing when not EDI-cued.
- Latency still often 30–60s per adaptive call.
- Chart type toggle automation remains flaky; data integrity on successful charts looks correct.
- R2 (engine consolidation) still deferred.

---

## Live revalidation

See `GENERATIVE_AI_LIVE_UI_VALIDATION_AFTER_FIXES.md`.
