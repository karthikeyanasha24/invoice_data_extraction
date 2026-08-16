# BridgeEDI — Client Test Workflow

**Purpose:** End-to-end checklist to verify the first-customer experience on production.

**Environment:** Production — [https://www.bridgeedi.com](https://www.bridgeedi.com)  
**Branch deployed:** `phase12-first-customer-ready`  
**Estimated time:** 30–40 minutes

---

## What you should see

| Area | What to expect |
|------|----------------|
| Admin login | `https://www.bridgeedi.com/` — operator console |
| Sidebar (admin) | Dashboard, Generative AI, Invoices, Customers, **Workspaces**, Customer users, SAT, Account Mapping, Supplier Tokens, Settings — **no Quotations** |
| Customer portal login | `https://www.bridgeedi.com/customer/login` — separate portal door |
| Create customer | Workspace settings created automatically |
| Create customer user + assign | One form; customer IDs readable (high contrast) |
| Workspace Settings | ERP, government, adapter, pipeline, readiness wizard |
| Pipeline gate | Cannot enable until ERP + adapter + government are ready |
| Customer portal | Overview → Invoices → SAT → Monitoring → AI Ops → Settings → Logout |
| Isolation | Customer cannot stay on admin pages |
| AI Ops | Explains operations — does **not** send invoices |

---

## Credentials (fill in before the session)

| Role | URL | Email | Password |
|------|-----|-------|----------|
| Admin / operator | https://www.bridgeedi.com/ | _______________ | _______________ |
| Customer portal user | https://www.bridgeedi.com/customer/login | _______________ | _______________ |

Use a real portal user assigned to **one** customer ID (created in section A), or a demo user provided by BridgeEDI.

---

## A. Admin path (15–20 min)

Base URL: **https://www.bridgeedi.com**

| # | Step | Expected |
|---|------|----------|
| 1 | Open `/` and sign in as admin | Dashboard loads; sidebar shows **Workspaces**; **Quotations** is absent |
| 2 | Open **Customers** → **Add Customer** | Form readable; create succeeds |
| 3 | Open **Customer users** → **Create customer user** | Modal: dark text on white; customer IDs readable; Cancel readable; Close (X) visible |
| 4 | Assign one customer ID → **Create** | User appears in list with that assignment |
| 5 | **Edit customers** on that user | Same contrast; Save works |
| 6 | Open **Workspaces** → select the customer → **Settings** | Readiness wizard + progress % visible |
| 7 | Configure ERP URL + secret refs, adapter `mx_cfdi`, government endpoint → **Save** | Checklist / progress advances |
| 8 | Enable **Pipeline** (only if unlocked) → **Save** | Succeeds when ready; if incomplete, blocked with a clear message |
| 9 | From the workspace shell, open **Monitoring** / **AI Ops** | Page loads; counts or activity visible when data exists |
| 10 | **Logout** | Returns to admin login |

**Fail if:** ghost-white text on white modal; customer IDs unreadable; pipeline enables with empty ERP/government; Quotations still in sidebar; Workspaces missing.

---

## B. Customer path (10–15 min)

| # | Step | Expected |
|---|------|----------|
| 1 | Open https://www.bridgeedi.com/customer/login | Customer Portal branding (not admin login) |
| 2 | Sign in as the portal user | Lands on `/customer/overview` |
| 3 | Confirm only **their** company / customer ID | No other tenants’ data |
| 4 | Walk **Overview → Invoices → SAT → Monitoring → AI Ops → Settings** | All pages load; no “Coming Soon”; no admin sidebar |
| 5 | Manually open `/dashboard` or `/customers` while logged in as portal user | Redirected back to portal (brief spinner only — no admin chrome flash) |
| 6 | Open **Settings** | Configuration is read-only for the customer |
| 7 | **Logout** | Returns to `/customer/login` |

**Fail if:** admin menu visible; other customer data visible; blank/broken pages; “Coming Soon” on portal routes.

---

## C. Contrast / UX smoke (2 min)

On a machine with **OS dark mode ON**:

1. As admin, open **/customer-users** → **Create customer user**
2. Confirm modal body is light (white) and text is dark
3. Confirm Assign list customer IDs are dark monospace (not washed-out grey)

---

## D. What this product does (one paragraph for stakeholders)

> BridgeEDI gives your company a private login and portal. Our team onboards you in the admin console (customer, users, ERP, government, pipeline). Your users only see your invoices, tax documents, monitoring, and settings. AI explains operations — it does not send invoices. To go live we plug in your real ERP and government credentials in the same Workspace Settings screens.

---

## Sign-off checklist (send back)

- [ ] Admin login works; **Workspaces** in sidebar; **no Quotations**
- [ ] Create customer works
- [ ] Create / assign customer user modal readable (dark-mode OS OK)
- [ ] Workspace Settings + readiness wizard works
- [ ] Pipeline blocked until ERP + adapter + government ready
- [ ] Customer portal login + full nav works
- [ ] Isolation verified (portal user cannot use admin pages)
- [ ] Monitoring / AI Ops pages load
- [ ] No “Coming Soon” on portal path

| Field | Value |
|-------|-------|
| Tester | _______________ |
| Date | _______________ |
| Environment | Production (bridgeedi.com) |
| Pass / Fail | _______________ |
| Notes | _______________ |

---

*BridgeEDI / Zodiac — Client handoff test · Confidential*
