# AI Analyst — how it is built, and how each part spends fewer tokens

Date: 12 October 2026. This describes the local code. It is not a production release note, and it does not claim the live site already has these changes.

## What the client reported

A year-over-year result showed billed sales of about **4,630,639 for 2001**. Asking for the related billing documents did not return the invoices that add up to that cell. The screen was mostly right, but not exact, and each extra question was expensive.

A local run of the same kind of question previously showed **DEM 4,630,839.02 for 2001** on SAP client 800 (550 documents in 2000, 537 in 2001). That is the same kind of row, not proof that 4,630,639 and 4,630,839.02 are the same stored total. This turn did not re-query the SAP database, so that figure is still not reproduced from scratch. What changed is the path that must be used to find the invoices: the selected row, not a new guess by the model.

## Correct behaviour for that row

1. The total stays tied to its year, currency, SAP client, and the filters in the original SQL.
2. “Show the related billing documents” does not start a new investigation.
3. If several currencies share that year, the product asks which row. It does not pick one because the amount looks familiar.
4. Naming the currency removes the doubt. “Related billing documents for 2001 DEM” selects the 2001 amount on the DEM row.
5. The database lists only billing documents whose contribution to that amount is not zero. A 2000 invoice, another currency, or another SAP client stays out.
6. The page shows the original total, the sum of those documents, the difference, and the document count. A difference is a mismatch, not a new answer.
7. That read uses **no model tokens**.

Charts may still abbreviate an axis label (for example `4.6M`). The table and the billing-document panel keep the exact decimal string. Abbreviation is a label, not a second total.

## How a question moves through the product

```text
Browser (TypeScript / Next.js)
    → POST /api/query/adaptive          Python / FastAPI
        → if this is a follow-up on a saved result: database only, 0 model calls
        → otherwise: analyst agent
            → OpenAI Responses API interprets the question and may write SQL
            → Python checks the SQL, runs it read-only, and stops when the result fits
    → the answer, rows, and an opaque result id go back to the browser
    → “Billing documents” calls POST /api/query/adaptive/results/{id}/documents
        → Python rebuilds the invoice query from the saved SQL and reconciles the sum
```

Languages:

| Layer | Language | Where it runs |
| --- | --- | --- |
| Screens, charts, number display | TypeScript, React, Next.js | `zodiac-front` |
| HTTP API, agent, SQL guards, reconciliation | Python, FastAPI, SQLAlchemy, sqlglot | `zodiac-api` |
| Saved totals and invoice lists | SQL, PostgreSQL dialect | business database or SAP extract |
| Question interpretation, when still required | OpenAI Responses API | provider; not used for drill-down |

## Each part, the file that owns it, and the token effect

### 1. Ask a question

`zodiac-front/src/components/DashboardAIAnalysis.tsx` (TypeScript) sends the question and the previous result reference. It does not rebuild SQL in the browser.

`zodiac-api/app/api/adaptive_query.py` (Python) is the entry point.

**Tokens:** a follow-up that only wants the SQL, or the invoices behind a saved row, returns before `run_analyst_agent`. Those answers record `llm_calls: 0`.

### 2. Decide who may see which SAP customer

`zodiac-api/app/services/adaptive_trusted_scope.py` (Python).

An administrator can analyse the connected extract. A customer user is limited to explicit SAP client and customer pairs from `AI_ANALYST_SAP_CUSTOMER_MAP`. If that map is missing or does not name their assigned customer, the query is denied. An empty assignment is not treated as “see everything”.

`zodiac-api/app/services/analyst_agent_sql.py` (Python) pushes that limit into the SQL, including queries hidden inside `WITH` and `UNION`. The same guard is used for the agent and for pasted `overrideSql`.

**Tokens:** a denied query never reaches the model loop. This is an access control, not a discount. It stops a restricted user from spending a long investigation on data they must not see.

### 3. Interpret a new question

`zodiac-api/app/services/analyst_agent.py` (Python) runs the tool loop.

The model may inspect schema and write SQL. When a query already satisfies the question, Python returns “Verified database result: N rows” immediately. It does not ask the model to narrate the table again. Instructions also say not to repeat `list_tables`, `search_schema`, or `describe_tables` after those tools have already run in the same conversation.

**Tokens:** this removes the extra narration call and repeated schema calls. A hard question can still use several model calls. The old loop allowed 14 decision turns; the current dispatch limit defaults to **10 model calls** per investigation (`AI_ANALYST_MAX_MODEL_CALLS`).

### 4. Check filters and relationships before trusting SQL

`zodiac-api/app/services/analyst_filters.py` (Python) checks declared filters as field, operator, and value. A plan that says currency is USD is rejected if the executed SQL drops that test or hides it behind `OR 1=1`.

`zodiac-api/app/services/agent_query_contract.py` (Python) refuses to pick the first of two equally short relationships when they mean different things. The agent must use the business role instead of a silent join.

`zodiac-api/app/services/analyst_evidence.py` (Python) prints each returned customer next to that customer’s amount. A sentence cannot attach Customer A’s name to Customer B’s number just because both numbers appeared.

**Tokens:** these checks avoid a repair loop. A rejected query used to cause another model call to “try again”. Failing closed in Python spends no extra tokens.

### 5. Save the result that the user is looking at

`zodiac-api/app/services/analyst_drilldown.py` (Python), function `capture_result`.

On a successful query, Python stores the SQL, the displayed rows, the schema, and which amounts can be opened. The browser receives only an id (`result_reference`). The row values are not pasted back into the next prompt in order to reconstruct the invoice list.

The store is table `ai_analyst_results`. A row expires after 7 days and can be read only by the same user with the same permission digest.

**Tokens:** the next “show the invoices” turn does not resend the full result into the model.

### 6. Open the invoices for one cell

Same file: `compile_selection`, `page_sql`, `reconcile`.

HTTP: `POST /api/query/adaptive/results/{result_id}/documents` in `adaptive_query.py`.

Screen: `zodiac-front/src/components/ai/AnalystDrilldown.tsx` (TypeScript). The chart click uses `matchingResultRow` in `zodiac-front/src/lib/analystNumbers.ts` so the selected point becomes a row index, not a search by the rounded amount.

What the compiler does:

- Accepts only a `SUM` of billed `netwr` from `VBRK` or `VBRP`.
- A year-over-year amount is usually `SUM(CASE WHEN the year is 2001 THEN netwr ELSE 0 END)`. The year test stays inside that expression. The date column is not mistaken for the money column.
- Every grouped value on the selected row (SAP client, currency, customer, country, and so on) is added back as a filter.
- Documents whose contribution is zero are left out, so a 2000 invoice does not appear in the 2001 list.
- The full sum is calculated in SQL across every matching document, not by adding the 50 rows on the screen.
- The next page must match the same snapshot digest. If the underlying rows changed, the request stops and says so.

**Tokens:** zero. The panel copy says “no AI tokens”. `meta.model_tokens` is 0 and `meta.deterministic` is true.

### 7. Show money the same way everywhere

`zodiac-front/src/lib/analystNumbers.ts` (TypeScript). `analystDecimal` formats a canonical decimal string with grouping commas. It does not guess whether `1.234,56` means one point two or one thousand. Chart axis shortening lives in `zodiac-front/src/lib/analystChartLayout.ts` and is only for the axis.

**Tokens:** formatting does not call a model. It also avoids a follow-up whose only job is “why does the chart not match the table?”

### 8. Count what a real answer costs

`zodiac-api/app/services/analyst_usage.py` (Python).

Each model response stores input tokens, output tokens, cached input tokens, reasoning tokens, the model name, and elapsed milliseconds. Cost is computed only when `AI_ANALYST_PRICING_JSON` has a versioned price for that model, in USD per million tokens. If the provider omits usage, further model calls in that investigation stop.

Optional caps:

| Setting | Default | Effect |
| --- | --- | --- |
| `AI_ANALYST_MAX_MODEL_CALLS` | 10 | Stops the loop |
| `AI_ANALYST_MAX_TOTAL_TOKENS` | 120000 | Stops when the running total leaves no room for another answer |
| `AI_ANALYST_MAX_OUTPUT_TOKENS` | 8000 | Caps one reply |
| `AI_ANALYST_MAX_REQUEST_USD` | unset | If set, the next call is refused when the estimate would pass the cap |
| `AI_ANALYST_PRICING_JSON` | unset | Without it, usage is counted and dollar cost is left blank |

**Tokens:** this does not shrink a single prompt by itself. It makes the spend visible and stops a runaway loop. Drill-down, reconciliation, and “show the SQL” never enter this counter.

## What the tests proved

`zodiac-api/tests/test_analyst_reliability_upgrade.py`: **14 passed** on 12 October 2026.

Covered with synthetic rows, not the live SAP extract:

- A 2001 USD total keeps the year, customer, client, and currency, and the document sum matches to the cent, including a negative invoice. Model calls stay at 0.
- A year-split total for DEM `sales_2001` returns only the 2001 DEM document on that SAP client. The 2000 DEM document, the 2001 EUR document, and the other SAP client are excluded.
- “Related billing documents for 2001” with both DEM and EUR is rejected as ambiguous. Adding DEM selects the 2001 measure on the DEM row.
- A changed page snapshot is not reported as success.
- Another user, or the same user after a permission change, cannot open the saved result.
- Customer scope is not escaped with `OR`, `UNION`, or a join.
- A missing customer map denies access.
- A declared USD filter must actually be in the SQL.
- Two different relationships are not silently collapsed.
- Swapped customer amounts stay paired in the grounded answer.
- Cached and reasoning tokens are counted once, and a token cap stops the next call.

## What is still not proven

- The stored total **4,630,639** was not queried again from SAP in this turn. Use the billing-document control on that exact row; the difference line is the check.
- Dollar cost stays blank until `AI_ANALYST_PRICING_JSON` is set for the model in use.
- This is local code. The public site is unchanged until these files are deployed.
- A local Llama, Mistral, Qwen, or Gemma model would change the invoice for interpretation. It would not repair a join, a dropped currency, or a chart cell. Those are the Python and SQL controls above. A local model is a later cost test, after the same accuracy checks pass on identical questions.
