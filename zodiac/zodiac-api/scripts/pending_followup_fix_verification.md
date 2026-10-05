# Local follow-up context fix — 4 October 2026

The local application now distinguishes an unanswered analytical request from an executed result. A clarification reply can complete the former without requiring result rows. References selecting entities from an already-returned result still require verified evidence.

## Changes

- Persist the accumulated request and its outstanding clarification as `pending_analysis`.
- Ask the understanding model to identify the turn relationship and its context source, rather than matching the reported sentence.
- Pass the model's complete resolved request to SQL planning even when no prior SQL or result exists.
- Preserve pending intent through successive clarifications and model failures.
- Clear pending analytical filters, grain and schema on a new topic while keeping conversational history.
- Refuse missing or SQL-shaped rewrites and keep the pending request for retry.

No new production rule matches the reported years, invoice wording, customer names, or reply text. Tests intentionally include different periods, purchasing, warehouses, partial replies, and confirmations.

## Evidence

The combined backend regression run passed **136 tests**. The tests exercise API context routing, clarification continuation, conversation behavior, execution contracts and existing analysis regressions.

The configured real understanding model passed four additional local cases: the reported invoice/order choice, supplier grouping, warehouse ranking and accepting proposed defaults. See `pending_analysis_understanding_verification.json` for the recorded model results. These checks verify context understanding; they do not establish database correctness.

## Outstanding acceptance

Full SQL/database acceptance and deployed-browser verification are **not complete**. Automatic approval review rejected the full local pipeline test because it may send internal SAP schema and query-result evidence to configured OpenAI API and Google Gemini services. Approval for that specific transmission has been requested. No deployment was performed by this fix.

After approval, run `python -X utf8 scripts/verify_pending_analysis.py --phase pipeline`, inspect SQL and result verification, then replay the original conversation against the local and deployed application. Do not call the deployed issue fixed until that acceptance succeeds.
