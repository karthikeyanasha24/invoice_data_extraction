# BridgeEDI — Client Demo Rehearsal Script

**For:** Andy (customer meeting)  
**Audience:** Manufacturing company that has never seen the platform  
**Tone:** Business outcomes, not architecture  
**Date prepared:** 2026-08-04  

---

## Before the meeting (30–45 minutes)

Do these **before** the customer sits down. Do not invent live government or ERP connectivity if credentials are not ready.

1. Use **admin** login (`/` — not `/customer/login`).
2. Pick **one** demo customer (recommended: a clean pilot ID with one assigned user only).
3. **Workspaces → Enable workspace settings** for that customer.
4. On **Workspace → Settings**, complete:
   - Display name customers recognize (company name, not a raw tax ID if possible)
   - ERP connection (secret refs only — `env:` / `vault:`)
   - Country adapter enabled (`mx_cfdi` for Mexico)
   - Government endpoint configured
   - **Pipeline enabled**
5. Confirm **Customer Users**: one portal user, assigned to **only** that customer.
6. Seed or run at least **one** monitored pipeline transaction so Monitoring and AI Ops are not zeros.
7. Never open **Quotations** (shows “Coming Soon”).
8. Hide or ignore the amber **LOCAL DEV** banner verbally: “We’re on our staging environment.”
9. Warm the app once (login + dashboard + workspace) so the first customer click is not a cold compile.

**Demo accounts (prepare yours):**
- Admin: your operator account
- Customer portal: `/customer/login` with a dedicated customer user (known password written on your note card)

---

## Opening (90 seconds)

**Say:**

> “BridgeEDI is the control layer between your ERP and the government e-invoicing system.  
> Your finance team sees only your company’s invoices.  
> Our operations team configures the country rules, connections, and monitoring.  
> I’ll show you both sides — how we set you up, then what your users see every day.”

**Do not say:** pipeline stages, adapters, orchestrator, outbox, correlation ID (yet).

---

# Part 1 — Admin demonstration

## 1. Login

**URL:** `/` (admin)

**Say:**  
> “This is the operator console. Only BridgeEDI administrators use this login.”

**Visible:** Zodiac/BridgeEDI sign-in, link to **Customer Portal sign-in**.

**Customer may ask:** “Why two logins?”  
**Answer:** “Your people never share the admin console. They get a separate portal so they only see their company.”

**Confusion risk:** Product title still says “Zodiac” in places.  
**Say if noticed:** “Zodiac is the product family; BridgeEDI is the invoice bridge we’re showing today.”

**Missing UX:** Branding inconsistency (Zodiac vs BridgeEDI).

---

## 2. Dashboard

**Say:**  
> “This is the operations overview — inbound documents, what reached SAP, what’s pending.  
> This is our view across customers. Your team will not see this screen.”

**Visible:** To ERP / From ERP / Business / Customer Comparison tabs, real counts if data exists, **LOCAL DEV** banner.

**Questions:** “Is this live production?”  
**Answer:** “This session is our staging environment with real flows wired the same way as production.”

**Confusion:** Banner “No production data. Switch to prod API.”  
**Avoid:** Dwelling on the banner. Move on.

**Missing UX:** Banner is too loud for a sales demo.

---

## 3. Customers

**Say:**  
> “Every manufacturer we onboard is a customer record — tax ID, target invoice format, validation rules.”

**Visible:** Customer table, **Add Customer**, Edit / Delete, certificates, tokens.

**Questions:** “Is that our RFC / VAT number?”  
**Answer:** “Yes — the customer ID is how we isolate your documents.”

**Confusion:** Format values like `XML_EMBED_X12` look like internal codes.  
**Say:** “That’s the technical format label for how your invoices are packaged. We’ll set the right one with you during onboarding.”

**Avoid:** Clicking **Delete**. Avoid editing format dropdowns casually (known confusing values).

---

## 4. Create Customer

**Say:**  
> “Onboarding starts here. We create your company once.”

**Visible:** Create Customer form — Customer ID, Target Format, tax fields, validation checkboxes, Create / Cancel.

**Questions:** “Can we change the format later?”  
**Answer:** “Yes, through configuration with our team — not something your end users toggle day to day.”

**Confusion:** Too many validation field checkboxes for a first meeting.  
**Demo tip:** Fill Customer ID + format only; Cancel if you already have a pilot customer prepared.

**Missing UX:** No plain-language “Company name” field separate from tax ID on some flows.

---

## 5. Customer Users

**Say:**  
> “These are the people at your company who will sign into the portal.  
> Each user is assigned only to the companies they’re allowed to see.”

**Visible:** User list, Create customer user, Edit customers (assignment modal).

**Questions:** “Can one person see two plants?”  
**Answer:** “Yes — we can assign multiple company IDs to one user. For clarity we usually start with one.”

**Confusion:** Assignment modal briefly shows “No customers” while loading.  
**Demo tip:** Pause one second after opening the modal until IDs appear.

---

## 6. Assign User

**Say:**  
> “This checkbox is the isolation boundary.  
> If you’re not assigned, you cannot see that company’s invoices.”

**Visible:** Assign customers modal, Save.

**Questions:** “Can another customer see our invoices?”  
**Answer:** “No. Portal users only see assigned customer IDs. Workspaces enforce that boundary.”

**Confusion:** Technical phrasing “customer IDs” instead of “companies.”  
**Say:** “Think of each ID as one legal entity or plant you want isolated.”

---

## 7. Workspace

**Say:**  
> “A workspace is your exclusive operating space inside BridgeEDI — settings, monitoring, and AI for your company only.”

**Visible:** Workspace cards; status like settings / pipeline on-off; **Enable workspace settings**.

**Questions:** “Is this a separate system?”  
**Answer:** “No — it’s your private area inside the same platform.”

**Confusion:** Cards showing raw IDs and “No settings yet.”  
**Demo tip:** Only open the prepared customer. Do not scroll a long list of unfinished workspaces.

**Missing UX:** No obvious “Back to Workspaces” once inside a workspace shell.

---

## 8. Workspace Settings

**Say:**  
> “This is where we finish onboarding: ERP connection, government connection, country rules, and whether the automated bridge is on.”

**Visible:** Onboarding checklist, Pipeline enabled, AI scoped, Monitoring, ERP form (secret refs), Country adapter, Save.

**Questions:** “Do we configure this ourselves?”  
**Answer:** “Usually we configure it with you during go-live. Your portal settings are read-only so nothing critical gets changed by accident.”

**Confusion:** `vault:` / `env:` secret language; `erp_update_mode` auto/always/never.  
**Say:** “We store references to secrets — not passwords on the screen.  
> Auto means: if SAP already got the update during submission, we don’t double-write.”

---

## 9. ERP Configuration

**Say:**  
> “This is how BridgeEDI talks back to your ERP after the government accepts the invoice — confirmation and status.”

**Visible:** Base URL, auth type, secret refs, confirmation callback.

**Questions:** “We use Oracle, not SAP.”  
**Answer:** “The platform connection is ERP-agnostic HTTP with auth. Today our deepest operational experience is SAP-oriented screens elsewhere in the product; Oracle is a connector configuration exercise, not a rewrite of the bridge.”

**Do not claim:** A finished Oracle connector UI if you cannot show it.

**Confusion:** SAP labels elsewhere in the admin nav while talking “any ERP.”

---

## 10. Government Configuration

**Say:**  
> “This is the path to the tax authority — for Mexico, the CFDI / SAT path through your enabled country adapter.”

**Visible:** Government endpoint, auth type, secret ref on the adapter section.

**Questions:** “What if the government API is down?”  
**Answer:** “Submission fails with a recorded status. Transport-level failures can retry automatically. You see FAILED / RETRYING in Monitoring — nothing is silently dropped.”

---

## 11. Country Adapter

**Say:**  
> “Each country has its own rules package — validation, mapping, formatting.  
> Mexico is `mx_cfdi`. Adding another country means enabling another adapter for the workspace — not rebuilding the platform.”

**Visible:** Country code, enabled toggle, government fields.

**Questions:** “How do I add another country?”  
**Answer:** “We enable a country adapter for your workspace and configure its government endpoint. New countries are adapter work on our side; you don’t get a DIY ‘add country’ wizard in the portal today.”

---

## 12. Pipeline Enabled

**Say:**  
> “When Pipeline is on for your workspace, invoices follow the controlled bridge path: validate → map → rules → format → submit to government → confirmation → update ERP → monitoring.  
> AI is intentionally **not** in that path.”

**Visible:** Pipeline enabled checkbox; checklist item for pipeline.

**Questions:** “Does AI send invoices?”  
**Answer:** “No. AI Ops reads monitoring facts only. It never submits invoices.”

**Confusion:** Customers may think “pipeline” means oil/gas.  
**Say:** “Pipeline here means the automated invoice processing path.”

---

## 13. Monitoring

**Say:**  
> “This is your operational flight recorder — running, completed, failed, retrying, latency, and the latest transactions.”

**Visible:** Counters, top errors, latest transactions table.

**Questions:** “How do I know an invoice failed?”  
**Answer:** “It appears as FAILED here, with stage and correlation. AI Ops can summarize failures from the same facts.”

**Confusion / embarrassment:** All zeros with “No pipeline transactions yet.”  
**Demo tip:** Only open Monitoring after seed data exists. If empty, show the screen structure and switch to a prepared screenshot or prior run — do not improvise.

---

## 14. AI Ops

**Say:**  
> “AI Ops explains what Monitoring already knows — summaries and recommendations for your workspace.  
> It does not touch invoice submission.”

**Visible:** Operational summary, recommendations, Ask box.

**Questions:** “How does AI work?”  
**Answer:** “It reads workspace-scoped monitoring data and produces operational summaries and recommendations. It cannot see other customers, and it cannot send invoices.”

**Confusion:** Empty “0 transactions” makes AI look useless.  
**Demo tip:** Same as Monitoring — need facts first.

---

# Part 2 — Customer demonstration

**Switch roles.** Log out of admin. Open **`/customer/login`**.

**Say:**  
> “Now you’re the customer. This is the only login your users need.”

---

## Login (`/customer/login`)

**Say:**  
> “Separate door. Admin accounts are rejected here on purpose.”

**Visible:** Customer Portal heading, Sign in to portal, Admin sign-in link.

**If admin tries this door:** Message — *“This login is for customer portal accounts only…”*

---

## Overview

**Business value:** One-page “is our workspace ready?” and activity snapshot for their company only.

**Enough information?** Yes for status; incomplete config shows an honest checklist.

**Looks like admin tool?** Mildly — readiness checklist uses technical missing keys (`erp_configured`, `pipeline_enabled`). Soften verbally.

**Hide?** Prefer not showing incomplete checklist in a first meeting unless you frame it as “we finish this together before go-live.”

**Say:**  
> “You only see your organization. Pipeline, monitoring, and AI status for your company.”

---

## Invoices

**Business value:** See invoices belonging to their company; status (e.g. Validated).

**Enough information?** Basic list yes; upload/receive called out as admin-managed.

**Admin-like?** “customer-scoped APIs” wording is too technical — avoid reading it aloud.

**Hide?** Internal jargon in subtitles if present.

**Say:**  
> “Your invoice list. Upload and receive are handled with our operations team during the pilot.”

---

## SAT

**Business value:** CFDI / tax authority documents for their assigned receivers.

**Enough information?** Empty state is clear if no docs.

**Admin-like?** Filters are fine; keep language on “tax documents,” not internals.

**Say:**  
> “Mexico tax documents for your company. If the list is empty, we haven’t received CFDI for this demo account yet — the structure is what your users will live in.”

---

## Monitoring

**Business value:** Know whether invoices are flowing, stuck, or failing — without calling support first.

**Enough information?** Only if transactions exist.

**Admin-like?** Correlation / stage columns are operator-grade; explain as “transaction ID and processing step.”

**Should hide?** Not hide — educate. Do not show empty zeros as the hero moment.

---

## AI Ops

**Business value:** Plain-language ops summary and “what should I look at?” without giving AI control of invoices.

**Enough information?** Message that AI never joins invoice processing is excellent — say it twice.

**Admin-like?** Less so if recommendations have content.

**Say:**  
> “Ask questions about operations — not ‘send this invoice.’”

---

## Settings

**Business value:** Transparency into how their workspace is configured; read-only safety.

**Enough information?** Yes for trust (“we can see what’s configured”).

**Admin-like?** ERP update mode `auto` needs a one-line business gloss.

**Hide?** Nothing critical; emphasize read-only.

**Say:**  
> “You can see the setup. Changes go through your BridgeEDI administrator so production wiring stays safe.”

---

## Logout

**Say:**  
> “Session ends here. Next login is back at the customer portal.”

**Visible:** Returns to `/customer/login`.

---

# Part 3 — Live transaction demonstration

**Audience framing (manufacturing):**

> “An invoice leaves your ERP, BridgeEDI checks and shapes it for the country, sends it to the tax authority, brings the confirmation back, updates the ERP, and leaves an audit trail you can see in Monitoring — with AI explaining the trail, not driving it.”

| Step | What to say (business) | Live tomorrow? |
|------|------------------------|----------------|
| ERP | “Invoice originates in your ERP.” | **Simulated / preconfigured** unless a real ERP sandbox is connected |
| BridgeEDI | “We pick it up into the controlled path.” | **Live UI** (workspace + pipeline flag) if enabled |
| Validation | “We reject bad structure before government.” | **Live code path** if pipeline runs; needs payload |
| Mapping | “Fields mapped to the country model.” | Same |
| Business Rules | “Your company rules applied.” | Same |
| Formatting | “Document shaped for the authority.” | Same |
| Government | “Submitted to the tax authority endpoint.” | **Needs credentials + endpoint** — often **not** realistic live tomorrow |
| Confirmation | “Acceptance/rejection recorded.” | Depends on government response |
| ERP | “Status pushed back to ERP.” | **Needs ERP URL + secrets** |
| Monitoring | “You see success or failure here.” | **Live UI**; needs at least one run |
| AI | “AI explains the monitoring facts.” | **Live UI**; needs facts |

**Preconfigured demo data required:** customer, user assignment, workspace settings, adapter, secrets, ideally one successful/failed timeline.

**Cannot realistically show tomorrow without prep:** Real SAT acceptance, real SAP posting, Oracle live, multi-country switch, Quotations.

**Honest demo pattern if government/ERP aren’t live:**  
Show the **path on Settings + Monitoring structure**, then a **pre-seeded transaction** (or recording), and say clearly:  
> “Government and ERP in this room are our sandbox endpoints — same software path as production.”

---

# Part 4 — Customer questions (answer only from what exists)

### How do I add another country?
Enable another **country adapter** on the workspace (registry today includes Mexico `mx_cfdi` and a sample GST adapter). There is no self-serve “add any country” wizard for the customer. New countries are delivered as adapters by BridgeEDI.

### How secure is my data?
- Separate **customer portal** vs admin console.  
- Portal users see **assigned customer IDs only**.  
- Workspace settings, monitoring, and AI Ops are **workspace-scoped**.  
- Secrets stored as **references** (`env:` / `vault:`), not pasted plaintext in API for connectors.  
- AI Ops is scoped and **does not join invoice submission**.

### Can another customer see my invoices?
**No** — not through the customer portal when assignments and workspace isolation are used correctly. Admin operators can see cross-customer operations by design.

### Can I integrate with Oracle instead of SAP?
The **ERP connection model** is HTTP + auth + confirmation callback (ERP-agnostic connector). Much of the broader admin UI still speaks SAP/SAT history. Do not promise a polished Oracle admin pack unless configured and shown.

### Can I have multiple companies?
**Yes** — multiple customer records; users can be assigned multiple customer IDs. Portal resolves a primary workspace (today: primary assignment / ordered selection). For demo, use **one** assignment.

### Can I customize business rules?
Rules run inside the **country adapter / pipeline** path. Customers do not get a full rules IDE in the portal today. Changes are configuration/adapter work with BridgeEDI.

### How does AI work?
AI Ops reads **monitoring facts** for the workspace and produces summaries/recommendations. It is **not** an invoice authoring or submission agent.

### Can AI send invoices?
**No.**

### What happens if the government API is down?
Submission fails; status is recorded. **Transport retries** apply for retryable codes (e.g. timeout / submit failed) up to the stage retry policy (transport stages: multiple attempts). Visible in Monitoring as failed/retrying.

### What happens if SAP is unavailable?
ERP update stage can fail with recorded failure; retryable ERP failure codes exist. Invoice government submission and ERP update are separate concerns — Monitoring shows where it stopped.

### How do retries work?
Platform-owned retry policy: most stages run once; **network-bound stages** use a transport retry policy (multiple attempts with backoff) for known transient error codes.

### How do I know an invoice failed?
**Monitoring** (FAILED / RETRYING, stage, transaction list). AI Ops can summarize from the same facts. Empty Monitoring means no pipeline runs yet — not that failures are hidden.

---

# Demo weaknesses (ranked)

| Rank | Weakness |
|------|----------|
| **Critical** | Workspace ERP / adapter / government / pipeline still incomplete → readiness banner and no live bridge story |
| **Critical** | Monitoring & AI Ops at **zero transactions** → looks unfinished |
| **Critical** | Live government + ERP confirmation not demoable without secrets/endpoints |
| **High** | **Quotations → Coming Soon** if anyone clicks it |
| **High** | `LOCAL DEV` / “No production data” banner on admin |
| **High** | Branding mix: **Zodiac** title vs **BridgeEDI** story |
| **High** | Target format `XML_EMBED_X12` looks broken/confusing |
| **High** | Existing customer users with **multiple** assignments (portal may open unexpected company) |
| **Medium** | Brief flash of admin shell if customer hits `/dashboard` before redirect |
| **Medium** | Assign-modal empty flash while customers load |
| **Medium** | No Back-to-Workspaces control |
| **Medium** | Cold Next.js compile / Neon latency on first loads |
| **Medium** | Technical checklist keys on customer Overview |
| **Low** | Sidebar still exposes many legacy admin tools during admin tour |
| **Low** | Password show/hide and minor portal polish |

---

# Small improvements before the meeting (no redesign)

1. Seed **one completed + one failed** pipeline timeline for the demo workspace.  
2. Finish Settings checklist for the demo customer (ERP refs, `mx_cfdi`, government endpoint, pipeline on).  
3. Create a **single-assignment** portal user with a known password.  
4. Mentally (or via nav discipline) **never open Quotations**.  
5. Rename display name to the prospect’s company name.  
6. Soften or hide LOCAL DEV banner for the demo session if easy.  
7. Fix or avoid showing `XML_EMBED_X12` on the demo customer.  
8. Add a one-line empty state on Monitoring: “No transactions yet — runs appear here after the first submission.” (if not already clear).  
9. Pre-warm pages: Dashboard, Workspace Settings, Customer Overview, Monitoring.  
10. Print this script’s Part 4 answers on one page.

---

# Final decision (for Andy)

| Question | Answer |
|----------|--------|
| Can Andy confidently demonstrate tomorrow? | **Yes for portal + onboarding story**, only if Settings + seed monitoring are finished tonight. **Not** confident for a live government round-trip without credentials. |
| Would a customer understand the value? | **Yes**, if you stay on: separate login → isolation → bridge path → monitoring → AI explains, doesn’t send. |
| Single biggest weakness? | **Empty Monitoring / incomplete workspace configuration** — kills the “live bridge” moment. |
| What should Andy avoid showing? | Quotations, unfinished workspace list, Delete buttons, format dropdown edge cases, empty AI with no narrative. |
| Where to spend most of the meeting? | **Customer portal (trust + isolation) + one prepared transaction in Monitoring/AI Ops + clear ERP↔government story.** Admin create-customer is a short opening, not the whole meeting. |

---

## Suggested meeting timeline (45 minutes)

| Minutes | Focus |
|---------|-------|
| 0–3 | Opening value prop |
| 3–12 | Admin: create/assign/workspace settings (prepared customer) |
| 12–28 | Customer portal walkthrough |
| 28–38 | One transaction story (Monitoring + AI) |
| 38–45 | Q&A from Part 4 |

---

*End of rehearsal script. This is a speaking guide, not a technical design doc.*
