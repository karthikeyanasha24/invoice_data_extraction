# BridgeEDI Product Roadmap

**Owner:** Product / Technical Owner  
**Principle:** Prioritize **real customer value** and operational excellence — not engineering curiosity.  
**Constraint:** Architecture is stable. Prefer configuration, reliability, and second-customer readiness over new frameworks.

---

## Short term (0–3 months) — Pilot success

| Priority | Item | Customer value | Notes |
|----------|------|----------------|-------|
| P0 | Complete staging → limited production for pilot | They can run live | Checklist + success plan |
| P0 | Harden secrets, CORS, SECRET_KEY, migrations on prod | Trust & uptime | Ops, not features |
| P0 | Edge rate limit / WAF | Abuse protection | Infra |
| P0 | Support + ops handbooks adopted | Faster recovery | Already authored |
| P0 | Weekly CS feedback loop | Catch issues early | Success plan |
| P1 | Dashboard of pilot KPIs (success rate, gov/ERP fails) | Visibility | Use monitoring; light UI ok |
| P1 | Certificate expiry reminders for Mexico | Avoid outages | Process + light alert |
| P1 | Documented ERP/Gov sandbox→prod cutover run | Safe go-live | CS + DevOps |
| P2 | Optional PR4: monitoring soft-fail polish / basic CB | Stability under blips | Only if pilot pain |
| P2 | Clearer admin “go-live” wizard copy | Fewer config mistakes | UX polish only |

**Explicit non-goals (0–3 mo):** new country adapters, pipeline rewrite, AI remediations, replacing SAT.

---

## Medium term (3–12 months) — Scale to N customers

| Priority | Item | Customer value |
|----------|------|----------------|
| P0 | Second / third customer onboarding playbook (reuse workspace) | Faster time-to-value |
| P0 | Durable pipeline queue + workers + DLQ (when volume justifies) | Reliability at scale |
| P0 | Multi-instance safe status tracking for legacy SAT path | Correctness under HA |
| P1 | Country #2 only when **paid** specs + customer exist | Revenue, not demo GST |
| P1 | Stronger vault integration in customer environments | Enterprise security |
| P1 | Customer-facing status page / incident comms | Trust |
| P1 | Workspace-scoped Adaptive Query guard (additive) | Safer analytics |
| P2 | Self-serve onboarding for admins (guided) | Lower CS load |
| P2 | Automated regression suite in CI against staging | Maintainability |

**Gate:** Do not force all legacy traffic through pipeline. Dual-path remains valid.

---

## Long term (1–3 years) — Enterprise platform

| Priority | Item | Customer value |
|----------|------|----------------|
| P1 | Multi-region / residency options | Enterprise deals |
| P1 | Marketplace of certified country adapters | Expansion |
| P1 | Formal SLA packages + multi-tier support | Commercial maturity |
| P1 | Continuous compliance (SOC2-oriented controls) | Procurement |
| P2 | Optional gradual migration of selected flows onto shared pipeline | Consistency |
| P2 | Advanced AI Ops (still outside invoice mutate path) | Ops productivity |
| P2 | Partner / SI enablement kits | Channel scale |

**Still avoid:** big-bang rewrite of SAT/V1/V2; speculative countries without customers.

---

## Prioritization rubric

Score initiatives:

1. Reduces pilot/customer downtime or data risk  
2. Shortens onboarding time for next customer  
3. Required by a signed customer contract  
4. Improves operability (MTTR, clarity)  
5. Nice-to-have engineering elegance → **defer**

---

## Review cadence

| Cadence | Action |
|---------|--------|
| Monthly | Re-rank short-term with CS feedback |
| Quarterly | Update medium-term with pipeline volume reality |
| Annually | Long-term with GTM / geography strategy |

---

*Roadmap version: 1.0 · Conditional GO era*
