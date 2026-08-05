# BridgeEDI — Client Demo Script

**Speaker:** Andy  
**Length:** ~40 minutes  
**Rule:** Business language. No architecture lecture. No SQL.

---

## Before the meeting (15 minutes)

1. Warm the app (admin login + Workspaces + customer portal once)
2. Prefer a prepared customer (e.g. seeded `DE875243162` or `DEMO_PILOT_MX`)
3. Ensure Monitoring has at least one completed and one failed timeline (`seed_first_customer_demo.py --seed-monitoring-only`)
4. Portal user ready: `demo.portal@bridgeedi.local` / known password → assigned to that customer only
5. Never open Quotations

---

## Opening (90 seconds)

> “BridgeEDI sits between your ERP and the tax authority.  
> We configure your company once. Your team gets a private login and only sees your data.  
> I’ll show how we onboard you, then what your users see every day.”

---

## Act 1 — Admin onboarding (12 minutes)

### Login `/`
> “Operator console — only our team.”

### Customers → Add Customer (or show existing)
> “We create your company record. The workspace is created automatically.”

### Customer users → Create + assign
> “Your people get accounts here. Assignment is the isolation boundary.”

### Workspaces → Settings
Show readiness wizard progress.

> “ERP connection, country rules, government endpoint — all configured here. No database work.”

Configure or show already configured sandbox values.

### Enable Pipeline (if prerequisites met)
> “We only turn the automated bridge on when the required connections are ready.”

### Monitoring + AI Ops (admin workspace tabs)
> “Here’s a successful run and a failure — stage, timing, and what went wrong.  
> AI explains monitoring facts. It does not send invoices.”

Logout.

---

## Act 2 — Customer portal (15 minutes)

### `/customer/login`
> “Separate door for your organization.”

Login as portal user.

### Overview
> “Only your company. Readiness and status at a glance.”

### Invoices
> “Your invoice list.”

### SAT
> “Tax documents for Mexico.”

### Monitoring
> “Same operational truth your ops team cares about — scoped to you.”

### AI Ops
> “Ask about failures or latency. AI cannot submit invoices.”

### Settings
> “Transparent, read-only. Changes go through BridgeEDI so production wiring stays safe.”

### Logout
Confirm return to `/customer/login`.

---

## Act 3 — Value close (5 minutes)

> “What you saw: dedicated login, isolation, configurable ERP and government connections, controlled pipeline enablement, monitoring, and AI that observes — it doesn’t send.  
> To go live we wire your real ERP and government credentials into those same Settings fields.”

---

## Likely questions (short answers)

| Question | Answer |
|----------|--------|
| Another customer see our data? | No — portal users only see assigned companies. |
| Oracle instead of SAP? | Same ERP connection model (HTTP + auth). We configure your endpoint. |
| Add another country? | Enable another country adapter on the workspace. |
| AI send invoices? | No. |
| Government down? | Failure recorded; transport retries for transient errors; visible in Monitoring. |
| How do we know something failed? | Monitoring FAILED / RETRYING; AI can summarize. |

---

## Do not show

- Quotations  
- Empty Monitoring (seed first)  
- Engineer missing-key dumps (portal Overview is softened)  
- Live claims of government acceptance without sandbox honesty  

---

## Success criteria for the meeting

- Customer understands separate login + isolation  
- Customer sees configured Settings path without SQL  
- Customer sees Monitoring with real sample transactions  
- Clear next step: provide ERP + government credentials for go-live  
