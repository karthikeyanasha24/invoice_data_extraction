# Manual Stakeholder Test Checklist (AI Analysis)

Use the same database connection as production AI analysis.

## 1) Year + billing category + count
- Ask: `invoice count for year 1999 and billing category X`
- Verify SQL contains:
  - FKDAT year predicate for `1999`
  - `FKTYP = 'X'`
  - `COUNT(` metric (not sum-only)
- Verify response numbers match script output from:
  - `zodiac-api/scripts/verify_ai_analysis_stakeholder_scenarios.py --year 1999 --billing-category X`

## 2) Year + billing category + total value
- Ask: `total sales for year 1999 and billing category X`
- Verify SQL contains FKDAT year predicate + `FKTYP = 'X'` + `SUM(` metric.
- Verify API numbers match script output (within documented rounding tolerance).

## 3) Currency consistency
- Ask with explicit currency: `... in USD`
- Verify SQL contains `WAERK = 'USD'`.
- Verify chart axis/tooltip/table and narrative all show consistent USD formatting.
- If multiple currencies are returned, verify mixed-currency badge/disclaimer appears.

## 4) Repetition/stale answer guard
- Ask Q1 and Q2 consecutively with different filters (for example year/category changed).
- Verify generated SQL differs between Q1 and Q2.
- Verify numeric outputs differ when DB data differs.
- Verify no previous-turn table or chart is reused unless SQL and rowset are identical.

## 5) SQL/UI/chart alignment
- If SQL misses explicit requested filters, verify:
  - charts are suppressed
  - response states constraint mismatch clearly
  - no title claims un-applied filters
- For valid SQL, verify chart title includes applied SQL filter context and true query dimensions.

## 6) Negative revenue + industry combinations
- Ask:
  - `show negative billing lines for year 1999`
  - `lowest billing line amounts for year 1999 by industry`
- Verify line-item path uses `VBRP` with correct net amount behavior (`netwr < 0` where required).
- Verify output reflects actual rowset and does not fall back to generic unrelated industry aggregates.

## 7) Ambiguity / clarification
- Ask underspecified filter questions such as:
  - `invoice count for billing category`
  - `show billing type results` (without code)
- Verify assistant asks 1–3 short clarification questions before running SQL.

