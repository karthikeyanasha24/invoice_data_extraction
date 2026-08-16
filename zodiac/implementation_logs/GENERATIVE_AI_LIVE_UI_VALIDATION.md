# Generative AI — Live End-to-End UI Validation

**Date:** 2026-08-16  
**Scope:** Live browser validation of `/dashboard/ai` only  
**Code changes:** None (validation pass only — no R2, no fixes)  
**Prior work:** R1/R3/R5 unit/eval passed offline (`GENERATIVE_AI_EVALUATION_REPORT.md`)

---

## Executive Summary

Browser automation **was available** and used against the live local stack. Login and Generative AI UI load succeeded. Several SAP/year/currency questions produce useful answers via scalable/catalog/universal paths. **The client's exact complaint scenario fails in the live UI.**

Exact client question  
`Show me highest sales for the year 2004 with customer and industry`  
returns an EDI fallback row-count (`invoice_v2_business_data` → 59), **not** Motomarkt / Trading & Distribution / 6,099,225 EUR.

Root cause (live API logs): universal SQL is generated correctly in spirit (VBRK + KNA1 + T016T + `fkdat` 2004), then **blocked by a contradictory guardrail**:

1. Guardrail demands `T016T.spras = 'E'`
2. Schema validation rejects `"spras"` because this DB's `T016T` columns are only `brsch`, `brtxt`
3. After 3 failed universal attempts → analyst mis-routes to `zodiac_edi` → `CANNOT_ANSWER` fallback count
4. HTTP status remains **200**, so UI looks like a soft failure, not an outage

Multi-turn follow-ups often request fresh SQL (R1 deltas appear in logs) but universal then fails again on unrelated/over-aggressive guardrails (especially a false-positive “zero-negative / VBRK.NETWR” rule), so the UI falls back to **narrating prior SQL** or suggesting EDI SQL — which is exactly the “not adaptive enough” client complaint.

**Final decision: LIVE UI VALIDATION FAILED**

---

## Environment

| Item | Value |
|------|--------|
| Frontend | `http://localhost:3000` (Next.js turbopack) |
| API | `http://127.0.0.1:8000` (`NEXT_PUBLIC_API_URL`) |
| Generative AI URL | `http://localhost:3000/dashboard/ai` |
| Adaptive endpoint | `POST /api/query/adaptive` |
| History endpoint | `GET /api/query/adaptive/history?thread_id=…` |
| QA login | `puspesh@gmail.com` (local admin) |
| Tab used | **Full Chat** (AI Data Analyst / 15-stage pipeline UI) |
| Browser | Cursor IDE browser automation (`cursor-ide-browser`) |
| DB gold check | Direct SQL against `DATABASE_URL` |

---

## Browser availability

**BROWSER VALIDATION EXECUTED** via Cursor browser automation (navigate, login, CDP evaluate for chat send/SQL capture, network Resource Timing).

Native DevTools Console export is limited in this automation surface; console assessment used page overlays + API server logs + Resource Timing for `/api/query/adaptive`.

---

## Login result — PASS

| Check | Result |
|-------|--------|
| Login succeeds | PASS → `/dashboard` |
| Dashboard loads | PASS |
| Generative AI nav available | PASS (sidebar “Generative AI”) |
| Auth errors | None observed (`/api/v1/user/auth/fetch_user` 200) |
| Navigate `/dashboard/ai` | PASS |
| React crash overlay | Not observed |

---

## Verify Generative AI UI — PARTIAL PASS

| Check | Result |
|-------|--------|
| Page loads | PASS |
| Chat input works | PASS |
| Send works | PASS |
| Response appears | PASS (including failure messages) |
| SQL section / View SQL | PASS |
| Table results | PASS when query succeeds |
| Charts | PASS when rows returned (e.g. 2005 sales, industry catalog) |
| Follow-up / New question controls | PASS (controls present) |
| History/thread | PASS (`/api/query/adaptive/history` 200) |
| Infinite loading | Not observed as permanent hang; some turns 45–75s |
| Duplicate visible answers | Occasional duplicate Executive Summary text in failure path |
| Failed API requests | Adaptive calls return **200** even on semantic failure |
| Slow requests | **All sampled adaptive calls >1s** (often 14–62s) |

---

## Scenario PASS/FAIL matrix

| # | Scenario | Verdict |
|---|----------|---------|
| 1 | Login + nav to Generative AI | **PASS** |
| 2 | UI shell (input/send/SQL/controls) | **PASS** (with soft-fail messaging on bad answers) |
| 3 | Client exact query (2004 + customer + industry) | **FAIL (CRITICAL)** |
| 4 | Follow-up “Show me the industry” | **FAIL (CRITICAL)** |
| 5 | Follow-up “Only the Trading industry” | **FAIL (HIGH)** |
| 6 | Follow-up “Now show the top 5” | **FAIL (HIGH)** |
| 7 | Follow-up “Compare this with 2003” | **FAIL (HIGH)** |
| 8 | Unrelated “invoice count by customer” | **PASS** (new SQL; EDI domain — expected for that phrasing) |
| 9 | Top products by sales 2004 (line grain) | **FAIL (HIGH)** |
| 10 | Total sales 2005 | **PASS** |
| 11 | Highest sales by customer 2004 (currency) | **PARTIAL / FAIL (MEDIUM–HIGH)** |
| 12 | Sales year 2099 empty | **PASS** |
| 13 | Memory reuse (sales → invoice count → industry) | **PARTIAL PASS** |
| 14 | Multi-turn chain (8 turns) | **FAIL (CRITICAL)** |
| 15 | Visualization | **PARTIAL PASS** |
| 16 | Console / Network | **FAIL (performance + soft 200s)** |
| 17 | DB cross-check Motomarkt | **DB PASS / UI FAIL** |

---

## Exact client scenario result — FAIL (CRITICAL)

**Question:** `Show me highest sales for the year 2004 with customer and industry`

### UI actual
- Message: automatic SQL failed; fallback row count for `invoice_v2_business_data`
- Visible SQL: `SELECT COUNT(*) AS total_rows FROM invoice_v2_business_data`
- Result: **59** total rows
- Duration shown: ~7590ms (analyst stage); end-to-end much longer (~36s+ cascade)
- No Motomarkt, no industry, no 6,099,225 EUR

### Checklist

| Item | Result |
|------|--------|
| A. Execute SQL? | Yes — wrong SQL |
| B. Return rows? | 1 row (count) |
| C. Identify customer? | NO |
| D. Identify industry? | NO |
| E. Correct year? | NO (year not in fallback SQL) |
| F. Header sales grain? | NO |
| G. Currency handled? | NO |
| H. Business sense? | NO |
| I. Chart ↔ rows? | No useful chart |
| J. NL matches data? | Failure message matches fallback; not client gold |

### API / cascade (server logs)
1. Universal attempt 1 — rejected: missing `T016T.spras = 'E'`
2. Universal attempt 2 — rejected: unknown column `spras` on `T016T`
3. Universal attempt 3 — rejected: missing `spras` again
4. `dashboard_query_router` → no_match
5. Analyst domain=`zodiac_edi`, tables=`invoice_v2_business_data`, `zodiac_customers`
6. `CANNOT_ANSWER` → fallback count
7. `POST /api/query/adaptive` → **200 OK**

### Ground-truth DB (same environment)

`T016T` columns: **`brsch`, `brtxt` only** (no `spras`).

Header sales 2004 + customer + industry (no spras — only columns that exist):

| Rank note | Customer | Industry | Currency | Sales |
|-----------|----------|----------|----------|-------|
| Gold EUR named customer | **Motomarkt Stuttgart GmbH** | **Trading & Distribution** | **EUR** | **6,099,225.00** |
| Also present | Motomarkt Heidelberg GmbH | Trading & Distribution | EUR | 5,947,880.00 |

**UI does not surface this gold answer** for the client's exact phrasing.

---

## Follow-up results

### 4. “Show me the industry” — FAIL
- UI: suggests `SELECT DISTINCT industry FROM invoice_v2_business_data…`
- Does **not** return T016T industries for the prior SAP sales context
- Logs: follow-up → fresh SQL attempted → universal failed → narrative suggestions

### 5. “Only the Trading industry” — FAIL
- UI: narrates prior count; suggests EDI `WHERE industry = 'Trading'`
- No executed Trading+2004+sales SAP result

### 6. “Now show the top 5” — FAIL
- UI: suggests top-5 SQL against `invoice_v2_business_data ORDER BY created_at`
- Not ranked SAP sales

### 7. “Compare this with 2003” — FAIL
- UI: asks clarification / suggests EDI fiscal_year compares
- No executed 2003+2004 SAP comparison SQL in result pane
- Logs show compare delta planned, then universal rejected (guardrails)

---

## Unrelated question — PASS (semantic switch)

**“Show me invoice count by customer”** (New question)
- New SQL against EDI invoice tables
- Chart + 15 rows (Trotters Trading Co Ltd = 24, etc.)
- Does **not** reuse VBRK sales SQL → good isolation for this phrasing

---

## Product / line-grain — FAIL

**“Show me the top products by sales in 2004”**
- UI: failure; View SQL showed `SELECT COUNT(*) AS total_rows FROM VBRK` with **0 rows** message path
- Did not demonstrate reliable VBRP/material ranking
- Does not prove safe header-vs-line distinction for product questions

---

## Year behavior — PASS (2005)

**“Show me total sales in 2005”**
- SQL: `VBRK`, `SUBSTRING(fkdat)=2005`, `GROUP BY waerk`
- Results: EUR 50,738,595.82 / USD 26,236,932.02
- No `gjahr`
- Charts present (multi-currency labeled)
- Not copied from 2004

---

## Currency behavior — PARTIAL / FAIL

| Case | Behavior |
|------|----------|
| Total sales 2005 | **PASS** — grouped by currency |
| Sales by industry (catalog) | **PASS** — currency column present; EUR/DEM/USD separate |
| Highest sales by customer 2004 | **FAIL/PARTIAL** — Motomarkt 6,099,225 shown, but SQL aggregates **`vbrp.netwr` (line grain)** without currency grouping; ranking can mix currencies |

No invented FX rates observed.

---

## Empty-result behavior — PASS

**“Show me sales for the year 2099”**
- Fresh SQL with `fkdat` year `2099`
- Clear explanation: no billing documents for 2099
- 0 rows; no Motomarkt hallucination; no unexplained generic crash

---

## Memory reuse behavior — PARTIAL PASS

Sequence (New question each time):
1. Highest sales 2004 by customer → Motomarkt path (intent/scalable), chart OK  
2. Invoice count by customer → distinct EDI SQL  
3. Sales by industry → **sql_catalog** template with T016T (no spras), multi-currency rows  

No persistent “SQL saved — will be reused for similar questions” banner observed in these turns.  
Semantic isolation across **New question** turns looked OK for these three.

**However:** after a **failed** client/industry thread, follow-ups contaminated with EDI suggestions — reuse/fallback behavior is unsafe when universal fails.

---

## Multi-turn results — FAIL (CRITICAL)

Chain executed in one Follow-up thread:

| Turn | Expected | Actual |
|------|----------|--------|
| 1 Highest sales 2004 | Customer/header ranking | Highest **single billing document** 1,530,000 EUR |
| 2 Include customer | Fresh SQL + customer | **Same SQL**; text says customer not in result |
| 3 Include industry | Fresh SQL + T016T | Suggested SQL in chat; **executed SQL unchanged** |
| 4 Only Trading | Industry filter | Narration; no Trading filter executed |
| 5 Top 5 | LIMIT 5 ranking | Still LIMIT 1 prior SQL; claims only one row |
| 6 Compare 2003 | Compare SQL executed | Suggested CTE text; prior SQL still shown |
| 7 Remove Trading | Clear filter | Narrates same 2004 doc |
| 8 Invoice count instead | Metric switch | Claims “Invoice count: 1” from prior single-doc context |

Logs confirm R1 often emits `follow-up → fresh SQL` deltas, then universal fails (especially false-positive zero-negative guardrail), and UI/analyst path answers from prior result text.

**R1 unit tests do not equal live adaptive success.**

---

## SQL correctness

| Path | Observation |
|------|-------------|
| Universal + industry | Deadlocked by spras requirement vs schema |
| Universal follow-ups | Frequently rejected by over-broad NETWR/zero-negative guardrail even for normal sales ranking |
| Intent/scalable customer 2004 | Returns Motomarkt amount but uses **line** `vbrp` SUM |
| Universal year totals | Correct `fkdat` + currency group (2005) |
| Catalog industry | Works without spras; groups by currency |
| Analyst fallback | Wrong domain (`zodiac_edi`) for SAP sales+industry |

---

## Database correctness

| Layer | Motomarkt 6,099,225 EUR / Trading & Distribution / 2004 |
|-------|----------------------------------------------------------|
| DATABASE | Present (header `VBRK.netwr` + KNA1 + T016T) |
| API for client exact Q | Does **not** return it (fallback count) |
| UI for client exact Q | Does **not** show it |

Separate question “highest sales by customer in 2004” **does** show Motomarkt 6,099,225 in UI — amount matches gold EUR figure — but SQL grain is line (`vbrp`), and industry is absent.

HTTP 200 ≠ correct answer.

---

## Charts — PARTIAL PASS

| Check | Result |
|-------|--------|
| Chart present when rows returned | PASS (2005, industry, customer ranking) |
| Chart matches table (2005) | PASS (EUR/USD) |
| Multi-currency indication | PASS (“Multi-currency” label) |
| Stale chart across New questions | Chat history retains prior charts (expected); new answer charts matched new rows when successful |
| Chart type toggle | UI shows PIE/BAR/LINE/AREA/TABLE; automated click targeting was unreliable; no data corruption observed on re-query |

---

## Console

| Item | Result |
|------|--------|
| React error overlay | Not observed |
| Failed adaptive HTTP | None (all 200) — masks semantic failure |
| Auth | 200 |
| Server ERROR/WARNING | Many universal guardrail rejections + analyst CANNOT_ANSWER |

---

## Network

**Primary adaptive endpoint:** `POST http://127.0.0.1:8000/api/query/adaptive`

| Observation | Detail |
|-------------|--------|
| Status | Typically 200 even when answer is fallback/wrong |
| Duration | Resource Timing samples commonly **14–62s**; nearly all >1s |
| Duplicates | Multiple adaptive posts per session (expected for many questions); no tight retry storm observed |
| History | `GET /api/query/adaptive/history?thread_id=…` 200 |

### Request path (observed)

Frontend Full Chat  
→ `POST /api/query/adaptive`  
→ adaptive router / follow-up plan (R1)  
→ universal SQL generation  
→ guardrail + schema validation  
→ (on fail) dashboard_query_router / analyst pipeline  
→ DB execute (or fallback)  
→ summary + charts  
→ UI

---

## Performance

| Metric | Observed |
|--------|----------|
| Client exact Q | ~36s+ cascade then analyst ~7.5s |
| Follow-ups after failure | often 45–75s then weak narrative |
| Successful universal (2005) | ~9–22s class |
| Production readiness concern | Latency + soft failures together feel broken |

---

## Failures (classified)

### CRITICAL-1 — Client exact query fails
- **Question:** highest sales 2004 with customer and industry  
- **Expected:** Motomarkt Stuttgart GmbH / Trading & Distribution / 6,099,225 EUR (header)  
- **Actual:** EDI count fallback 59  
- **SQL:** `SELECT COUNT(*) AS total_rows FROM invoice_v2_business_data`  
- **API:** 200  
- **Root cause:** Guardrail requires `T016T.spras='E'` but column does not exist (`brsch`,`brtxt` only) → universal impossible → wrong domain fallback  
- **Files:** `zodiac-api/app/api/adaptive_query.py` (`_sql_guardrail_violations` / `_universal_query`), analyst domain routing  
- **Owner:** AI logic / schema-guard mismatch (not missing Motomarkt data)  
- **Production impact:** Client’s primary demo question fails

### CRITICAL-2 — Multi-turn adaptivity fails after success
- **Expected:** Each delta regenerates and executes SQL  
- **Actual:** UI reuses prior result / suggests SQL text; executed SQL often unchanged  
- **Root cause:** Follow-up planning runs, universal fails guardrails, response path narrates old result  
- **Files:** `adaptive_query.py`, follow-up/analyst continuation path, possibly `ai_query_plan.py` consumers  
- **Production impact:** “Not adaptive enough” complaint confirmed live

### HIGH-1 — Industry / Trading / Top-N / Compare follow-ups after failed SAP start
- Collapse into EDI suggestions  
- No T016T Trading filter executed for client thread

### HIGH-2 — Product/line-grain question fails
- Top products 2004 → fallback / no product ranking

### HIGH-3 — False-positive zero-negative / VBRK.NETWR guardrail blocks normal follow-up SQL
- Logs reject ordinary ranking/compare SQL with zero-negative rule text  
- Prevents R1 fresh SQL from landing

### MEDIUM-1 — Customer ranking uses line grain without currency split
- Motomarkt amount happens to match EUR gold, but SQL is `SUM(vbrp.netwr)` without `waerk` group  
- Risky under mixed currency

### MEDIUM-2 — Soft HTTP 200 on semantic failure
- Harder for operators/UI to distinguish outage vs wrong answer

### LOW-1 — Duplicate executive-summary text on failure cards  
### LOW-2 — Long adaptive latency (>1s always; often tens of seconds)

---

## Regression

| Area | Note |
|------|------|
| R1/R3/R5 unit tests | Still green offline — **do not** imply live UI readiness |
| Login / dashboard shell | OK |
| Some SAP year/currency paths | OK (2005 totals, catalog industry) |
| Client industry+customer sales path | Regressed / still broken in live |

---

## Production readiness score: **38 / 100**

Rationale: core client scenario fails; multi-turn adaptivity fails; some happy-path SAP queries work; empty-year messaging is good; latency is poor; HTTP 200 masks failure.

---

## Most important remaining issues (do not fix in this pass)

1. **Resolve T016T `spras` guardrail vs real schema** (CRITICAL) — schema-aware language filter or skip when column absent  
2. **Stop routing SAP sales+industry failures into EDI row-count fallback**  
3. **Fix false-positive zero-negative NETWR guardrail** that blocks normal follow-up SQL  
4. **Ensure follow-up failures do not silently answer from previous SQL/result**  
5. **Header vs line grain + currency grouping** on ranking questions  
6. **Product/line questions** must use item tables reliably  

---

## FINAL DECISION

### 3. LIVE UI VALIDATION FAILED

Do **not** treat unit-test green as feature complete.  
Do **not** start R2 until CRITICAL-1 (client query) and CRITICAL-2 (multi-turn execute path) are addressed and re-validated live.

---

## Appendix — Evidence snippets

**Client UI SQL:**
```sql
SELECT COUNT(*) AS total_rows FROM invoice_v2_business_data
```

**Live guardrail contradiction (API):**
- reject: missing `spras = 'E'`
- reject: unknown column `"spras"` on `"T016T"`

**DB:**
```
T016T columns: ['brsch', 'brtxt']
Motomarkt Stuttgart GmbH | Trading & Distribution | EUR | 6099225.00
```

**Successful contrasting SQL (2005 totals):**
```sql
SELECT k."waerk" AS currency,
       SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
FROM "VBRK" k
WHERE SUBSTRING(TRIM(k."fkdat"), 1, 4) = '2005'
GROUP BY k."waerk";
```
