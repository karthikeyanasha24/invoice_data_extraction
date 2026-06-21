# Dashboard AI — Fix Summary

**Status: Verified locally and working** (tested live against `localhost:3000/dashboard` → `localhost:8000`, dev database).

## What was broken

1. **Generic "Real-time" replies.** The AI box answered every operational question with the same canned line — "Found N row(s) from the Zodiac operational database" — instead of an answer that referenced the actual data.
2. **Country + product comparisons failed.** Asking to compare inbound SAT documents vs. outbound invoices by country and product silently fell back to a meaningless `SELECT COUNT(*) FROM sat_documents` (a single number), instead of a real breakdown.

## Root causes found

1. The summary step never called the LLM to describe the rows — it always returned the static fallback string.
2. The SQL builder for inbound/outbound comparisons only supported a single dimension (e.g. country *or* supplier), not combinations like country *and* product.
3. **The real blocker:** the `products` column on `invoice_v2_business_data` is stored as plain `json` in the database, but the query code (and the schema notes feeding the AI) assumed it was `jsonb`. Combining a `json` column with a `jsonb` value in the same SQL expression caused Postgres to reject the query outright. That failure was silent to the user — the system just dropped down to the generic fallback path with no error shown.

## What was fixed

- The AI summary step now writes a real 2–4 sentence answer naming the actual countries, products, and amounts from the result set.
- The comparison query builder now supports any combination of country, product, document type, and supplier.
- The `products` column is now explicitly cast to the correct type before use, so the comparison query runs instead of failing.

## Verification performed

Queried the live local API directly (bypassing the UI) with: *"Compare inbound SAT documents vs outbound invoices by country and product."*

Confirmed in the raw response:
- `pipeline: "operational_inbound_vs_outbound_comparison"` — the real comparison logic ran, not a fallback.
- `rowCount: 8` — actual country/product breakdown rows returned.
- Sample data: Germany — product 2050000000249 — €20,492.40; France — multiple products; United States — CONCRETE — $75,000.00.
- Summary text named these countries, products, and amounts directly instead of a generic line.

## Known limitation to flag

Complex AI queries currently take roughly 1.5–4 minutes to return an answer end-to-end. This is a pre-existing latency characteristic of the multi-stage query pipeline, separate from the bugs above, and worth addressing if faster turnaround is needed.
