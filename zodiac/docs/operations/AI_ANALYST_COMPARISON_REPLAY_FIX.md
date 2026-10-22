# Order/invoice comparison and saved-query replay

The item-level comparison fix must be included in the backend deployment. It adds the documented VBAP/VBFA and VBFA/VBRP item relationships to manual SQL Training, retaining client/document/item keys. It does not disable grain or currency validation.

The SQL Training picker now submits `basicTrainingExampleId` and `basicTrainingRevision` along with the saved wording. The backend resolves that exact example from the authenticated user's workspace, checks its revision, executed status, wording and configured source, then reruns its SQL against current data. Prior chat filters are discarded for this explicit selection.

A stale or unavailable selection returns a clear error. A query that fails current validation remains a failed SQL replay; it does not automatically call Ollama or a paid Agentic provider. Ordinary new Basic questions retain their existing configured behavior.

For typed questions, an automatic memory copy of the identical SQL and source now retains its original SQL Training provenance. Provenance is not transferred to different SQL, another source or a planned/multi-query investigation.

Deploy the backend first, then the frontend from the same branch revision. The older frontend can still ask saved questions by wording; the new explicit-selection contract requires both deployments for the picker guarantee.

## Verification

- 224 backend tests passed across the comparison API, SQL Training, Basic replay/retrieval/local provider, Agentic and SQL contract suites.
- Frontend TypeScript check passed; 64 UX/context tests passed.
- Read-only checks against the configured extract passed for header pairs, raw item pairs, independently aggregated item pairs, originating-order header references, and preserved missing-item references.
- The existing saved 1999 comparison returned 200 current rows with zero model calls through both explicit saved-example replay and typed-question retrieval/replay.
- Item-flow queries may validly return zero rows when referenced source items or links are absent. Successful validation does not establish a price/quantity cause without those records.

Reproduce the connected-data checks without sending records to a model:

```powershell
cd zodiac/zodiac-api
python scripts/verify_client_sql_workflows.py --user-email YOUR_STAFF_EMAIL --invoice INVOICE_ID --basic-replay
```

The generated `scripts/client_sql_workflows_live_results.json` is local and Git-ignored because it can contain business records. SQL regression fixtures use synthetic data. No production UI sign-off is claimed until the matching frontend/backend revisions have been deployed and retested.
