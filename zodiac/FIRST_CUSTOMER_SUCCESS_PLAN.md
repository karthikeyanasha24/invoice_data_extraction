# First Customer Success Plan

**Goal:** Make the pilot customer successful, confident, and referenceable — without expanding product scope.  
**Posture:** CONDITIONAL GO · single workspace  
**Owners:** Customer Success (primary) · Tech Owner · Support · DevOps  

Related: [`CUSTOMER_SUPPORT_GUIDE.md`](CUSTOMER_SUPPORT_GUIDE.md) · [`demo/first_customer/`](demo/first_customer/) · [`FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md`](FIRST_CUSTOMER_DEPLOYMENT_CHECKLIST.md)

---

## Success definition (pilot)

The customer can, repeatedly:

1. Authenticate and open **their** workspace only.  
2. Process invoices on the agreed path (SAT primary; pipeline only if enabled).  
3. See government/confirmation outcomes as designed for Mexico.  
4. Receive ERP confirmation or an agreed intentional skip (`erp_update_mode`).  
5. View monitoring for their invoices.  
6. Use AI Ops for operational questions (optional).  
7. Get support within SLA without architecture debates.

---

## Week 1 — Stabilize & trust

| Day | Activity | Exit criteria |
|-----|----------|---------------|
| 1 | Kickoff: roles, SLAs, escalation, dual-path explanation | Named contacts both sides |
| 1–2 | Staging validation record completed | Signed staging gate |
| 2 | Admin training: Workspaces, Settings, secret refs | Admin completes onboarding checklist |
| 3 | Sandbox invoice #1–3 end-to-end | correlation_ids recorded |
| 4 | Failure drill (gov or ERP sandbox down) + recovery | Customer sees recovery |
| 5 | Go / hold decision for limited prod cutover | Written decision |
| Ongoing | Daily health check (CS + Ops) | `/health/ready` green |

**CS touchpoints:** Daily Slack/email standup (15 min).

---

## Week 2 — Limited production

| Activity | Exit criteria |
|----------|---------------|
| Production URL cutover for gov/ERP (or phased) | Checklist items closed |
| First production invoice watched live | Success or documented incident & fix |
| Monitoring dashboard reviewed with customer | They can find a failed vs success case |
| Support ticket dry-run (fake Sev-3) | Response within SLA |
| Feedback session #1 (30 min) | Top 3 pain points logged → roadmap |

**Do not** enable pipeline in prod this week unless Week 1 dry-run was flawless and customer asks.

---

## Week 4 — Operating rhythm

| Activity | Exit criteria |
|----------|---------------|
| Weekly ops review (success rate, failures, MTTR) | KPI snapshot shared |
| Certificate / credential expiry calendar | Dates owned |
| AI Ops optional workshop (ops questions only) | Clear expectations |
| Feedback session #2 | Improvements prioritized (ops/UX only) |
| Confirm rollback still understood | Customer knows SAT escape hatch |

---

## Month 2 — Embed

| Activity | Exit criteria |
|----------|---------------|
| Reduce CS cadence to 2×/week unless Sev-2+ | Customer self-serves basics |
| Volume review vs capacity assumptions | No surprise scale risk |
| Secret rotation rehearsal | Documented |
| Optional: pipeline sandbox re-evaluation | Go/no-go written |
| Capture reference quote / case study draft | Marketing-ready notes (if happy) |

---

## Month 3 — Pilot exit / expand decision

| Activity | Exit criteria |
|----------|---------------|
| Formal QBR: KPIs, incidents, roadmap ask | Joint scorecard |
| Decision: continue pilot / expand volume / second country later | Written |
| Update TECHNICAL_DEBT.md with real pain | Ranked |
| Hand off to steady-state support | Success plan closed or renewed |

---

## Health checks (customer-facing cadence)

| Check | Frequency | Owner |
|-------|-----------|-------|
| API health / ready | Daily (ops) | DevOps |
| Onboarding still `ready` | Weekly | CS |
| Failed invoice sample review | Weekly | CS + Ops |
| Cert / token expiry | Monthly | Support |
| Access review (users) | Monthly | Customer admin + CS |

---

## Success metrics & KPIs

| KPI | Pilot target | Measure |
|-----|--------------|---------|
| Invoice success rate | ≥ 98% of processable invoices (agree definition) | Monitoring + legacy stats |
| Time to first production success | ≤ 14 days from kickoff | Calendar |
| Sev-1 incidents | 0 | Incident log |
| Sev-2 MTTR | ≤ 4 business hours | Incident log |
| Config-related tickets | Declining after Week 2 | Support tags |
| Customer NPS / sat score | ≥ 8/10 at Month 3 | Survey |
| Onboarding readiness regressions | 0 unexplained | onboarding-status |
| Cross-tenant issues | 0 | Security log |

---

## Feedback sessions

| Session | When | Agenda |
|---------|------|--------|
| #1 | End Week 2 | Friction, training gaps |
| #2 | End Week 4 | Reliability, UX of workspace |
| QBR | Month 3 | KPIs, commercial next steps |

**Rules for feedback:** Log as ops/UX/process first. Architecture redesign requests → acknowledge and park on roadmap only if customer-value scored.

---

## Improvements policy (pilot)

Allowed without “new platform work”:

- Copy/clarity in Settings  
- Runbook tweaks  
- Flag defaults  
- Training materials  
- Monitoring alert thresholds  

Requires Tech Owner + change control:

- Connector behavior changes  
- Pipeline enablement in production  
- New adapters / countries  

---

## RACI (pilot)

| Activity | CS | Support | DevOps | Eng | Tech Owner |
|----------|----|---------|--------|-----|------------|
| Training | A | C | I | I | C |
| Incidents Sev-1/2 | C | R | R | C | A |
| Config changes | C | C | R | I | A |
| Go-live decision | C | I | C | C | A |
| Roadmap intake | R | C | I | C | A |

R = Responsible · A = Accountable · C = Consulted · I = Informed

---

*Success plan version: 1.0*
