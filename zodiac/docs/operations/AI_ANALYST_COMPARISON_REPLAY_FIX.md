# Order/invoice comparison and saved-query replay

The item-level comparison fix must be included in the backend deployment. It adds the documented VBAP/VBFA and VBFA/VBRP item relationships to manual SQL Training, retaining client/document/item keys. It does not disable grain or currency validation.

The SQL Training picker now submits `basicTrainingExampleId` and `basicTrainingRevision` along with the saved wording. The backend resolves that exact example from the authenticated user's workspace, checks its revision, executed status, wording and configured source, then reruns its SQL against current data. Prior chat filters are discarded for this explicit selection.

A stale or unavailable selection returns a clear error. A query that fails current validation remains a failed SQL replay; it does not automatically call Ollama or a paid Agentic provider. Ordinary new Basic questions retain their existing configured behavior.

For typed questions, an automatic memory copy of the identical SQL and source now retains its original SQL Training provenance. Provenance is not transferred to different SQL, another source or a planned/multi-query investigation.

Deploy the backend first, then the frontend from the same branch revision. The older frontend can still ask saved questions by wording; the new explicit-selection contract requires both deployments for the picker guarantee.

## Verification

- 283 backend tests passed across the comparison API, SQL Training, Basic replay/retrieval/local provider, Agentic, ranking, chart and SQL execution contract suites.
- Frontend TypeScript check passed; 74 UX/context/progress/presentation tests passed.
- Read-only checks against the configured extract passed for header pairs, raw item pairs, independently aggregated item pairs, originating-order header references, and preserved missing-item references.
- The existing saved 1999 comparison returned 200 current rows with zero model calls through both explicit saved-example replay and typed-question retrieval/replay.
- Item-flow queries may validly return zero rows when referenced source items or links are absent. Successful validation does not establish a price/quantity cause without those records.

Local browser testing also caught a numeric-looking sales-order number being classified as a monetary chart series. Document aliases now remain labels, while amount/value/count suffixes keep their measure roles. The regression fixture uses synthetic records. Typed and selected replay, currency switching, New Chat, schema selection retention and manual item queries have been exercised through the local browser with external model transports blocked.

A subsequent browser check also corrected SAP client aliases being formatted with decimal places in the verified table. Client codes and document identifiers stay verbatim; dates and amounts retain their existing formats. The presentation tests are included in `npm run test:ux`.

Reproduce the connected-data checks without sending records to a model:

```powershell
cd zodiac/zodiac-api
python scripts/verify_client_sql_workflows.py --user-email YOUR_STAFF_EMAIL --invoice INVOICE_ID --basic-replay
```

The generated `scripts/client_sql_workflows_live_results.json` is local and Git-ignored because it can contain business records. SQL regression fixtures use synthetic data. No production UI sign-off is claimed until the matching frontend/backend revisions have been deployed and retested.

## Real-provider Agentic verification, 22 October 2026

The configured provider passed a literal-only readiness probe. Real Agentic decisions were then exercised against an isolated, invented SQLite fixture using the normal relationship catalog, plan validator, SQL validator, read-only executor and answer renderer. The model response function was not mocked. Application/SAP records, chat history and connected schema snapshots were not sent to the provider; non-SQLite connections are blocked in the harness.

This uncovered another validator gap: planned quantity measures were treated as money, and a currency-guarded quantity/price diagnostic CASE was treated as an unsupported cross-source subtraction. The validator now distinguishes SAP quantity fields and accepts guarded net-unit-price differences, their quantity-weighted price effect and guarded textual observations. Complete client/document/item identities, displayed currencies, currency equality and independent grain proofs remain required. An unguarded expression or a product of two independent monetary values remains rejected. Provider tool schemas also declare the existing row-limit and column-filter bounds to avoid unnecessary retries.

The real-provider results were:

| Synthetic scenario | Verified behavior |
| --- | --- |
| Order 200 USD / 10 EA; invoice 100 USD / 5 EA | Agent repaired rejected SQL and returned net unit values of 20, quantity effect -100, price effect 0 and the lower-billed-quantity observation. |
| Referenced order item absent | Original order/item references remain visible, target fields are null and the missing evidence is explained. |
| Order in USD; invoice in EUR | Both currencies are displayed, the mismatch is explained and the numeric difference is null. |

These scenarios used 9, 12 and 5 model calls respectively. They establish these covered workflows, not a guarantee that every new question will finish within its budget. The missing-item case was close to the test's 12-call cap. The actual client's missing order-item records still require a fuller source extract before their precise quantity/price cause can be established.

Reproduce individual real-provider cases (these use configured API credits, with invented data only):

```powershell
python scripts/verify_agentic_synthetic_provider.py --case quantity
python scripts/verify_agentic_synthetic_provider.py --case missing
python scripts/verify_agentic_synthetic_provider.py --case currency
```

Each run checks returned fields against the fixture oracle and saves a Git-ignored `scripts/agentic_synthetic_*_live_results.json` report. The acceptance harness does not enable model transports on the locally running application/SAP-backed API. A separate regression also corrected inventory charts losing their quantity series after monetary-series filtering; quantities and money remain on separate axes/charts.

After the final changes, all three captured model-generated queries were revalidated and executed again against the synthetic fixture with exact row-oracle checks and zero additional model calls. The focused backend regression run passed 203 tests across Agentic, plan/grain/currency contracts, diagnostic expressions, SQL Training/Basic comparison execution, schema-backed comparisons, ranking, charts and public-research isolation. These changes require deployment before they apply to the live service.
