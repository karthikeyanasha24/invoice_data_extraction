# BridgeEDI — First Customer User Guide

**Audience:** Users at the manufacturing / finance customer  
**Login:** `/customer/login` only

---

## What you get

Your organization has a private BridgeEDI portal. You see only your company’s invoices, tax documents, monitoring, and settings. You never use the operator (admin) console.

---

## Sign in

1. Open the customer portal URL: `/customer/login`
2. Enter the email and password provided by your BridgeEDI administrator
3. You land on **Overview**

If you try the admin login by mistake, ask your administrator for the portal link.

---

## Pages

### Overview
Shows whether your workspace is ready, pipeline / monitoring status, and recent activity counts.

### Invoices
Lists invoices for your organization. Upload and receive are coordinated with your BridgeEDI administrator during the pilot.

### SAT
Mexico CFDI / tax authority documents for your assigned company. Empty means none have been received yet for your account.

### Monitoring
Operational status of BridgeEDI processing: running, completed, failed, retrying, and recent transactions.

### AI Ops
Operational summaries and recommendations from monitoring data only. **AI never sends invoices.**

### Settings
Read-only view of workspace configuration (ERP, adapters, pipeline flags). Changes are made by your BridgeEDI administrator.

---

## Sign out

Click **Logout**. You return to `/customer/login`.

---

## Security notes

- Another customer cannot see your invoices through the portal
- Admin routes are blocked for customer accounts
- Do not share your password; ask the administrator to reset if needed

---

## Support

Contact your BridgeEDI administrator for access issues, missing documents, or failed transactions shown in Monitoring.
