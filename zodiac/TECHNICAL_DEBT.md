# BridgeEDI Technical Debt Register

**Rule:** Debt is tracked for risk management — not as a license to redesign the platform.  
**Sources:** Enterprise audit, PR0–PR2, production readiness, pilot ops.  
**Update:** After each incident or quarterly.

Legend — **Can wait?** Yes = safe for pilot if mitigated · No = block or mitigate before scale

---

## Active debt

### TD-01 — Dual processing worlds (legacy vs pipeline)

| | |
|--|--|
| **Debt** | V1/V2/SAT do not flow through shared pipeline/monitoring by default |
| **Reason** | Additive strategy; protect production Mexico path |
| **Risk** | Ops confusion; monitoring gaps on legacy path |
| **Priority** | P2 (communicate) / P1 if customers expect one timeline for all |
| **Recommended fix** | Document dual-path clearly; optional later “monitor bridge” for legacy — **do not force cutover** |
| **Can wait?** | **Yes** for pilot — treat as intentional |

---

### TD-02 — Mexico submit calls ERP inside adapter

| | |
|--|--|
| **Debt** | `mx_cfdi` submit may fulfill SAP; ideal diagram is Gov → Confirm → ERP |
| **Reason** | CFDI already stamped; historical SAP integration |
| **Risk** | Double ERP update if platform ERP also runs |
| **Priority** | P0 mitigated |
| **Recommended fix** | Keep `erp_update_mode=auto` (PR1); document in CS/ops |
| **Can wait?** | **Yes** if mode enforced for pilot |

---

### TD-03 — No durable pipeline DLQ / workers

| | |
|--|--|
| **Debt** | No Task 10.4-style durable queue + DLQ for pipeline |
| **Reason** | Deferred until volume justifies |
| **Risk** | Lost/stuck jobs under load or crash |
| **Priority** | P1 post-pilot |
| **Recommended fix** | Outbox + worker when second customer or volume rises |
| **Can wait?** | **Yes** for low-volume single pilot |

---

### TD-04 — In-memory V1 `status_tracker`

| | |
|--|--|
| **Debt** | Multi-instance incorrectness for legacy status |
| **Reason** | Historical design |
| **Risk** | Wrong status under horizontal scale |
| **Priority** | P1 before multi-instance SAT scale |
| **Recommended fix** | Externalize status store; do not rewrite pipeline to “fix” this |
| **Can wait?** | **Yes** if single-instance or sticky sessions for SAT |

---

### TD-05 — App-level rate limit / circuit breaker absent

| | |
|--|--|
| **Debt** | No in-app RL/CB (PR4 optional / edge expected) |
| **Reason** | Phase 10 accepted edge mitigation |
| **Risk** | Abuse, cascading ERP/gov calls |
| **Priority** | P0 ops (edge) · P2 app CB |
| **Recommended fix** | WAF/API gateway now; connector CB when pain appears |
| **Can wait?** | **Edge: No** · **App CB: Yes** for pilot |

---

### TD-06 — Manual migrations (no auto-migrate)

| | |
|--|--|
| **Debt** | SQL applied by ops; easy to forget |
| **Reason** | Expand-only safety; no surprise DDL |
| **Risk** | `/health/ready` 503; monitoring/ERP tables missing |
| **Priority** | P0 process |
| **Recommended fix** | Checklist + ready probe (done); CI check against staging |
| **Can wait?** | **No** — process must be followed every deploy |

---

### TD-07 — Adaptive Query / dashboard AI ≠ AI Ops

| | |
|--|--|
| **Debt** | Global AI surfaces not workspace-scoped like AI Ops |
| **Reason** | Pre-existing product; AI Ops added additively |
| **Risk** | Confusion; broader data exposure if mis-permissioned |
| **Priority** | P1 |
| **Recommended fix** | Access review; additive workspace guards — **do not rewrite agent** |
| **Can wait?** | **Yes** if admin-only and reviewed |

---

### TD-08 — Secret provider stubs (`arn:`, `kms:`, `ref:`)

| | |
|--|--|
| **Debt** | Schemes return PROVIDER_NOT_CONFIGURED until wired |
| **Reason** | PR2 shipped env + vault; cloud IAM later |
| **Risk** | Misconfig if customers use unwired schemes |
| **Priority** | P2 |
| **Recommended fix** | Wire when a customer requires that scheme; document allowed prefixes |
| **Can wait?** | **Yes** if pilot uses `env:` / `vault:` |

---

### TD-09 — Placeholder / weak local secrets in some envs

| | |
|--|--|
| **Debt** | Dev `.env` may use weak `SECRET_KEY`, empty `API_HASH_KEY` |
| **Reason** | Local convenience |
| **Risk** | Accidental promote to prod |
| **Priority** | P0 for production |
| **Recommended fix** | Deploy-time secret injection; checklist gate |
| **Can wait?** | **No** for any shared/staging/prod host |

---

### TD-10 — Soft-fail monitoring can hide DB issues

| | |
|--|--|
| **Debt** | Pipeline may succeed while metrics fail to persist |
| **Reason** | Prefer invoice success over metrics |
| **Risk** | Blind ops |
| **Priority** | P1 |
| **Recommended fix** | Alert on monitoring write error rate; RB-5 |
| **Can wait?** | **Yes** with daily monitoring review |

---

### TD-11 — sample_gst adapter in codebase

| | |
|--|--|
| **Debt** | Sample country adapter could be mistaken for production |
| **Reason** | Framework proof |
| **Risk** | Accidental enablement |
| **Priority** | P2 |
| **Recommended fix** | Policy: never enable for real customers; docs warn |
| **Can wait?** | **Yes** |

---

### TD-12 — Long JWT default expiry

| | |
|--|--|
| **Debt** | Long-lived tokens (~30d class defaults historically) |
| **Reason** | UX convenience |
| **Risk** | Stolen token window |
| **Priority** | P1 |
| **Recommended fix** | Tighten `ACCESS_TOKEN_EXPIRE_MINUTES` for prod |
| **Can wait?** | **Partially** — tighten for pilot prod |

---

## Cleared / mitigated (keep for history)

| ID | Item | Status |
|----|------|--------|
| TD-M1 | Double ERP without policy | Mitigated by PR1 `erp_update_mode` |
| TD-M2 | No central secret resolver | Mitigated by PR2 |
| TD-M3 | ERP ownership unclear | Mitigated by PR0 contract |
| TD-M4 | No onboarding readiness signal | Mitigated by onboarding-status |
| TD-M5 | No `/health/ready` | Mitigated by PR3 probe |

---

## How to add debt

1. One row per debt; link incident or audit ID.  
2. Prefer “Can wait? Yes + mitigation” over rushing redesign.  
3. Close only when risk is eliminated or accepted in writing by Tech Owner.

---

*Register version: 1.0*
