# AI page agent implementation

The authenticated AI page now uses an OpenAI Responses function-calling loop by default. The model chooses whether to answer conversationally, inspect the catalog, execute a query, calculate, clarify, or continue investigating. A SQL error or failed answer validation becomes feedback for another decision in the same request.

The available tools are `list_tables`, `search_schema`, `describe_tables`, `run_readonly_sql`, and `calculate`. Conversation history, user preferences, pending clarifications, and the retained database analysis are supplied as context. Previous client-supplied rows are context only; current database claims require new tool evidence.

The frontend displays multiple supporting result tables, executed SQL, and a collapsible **Steps taken** view. It does not display hidden reasoning. Visible patent wording has also been changed from “USPTO” to “Patent Office”; the official filing link is retained.

## Runtime configuration

Set these on the **backend**, using the existing environment/secrets configuration:

```dotenv
OPENAI_API_KEY=<key from the funded OpenAI organization/project>
AI_ANALYST_AGENT_ENABLED=true
AI_ANALYST_AGENT_MODEL=gpt-6-astra
AI_ANALYST_AGENT_REASONING_EFFORT=medium
```

`AI_ANALYST_AGENT_ENABLED` defaults to true. The model override is optional; without it the existing analyst model policy is used. The current local configuration selects `gpt-6-astra`. The agent transport uses OpenAI; settings for other AI features do not change its provider. Keep API keys out of the frontend and chat. Update the backend deployment's secret and restart/redeploy the backend after changing configuration. A frontend deployment alone cannot fix API billing.

No Agent Builder workflow or new database migration is required. The application implements its own bounded loop using the [Responses function-calling API](https://developers.openai.com/api/docs/guides/function-calling).

Set `AI_ANALYST_AGENT_ENABLED=false` to use the existing legacy pipeline. Existing admin-only SQL override behavior is retained.

## Execution controls and practical limits

- Database connections and authenticated identity belong to the server. Tool arguments cannot choose an identity, tenant, connection string, or arbitrary database.
- SQL is parsed and checked against the tool-visible schema. Writes, multiple statements, locks, cross-database sources, administration/external-access functions, and unsupported functions are rejected.
- Credential/configuration tables and secret columns are excluded from SQL tools; stars expand to allowed columns.
- Every base relation with `user_id` is filtered with the authenticated server identity before joins, CTEs, OR conditions, or unions. Known application tables require their ownership field. Tables without ownership fields continue to rely on the existing database connection/access configuration.
- Queries use read-only transactions, statement timeouts, and bounded fetching. Each SQL result displays at most 200 rows and reports truncation.
- Each request permits at most 10 model decisions, 16 tool calls, and two final-answer correction attempts, within the existing investigation deadline (120 seconds by default). Successful identical tool calls are reused within the request. Cancellation stops additional decisions and tools at checkpoints.
- Final answers must select successful tool result IDs. Analytical intent and numerical evidence checks return feedback for correction. These checks reduce unsupported answers; they do not prove every business interpretation correct.
- Cached schema results are explicitly described as snapshots when the live catalog cannot be verified.
- During model outages, grounded catalog questions and arithmetic can continue locally. General conversation and analytical planning report the actual model failure.
- General knowledge uses the model's knowledge; web browsing, arbitrary terminal execution, and database writes are not agent tools in this implementation. It cannot guarantee an answer to every possible question.

## Validation and current API status

Backend regression and execution checks passed (289 tests), and frontend conversation/progress/result checks passed (22 tests). Agent checks include snapshot disclosure. TypeScript checking and the production frontend build passed. Real database verification passed catalog count, referential listing (“list those”), column inspection, and correction of an invalid-column query into a successful read-only count.

The initial database verification uses scripted model decisions with external model transport disabled. It validates actual tools and execution. Reports intentionally exclude business records and secrets.

The earlier **HTTP 429 / `credit_balance_exhausted`** blocker is now resolved for the configured key: the fresh literal-only provider probe returned **ready=true**, and the model listing included `gpt-6-astra`. No organization/project override was found in the checked configuration. See `zodiac-api/scripts/analyst_agent_provider_report.json`. The supplied Billing Overview screenshot shows a $9.99 API credit balance at capture time; there is no need to purchase another model to continue these checks.

Live model checks passed general conversation and a general explanation with all database access disabled. After the user explicitly approved sending schema names/columns and a VBRK aggregate count to OpenAI, the live database smoke check passed all five cases: greeting, catalog count, “list those” followup, executed VBRK row-count SQL, and a general question after SQL. The live verifier rejects SQL other than a single unfiltered COUNT(*) over VBRK, so it cannot return individual business records. See `zodiac-api/scripts/analyst_agent_chat_report.json` and `zodiac-api/scripts/analyst_agent_live_report.json`.

These are focused live checks, not proof that every business question will be interpreted correctly. Browser login/session behavior still uses the existing authenticated application flow. The local frontend responds on port 3000 and its configured backend on port 8003. Restart an older backend process to load the latest code and clear any cached quota failure before browser testing.

Useful checks from the backend directory:

```powershell
python scripts/probe_analyst_agent_provider.py
python scripts/verify_analyst_agent_runtime.py
python scripts/verify_analyst_agent_chat.py
# Sends approved schema/aggregate evidence to the configured OpenAI API:
python scripts/verify_analyst_agent_live.py
python -m pytest tests/test_analyst_agent.py -q
```

This implementation is saved locally. It has not been deployed or published by this task. Provider readiness and the focused live agent checks now pass. Deploy backend and frontend changes together when publishing the implementation.

## Vercel production environment update

Updated and verified the **Production** environment of `https://vercel.com/andys-projects-45836994/zodiac-back` through the authenticated browser session:

- `AI_ANALYST_AGENT_ENABLED=true` (Config)
- `AI_ANALYST_AGENT_MODEL=gpt-6-astra` (Config)
- `AI_ANALYST_AGENT_REASONING_EFFORT=medium` (Config)
- Existing `OPENAI_API_KEY` replaced with the locally tested key as a write-only **Secret**, after the user explicitly approved that transfer.

Other variables and environments were not changed. Vercel confirmed the settings were saved and requires a new deployment to apply them. No redeployment or source-code publication was performed as part of this environment-only update. The current production source observed in the dashboard is the older `fix/ai-analyst-live` revision `b360e10`; the new agent files are still local.

The installed CLI is authenticated as `karthikeyanasha24` and cannot access Andy's requested scope. These changes were made through the browser account, not that CLI account. Verify the destination account/project link before any later CLI deployment. Proof of the non-secret configuration is saved in `vercel-agent-production-settings.jpg`; the API key is not included in the image or this document.

## 2026-10-11 analytics repairs and acceptance status

The local agent still uses `gpt-6-astra`, medium reasoning, through the Responses API. The Next.js page runs at `http://localhost:3000/dashboard/ai`; its backend proxy targets FastAPI on port 8003. The agent owns five tools: catalog listing, schema search, table/column inspection, read-only SQL, and calculations. It has no arbitrary terminal or web-browsing tool.

Repairs made during the requested browser acceptance tests:

- Coordinated grouping lists preserve country, customer, and product together, and customer with industry.
- PostgreSQL-normalized SUBSTRING dates and complete calendar-year BETWEEN predicates pass date/grain validation. A year appearing only in a title does not establish a date filter.
- An unspecified ranking display size is no longer treated as an exact user-requested count. Explicit top-N requirements remain checked, including qualified ROW_NUMBER rank filters.
- Ranking row counts are checked separately for SAP client and currency; legitimate same-currency rows from different clients no longer cause a false rejection.
- Tool purposes explain intermediate work. They are no longer parsed as independent user requests; schema, SQL structure, fanout, function, ownership, and read-only execution controls remain at the tool boundary. The final selected analytical evidence is checked against the actual user request.
- The model receives verified metric contracts and explicit guidance about signed values, currency separation, requested dimensions, and complete requests versus short follow-ups.
- Schema inspection accepts multiple column-name fragments. Long prior SQL remains available for repairs and SQL follow-ups. Large result evidence is sampled for the model while the application retains bounded results for display.
- Standard deterministic trim functions are allowed. SAP client identifiers are excluded from chart measures. Steps taken can show bounded validation feedback while withholding raw database connection exceptions.
- Year-over-year wording does not invent a monthly output grain.

Validation: the broader selected backend regression set passed **241 tests**. After the final predicate/agent-purpose regression additions, the focused agent and ranking set passed **52 tests**. Frontend checks passed **23 tests**, and TypeScript checking passed. These are local automated checks, not a claim that the 19 live business cases have all passed.

Observed live browser results: questions **1–4, 6, and 7** completed successfully. Question 5 initially inherited the previous year; the context instructions were then corrected and its final rerun is pending. Question 8 failed before the latest ranking and tool-purpose repairs; a later rerun was submitted, but its final browser result was not observed. Questions 9–19 still require acceptance testing, including the profit case. No independent numeric oracle check or production deployment was completed during this test pass.

The last browser status check was blocked because automatic approval review could not run after the Codex usage limit was reached. It was a review availability failure, not a determination that the browser action was unsafe. The user is continuing manual testing. Existing production environment settings were saved earlier; that does not deploy these local code changes.

Screenshots and DOM captures are under `artifacts/ai-agent-2026-10-11/`. They contain local test data and are excluded from Git in that directory. Keep follow-ups 9–11 in the same conversation after question 5, and clear chat between the requested groups.

Next improvements, in priority order: finish the 19-case acceptance run with independently checked expected totals; formalize metric definitions and missing-cost coverage for profit; verify cohort/filter continuity for follow-ups; persist structured query errors, latency, and token costs for diagnosis; then tune retry behavior and model routing using measured results.

## Main files

- `zodiac-api/app/services/analyst_agent.py`: decision/tool/evidence loop, memory, answer validation, outage behavior.
- `zodiac-api/app/services/analyst_agent_provider.py`: Responses transport and rollback flag.
- `zodiac-api/app/services/analyst_agent_sql.py`: SQL/schema and ownership boundary.
- `zodiac-api/app/api/adaptive_query.py`: authenticated integration, shared read-only executor, persistence.
- `zodiac-front/src/components/DashboardAIAnalysis.tsx`: result sets and steps display.
- `zodiac-api/tests/test_analyst_agent.py`: agent and execution tests.
- `zodiac-api/scripts/analyst_agent_runtime_report.json`: real database checks with scripted decisions.
- `zodiac-api/scripts/analyst_agent_live_report.json`: approved live model/database smoke checks, without individual business records.

## 2026-10-11 chat layout and conversational memory improvements

Implemented locally after the user reported the agent working:

- A centered conversation, neutral user bubbles, plain assistant answers, and a message composer that stays in the viewport. A dynamic viewport height fixes long chats pushing the composer off-screen, including on mobile.
- Header controls jump to the top or bottom; a floating Latest message control appears when reading earlier messages. Automatic following applies only near the bottom, and observes content/viewport size changes. Reduced-motion preferences are respected.
- Users can draft the next question during an investigation; cancellation remains available. Enter sends, Shift+Enter inserts a newline, and IME composition remains protected. Copy answer gives explicit success/failure feedback.
- Primary and supporting data tables are expandable, retaining filters, exports, SQL disclosures, and execution steps. Clarifications display the complete generated answer.
- Conversational memory reserves user preferences and allocates the remaining budget from newest to oldest, then returns turns in chronological order. Old lengthy results cannot consume the budget before recent follow-ups. Excerpts are explicitly marked. Memory remains bounded to 40 candidate turns, 6,000 characters per turn, and the existing caller prompt budget; it is not unlimited memory.

Validation: **107 backend tests**, **27 frontend tests**, TypeScript checking, and the full production build passed. The initial sandbox build compiled but could not spawn its type-check worker; the build completed when allowed to launch that worker. Browser checks covered top/latest navigation, multiline drafting, data disclosure, and 390x844 / 1440x900 layouts. Both layouts kept the document within the viewport without horizontal overflow. Temporary viewport overrides were reset. Screenshots are `artifacts/ai-agent-2026-10-11/chat-layout.jpg`, `chat-mobile.jpg`, and `chat-desktop.jpg`.

The previously submitted question 8 now has a completed answer visible in persisted local history; this is UI evidence, not an independent verification of every total. The entire 19-case business acceptance suite has not been rerun in this pass. These changes have not been deployed to Vercel.

Further accuracy improvements should start with agreed sales/profit/cancellation definitions and independent expected answers for the business acceptance questions. Measure model/tool time and token cost before introducing model routing or wider caching. Keep cached business results scoped to authorization and data freshness; do not equate a successful response with a verified business total.

## 2026-10-11 wider responsive chat and chart styling

The approved wider layout uses up to 1,280 pixels for conversations and analytical evidence, an 896-pixel composer, and a 768-pixel cap for prose. Tables retain their own horizontal scrolling, with keyboard-accessible scroll regions, rounded frames, clearer row spacing, mobile-visible filters, and larger export/pagination controls. KPI cards adapt to the available card width instead of squeezing long values into fixed columns.

Charts now measure their actual container width. The old 700-pixel minimum canvas width is removed; heights, axis widths, donut sizes, category labels, and brush windows adapt to the available space. Tooltips and table views retain full values and labels. Chart headers wrap their type controls, show currency badges, and provide a working CSV export. Unsupported prior chart-type overrides fall back to a supported type when the selected dataset changes. Series redraw animations are disabled after an animation error was observed during repeated viewport changes; the card fade respects reduced-motion preferences.

Validation: the selected **30 frontend tests** passed, including layout/CSV checks; the final TypeScript and production build passed. The real chat passed 320x844, 390x844, 768x1024, 1440x900, and 844x390 viewport checks without document overflow or a hidden composer. The same device checks covered bar, line, area, donut, and horizontal charts using explicitly labeled synthetic data. After the animation change, seven successive viewport changes retained all five rendered charts without overflow. Mobile filtering reduced the existing displayed table from 19 data rows to 2 matching rows and restored the full rows when cleared. The downloaded synthetic chart CSV was checked for exact amounts, negative values, and currency.

Browser testing used temporary agent tabs; the original chat history was preserved. The temporary development preview route was removed and viewport overrides were reset. Screenshots and numeric layout checks are saved privately under `artifacts/ai-agent-2026-10-11/`: `wide-chat-desktop.jpg`, `wide-chat-phone.jpg`, `wide-chat-final.jpg`, `charts-desktop-styled.jpg`, `charts-phone.jpg`, `chat-responsive-checks.json`, and `chart-responsive-checks.json`. The wider desktop screenshot predates the final explicit prose-width enforcement; `wide-chat-final.jpg` shows the existing chat after that change at its normal window size.

These are local presentation changes. No provider switch, database calculation change, new model request, or Vercel deployment was performed in this pass. The 19-case business acceptance suite remains separate from this styling validation.
