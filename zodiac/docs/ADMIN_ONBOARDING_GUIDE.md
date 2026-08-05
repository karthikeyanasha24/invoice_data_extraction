# BridgeEDI — Admin Onboarding Guide

**Audience:** BridgeEDI operators  
**Principle:** Everything for first-customer setup is done in the UI. No SQL. No manual DB edits.

---

## Prerequisites (environment)

| Item | Notes |
|------|--------|
| Admin account | Operator with `is_admin` |
| API running | Health `/health` OK |
| Optional | `ENABLE_PIPELINE_API=true` when you want pipeline execute APIs live |
| Secrets | Use `env:` / `vault:` refs — never paste production secrets into the UI as plaintext |

Live ERP and government endpoints are **customer/environment** items. The platform stores references and configuration only.

---

## End-to-end onboarding (UI)

### 1. Create the customer
1. Login at `/`
2. Open **Customers**
3. **Add Customer** — set Customer ID (tax ID / account code), target format, tax fields as needed
4. Save

**Automatic:** Workspace settings are created with pipeline **off**, monitoring **on**, AI scoped **on**, `erp_update_mode=auto`.

### 2. Create the portal user
1. Open **Customer users**
2. **Create customer user** — email, username, password (min 8 chars)
3. **Assign customers** in the same form (select the Customer ID)
4. Save

The user signs in only at `/customer/login`.

### 3. Configure the workspace
1. Open **Workspaces** → select the customer  
   (or open `/workspace/{customerId}/settings`)
2. Use the **Readiness wizard** at the top — progress % and checklist
3. Fill **ERP connection**: base URL, auth type, secret refs (`env:` / `vault:`)
4. **Country adapter**: choose `mx_cfdi` (Mexico) or `sample_gst` (demo), enable it
5. Set **Government endpoint** (`https://…` or secret ref) and auth if required
6. Confirm **Monitoring** and **AI Ops scoped** remain on
7. **Save workspace configuration**

### 4. Enable pipeline
Pipeline checkbox unlocks only when prerequisites are met:

- Workspace settings
- ERP base URL
- ERP secrets (for the chosen auth type)
- Adapter enabled
- Government endpoint
- Monitoring enabled

Then enable **Pipeline** and save again.

### 5. Verify readiness
Wizard should show **Ready for production** when required steps (including portal user assigned and pipeline enabled) are complete.

### 6. Hand off to the customer
Share:

- Portal URL: `/customer/login`
- Email / temporary password
- This user guide: `docs/FIRST_CUSTOMER_USER_GUIDE.md`

---

## Demo / staging seed (optional)

From `zodiac/` with API `.env` loaded:

```bash
python scripts/seed_first_customer_demo.py
python scripts/seed_first_customer_demo.py --customer-id DE875243162 --seed-monitoring-only
python scripts/seed_first_customer_demo.py --ready
```

`--ready` writes **sandbox** ERP/gov URLs and `env:DEMO_*` refs — not live production credentials.

---

## What not to do

- Do not enable pipeline before ERP/adapter/government are set (API will reject it)
- Do not open Quotations for demos (not part of BridgeEDI package; removed from sidebar)
- Do not run SQL to create workspace rows — use Customers / Workspaces UI
- Do not give customers admin accounts

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Pipeline checkbox disabled | Complete ERP + adapter + government; save; refresh |
| Customer login rejected for admin | Use `/` for admins; portal is customer-only |
| “No workspace assigned” in portal | Assign customer ID on the user |
| Empty Monitoring | Run seed script or a real pipeline transaction |
| Secret rejected | Must use `vault:` / `env:` / `secret:` prefixes |
