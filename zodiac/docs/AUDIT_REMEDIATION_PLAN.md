# BridgeEDI — Audit Remediation Plan

**Status:** Planning only — **no production code changes in this document**  
**Input:** [`FINAL_ENTERPRISE_ARCHITECTURE_AUDIT.md`](FINAL_ENTERPRISE_ARCHITECTURE_AUDIT.md)  
**Companion:** [`IMPLEMENTATION_PR_PLAN.md`](IMPLEMENTATION_PR_PLAN.md)  
**Constraint:** Preserve additive architecture; never break SAT, V1, V2, Dashboard, current AI, Auth, or existing ERP/Government production paths.

---

## 1. Executive Summary

The audit verdict **CONDITIONAL GO (Pilot Only)** is upheld after re-verification against source. Six findings cluster into three remediation tracks:

| Track | Findings | Pilot gate? |
|-------|----------|-------------|
| **A — Mexico / ERP path clarity** | F2, F3 | **Yes** (policy + guard before enabling MX on pipeline) |
| **B — Secrets & ops safety** | F4, part of F6 | **Yes** for any real ERP/Gov credentials |
| **C — Platform evolution** | F1, F5, rest of F6 | **No** for pilot; post-pilot / never (F1 dual-world) |

**Key principle:** Finding 1 (legacy outside pipeline) and Finding 2 (Mexico submit→SAP) are largely **intentional** transitional / domain facts. They must be **governed and documented**, not “fixed” by forcing all traffic through the new pipeline or inventing a live SAT client.

**Do not redesign** Workspace, Pipeline stage plan, Adapter Framework, Government/ERP contracts, Monitoring, or AI Ops. Prefer flags, DI, thin adapters, and expand-only migrations.

---

## 2. Finding-by-Finding Analysis

---

### Finding 1 — Legacy SAT / V1 / V2 / SAP outside shared pipeline

#### Step 1 — Verification

| Result | **Confirmed** |
|--------|----------------|

**Evidence**

- `app/server.py` mounts invoices, invoices_v2, sat*, dashboard, adaptive_query **and** separately workspace/pipeline/monitoring/ai.
- Legacy processing: `app/services/process_service.py` + `app/services/status_tracker.py` — no call to `InvoicePipelineOrchestrator`.
- Pipeline is opt-in: `ENABLE_PIPELINE_API` default false (`app/api/pipeline.py`); workspace `pipeline_enabled` gate in resolve-workspace stage.

**Execution trace (legacy):** Client → `/api/v1/sat/*` or `/api/v1/invoices*` → process/SAT services → SAP client / DB.  
**Execution trace (enterprise):** Client → `/api/v1/pipeline/run` → orchestrator → adapter → … → monitoring.

#### Step 2 — Root cause

| Question | Answer |
|----------|--------|
| Why | Additive delivery strategy (Phases 2–10): do not rewrite production Mexico path |
| Design decision | Explicit dual-path / strangler pattern |
| Intentional? | **Yes** |
| Technical debt? | Transitional debt if dual-path never retired; acceptable for years |
| Acceptable for pilot? | **Yes** |
| Blocks production? | **No** — blocks only the claim “everything uses the shared pipeline” |

#### Step 3 — Architecture proposal

| | |
|--|--|
| **Current** | Two worlds: legacy SAT/V1/V2 and opt-in pipeline |
| **Desired** | Same dual-world for pilot; optional later “bridge” that emits monitoring facts from legacy without changing business logic |
| **Migration** | Never big-bang cutover. Future: (1) monitoring façade for SAT correlation IDs; (2) optional adapter-backed SAT; (3) retire only when metrics prove parity |
| **Rollback** | N/A for “no change”; any future bridge behind feature flag |
| **Risk** | Low if we stop overselling architecture; High if forced migration |
| **Complexity** | Low (governance); High (full migration) |
| **Backward compatibility** | Preserve legacy indefinitely until explicit program |

#### Recommendation

| Classification | **Do not “fix” before pilot** — treat as **Never change** for pilot scope |
|----------------|-------------------------------------------------------------------------------|
| Action | Product/architecture communication + checklist language; optional post-pilot monitoring bridge (separate initiative) |

---

### Finding 2 — `MxCfdiAdapter.submit()` calls `sap_api_client` (Government bypassed)

#### Step 1 — Verification

| Result | **Confirmed** |
|--------|----------------|

**Evidence**

- `app/adapters/mx_cfdi/adapter.py` → `submit()` imports `sap_api_client.sap_client` and calls `send_json_to_sap_with_session`.
- `get_government_connector()` defaults to `AlreadyStampedGovernmentConnector` but is **not invoked** from `submit`.
- Capabilities omit live government API (comments in adapter `__init__` / `capabilities`).
- Sample GST **does** use Government Connector: `app/adapters/sample_gst/connector.py` → `gov.submit`.

#### Step 2 — Root cause

| Question | Answer |
|----------|--------|
| Why | Mexico CFDI arrives **already stamped**; no PAC/SAT HTTP exists in repo |
| Design decision | Phase 7: do not invent SAT client; façade submit preserves SAP path |
| Intentional? | **Yes** (domain + Phase 7 contract) |
| Technical debt? | Naming/diagram debt (“submit” ≠ government) |
| Acceptable? | **Yes** for Mexico reality |
| Blocks production? | **No** for legacy SAT; **Yes** for misleading ops if pipeline MX enabled without docs |

#### Step 3 — Architecture proposal

| | |
|--|--|
| **Current** | MX: parse/validate/… → `submit` = SAP ERP egress; Gov port = AlreadyStamped unused on submit |
| **Desired** | Explicit semantics: (A) `submit` remains “authority/egress” for adapter; for MX that egress is ERP; (B) optional `acknowledge_stamp` via AlreadyStamped for audit; (C) `erp_update` reserved for **confirmation callback** to customer ERP when distinct from SAP send |
| **Migration** | Documentation + capability flags first; code only if dual-ERP (F3) needs a skip hook — see Finding 3 |
| **Rollback** | Keep current submit path as default forever for MX |
| **Risk** | Low if we don’t invent live SAT |
| **Complexity** | Low–Medium |
| **Backward compatibility** | Mandatory — no change to SAP send behavior |

#### Recommendation

| Classification | **Govern / clarify** — do **not** force Government Connector HTTP for Mexico |
|----------------|--------------------------------------------------------------------------------|
| Before pilot | Document + capability metadata; ensure ops runbooks say “MX submit = SAP” |
| Code change | Only as part of Finding 3 (skip/`erp_mode`) if needed — not a standalone rewrite |

---

### Finding 3 — Possible double ERP communication

#### Step 1 — Verification

| Result | **Confirmed** (conditional on workspace ERP config) |
|--------|-----------------------------------------------------|

**Evidence**

1. MX `submit` → SAP (`mx_cfdi/adapter.py`).  
2. Pipeline always schedules `erp_update` after confirmation (`stages.default_stage_plan` / `stage_update_erp`).  
3. `WorkspaceErpUpdater.update` (`core/erp/hooks.py`) pushes via `HttpErpConnector` when an **active** workspace ERP connection exists; otherwise raises `NotImplementedError` → stage **SKIPPED**.

So double contact occurs **iff** pilot enables pipeline for MX **and** configures workspace ERP connection (callback/base_url).

**Need runtime verification:** Staging dry-run with MX adapter + ERP connection on/off to capture whether confirmation payload triggers a second business-significant SAP/ERP write.

#### Step 2 — Root cause

| Question | Answer |
|----------|--------|
| Why | Stage plan always includes `erp_update`; MX historically folded ERP into `submit` |
| Design decision | Country-neutral stage plan vs Mexico façade convenience |
| Intentional? | Partially — stage plan intentional; dual write **unintentional side effect** |
| Technical debt? | **Yes** |
| Acceptable? | **No** for pilot with both paths live |
| Blocks production? | **Yes for MX pipeline pilot** until mitigated |

#### Step 3 — Architecture proposal

| | |
|--|--|
| **Current** | submit (MX→SAP) → confirmation → erp_update (HttpErpConnector if configured) |
| **Desired** | Single business ERP write per transaction, selected by policy |
| **Options (additive)** | **Option A (preferred):** Workspace / adapter flag `erp_update_mode`: `auto` \| `skip_if_submit_did_erp` \| `always` \| `never`. MX default `skip_if_submit_did_erp`. **Option B:** MX `receive_confirmation` marks metadata `erp_already_updated=true`; `stage_update_erp` or `WorkspaceErpUpdater` skips. **Option C:** Do not configure workspace ERP for MX pilot (ops-only) — weak, easy to misconfigure |
| **Migration** | Default preserves today’s SKIP when no ERP connection; when connection exists, new skip policy defaults for MX only via adapter metadata/capability — **no SAT route changes** |
| **Rollback** | Flag `erp_update_mode=always` restores current dual behavior |
| **Risk** | Medium (wrong skip = missing ERP ack) |
| **Complexity** | Medium |
| **Backward compatibility** | Legacy SAT untouched; pipeline dry-run unaffected |

#### Recommendation

| Classification | **Critical before MX pipeline pilot** |
|----------------|----------------------------------------|
| If pilot is SAT-only (pipeline off) | Can wait |
| If pilot enables `/pipeline` + MX | **Must fix** (Option A or B) |

---

### Finding 4 — Secret resolver validates but does not resolve

#### Step 1 — Verification

| Result | **Confirmed** |
|--------|----------------|

**Evidence**

- Validation: `app/core/workspace/context.py` — `is_valid_secret_ref`; schemas `app/schemas/workspace.py`.  
- Government: `LiteralSecretResolver.resolve` returns `None` for `vault:`/`env:` prefixes (`app/core/government/auth.py`).  
- ERP: `HttpErpConnector._auth_header` uses `extra_config.bearer_token` literal; docstring states refs not resolved (`app/core/erp/connector.py`).

#### Step 2 — Root cause

| Question | Answer |
|----------|--------|
| Why | Phase 6/7 deferred vault integration; tests use literals |
| Design decision | Store refs early; resolve later (Task 10.5) |
| Intentional? | **Yes** as interim |
| Technical debt? | **Yes** — P0 for real credentials |
| Acceptable for pilot? | Only with sandbox + no real secrets in DB |
| Blocks production? | **Yes** for production ERP/Gov credentials |

#### Step 3 — Architecture proposal

| | |
|--|--|
| **Current** | Refs stored; `LiteralSecretResolver`; ERP bearer from plaintext extra_config in tests |
| **Desired** | Shared `SecretResolver` protocol: `env:` → `os.environ`; `vault:` → pluggable backend; inject into `HttpGovernmentConnector` and `HttpErpConnector` via DI |
| **Migration** | 1) Implement EnvSecretResolver; 2) Wire factory defaults behind `SECRET_RESOLVER=env|literal`; 3) Vault adapter later; 4) Reject plaintext bearer in non-dev |
| **Rollback** | `SECRET_RESOLVER=literal` for local/dev |
| **Risk** | Medium (auth failures if misconfigured) |
| **Complexity** | Medium |
| **Backward compatibility** | Tests keep literal/extra_config under explicit env |

#### Recommendation

| Classification | **Critical before any non-sandbox connector use** |
|----------------|-----------------------------------------------------|

---

### Finding 5 — Adaptive Query AI separate from AI Ops

#### Step 1 — Verification

| Result | **Confirmed** |
|--------|----------------|

**Evidence**

- AI Ops: `app/core/ai/datasource.py` — monitoring only; APIs under `/api/v1/ai/*`.  
- Adaptive Query: `app/api/adaptive_query.py` — `get_current_user_optional`, schema/SQL over many tables, **no** `require_workspace_access`.  
- Pipeline `stage_ai_event` → `LoggingAiEventSink` only — does not feed AI Ops.

#### Step 2 — Root cause

| Question | Answer |
|----------|--------|
| Why | Pre-existing product AI vs Phase 9 operational AI |
| Design decision | “Do not modify existing AI” in Phase 9 |
| Intentional? | **Yes** |
| Technical debt? | Product/security boundary debt |
| Acceptable? | **Yes** if marketed as separate; **No** if conflated |
| Blocks pilot? | **No** for pipeline pilot |

#### Step 3 — Architecture proposal

| | |
|--|--|
| **Current** | Two AI products |
| **Desired** | Keep both; hard product naming; optional later wrapper: adaptive query requires auth + optional `workspace_id` filter (additive query param, default = legacy behavior) |
| **Migration** | Docs first; code wrapper only in post-pilot security program |
| **Rollback** | Omit workspace_id → legacy |
| **Risk** | High if adaptive query rewritten carelessly |
| **Complexity** | High for full scoping; Low for docs |
| **Backward compatibility** | Absolute requirement |

#### Recommendation

| Classification | **Do not change Adaptive Query before pilot** |
|----------------|------------------------------------------------|
| Action | Documentation + access control review (admin-only); optional post-pilot additive guard |

---

### Finding 6 — Production infrastructure gaps

#### Step 1 — Verification

| Component | Result | Evidence |
|-----------|--------|----------|
| Rate limiting | **Confirmed absent** | No middleware; comment in `supplier_tokens.py` |
| Circuit breakers | **Confirmed absent** | No implementation; docstring mention in `adapters/base.py` only |
| DLQ | **Confirmed absent** | ERP outbox ≠ DLQ; no pipeline dead-letter |
| Workers | **Confirmed absent** | No Celery/worker; in-process asyncio |
| Startup migrations | **Confirmed absent** | No lifespan in `server.py`; SQL manual per `migrations/README.md` |

#### Step 2 — Root cause

| Question | Answer |
|----------|--------|
| Why | Phase 10 documented gaps; Task 10.4/10.5 deferred |
| Intentional deferral? | **Yes** |
| Blocks pilot? | Partially — edge rate limit + migration discipline required; full workers/DLQ not required for single-pilot low volume |

#### Step 3 — Architecture proposal

| Sub-item | Desired (additive) | Pilot need |
|----------|-------------------|------------|
| Rate limiting | API gateway/WAF first; optional SlowAPI later | **Edge before public pilot** |
| Circuit breaker | Per-connector consecutive-failure trip in Gov/ERP HTTP clients | After pilot / with volume |
| DLQ + workers | Durable pipeline outbox + worker process (Task 10.4) | After pilot |
| Startup migrations | Readiness check: verify required tables exist (fail health); **do not** auto-migrate blindly in prod | **Yes** — check or runbook enforcement |

#### Recommendation

| Before pilot | Edge rate limit; apply migrations; readiness table check (optional small PR) |
| After pilot | Workers, DLQ, circuit breakers |
| Never in panic | Auto `DROP`/destructive migrations |

---

## 3. Implementation Order (Severity)

| Rank | Finding | Severity | Before pilot? | After pilot? | Never change? |
|------|---------|----------|---------------|--------------|---------------|
| 1 | F3 Double ERP | **Critical** | **Yes** if MX pipeline on | — | — |
| 2 | F4 Secret resolver | **Critical** | **Yes** if real credentials | Vault provider | — |
| 3 | F6 Migrations + edge rate limit | **High** | **Yes** (ops + edge) | App rate limit | — |
| 4 | F2 MX Gov “bypass” | **Medium** | Docs/capabilities | Optional stamp ack | Do **not** invent SAT HTTP |
| 5 | F6 CB / DLQ / workers | **Medium** | No (low volume) | **Yes** | — |
| 6 | F5 Adaptive Query | **Medium** | Docs + access review | Additive workspace guard | Do not rewrite agent |
| 7 | F1 Legacy outside pipeline | **Low** (as debt) | Communicate | Optional monitoring bridge | **Do not force cutover** |

### Pilot-safe posture (no code)

1. `ENABLE_PIPELINE_API=false` OR pipeline only for non-MX sample in staging.  
2. If MX pipeline: no workspace ERP connection **until** F3 fix ships — **or** ship F3 first.  
3. No production secrets in DB until F4 ships.  
4. Migrations applied manually; CORS locked; checklist signed.

---

## 4. Consolidated Remediation Table

| Finding | Evidence | Root cause | Impact | Recommended solution | Effort | Regression risk | Rollback |
|---------|----------|------------|--------|----------------------|--------|-----------------|----------|
| F1 | `server.py`, process_service, no orchestrator | Additive dual-path | Narrative only | Keep; document; optional later monitor bridge | S (docs) | None | N/A |
| F2 | `mx_cfdi.adapter.submit` | Already-stamped MX | Diagram mismatch | Document; capability; optional AlreadyStamped call for audit only | S–M | Low if audit-only | Flag off audit call |
| F3 | submit + `stage_update_erp` + WorkspaceErpUpdater | Stage plan vs MX façade | Duplicate ERP writes | Skip policy / metadata (Option A/B) | M | Medium | `erp_update_mode=always` |
| F4 | LiteralSecretResolver; ERP bearer literal | Deferred Task 10.5 | Cannot use vault safely | Shared SecretResolver + env impl + DI | M | Medium | `SECRET_RESOLVER=literal` |
| F5 | adaptive_query vs core/ai | Separate products | Confusion / data scope | Naming + admin policy; later additive guard | S then L | High if rewrite | Keep legacy default |
| F6 | Missing infra | Deferred Phase 10 | Scale/abuse/ops | Edge RL + migration readiness; later workers/DLQ/CB | S then L | Low (edge) / Med (workers) | Remove edge rules / disable workers |

---

## 5. Testing Strategy (for future implementation)

| Finding | Tests |
|---------|-------|
| F3 | Unit: MX metadata skip; Integration: one SAP mock call when skip on; Regression: sample_gst still erp_updates; SAT routes untouched |
| F4 | Unit: env resolver; Gov/ERP auth with `env:`; Reject unresolved in prod mode; existing literal tests behind flag |
| F6 readiness | Health fails or warns if `pipeline_timelines` missing when monitoring on |
| F1/F2/F5 | Doc + architecture tests only unless code chosen |

**Frozen regression suite (always):**  
`app/tests` enterprise discovery + MX parity + SAT-critical smoke in staging.

---

## 6. Production Impact Summary

| If we do nothing | Acceptable only for: legacy SAT pilot, pipeline off, no real vault secrets |
|------------------|------------------------------------------------------------------------------|
| Minimum to expand pilot to MX+pipeline | F3 + F4 + migrations + edge rate limit |
| Full multi-tenant GO | F3, F4, F6 workers/DLQ/CB, F5 access hardening, F1 monitoring bridge optional |

---

## 7. Dependencies Graph

```text
F4 SecretResolver ──► safe ERP/Gov pilot credentials
F3 ERP skip policy ──► safe MX pipeline + workspace ERP
F6 migrations ──► monitoring/outbox durability
F6 edge RL ──► public exposure
F2 docs ──► operator clarity (no code dep)
F5 docs ──► sales/security clarity
F1 ──► no code dep; program governance
F6 workers/DLQ ──► depends on pipeline volume (after F3/F4)
```

---

## 8. What Should Never Be Changed (Pilot Program)

1. Forcing all SAT/V1/V2 through shared pipeline.  
2. Inventing live Mexico SAT/PAC HTTP to “satisfy” the diagram.  
3. Rewriting Adaptive Query / `sap_sql_agent` core.  
4. Redesigning Workspace, Pipeline stage order, Monitoring, or AI Ops contracts.  
5. Breaking `/api/v1/sat/*` or invoice V1/V2 behavior.

---

## 9. Next Step

See [`IMPLEMENTATION_PR_PLAN.md`](IMPLEMENTATION_PR_PLAN.md) for PR slicing.  
**Do not implement until this plan and PR plan are approved.**
