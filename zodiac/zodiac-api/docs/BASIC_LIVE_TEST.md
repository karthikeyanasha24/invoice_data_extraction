# Test Basic on the live AI Analyst

Use a new chat for each case at `https://www.bridgeedi.com/dashboard/ai`. Select **Basic**, then check the answer path badge, usage, returned rows, and **Executed SQL**. Do not treat the badge alone as proof of business correctness. Compare amounts within one currency and open **Billing documents** where offered; the document sum should reconcile to the selected amount.

| Question | Expected path | What to check |
| --- | --- | --- |
| Select **top 5 customers by billed sales in 2000** from **Questions → Verified saved questions** | Checked SQL replay; 0 model calls | SQL filters 2000; customer number and name are present; rankings are separate for each currency. |
| Ask **top 5 customers by billed sales in 2001** in a new chat | Basic SQL pattern or a separately checked 2001 query; never replay the 2000 SQL | SQL filters 2001; inspect names, currency, and invoice drilldown availability. |
| Select **compare billed sales in 2001 and 2002** | Basic SQL pattern; 0 model calls | Period A means 2001; period B means 2002; change is 2002 minus 2001. Compare each currency separately. |
| Ask **show me highest profit** | Must use an actual profit measure or revenue-minus-cost calculation | A `BSAD.dmbtr` sum labeled `total_sales` is not profit. This saved example is unsafe on the current live deployment and is excluded by the local fix pending deployment. |
| Ask a new question absent from saved questions and patterns | Basic model investigation or an explicit inability to answer | Model calls and token usage may be nonzero. A model-service error is a failure, not a verified answer. |

After a checked Agentic result, inspect its SQL, filters, grain, currency, and business definition before choosing **Reuse it in Basic Model**. Saving a question stores SQL for later reruns; it does not train model weights or automatically verify future outputs. The **How Basic works** button at the top explains the paths.

For customer names in this SAP extract, inspect the actual `VBRK.kunag → KNA1.kunnr` join and `KNA1.name1` field in the schema. External descriptions can suggest a mapping but cannot prove the field exists or that a query joins it correctly. Optional Basic Gemini terminology lookup is limited to an unfamiliar SAP field label after saved SQL and deterministic patterns miss. It sends only that label, validates suggestions against live metadata, and never supplies SQL or database evidence. It is disabled unless `BASIC_GEMINI_FIELD_LOOKUP=true` and a backend Google key is configured; when disabled or unavailable, checked examples and deterministic Basic paths continue to work. A successful provider request consumes Gemini quota and may be billed.
