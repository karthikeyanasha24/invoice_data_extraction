# BridgeEDI — Implementation PR Plan (Post-Audit)

**Status:** Planning only — **await approval before any production code**  
**Parent:** [`AUDIT_REMEDIATION_PLAN.md`](AUDIT_REMEDIATION_PLAN.md)  
**Rules:** Additive only · No redesign of frozen components · Do not break SAT / V1 / V2 / Dashboard / Adaptive AI / Auth

PRs are ordered for **pilot safety**. Later PRs must not be required to keep legacy Mexico SAT in production.

---

## Program overview

| PR | Theme | Findings | Pilot required? |
|----|-------|----------|-----------------|
| **PR1** | Governance & MX ERP dual-write guard | F2 (docs/capabilities), F3 | **Yes** if MX+pipeline |
| **PR2** | Shared secret resolution (env) | F4 | **Yes** if real connector creds |
| **PR3** | Readiness / migration safety | F6 (partial) | **Yes** (ops safety) |
| **PR4** | Resilience foundations (opt-in) | F6 CB stubs, emit soft-fail; **not** full workers | After pilot OK |

**Out of PR scope (by design):**

| Item | Finding | Why |
|------|---------|-----|
| Migrate SAT/V1/V2 into pipeline | F1 | Never for this program |
| Live Mexico SAT/PAC client | F2 | Never invent |
| Adaptive Query rewrite / workspace SQL agent | F5 | Separate security program |
| Full worker fleet + DLQ | F6 | Post-pilot initiative (future PR5+) |
| Edge/WAF rate limiting | F6 | Infra ticket, not app PR |

---

## PR1 — Mexico pipeline ERP policy (prevent double write)

### Purpose

Ensure a single business ERP write when MX adapter already sent to SAP in `submit`, while keeping the country-neutral stage plan and leaving SAT routes untouched.

### Findings addressed

- F3 (Critical)  
- F2 (clarify via adapter capability / metadata only — no Gov HTTP)

### Approach (Recommendation — not yet coded)

**Verified today:** `WorkspaceErpUpdater` skips when no ERP connection; dual write when connection exists + MX submit→SAP.

**Recommended design:**

1. MX `submit` / `receive_confirmation` sets adapter context metadata, e.g. `erp_fulfilled_in_submit=True` (or confirmation field).  
2. `WorkspaceErpUpdater.update` (or thin check in `stage_update_erp`) skips with clear reason when metadata says ERP already fulfilled **and** workspace/adapter policy is `skip_if_submit_did_erp` (MX default).  
3. Document in adapter docstring + ops runbook: MX submit target = SAP.

**Assumption:** Confirmation shape from MX can carry a stable flag without breaking SAP response consumers — needs fixture check in implementation.

### Files (expected)

| File | Change type |
|------|-------------|
| `app/adapters/mx_cfdi/adapter.py` | Set metadata / confirmation marker after successful SAP submit |
| `app/core/erp/hooks.py` | Honor skip policy (DI-safe) |
| `app/core/pipeline/stages.py` | Optional: pass-through only if needed — **prefer ERP hook** to avoid stage redesign |
| `app/models/workspace.py` or workspace `flags` JSON | Optional `erp_update_mode` — prefer flags JSON to avoid migration |
| `GOVERNMENT_CONNECTOR_CONTRACT.md` / short `docs/operations` note | Diagram clarification for MX |
| `app/tests/test_mx_pipeline_erp_skip.py` (new) | Unit/integration |
| `app/tests/test_erp_connector.py` | Regression: non-MX still pushes |

### Migration

None preferred (use `workspace_settings.flags` or adapter-constant default).  
If a column is insisted upon → expand-only nullable text — avoid.

### Testing

- [ ] MX + ERP connection configured → `erp_update` SKIPPED (or no second HTTP)  
- [ ] MX + no ERP connection → still SKIPPED as today  
- [ ] sample_gst + ERP connection → still pushes via HttpErpConnector  
- [ ] `test_mx_cfdi_adapter_parity` green  
- [ ] SAT API smoke unchanged (no file overlap ideally)

### Rollback

- Feature flag / workspace flag `erp_update_mode=always`  
- Or revert PR; SAT unaffected

### Regression risk

**Medium** — wrong skip could drop required callback to a secondary ERP system. Mitigate with explicit opt-in `always` for customers who need submit SAP + separate confirmation webhook.

### Estimated effort

2–4 days

---

## PR2 — SecretResolver (env) for ERP + Government

### Purpose

Resolve `env:` (and keep `vault:` pluggable) so workspace secret refs become usable without storing plaintext bearer tokens in `extra_config`.

### Findings addressed

- F4 (Critical for real credentials)

### Approach (Recommendation)

1. Introduce shared resolver module usable by both packages, e.g. `app/core/secrets/resolver.py` (or extend government `SecretResolver` and import from ERP — **one protocol**).  
2. Implementations: `LiteralSecretResolver` (dev), `EnvSecretResolver` (`env:NAME` → `os.environ`).  
3. Inject into `HttpGovernmentConnector` factory and `HttpErpConnector` (resolve `client_secret_ref` / auth refs).  
4. Env `SECRET_RESOLVER=literal|env` (default `env` in prod docs; `literal` in tests).  
5. Do **not** remove test `extra_config.bearer_token` escape when `SECRET_RESOLVER=literal` or `APP_ENV=test`.

### Files (expected)

| File | Change type |
|------|-------------|
| `app/core/secrets/` (new) or `government/auth.py` + ERP import | Protocol + Env resolver |
| `app/core/government/factory.py` / `connector.py` | Inject resolver |
| `app/core/erp/connector.py` | Resolve refs for auth headers |
| `app/core/erp/hooks.py` | Pass resolver if needed |
| `app/tests/test_secret_resolver.py` (new) | Unit |
| `app/tests/test_government_connector.py` | Auth with env: |
| `app/tests/test_erp_connector.py` | Auth with env: |
| `docs/operations/CONFIGURATION_GUIDE.md` | Document |

### Migration

None.

### Testing

- [ ] `env:MY_TOKEN` resolves when set  
- [ ] `vault:` remains unresolved until vault backend (explicit None + log)  
- [ ] Existing mock/literal tests pass with `SECRET_RESOLVER=literal`  
- [ ] No plaintext required in workspace schema

### Rollback

`SECRET_RESOLVER=literal` + prior image.

### Regression risk

**Medium** — misconfigured env names → auth failures on connectors only (SAT path unused).

### Estimated effort

3–5 days

---

## PR3 — Startup readiness check for enterprise tables

### Purpose

Fail loudly (or degrade health) when Phase 2/6/8 tables are missing, instead of silent monitoring/outbox soft-fail.

### Findings addressed

- F6 (High — migrations portion)

### Approach (Recommendation)

1. Add `GET /health/ready` (or extend `/health`) that checks `to_regclass` / SQLAlchemy inspect for:  
   `workspace_settings`, `erp_push_outbox`, `pipeline_timelines`, `pipeline_events` (and optionally metrics/alerts).  
2. **Do not** auto-run SQL migrations in production startup (avoid surprise DDL).  
3. Document: deploy pipeline must run migrations before flipping ready probe green.  
4. Optional: log warning once on API startup if tables missing (non-fatal for SAT).

### Files (expected)

| File | Change type |
|------|-------------|
| `app/server.py` or `app/api/health.py` (new) | Readiness endpoint |
| `app/database.py` | Helper `enterprise_tables_status()` |
| `app/tests/test_production_readiness.py` | Extend with mocked inspect |
| `docs/operations/MIGRATION_GUIDE.md` / `DEPLOYMENT_GUIDE.md` | Wire into deploy |

### Migration

Ops runs existing SQL files — no new DDL required for the check itself.

### Testing

- [ ] Ready → 200 when tables present  
- [ ] Ready → 503 when missing (if that contract chosen)  
- [ ] `/` liveness remains 200 for orchestrators that only need process up  
- [ ] SAT routes not impacted

### Rollback

Remove readiness route or make it informational (`?strict=false`).

### Regression risk

**Low** — additive endpoint; risk is over-strict probes blocking deploys before migrations (process issue, not SAT break).

### Estimated effort

1–2 days

---

## PR4 — Soft-fail monitoring emit + lightweight connector circuit breaker (opt-in)

### Purpose

Improve resilience without introducing workers/DLQ yet.

### Findings addressed

- F6 (Medium)  
- Audit note: `monitoring.emit` not soft-failed today

### Approach (Recommendation)

1. Wrap `stage_monitoring` / `stage_ai_event` emit calls so sink exceptions → stage success with warning meta (or SKIPPED), never fail the run.  
2. Optional consecutive-failure counter on `HttpGovernmentConnector` / `HttpErpConnector` behind `ENABLE_CONNECTOR_CIRCUIT_BREAKER=false` default.  
3. **Explicitly exclude** Celery/SQS worker and DLQ from this PR.

### Files (expected)

| File | Change type |
|------|-------------|
| `app/core/pipeline/stages.py` | Soft-fail emit |
| `app/core/government/connector.py` | Optional breaker |
| `app/core/erp/connector.py` | Optional breaker |
| `app/tests/test_pipeline_orchestrator.py` | Emit failure does not fail run |
| `app/tests/test_monitoring.py` | Regression |

### Migration

None.

### Testing

- [ ] Raising monitoring sink no longer fails pipeline  
- [ ] Breaker open → fail fast with stable error code when enabled  
- [ ] Default breaker off → identical to today  

### Rollback

Flags off / revert PR.

### Regression risk

**Low–Medium** (breaker mis-trip). Default off mitigates.

### Estimated effort

2–3 days

---

## Future PRs (not scheduled now)

| PR | Scope | Finding |
|----|-------|---------|
| PR5 | Durable pipeline outbox + worker + DLQ | F6 / Task 10.4 |
| PR6 | Vault/AWS secret backend | F4 extension |
| PR7 | Adaptive Query additive `workspace_id` guard (default legacy) | F5 |
| PR8 | Optional legacy SAT → monitoring event bridge (observe-only) | F1 |

---

## Cross-PR dependency order

```text
PR1 (ERP skip) ──────────────┐
PR2 (secrets) ───────────────┼──► safe MX pipeline pilot with real-ish creds
PR3 (readiness) ─────────────┘
         │
         ▼
PR4 (soft-fail / optional CB) ──► hardening
         │
         ▼
PR5+ workers/DLQ (post-pilot)
```

**Parallelizable:** PR1 ∥ PR2 ∥ PR3 after design approval.  
**PR4** after PR1 if both touch `stages.py` — otherwise parallel with care.

---

## Global regression checklist (every PR)

```bash
cd zodiac/zodiac-api
python -m unittest discover -s app/tests -p "test_*.py" -q
```

Staging smoke:

- [ ] Login / auth  
- [ ] SAT upload or known SAT health path  
- [ ] Invoice V1 or V2 read path  
- [ ] Dashboard load  
- [ ] Adaptive query smoke (admin)  
- [ ] Pipeline dry-run (if flag on)

---

## Approval gate

| Role | Approves |
|------|----------|
| Architecture | This PR split + “never change” list |
| Engineering | Effort / sequencing |
| Security | PR2 secret design |
| Ops | PR3 readiness contract |

**No production code until written approval of this plan.**
