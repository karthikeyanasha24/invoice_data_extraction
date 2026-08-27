# Full Web App Product Audit and Advanced Product Roadmap

**Product:** BridgeEDI / Zodiac (ANDY)  
**Audit date:** 2026-08-27  
**Mode:** Audit only. No UI rewrite, no backend change, no deploy, **no R4-4**.  
**Production frontend:** https://www.bridgeedi.com  
**Production API:** https://zodiac-back.vercel.app  
**Full Chat:** https://www.bridgeedi.com/dashboard/ai  

**Analytical baseline (frozen):**

| Suite | Live status |
|-------|-------------|
| R3 | Production complete — 23 PASS / 2 DATA GAP / 0 FAIL |
| R4-1 | Production complete — 47 PASS / 2 DATA GAP / 0 FAIL |
| R4-2 | Production complete — 40 PASS / 1 DATA GAP / 0 FAIL |
| R4-3 | Production complete — 31 PASS / 6 DATA GAP / 0 FAIL (P50 775ms / P95 1230ms). Independent comparison SQL 0 value mismatches. |

This report is based on repository tracing plus live production inspection (authenticated Full Chat in a prior session; unauthenticated shell, OpenAPI, and API probes in this session).

---

## 1. Executive summary

BridgeEDI is two products sharing one browser: an **EDI / CFDI / SAP document operations system**, and a **governed natural-language SAP analytics analyst** (Full Chat). The analytics engine is the strongest part of the company. The surrounding web app does not yet present that engine as an enterprise intelligence product.

**What a serious customer would trust today:** honest DATA GAPs, grain-safe SQL, multi-turn context, independent SQL validation, and sub-second typical answers.

**What would make them hesitate:** three names (Zodiac / BridgeEDI / Document Management), public signup, Full Chat answering SAP questions with **optional JWT**, operational Dashboard routes **missing from live OpenAPI**, and a settings page that opens without a session.

**What would confuse them:** Real-time vs Historical doing almost the same thing; follow-up chips that say `LAND1` and `VBRK.FKDAT`; sidebar descriptions truncated; “15-stage pipeline” that is not the backend.

**What would impress them:** asking “high inventory but low sales” and getting a ranking with snapshot caveats instead of a hallucinated turnover number.

**Do not start R4-4 from this audit.** Fix identity, session gating, and dashboard-API availability before adding more analytical depth.

---

## 2. Current product understanding

### Stack (traced, not inferred)

| Layer | Implementation |
|-------|----------------|
| Frontend | Next.js 16 App Router, React 19, Tailwind 4, Geist fonts (body still falls back to Arial in `globals.css`), Axios, Recharts, lucide-react |
| Backend | FastAPI on Vercel (`zodiac-api` / project **zodiac-back**), SQLAlchemy, Neon SAP extract + app DB |
| Auth | JWT in `localStorage` (`access_token`), Axios Bearer interceptor, optional vs required Depends mixed by router |
| State | React context (`AuthContext`, `CustomerPortalContext`). No Redux/Zustand |
| Design system | Informal Tailwind utilities. No tokenized component library. Blue/indigo admin, emerald customer portal, purple Full Chat accents |
| Charts | Recharts via `AIChartRenderer` |
| AI | `POST /api/query/adaptive` → classify_turn → `analytical_deep_dive` / follow-up resolver / grain guard / dashboard router / universal SQL |
| Deploy | Frontend: `www.bridgeedi.com`. Backend: `zodiac-back.vercel.app`. Next rewrites `/api/v1/*` and `/api/query/*` in **dev**; production frontend sets `NEXT_PUBLIC_API_URL` to the backend |
| Feature flags | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WORKSPACE_UI` (workspaces on unless `false`) |

### What the product actually is

1. **Operations:** inbound SAT/CFDI → merge → SAP; outbound EDI invoice validate/convert; customers, tokens, account mapping, workspaces, customer portal.
2. **Intelligence:** NL questions over SAP billing/inventory with governed metrics, DATA GAP refusal, and contextual follow-ups (R3–R4-3).

The landing page copy says only (1): “AI-powered document management system.” It does not mention governed SAP analytics.

---

## 3. Complete route inventory

Auth: **Inconsistent.** `MainLayout` does **not** require login. Some pages redirect, some spinner forever, some render chrome and call APIs.

| Route | Page | Auth required (client) | Purpose | User type | Main actions | Data source | Status |
|-------|------|------------------------|---------|-----------|--------------|-------------|--------|
| `/` | Admin login/signup | Public | Sign in / create account | Admin / operator | Login, signup | `/api/v1/user/auth/*` | Live. No forgot-password. Public signup |
| `/customer/login` | Customer portal login | Public | Customer-only sign-in | Customer user | Login | Auth + portal | Live. Clearer value copy than admin |
| `/dashboard` | Dashboard V2 tabs | **Not gated** | Inbound/outbound/business/compare | Admin | Tabs, date filters | `/api/v1/dashboard/v2/*` | **CRITICAL:** those paths are **absent** from live OpenAPI (404) |
| `/dashboard/ai` | Intelligence + Full Chat | **Not gated** | NL analytics + ops KPIs | Analyst / exec | Ask, follow-up, SQL | `/api/query/adaptive` + dashboard V2 | Full Chat **works without JWT**. Real-time KPIs depend on missing dashboard routes |
| `/invoices-v2` | Invoice ops | Soft | Documents/validation/convert | Operator | Upload, validate, convert | `/api/v1/invoices-v2/*` | Live. Unauth: “Not authenticated” |
| `/invoices-v2/processing` | Validation progress | Soft | Poll job | Operator | Watch progress | validation-progress | Live |
| `/invoices` | Legacy V1 list | Checks `isAuthenticated` | Old file list | Operator | Search, recycle | `/api/v1/invoices/*` | Legacy; not in sidebar |
| `/invoice/[id]` | V1 success detail | Soft | Download/share stub | Operator | Download | invoices API | Legacy |
| `/failed-invoice/[id]` | V1 failed detail | Soft | XML edit, AI fix | Operator | Edit, reprocess | invoices API | Legacy; debug logs in code |
| `/upload` | V1 upload | Soft | File drop | Operator | Upload | invoices process | Legacy |
| `/customers` | EDI customers | Redirect if `!user` | Customer CRUD | Admin | CRUD, tokens | `/api/v1/customers/` | Live |
| `/customer-users` | Users & assignments | `is_admin` | Provision portal users | Admin | Create/assign | `/api/v1/customer-users` | Live |
| `/workspace` | Workspace index | Redirect `!user` | Per-customer shells | Admin | Open workspace | `/api/v1/workspace` | Live |
| `/workspace/[customerId]` and `/invoices` `/sat` `/monitoring` `/ai` `/settings` | Customer workspace | API access-check | Scoped ops | Admin / customer | Navigate modules | workspace + monitoring + ai-ops | Live |
| `/sat-documents` | CFDI hub | Spinner if `!user` | Docs, merge, send SAP | Operator | Tabs | `/api/v1/sat/*` | Live. Unauth = **blank/spinner**, no redirect |
| `/sat-documents/upload`, `/[id]`, `/simple-merge/[id]`, `/canonical/[id]` | SAT detail | Soft | Document/merge detail | Operator | Preview, send | SAT APIs | Live |
| `/admin/account-mapping` | RFC → G/L | Spinner if `!user` | Mapping table/CSV | Admin | Upload CSV | SAT mapping | Live |
| `/admin/supplier-tokens` | Supplier tokens | Spinner if `!user` | Token KPIs | Admin | Generate | `/api/v1/supplier-tokens` | Live |
| `/settings` | Account + API key | **Not gated** | Profile, fake prefs, API key | Admin | Generate API key | invoices api-key | **UX/security:** opens unauthenticated; username/email empty; notification checkboxes look real but several are `readonly` |
| `/quotations` | Empty by design | Shell only | Package boundary | All | CTA to invoices | None | Honest empty state |
| `/export` | Empty by design | Shell only | Package boundary | All | CTA to invoices | None | Honest empty state |
| `/customer` | Redirect | Portal | Entry | Customer | — | — | Redirect |
| `/customer/overview` | Portal home | Portal provider | Readiness | Customer | View status | workspace | Live |
| `/customer/invoices` `/sat` `/monitoring` `/ai` `/settings` | Portal modules | Portal | Scoped views | Customer | Read, ask AI Ops | scoped APIs | Live. Portal AI dumps JSON |
| `/customer-dashboard`, `/customer-invoices`, `/customer-sat-documents` | Legacy redirects | — | Compat | Customer | Redirect | — | Redirects |

Hidden/secondary: V1 invoice routes, quotations/export (intentional empty), `Dashboard.tsx` / `DashboardNew.tsx` **orphans** (not routed).

---

## 4. Product architecture (real IA)

```text
BridgeEDI / Zodiac
│
├── Public
│   ├── Admin login + signup (/)  — branded “Zodiac”
│   └── Customer Portal login (/customer/login)  — branded “CP”
│
├── Admin shell (MainLayout + Sidebar)  — no global auth guard
│   ├── Dashboard          To ERP | From ERP | Business | Customer Comparison
│   ├── Generative AI      Real-time | Historical | Full Chat
│   ├── Invoices V2        Documents | Validation | Failed | Successful | Convert | Converted
│   ├── Customers
│   ├── Workspaces         Overview | Invoices | SAT | Monitoring | AI Ops | Settings
│   ├── SAT Documents      Documents | Simple merge | Canonical | Send to SAP
│   ├── Account Mapping
│   ├── Supplier Tokens
│   └── Settings           Profile | Notifications (mostly local/readonly) | API keys
│
├── Customer portal (separate chrome)
│   ├── Overview | Invoices | SAT | Monitoring | AI Ops | Settings
│
├── Legacy / out of package
│   ├── /invoices, /upload, /invoice/[id], /failed-invoice/[id]
│   └── /quotations, /export
│
└── Analytical engine (not a nav section — lives under Generative AI)
    └── Adaptive query → deep multidim → grain guard → Neon SAP
```

This is **not** a BI tool with invoice add-ons. It is an **invoice bridge with a world-class analyst bolted into one nav item**.

---

## 5. User journeys

### New user

Landing → “Welcome to Zodiac” / document management → optional public **Sign up** → Dashboard.

**Breaks:** Value is document ops, not “ask your SAP data.” No onboarding, no sample questions until they find Generative AI. Signup is not an enterprise-ready first mile.

### Returning operator

Login → Dashboard (To ERP).

**Breaks (live):** Dashboard V2 APIs 404. They may click Generative AI instead (the thing that works).

### Analytics user

Dashboard → Generative AI → Full Chat → follow-ups.

**Works (authenticated, prior session):** profits → inventory → sales → high inv/low sales → groups → aging DATA GAP → inventory again → plant. Context holds.

**Breaks:** Real-time/Historical look like different AI modes but are ops KPI pages. Center “AI Analysis” panel has **no conversation memory**. SAP field names in chips. Duplicate summary + table.

### Executive

Expect: open app → what changed → exceptions → decide.

**Breaks:** No executive briefing. Dashboard is SAT/EDI funnels, not P&L/inventory risk. Full Chat can answer those questions **if they know to go there and how to ask**.

### Customer (portal)

Login → exclusive workspace → invoices/SAT/monitoring.

**Works:** Isolation copy is clear. Settings say BridgeEDI admin manages upload.

**Breaks:** Portal “AI Ops” is monitoring JSON, **not** Full Chat. Two different “AI” products.

---

## 6. Page-by-page audit

### `/` Admin login

- Purpose obvious in 5s: sign in. Product purpose is **wrong-sized** (“document management”).
- Primary CTA: Sign in. Secondary: Sign up (enterprise smell), Customer Portal link (good).
- No password recovery.
- Footer: Abor-Tech Ltd. Browser title: “Zodiac - Invoice Management System” while marketing domain is BridgeEDI.

### `/customer/login`

- Purpose and data-isolation message are better than admin login.
- Admin sign-in correctly goes to `/`.
- “CP” mark vs Zodiac “Z” — two brands before the first query.

### `/dashboard`

- Title “Dashboard” / subtitle “Inbound, outbound, and business analytics” — ops, not SAP P&L.
- Tabs: To ERP, From ERP, Business, Customer Comparison. Labels need domain knowledge (SAT→SAP vs EDI outbound).
- **Live evidence:** To ERP = `Request failed with status code 404` + Try Again. Axios error string, not a business explanation.
- KPI grid never appears because the request never succeeds.

### `/dashboard/ai` Intelligence

- Header “Intelligence” is closer to the real product than “Generative AI” in the sidebar.
- Tabs Real-time / Historical / Full Chat. Historical ≠ historical SAP (code: same fetch, no 60s poll).
- Full Chat (authenticated prior session): tables, follow-up chips, Follow-up vs New question, View SQL, DATA GAP markdown for aging.
- Follow-up chips expose `LAND1`, `VBRK.FKDAT`, `WAVWR` — analyst jargon.
- Footer: “15-stage pipeline · Auto SQL · Auto charts” — **cosmetic** timed steps, not backend `stage_timings`.
- Duplicate narrative: markdown summary above and Summary card below.
- Unauthenticated: adaptive still returns live inventory SQL (probed this session).

### `/invoices-v2`

- Purpose clear. Six tabs is a lot; Successful/Convert have empty-state implementations in code.
- Unauth: error “Failed to load documents: Not authenticated” **and** empty “Upload an invoice” — mixed signals.
- Page title “Invoices V2” is an internal version name.

### SAT / mapping / tokens / workspaces

- Real operational value for Mexico CFDI + SAP.
- Gating inconsistent (spinner vs redirect vs open).
- Unauth SAT: **blank white page** (LoadingSpinner, no copy, no redirect). Observed live.

### `/settings`

- Opens without login. Empty username/email. Security box says contact support for password change (no self-service).
- Notification and processing controls look like product settings; several are `readonly` / not clearly persisted.
- API key management is the only high-value block — buried.

### Quotations / Export

- Honest “not in package” empty states. Rare example of mature product communication. Still routable if someone types the URL.

---

## 7. Navigation audit

**Sidebar (admin):** Dashboard, Generative AI, Invoices, Customers, Workspaces, SAT Documents, Account Mapping, Supplier Tokens, Settings.

Issues:

- First-time user cannot tell that **Generative AI is the SAP business analyst**. Description: “AI-powered dashboard analysis.”
- Workspaces description: “Customer exclusive workspace shell” — engineering language.
- Account Mapping and Settings **share the Settings icon**.
- Descriptions truncate at 1440px (`AI-powered dashboard analy…`).
- Env badge “● PRODUCTION” is for engineers, not customers.
- Collapse works; `<1024px` uses hamburger overlay (`MainLayout`).
- No breadcrumbs. Deep SAT/invoice IDs rely on back buttons.
- Customer users get a **one-item** menu pointing at the portal (good isolation).

**First-time test:** No. They would not know whether to open Dashboard, Generative AI, or Invoices to “understand the business.”

---

## 8. Dashboard audit

Within 5–10 seconds on live production **without a working V2 API**, the user learns: something failed with HTTP 404.

**Intended** To ERP KPIs (from code): SAT documents, merges, sent to SAP, pending, token stats, suppliers, recent docs. These support **ops control**, not “what happened to margin.”

**Business tab** (code): revenue trend, currency/customer/country, industry, qty/ASP, AI insights — closer to an executive view, but **same 404** live because `/api/v1/dashboard/v2/business` is not in OpenAPI.

**Customer Comparison:** A/B plus a second chat (`postCustomerComparisonChat`) — a third AI surface besides Full Chat and Intelligence panel.

**Hierarchy:** operational funnels first, business second. For an analytics buyer this is inverted.

**Decorative vs decision:** Token expired counts are useful for ops. They are not “what needs a decision this morning.”

---

## 9. AI / Full Chat architecture

```text
Browser (DashboardAIAnalysis)
  → POST /api/query/adaptive  { question, contextData?, threadId }
      → classify_turn
      → try_deep_multidim_analysis
            analytical_followup_resolver
            sql_grain_guard
            inventory_sales (R4-3)
            business_semantic_layer DATA GAP payload
      → FOLLOWUP_DELTA / period compare / run_dashboard_query / universal
      → execute SQL on SAP extract
      → charts + summary + suggested_followups + stage_timings
  → ResultDashboard (KPIs, charts, markdown, table, View SQL, chips)
```

**Auth:** `get_current_user_optional`. Persistence of threads only if user + `ada_*` thread.

**Unused live path:** `POST /api/v1/dashboard/ai-analysis/chat` (required auth, historical scope) is **not** what Full Chat calls. `sapGenerativeAIRouting.ts` is dead for the live UI.

---

## 10. AI UX audit

| Topic | Finding |
|-------|---------|
| Placeholder | Good example question |
| Suggested questions | Intelligence “What can you ask?” uses emojis + domains including logistics/finance that often DATA GAP |
| Keyboard | Enter to send (standard) |
| Loading | Fake 15-stage pipeline |
| Cancel | **None** on adaptive (old .bak had abort) |
| Retry | **None** |
| Follow-up vs New question | Correct product idea; easy to miss |
| Duplicate summary | Same markdown twice |
| SQL | View SQL in Full Chat only; center panel has no SQL |
| DATA GAP | Honest markdown + 0 rows; **no distinct badge** vs error |
| Jargon | Intent names, SAP tables, WAVWR |
| Charts | Deep-dive chart shape often dropped by `ChartsGrid` |

### R4-3 / Full Chat sessions

**Session A (authenticated, prior session, UI):**  
Highest profits (`product_profitability`, Ship Project) → inventory (`inventory_analysis`, Fire fighting vehicle, snapshot caveat) → sales (context kept) → high inv/low sales (`inventory_risk_analysis`, Tires, ranking not stock-out) → product groups → aging **DATA GAP (MSEG)** → inventory again PASS → plant (`inventory_by_plant`, plant `3000`, LABST, T001W caveat).

**Session B/C (API harness):** aging/net profit DATA GAP then inventory PASS. Frozen.

Never presented current MBEW as 2004 inventory or as aging.

---

## 11. Analytics visualization audit

- Full Chat: tables do more work than charts; often appropriate.
- Deep charts frequently **don’t render** (schema mismatch) — users see tables. Acceptable if tables are good; wasteful if a bar was intended.
- Dashboard V2 charts (inbound bars/pies, outbound area, treemap) **not verifiable live** due to 404.
- Intelligence inbound vs outbound line chart depends on the same missing APIs.
- No export/share on Full Chat results.
- Mobile: Full Chat at ~887px used hamburger; table columns (PLANT / PRODUCT / NAME) already tight.

---

## 12. Table UX audit

Full Chat tables: many columns, formatted numbers, row count chip, no sort/filter/sticky header/export/search. Fine for 10–40 rows; not an analysis workbook.

Invoice/SAT tables: pagination exists in V1; V2 tabs vary. Null inventory fields show as `None` / `n/a` in chat cards (plant n/a on MBEW snapshot — correct grain, confusing label).

---

## 13. Filter / search audit

- Dashboard days: 0/7/30/90 inbound; 7/30/90 outbound; 30/90/365 business. **Not URL-persisted.**
- Intelligence days 7–90. Historical tab does not change semantic time scope.
- Invoice V2: `?tab=` synced. Source filter All / Manual / From SAP.
- Full Chat: no date picker; period lives in the question + follow-up context. Power users OK; executives expect a period control.

---

## 14. Loading / empty / error / DATA GAP

| State | Quality |
|-------|---------|
| Loading | Mix of “Loading…”, silent spinner, fake pipeline. SAT unauth ≈ blank |
| Empty | Quotations/export excellent. Invoice “No documents / Upload…” good |
| Error | Invoices: “Not authenticated.” Dashboard: raw Axios 404. No recovery besides Try Again |
| DATA GAP | Best-in-class honesty in **answer text**. UI does not badge it as “limitation” vs “outage” |
| Success | Little confirmation besides the answer appearing |
| Partial | Soft caveats in `keyFindings` on SUCCESS — easy to miss |

---

## 15. Responsive audit

| Viewport | Evidence |
|----------|----------|
| ~390–768 | `MainLayout` treats &lt;1024 as mobile hamburger. Chat input remains usable; tables clip |
| 887×446 (audit browser before override) | Intelligence header cramped; hamburger |
| 1024–1440 | Sidebar 256px; descriptions truncate; dual Settings icons |
| 1440+ | Comfortable density; still truncated nav copy |

Not a separate mobile product. Compressed desktop.

---

## 16. Accessibility audit

- Login fields have labels. Password show/hide button in snapshot **unnamed** on admin login (`button` with no name).
- Sidebar collapse has title; mobile menu has `aria-label`.
- Customer portal nav has `aria-label`.
- Dashboard tabs use `aria-current`.
- Charts: Recharts, limited screen-reader meaning.
- Color: blue active vs gray; not color-only for errors (text + red box).
- Focus rings exist on some inputs (`focus:ring-2`).
- Touch: sidebar items OK; chip clouds on Full Chat are small and jargon-heavy.
- `lang="en"` on html. No skip link.

Not WCAG AA. Highest impact: unnamed icon buttons, infinite unlabeled spinner, tables without captions.

---

## 17. Performance audit

**AI (accepted live harness, authenticated):** R4-3 P50 775ms / P95 1230ms / max 1664ms. R3 P50 731ms. Meets &lt;1s / &lt;3s for analytical questions.

**This session unauthenticated probe:** `POST https://zodiac-back.vercel.app/api/query/adaptive` “Show inventory.” returned **200** with MBEW SQL (engine is up). Same-origin `/api/query/adaptive` **Failed to fetch** (CORS/rewrite) — frontend relies on `NEXT_PUBLIC_API_URL`.

**Dashboard:** failure is availability (404), not latency.

**Frontend:** Axios timeout 600s; Next `proxyTimeout` 600s. Large adaptive logging was explicitly disabled to avoid UI freeze.

**Do not** speed this up by weakening grain guard or skipping validation.

---

## 18. Security / permissions audit

| Issue | Class | Evidence |
|-------|-------|----------|
| Adaptive query optional auth returns SAP extract rows | **CRITICAL BUG** | OpenAPI + live POST 200 without token |
| Admin `MainLayout` no login requirement | **CRITICAL BUG** | `/dashboard`, `/dashboard/ai`, `/settings`, `/invoices-v2` render |
| Dashboard router missing on live OpenAPI | **CRITICAL BUG** (reliability) | 149 paths; **zero** `/api/v1/dashboard/*`; `server.py` try/except swallows import failure |
| JWT in localStorage | Standard SPA risk | XSS ⇒ token theft |
| Public signup | Enterprise gap | `/` Sign up |
| No forgot password | UX + security ops | AuthForm |
| Customer portal isolation | Strength | Separate login, `is_customer_user`, access-check |
| 401 interceptor | Mixed | Skips logout on `/dashboard/ai` but **not** `/api/query/adaptive` |
| Direct URL | SPA 200s | Client gates only |

Do not weaken RLS or grain safety to “fix” UX.

---

## 19. Code quality audit (frontend)

- Dead: `Dashboard.tsx`, `DashboardNew.tsx`, `DashboardLanding.tsx`, `sapGenerativeAIRouting.ts` (live), `DashboardAIAnalysis.tsx.bak`.
- Dual invoice stacks (V1 + V2).
- `dashboard.py` ~6k lines — likely cause of **production router import failure** inside try/except.
- `console.log` auth noise; failed-invoice debug logs.
- Hard-coded “15-stage”; Intelligence KPI “Validated OK” = `merges_sent_to_sap` (mislabel).
- `globals.css` forces Arial after loading Geist.
- Emoji in `DOMAIN_CATEGORIES`.

Prioritize: auth gate, dashboard router load, remove dead stacks later. Do not drive-by refactor.

---

## 20. Architecture audit

```text
Browser (Next)
  → Axios + JWT (optional)
  → FastAPI
       ├─ invoices / sat / customers / workspace / monitoring   (loaded live)
       ├─ adaptive_query                                         (loaded live)
       └─ dashboard.py                                           (NOT in live OpenAPI)
  → App DB (invoices, users, SAT)
  → SAP extract (Neon) via grain-guarded SQL
  → Transformation + markdown + charts
  → Full Chat UI
```

**Bottlenecks:** Vercel serverless import of huge `dashboard.py`; 10-minute AI timeout; optional-auth data plane.

**SPOFs:** single adaptive endpoint; single SAP extract; JWT in the browser.

**Observability:** AI `stage_timings` exist but UI fakes a pipeline. No customer-facing freshness clock.

**Do not redesign the analytical backend.** Load or split `dashboard.py`. Require auth on adaptive. Gate `MainLayout`.

---

## 21. Feature inventory

| Feature | Page | Behavior | Backend | User value | UX | Tech | Missing | Priority | Class |
|---------|------|----------|---------|------------|----|------|---------|----------|-------|
| Full Chat NL→SQL | `/dashboard/ai` | Multi-turn governed analyst | adaptive + deep dive | Very high | Med | High | Auth, badges, cancel | P0/P1 | Core |
| DATA GAP | Full Chat | Honest refusal | semantic layer | Very high | Med | High | Distinct UI | P1 | Core |
| R3–R4-3 inventory/sales | Full Chat | Snapshot vs sales, risk rank, plant | inventory_sales | High | Med | High | Hide SAP names | P1 | Core |
| Dashboard V2 | `/dashboard` | Ops KPIs | dashboard v2 | High if up | Low live | — | **Routes not live** | P0 | Broken |
| Invoices V2 | `/invoices-v2` | Validate/convert | invoices-v2 | High ops | Med | Med | V1 leftover | P1 | Core |
| SAT/CFDI | `/sat-documents` | Intake/merge/SAP | sat/* | High ops | Med | Med | Auth spinner | P1 | Core |
| Customer portal | `/customer/*` | Tenant workspace | workspace | High | Med | Med | Not Full Chat | P2 | Important |
| Workspaces | `/workspace` | Admin per customer | workspace | Med | Med | Med | “shell” copy | P2 | Important |
| Intelligence Real-time | `/dashboard/ai` | Ops + one-shot ask | dashboard v2 + adaptive | Low until APIs up | Low | — | Historical is fake | P1 | Incomplete |
| Comparison chat | Dashboard tab | Extra NL | dashboard chat | Low/dup | — | — | Unify with Full Chat | P2 | Redundant |
| Quotations/Export | routes | Honest empty | none | Low | High | — | Keep | — | Nice |
| Saved analysis | — | — | thread store partial | High | — | — | No UI | P2 | Future |
| Share/export insight | — | Share stub on V1 invoice | — | High | — | — | None on chat | P2 | Missing |
| Public signup | `/` | Create user | auth | Negative for enterprise | — | — | SSO | P1 | Experimental |

---

## 22. Missing capabilities

- **Product:** One name, one promise, SSO, password reset, session-required shell.
- **UX:** Period control on Full Chat; cancel; retry; non-jargon follow-ups.
- **AI:** Saved threads UI; share link; executive briefing; anomaly with methodology (R4-2 growth exists — not proactive).
- **Trust:** “How calculated?” without dumping SQL by default; data-as-of; DATA GAP badge.
- **Collaboration:** none.
- **Continuity:** `ada_*` thread in sessionStorage; no “resume last briefing.”
- **Actionability:** insight stops at table. No ticket/export/owner.
- **Enterprise:** audit log of who asked what; RLS on SAP extract per tenant.

---

## 23. Product differentiation

Not “AI analytics.” The defensible story, already implemented:

```text
Business question
→ governed semantic intent
→ safe SQL (grain guard)
→ verified numbers (independent SQL in QA)
→ contextual follow-up
→ multidimensional drill
→ honest DATA GAP
→ decision support (partial)
```

Competitors (Power BI Copilot, ThoughtSpot Spotter, Tableau AI, Databricks Genie) win on **platform, SSO, sharing, semantic modeling UI, and polish**. BridgeEDI can win on **SAP-table honesty + invoice/CFDI operational context in the same company**. That story is not on the login page.

---

## 24. Competitive benchmark (patterns, not copies)

| Pattern | Leaders | BridgeEDI today |
|---------|---------|-----------------|
| Search-first NL | ThoughtSpot | Full Chat (strong engine, weak chrome) |
| Semantic layer governance | ThoughtSpot / Looker / Fabric | Code-level intents + grain guard (strong, invisible) |
| Copilot on existing reports | Power BI | No report canvas |
| Automated insights / anomalies | SpotIQ / Copilot narratives | Exists in SQL (growth, risk rank); not pushed |
| SSO / RLS / audit | All enterprise BI | JWT localStorage, optional adaptive auth |
| Share / schedule | All | Absent |
| Ops + analytics in one app | Rare | **Actual differentiator** if IA is cleaned |

Do not copy Fabric dashboards. Make the analyst feel like a **named role**, not a chatbot in a document CMS.

---

## 25. Advanced feature opportunities (evaluate, do not build yet)

| Idea | Valuable? | Supported? | When |
|------|-----------|------------|------|
| Executive briefing | Yes | Needs dashboard APIs + existing intents | After P0 |
| Anomaly detection | Yes if methodology shown | R4-2 style change metrics | P2 |
| Explainable “why” | Already partially | Follow-up Why? | P1 UX |
| Conversational drill-down | **Already works** | Resolver | Polish only |
| Insight-to-action | Not until ops systems | Weak | P3 |
| Saved analyses | Yes | thread store | P2 |
| Share/PDF | Yes | Auth first | P2 |
| Scheduled intelligence | After auth + briefing | Email infra unknown | P3 |
| NL dashboard generation | Tempting, low trust | No layout engine | **Do not build** |
| Role workspaces | If roles exist | is_admin / customer only | P3 |

---

## 26. Top 10 critical issues

1. **CRITICAL BUG** — `/api/query/adaptive` optional auth returns live SAP data.  
2. **CRITICAL BUG** — Live OpenAPI has no `/api/v1/dashboard/*` (V2 dashboard 404). Likely `dashboard.py` import swallowed.  
3. **CRITICAL BUG** — `MainLayout` allows admin chrome without a session.  
4. **CRITICAL BUG** — Product identity: Zodiac vs BridgeEDI vs document management vs Intelligence.  
5. Settings and Full Chat usable logged out; SAT blank spinner. Inconsistent security UX.  
6. Historical tab is not historical.  
7. SAP jargon in user-facing chips.  
8. Fake 15-stage pipeline (trust tax).  
9. Public signup + no password reset.  
10. Two AI products (Full Chat vs portal AI Ops JSON vs comparison chat).

---

## 27. Top 10 UX issues

1. Dashboard 404 as Axios text.  
2. Duplicate Full Chat summary.  
3. No cancel/retry on long queries.  
4. Truncated sidebar descriptions.  
5. Dual Settings icons.  
6. “Invoices V2” in the title.  
7. `None` / `n/a` in inventory cards.  
8. Intelligence “Validated OK” mislabel (code).  
9. Unnamed password-toggle control.  
10. No period picker on the analyst.

---

## 28. Top 10 product opportunities

1. Make Full Chat the **home** for analytics buyers (or a real “Ask” entry).  
2. Executive briefing from **existing** intents (revenue, margin, inventory risk).  
3. DATA GAP as a first-class UI pattern.  
4. Metric glossary / “How calculated?”.  
5. Saved questions.  
6. Export table.  
7. Unify AI surfaces.  
8. Hide technical follow-up labels; keep them in View SQL.  
9. Customer portal: optional **governed** ask, not raw JSON.  
10. SSO + audit — table stakes after P0.

---

## 29. Product maturity scores (0–10)

| Area | Score | Evidence |
|------|------:|----------|
| Product clarity | 3 | Three names; login ≠ analyst |
| Information architecture | 4 | Ops + AI mashed; dead V1 routes |
| UI quality | 6 | Clean Tailwind; generic CMS look |
| UX quality | 5 | Follow-up model good; gating/errors poor |
| Visual design | 5 | No design system; mixed purple/blue/emerald |
| Accessibility | 4 | Labels mixed; blank SAT; unnamed buttons |
| Responsive design | 5 | Hamburger &lt;1024; tables clip |
| AI UX | 7 | Context + DATA GAP; jargon + fake pipeline |
| Analytics UX | 4 | Engine 8; dashboard 404; no briefing |
| Data trust | 8 | Governed metrics, independent SQL, honest gaps |
| Performance | 7 | R4-3 P50 775ms |
| Reliability | 4 | Dashboard router missing; optional auth |
| Error handling | 4 | 404 vs blank vs “Not authenticated” |
| Enterprise readiness | 3 | Signup, no SSO, no share |
| Security UX | 2 | Unauthenticated SAP answers |
| Collaboration | 2 | No share/save UI |
| Actionability | 3 | Stops at table |
| Differentiation | 8 | Governed SAP NL + invoice ops (if told) |
| **Overall product maturity** | **5** | Engine ahead of product |

---

## 30. Prioritized roadmap

### P0 — Fix immediately (production blockers)

**P0.1 Require auth on adaptive query**  
Problem: SAP extract is publicly queryable.  
Current: `get_current_user_optional`; live 200 without token.  
Why: Enterprise disqualifier; data leak.  
Solution: `get_current_user`; 401 with “Sign in to ask.” Do **not** change SQL.  
Risk: Low if JWT already sent from logged-in app.  
Effort: Low.  
Acceptance: Unauthenticated POST `/api/query/adaptive` → 401. Authenticated R3/R4-1/R4-2/R4-3 harnesses still 0 FAIL.

**P0.2 Restore dashboard router on zodiac-back**  
Problem: OpenAPI has no dashboard paths; UI 404.  
Current: `server.py` try/except on `dashboard.py` (~6k lines).  
Why: Primary nav item is dead.  
Solution: Split router or fix import; confirm `/api/v1/dashboard/v2/inbound` in `/openapi.json`.  
Risk: Medium (serverless size).  
Effort: Medium.  
Acceptance: Authenticated To ERP loads KPIs. No adaptive/SQL change.

**P0.3 Global session gate on admin shell**  
Problem: Chrome + Settings without user.  
Solution: `MainLayout` redirects to `/` when `!loading && !isAuthenticated`. SAT/settings never infinite-spinner.  
Acceptance: Logged-out `/dashboard` → login. No blank SAT.

### P1 — High-impact product/UX

- Rename nav: Intelligence / Ask data (keep route `/dashboard/ai`).  
- One product name on login (BridgeEDI) or honest dual: “BridgeEDI operations · Zodiac intelligence” — **decide, don’t mix**.  
- Disable or hide public signup; password reset.  
- Historical tab: either wire `time_scope` or remove.  
- Human follow-up labels; SAP names only in View SQL.  
- DATA GAP badge + keep recovery.  
- Cancel + retry.  
- Deduplicate summary.  
- Fix Intelligence KPI labels.  
- Drop “15-stage pipeline” or bind to real `stage_timings`.

### P2 — Differentiation

- Executive briefing (supported findings only).  
- Saved analyses from `ada_*` threads.  
- CSV/PDF export of the current result.  
- Metric “How calculated?” popover (Revenue = NETWR, etc.).  
- Unify comparison chat into Full Chat.

### P3 — Later

- SSO, audit log, scheduled briefing, role workspaces, insight-to-ticket.  
- **Not now:** NL dashboard builder, invented aging, R4-4, hardcoded risk thresholds.

---

## 31. Detailed acceptance criteria (examples)

**P0.1**  
Before: unauthenticated inventory SQL 200.  
After: 401; Full Chat shows sign-in.  
Test: curl without token; curl with token still PASS R4-3 fingerprint `inventory_sales_comparison`. Desktop + existing harness.

**P0.2**  
Before: OpenAPI 0 dashboard paths.  
After: inbound/outbound/business present; authenticated Dashboard To ERP not 404.  
R3/R4 harnesses unchanged.

**P1 DATA GAP UI**  
Before: gap looks like empty analysis.  
After: visible “Data limitation” (not error). Aging still DATA GAP; next inventory question PASS.

**P1 jargon**  
Before: chip `Monthly trend (YYYY-MM from VBRK.FKDAT)`.  
After: `Monthly trend`. SQL still contains FKDAT when View SQL opened.

---

## 32. R3 / R4-1 / R4-2 / R4-3 regression requirements

Any UI or auth change must re-run:

- R3: **23 PASS / 2 DATA GAP / 0 FAIL**
- R4-1: **47 PASS / 2 DATA GAP / 0 FAIL**
- R4-2: **40 PASS / 1 DATA GAP / 0 FAIL**
- R4-3: comparison, risk ranking, plant codes, aging DATA GAP, no turnover claims, no invented history

Never trade grain safety or DATA GAP honesty for prettier chat.

---

## 33. Recommended next phase (implementation sequence)

1. P0.1 adaptive auth  
2. P0.3 MainLayout gate  
3. P0.2 dashboard router live  
4. Broken states (SAT spinner, Axios 404 copy)  
5. Nav / naming  
6. Full Chat UX (chips, pipeline, duplicate summary, DATA GAP badge)  
7. Dashboard Business tab as secondary home once APIs live  
8. Explainability popovers  
9. Responsive/a11y on login + chat  
10. P2 briefing / save / export  

**Do not start R4-4 in that sequence.**

---

## 34. Implementation plan (second pass — still not implementing)

Order matches §33. Each change: isolated PR, harness green, no SQL semantics change unless P0.1 (auth wrapper only).

---

## 35. Final executive verdict

### WHAT THE PRODUCT IS TODAY

A production **invoice / CFDI / SAP operations console** branded Zodiac, plus a **governed SAP natural-language analyst** (Full Chat) that already refuses aging and net profit, compares inventory snapshots to billed activity, and holds product context across turns — while the website still introduces itself as a document CMS and, on live, will answer inventory SQL **without a login**.

### WHAT IT COULD BECOME

The only platform where a Mexico/SAP operator **and** a finance lead share one system: documents that move, and questions that are **allowed** to be answered — with the same grain rules.

### BIGGEST CURRENT WEAKNESS

**Unauthenticated access to the analytical data plane**, compounded by a missing dashboard API on the same host and a confused product name.

### BIGGEST PRODUCT OPPORTUNITY

Make Full Chat the **visible** product (clarity, trust chrome, briefing) without touching R3–R4-3 logic.

### MOST IMPORTANT 30-DAY PLAN

Auth on adaptive; session gate; restore dashboard routes; rename/clarify Intelligence; DATA GAP badge; human follow-ups; kill fake pipeline copy; hide or lock signup.

### MOST IMPORTANT 90-DAY PLAN

Executive briefing from existing intents; saved analyses; export; metric glossary; one AI surface; SSO design; portal vs admin IA cleanup; delete or redirect V1 invoice routes.

### DO NOT BUILD YET

NL dashboard generation; scheduled email intelligence; personalized five-persona workspaces; stock-out prediction; inventory aging from billing dates; R4-4; competitor-feature clones without a user job.

---

## 36. The question this audit must answer

**If a serious enterprise customer were given this product today:**

- **Trust:** DATA GAP honesty, grain-safe SQL, independent QA numbers, fast answers, snapshot language on inventory.  
- **Hesitate:** optional-auth SAP queries; Dashboard 404; public signup; JWT in localStorage; no SSO.  
- **Confuse:** Zodiac vs BridgeEDI; Generative AI vs Intelligence vs AI Ops; Historical; SAP chips; 15-stage pipeline.  
- **Impress:** “High inventory but low sales” as a ranking with caveats; aging refused; plant as WERKS codes with T001W gap; follow-up “Show their inventory” after profits.

**Ten changes that would most move it toward an enterprise AI BI platform:**

1. Require auth on adaptive query.  
2. Gate the admin shell.  
3. Put dashboard APIs back on production.  
4. One product name and one sentence on login that includes governed SAP Q&A.  
5. Make Intelligence/Full Chat the analytics home.  
6. Human-language follow-ups; SQL on demand.  
7. DATA GAP as a designed state.  
8. Honest loading (real timings or simple “Running query”).  
9. Executive briefing from **existing** R3–R4-3 intents.  
10. Save + export + (then) SSO.

All ten are justified by **this** codebase and **this** production behavior — not generic BI advice.
