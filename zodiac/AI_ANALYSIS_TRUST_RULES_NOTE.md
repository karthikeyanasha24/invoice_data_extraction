# AI Analysis Trust Rules (SAP Billing)

## Date / Year rule
- Calendar/fiscal year for SAP billing is derived from `VBRK.fkdat` (`YYYYMMDD` text).
- SQL must use FKDAT-based year logic (for example `SUBSTRING(TRIM(r."fkdat"),1,4) = '1999'`).
- `gjahr` is not used for billing year filtering because this DB has unreliable `gjahr` values (`0000`).

## Currency rule
- Currency display is result-bound:
  - Prefer row currency (`waerk`/`waers`/`currency`) for chart tooltip/table formatting.
  - Do not default to `$`/USD when no currency code exists.
  - Mixed-currency result sets are labeled as mixed and avoid single-currency axis claims.

## Billing category and billing type mapping
- Billing category: `VBRK.FKTYP`
- Billing type: `VBRK.FKART`
- Deterministic and validated SQL paths enforce these predicates when requested in the question.
- If the question names billing category/type but does not provide a code, the assistant asks clarification questions before SQL execution.

## Repetition / stale answer elimination
- Reuse/follow-up actions are forced to fresh SQL execution for analysis queries.
- Similarity/memory SQL reuse is skipped when explicit constraints are present (year/category/type/currency/count intent).
- If generated SQL still does not satisfy explicit constraints after retries, the orchestrator returns a constraint failure response (no narrative/charts), rather than answering with mismatched data.

