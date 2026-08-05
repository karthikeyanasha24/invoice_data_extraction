# Phase 12 — First Customer Complete

**Date:** 2026-08-04  
**Constraint:** Additive only — no architecture redesign; SAT/V1/V2, Pipeline, Adapters, Monitoring, AI Ops, Customer Portal preserved.

---

## Goal

Honest client statement:

> The platform is deployed, customers have their own login, their own isolated portal, and we are ready to onboard the first customer.

---

## Gap checklist (before → after)

| Category | Gap | Resolution |
|----------|-----|------------|
| Customer onboarding | Workspace not auto-created | `POST /customers` now creates `workspace_settings` |
| Admin workflow | Fragmented enable step | Auto-create + Workspaces list still available |
| Customer users | Assign optional on create API | `customer_ids` accepted on create |
| Pipeline | Could enable without ERP/gov | API + Settings UI gate on prerequisites |
| Readiness | Advisory only | Progress %, wizard copy, customer-friendly portal labels |
| Customer user step | Not in checklist | `customer_user_assigned` required step |
| Placeholders | Quotations / Export Coming Soon | Production empty states; Quotations removed from sidebar |
| Security / UX | Admin shell flash | `MainLayout` renders spinner for portal users (no Sidebar) |
| Navigation | No Back to Workspaces | Added on workspace shell |
| Demo data | Empty Monitoring / AI | `scripts/seed_first_customer_demo.py` |
| Portal copy | Engineer keys / “APIs” | Softened Overview + Invoices |
| Adapter UX | Free-text country code | Dropdown `mx_cfdi` / `sample_gst` |

---

## Implemented changes

### Backend
- `app/api/customers.py` — auto workspace settings on create
- `app/api/customer_users.py` — optional `customer_ids` on create
- `app/core/workspace/onboarding.py` — progress, pipeline prerequisites, customer user step
- `app/api/workspace.py` — block `pipeline_enabled=true` until prerequisites; onboarding returns prereq fields
- `app/schemas/workspace.py` — response fields for prerequisites
- `app/tests/test_customer_onboarding.py` — updated + pipeline prereq test (**7 OK**)

### Frontend
- `MainLayout.tsx` — no admin chrome for customer users
- `customer-dashboard/page.tsx` — spinner-only redirect
- `Sidebar.tsx` — Quotations removed from nav
- `quotations/page.tsx`, `export/page.tsx` — production empty states
- `workspace/.../settings/page.tsx` — readiness wizard, pipeline lock, adapter select
- `customer/(portal)/overview/page.tsx` — business-friendly readiness
- `customer/(portal)/invoices/page.tsx` — softened copy
- `customer-users/page.tsx` — single create+assign API call
- `WorkspaceShell.tsx` — Back to Workspaces
- `lib/api.ts` — `customer_ids` on create

### Scripts / docs
- `scripts/seed_first_customer_demo.py`
- `docs/FIRST_CUSTOMER_USER_GUIDE.md`
- `docs/ADMIN_ONBOARDING_GUIDE.md`
- `docs/CLIENT_DEMO_SCRIPT.md`
- This log

---

## First-customer walkthrough (UI only)

### Admin
1. Login `/`
2. Customers → Add Customer → save (workspace settings created automatically)
3. Customer users → Create → select customer IDs → save
4. Workspaces → open customer → Settings
5. Configure ERP (base URL + secret refs), enable adapter, government endpoint
6. Enable Pipeline (unlocked when prerequisites met)
7. Confirm readiness wizard shows Ready
8. Logout

### Customer
1. Login `/customer/login`
2. Overview → Invoices → SAT → Monitoring → AI Ops → Settings → Logout

No SQL. No manual DB edits for onboarding.

---

## External deployment / configuration (not platform gaps)

These remain **environment** tasks — not missing product features:

| Item | Why external |
|------|----------------|
| Live ERP credentials / reachable ERP URL | Customer infrastructure |
| Live government / SAT credentials & endpoint | Tax authority / PAC |
| `ENABLE_PIPELINE_API=true` on API process | Ops env flag |
| DNS / TLS / production hosting | Infrastructure |
| Real vault secrets behind `vault:` / `env:` refs | Secrets management |
| Production Neon vs local DEV banner | Deploy target |

Sandbox demo uses `https://sandbox.example/...` and `env:DEMO_*` refs — clearly non-production.

---

## Remaining checklist

### Platform (customer-facing) — closed for first customer
- [x] Dedicated customer login
- [x] Isolated customer portal
- [x] Admin cannot use portal login; customers redirected from admin shell without flash
- [x] Create customer + workspace from UI
- [x] Create/assign portal user from UI
- [x] Configure ERP / gov / adapter / pipeline from Settings
- [x] Readiness wizard with progress
- [x] Pipeline enablement gated
- [x] No Coming Soon on customer-facing BridgeEDI path
- [x] Demo monitoring seed available

### External (before live production invoices)
- [ ] Customer sandbox/production ERP credentials
- [ ] Government / PAC endpoint + auth material
- [ ] Production `ENABLE_PIPELINE_API` and secret store
- [ ] Staging smoke of one real submission (optional before go-live)

---

## Verdict

**First-customer platform experience is complete for onboarding and portal isolation.**  
Live government/ERP submission depends on external credentials — clearly separated above.
