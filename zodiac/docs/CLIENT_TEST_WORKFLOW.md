# BridgeEDI — Client Test Workflow

**Purpose:** Hand this to the client (or run yourself) to verify the first-customer experience after deploying the latest branch (`phase12-first-customer-ready` + contrast fix).

**Production note:** [bridgeedi.com](https://www.bridgeedi.com/customer-users) must be redeployed for these fixes to appear. Until then, test on staging/local with the latest code.

---

## What was built (so far)

| Area | What the client should see |
|------|----------------------------|
| Admin login | `/` — operator console |
| Customer portal login | `/customer/login` — separate door |
| Create customer | Workspace settings created automatically |
| Create customer user + assign | One form; customers readable (high contrast) |
| Workspace Settings | ERP, government, adapter, pipeline, readiness wizard |
| Pipeline gate | Cannot enable until ERP + adapter + government ready |
| Customer portal | Overview → Invoices → SAT → Monitoring → AI Ops → Settings → Logout |
| Isolation | Customer cannot stay on admin pages |
| Monitoring demo | Seed script can populate sample success/fail runs |

---

## Pre-test setup (internal)

1. Deploy frontend + API from `phase12-first-customer-ready` (plus latest contrast commit if separate).
2. Confirm API health.
3. Optional demo data:
   ```bash
   cd zodiac
   python scripts/seed_first_customer_demo.py --customer-id DE875243162 --seed-monitoring-only
   ```
4. Know credentials:
   - Admin: operator account
   - Customer: e.g. `demo.portal@bridgeedi.local` (portal password from seed/admin)

---

## A. Admin path (15–20 min)

| # | Step | Expected |
|---|------|----------|
| 1 | Open `/` and sign in as admin | Dashboard loads |
| 2 | Open **Customers** → **Add Customer** | Form readable; create succeeds |
| 3 | Open **Customer users** → **Create customer user** | Modal: dark text on white; customer IDs readable; Cancel readable; Close (X) visible |
| 4 | Assign one customer ID → **Create** | User appears in list with assignment |
| 5 | **Edit customers** on that user | Same contrast; Save works |
| 6 | Open **Workspaces** → customer → **Settings** | Readiness wizard + progress |
| 7 | Configure ERP URL + secret refs, enable `mx_cfdi`, government endpoint → Save | Checklist advances |
| 8 | Enable **Pipeline** (only if unlocked) → Save | Succeeds; if incomplete, blocked with message |
| 9 | Open **Monitoring** / **AI Ops** | Counts or seeded transactions visible |
| 10 | Logout | Back to admin login |

**Fail if:** ghost-white text on white modal; customer IDs unreadable; pipeline enables with empty ERP/gov.

---

## B. Customer path (10–15 min)

| # | Step | Expected |
|---|------|----------|
| 1 | Open `/customer/login` | Customer Portal branding |
| 2 | Sign in as portal user | Lands on `/customer/overview` |
| 3 | Confirm only **their** company ID | No other tenants |
| 4 | Walk **Overview → Invoices → SAT → Monitoring → AI Ops → Settings** | All load; no Coming Soon; no admin sidebar |
| 5 | Try `/dashboard` or `/customers` | Redirected to portal (spinner only — no admin flash) |
| 6 | Settings | Read-only configuration |
| 7 | Logout | `/customer/login` |

**Fail if:** admin menu visible; other customer data visible; blank/broken pages.

---

## C. Contrast / UX smoke (2 min)

On a machine with **OS dark mode ON**:

1. Open `/customer-users` → Create customer user  
2. Confirm body is light (white), text is dark  
3. Confirm Assign list IDs are dark monospace, not washed out  

---

## D. What to tell the client

> BridgeEDI gives your company a private login and portal. Our team onboards you in the admin console (customer, users, ERP, government, pipeline). Your users only see your invoices, tax documents, monitoring, and settings. AI explains operations — it does not send invoices. To go live we plug in your real ERP and government credentials in the same Settings screens.

---

## Sign-off checklist (send back)

- [ ] Admin create customer works  
- [ ] Create/assign user modal readable (dark mode OS OK)  
- [ ] Workspace settings + readiness wizard works  
- [ ] Customer portal login + full nav works  
- [ ] Isolation verified  
- [ ] Monitoring shows data (live or seeded)  
- [ ] No Coming Soon on portal path  

**Tester:** _______________  **Date:** _______________  **Environment:** Prod / Staging / Local
