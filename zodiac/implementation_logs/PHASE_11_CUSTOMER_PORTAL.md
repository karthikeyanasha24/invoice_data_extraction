# Phase 11 — Customer Login & Dedicated Customer Portal

**Date:** 2026-08-03  
**Goal:** Deliver Andy’s requirement — each customer gets a **separate login** and enters an **exclusive portal** with only their data.  
**Constraint:** Reuse enterprise Workspace / Monitoring / AI Ops APIs. No admin redesign. No new user tables.

---

## Architecture

```
Customer Portal (frontend route group)
  /customer/login          ← dedicated auth UX
  /customer/overview       ← workspace GET + activity + onboarding
  /customer/invoices       ← CustomerInvoicesDocumentsTab (existing)
  /customer/sat            ← CustomerSATDocumentsTab (existing)
  /customer/monitoring     ← monitoringApi.getSummary
  /customer/ai             ← aiOpsApi summary / recommendations / ask
  /customer/settings       ← read-only workspace GET (ERP + adapters)

Admin console (unchanged)
  /                        ← admin AuthForm
  /dashboard, /customers, /workspace/*, …
```

**Identity resolution (no workspace picker):**

```
Login (customer)
→ zodiac_users (JWT sub)
→ GET /api/v1/customer-users/me/customers
→ resolvePortalCustomerId(assigned)  // first sorted assigned id
→ all portal APIs scoped to that customer_id
```

If a user has multiple `user_customers` rows, the portal locks to the **alphabetically first** assignment (Andy’s model assumes one customer per portal user; admins should assign one).

---

## Authentication flow

1. Customer opens **`/customer/login`** (not `/`).
2. Same `POST /api/v1/user/auth/login` + `zodiac_users` password hash.
3. After login, portal verifies `is_customer_user && !is_admin`.
4. Non-customer accounts are logged out with an error (admins must use `/`).
5. JWT unchanged: `{ sub, exp }`; roles from DB on each request.
6. Session restore on `/customer/*` uses existing `AuthContext` + token.
7. 401 while on `/customer/*` redirects to `/customer/login` (not `/`).

Admin login at `/` still works. Customer users who somehow use `/` are redirected to `/customer/overview`.

---

## Routing

| Path | Purpose |
|------|---------|
| `/customer/login` | Dedicated customer login |
| `/customer` | Redirect → overview or login |
| `/customer/overview` | Exclusive overview |
| `/customer/invoices` | Invoices |
| `/customer/sat` | SAT / CFDI |
| `/customer/monitoring` | Monitoring |
| `/customer/ai` | AI Ops |
| `/customer/settings` | Read-only ERP / adapter / flags |
| `/customer-invoices` | Legacy → `/customer/invoices` |
| `/customer-sat-documents` | Legacy → `/customer/sat` |

**Not shown in portal:** Dashboard, Customers, Workspaces list, Admin settings, Global AI, Account mapping, Supplier tokens, Quotations.

---

## Security

| Control | Behavior |
|---------|----------|
| Portal layout | Rejects non–customer-users → `/` |
| MainLayout | Customer users bounced to `/customer/overview` |
| Workspace APIs | Existing `require_workspace_access` / `user_customers` |
| Cross-customer | Cannot call another `customer_id` successfully |
| Settings mutations | Still admin-only on API; portal is read-only |
| URL tampering | No customer_id in portal URL — resolved server-side from assignments |
| Admin pages | Inaccessible via MainLayout redirect |

---

## Screens

1. **Customer Login** — emerald-branded portal sign-in; link to admin `/`.  
2. **Overview** — readiness, flags, activity, adapters.  
3. **Invoices** — existing customer invoice tab.  
4. **SAT** — existing customer SAT tab.  
5. **Monitoring** — workspace summary cards/transactions.  
6. **AI Ops** — monitoring-backed summary + ask.  
7. **Settings** — read-only ERP + adapters + flags.  
8. **Logout** — clears session → `/customer/login`.

---

## APIs reused (no new business endpoints)

- `POST /api/v1/user/auth/login`
- `GET /api/v1/user/auth/fetch_user`
- `GET /api/v1/customer-users/me/customers`
- `GET /api/v1/workspace/{id}`
- `GET /api/v1/workspace/{id}/activity`
- `GET /api/v1/workspace/{id}/onboarding-status`
- `GET /api/v1/monitoring/workspaces/{id}/summary`
- `GET /api/v1/ai/workspace/{id}/summary|recommendations`
- `POST /api/v1/ai/workspace/{id}/ask`
- Existing invoices-v2 / SAT **for-customer-user** endpoints (via shared tabs)

**Migration:** none (reuse `zodiac_users`, `user_customers`, workspace tables).

---

## Key files

| File | Role |
|------|------|
| `src/app/customer/login/page.tsx` | Dedicated login |
| `src/app/customer/(portal)/layout.tsx` | Portal shell + provider |
| `src/app/customer/(portal)/*/page.tsx` | Portal screens |
| `src/contexts/CustomerPortalContext.tsx` | Resolve exclusive customer_id |
| `src/components/customer/CustomerPortalShell.tsx` | Portal nav (no admin menu) |
| `src/lib/customerPortal.ts` | Role + resolve helpers |
| `src/components/MainLayout.tsx` | Block customers from admin shell |
| `src/app/page.tsx` | Post-login redirect to portal |
| `src/lib/api.ts` | 401 → `/customer/login` when on portal |

---

## Regression analysis

| Area | Impact |
|------|--------|
| Admin `/` login | Unchanged |
| Admin dashboard / customers / workspace admin UI | Unchanged |
| Workspace APIs | Unchanged |
| Pipeline / ERP / adapters backend | Unchanged |
| Legacy `/customer-invoices` | Redirect only |
| Customer user provisioning | Still admin `/customer-users` |

---

## Manual QA checklist

1. Open `/customer/login` — see Customer Portal branding (not admin Zodiac signup).  
2. Login as admin (`puspesh`) on `/customer/login` → rejected / redirected away.  
3. Login as customer user (`test@gmail.com` or `dodandre8@gmail.com`) with their password → `/customer/overview`.  
4. Confirm nav: Overview, Invoices, SAT, Monitoring, AI Ops, Settings, Logout only.  
5. Confirm no Dashboard / Customers / Workspaces list.  
6. Overview APIs 200 for assigned customer only.  
7. Attempt `/dashboard` while logged in as customer → bounce to portal.  
8. Attempt `/workspace/OTHER_CUSTOMER` via admin shell → bounced; API still 404 if forced.  
9. Logout → `/customer/login`; token cleared.  
10. Admin still logs in at `/` → `/dashboard`.  
11. Hard refresh on `/customer/monitoring` — session persists.  
12. Settings shows ERP/adapters read-only (no save that mutates as customer).

### Demo credentials note

Use an existing `is_customer_user` account from admin **Customer users** (e.g. DB users `test` / `andix`). Passwords are whatever was set at creation — reset via admin if needed. Assign **one** `customer_id` for the cleanest Andy demo.

---

## Andy demonstration statement

A customer receives **`/customer/login`**, signs in with their own password, lands in the **Customer Portal**, sees **only their resolved workspace** (invoices, SAT, monitoring, AI Ops, read-only settings), and has **no visibility** into the admin Dashboard, customer list, or other tenants.
