# BridgeEDI Customer Support Guide

**Audience:** Support, Customer Success, first-line ops  
**Pilot:** Single customer — escalate fast; do not experiment in production  
**Related:** [`OPERATIONS_HANDBOOK.md`](OPERATIONS_HANDBOOK.md) · [`docs/operations/RUNBOOKS.md`](docs/operations/RUNBOOKS.md) · [`demo/first_customer/`](demo/first_customer/)

---

## 1. Support principles

1. **Stabilize before explain** — if invoices stop, protect SAT path; disable pipeline if unsure.  
2. **Never ask for plaintext secrets in chat** — use `env:` / vault refs and ops to set them.  
3. **Always capture** `customer_id`, approximate time, invoice id / UUID, `correlation_id` if known.  
4. **Do not promise redesigns** — log product feedback for roadmap.  
5. **Isolation is sacred** — any cross-customer visibility → Sev-1 immediately.

---

## 2. Severity & response (pilot)

| Sev | Example | First response | Target |
|-----|---------|----------------|--------|
| 1 | Data leak, auth broken for all | On-call + Security | Immediate |
| 2 | Pilot cannot process invoices | On-call | &lt; 1 hour |
| 3 | Single invoice stuck / ERP delay | Support + Ops | Same business day |
| 4 | UI confusion / AI Ops wording | CS | Next business day |

---

## 3. Common issues

| Issue | Likely cause | First check |
|-------|--------------|-------------|
| Cannot log in | Password, `SECRET_KEY` rotate, user disabled | Auth / user admin |
| Workspace empty / 404 | Not assigned; wrong id | Assignments |
| Settings locked | Non-admin | Admin configures |
| “Not ready” banner | Incomplete ERP/adapter/gov | Onboarding status |
| Invoice stuck | SAT/ERP/gov external | Monitoring + legacy status |
| CORS / blank API | Origin not in `CORS_ORIGINS` | RB-6 |
| AI wrong answer | Asking invoice content vs ops | Clarify AI Ops scope |

---

## 4. Troubleshooting checklist

```text
1. Which customer_id / workspace?
2. Admin or customer user?
3. Which surface: login / upload / SAT / pipeline / ERP / monitoring / AI?
4. When did it last work?
5. Any deploy or config change today?
6. /health and /health/ready?
7. onboarding-status.ready?
8. correlation_id?
```

Escalate to Ops with answers to the above — not “it’s broken.”

---

## 5. Configuration problems

| Symptom | Guidance |
|---------|----------|
| Pipeline not available | Needs `ENABLE_PIPELINE_API` **and** workspace `pipeline_enabled` |
| Adapter “enabled” but no submit | Check endpoint_url_ref + auth; Mexico may use SAT path |
| Wrong ERP updated twice | Set `erp_update_mode=auto` or `never`; escalate Eng |
| Display name / flags wrong | Admin → Workspace Settings → Save |
| sample_gst mentioned | Not for pilot customers — ignore / disable |

Point admins to Settings onboarding checklist. Do not edit DB by hand unless DevOps.

---

## 6. Secret problems

| Symptom | Cause | Resolution |
|---------|-------|------------|
| API rejects secret on save | Plaintext not allowed | Use `vault:` / `env:` / `secret:` prefix |
| Runtime auth fails | Env var missing on host | DevOps sets env or vault map |
| `VAULT_UNAVAILABLE` | Vault not configured | Wire vault or switch to `env:` |
| Token in ticket | Process violation | Rotate secret; delete from ticket |

**Support never stores customer passwords in CRM notes.**

---

## 7. ERP problems

Use customer-friendly language + Ops RB-3.

| Customer says | You check | You say |
|---------------|-----------|---------|
| “Not in SAP” | Monitoring erp_update; outbox; mode skip | Investigating confirmation path; invoice may still be valid |
| “Duplicate in SAP” | `erp_update_mode` + MX submit | We will set auto/never to stop double update |
| “Auth error” | Secret refs resolve | Credential refresh with their IT — refs only |

---

## 8. Government problems

| Customer says | You check | You say |
|---------------|-----------|---------|
| “SAT/gov rejected” | Adapter endpoint sandbox vs prod; auth | Confirm environment; pause retries if flooding |
| “Timeout” | Gov availability; retry exhaustion | Temporary government/network; we will reprocess |
| “Wrong stamp expectation” | Mexico already-stamped design | BridgeEDI does not invent timbrado |

---

## 9. Monitoring problems

| Symptom | Guidance |
|---------|----------|
| Empty timeline | Monitoring disabled? Migrations missing? Soft-fail? |
| Events for wrong customer | Sev-1 isolation |
| Lag / missing metrics | Pipeline may still succeed; fix DB (RB-5) |
| Alert noise | Tune with Ops; do not disable blindly in prod without note |

---

## 10. AI Ops questions

**What AI Ops is:** operational Q&A over **monitoring** data for this workspace.  
**What it is not:** rewriting invoices, calling SAT, or replacing finance chat.

| Question type | Answer |
|---------------|--------|
| “What failed today?” | Valid AI Ops use |
| “Why is this UUID stuck?” | Valid if correlation in monitoring |
| “Fix my invoice totals” | Out of scope — human + invoice tools |
| “Show other customers” | Forbidden — must 404 / deny |

If Adaptive Query / dashboard AI is used, remind: **separate** from workspace AI Ops; admin-controlled.

---

## 11. Standard replies (templates)

### Invoice delayed

> We’ve identified your workspace and the invoice reference. We’re tracing processing and confirmation (government/ERP). You’ll get an update within [SLA]. No action needed unless we ask for a corrected file.

### Config change request

> Workspace settings (ERP URLs, adapters, secrets) are admin-only. Please have your BridgeEDI admin update Settings using secret references (`env:` / `vault:`). We can join a 15-minute config call.

### Pipeline vs SAT

> Your production path uses the established Mexico processing route. The shared pipeline is optional and controlled by flags for safety. We will not enable it without a staged dry-run.

---

## 12. Handoff to engineering

Include:

- Severity  
- customer_id  
- User id / role  
- Endpoint or UI path  
- Timestamp (timezone)  
- correlation_id  
- Already tried  
- Customer impact (volume, revenue, deadline)

---

*Support guide version: 1.0 · Pilot*
