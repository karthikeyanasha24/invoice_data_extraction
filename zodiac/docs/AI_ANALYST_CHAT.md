# AI Analyst conversation improvements

The AI Analyst uses model-generated replies for general conversation, knowledge,
writing and coding, and grounded database answers through the existing SQL pipeline.
No question-specific answer templates or fixed database results were added.

## Conversation and database context

- Every reply keeps its conversation context, including explanations and unsuccessful analyses.
- Changing analytical topics clears old SQL filters while retaining the conversation.
- The browser remembers the active thread separately for each signed-in user across sessions.
- The API can restore context from that user's saved thread when browser context is unavailable.
- User and assistant turns are stored together in a transaction with a database lock protecting turn indices.
- Responses retain their mode, original row count, plan and result sample across reloads.
- Recent prompt memory is bounded to 40 messages and approximately 26,000 characters. Older turns remain in the database; this change does not implement unlimited recall or memory across separate chats.
- Stored result samples are labeled as samples. Full-result frequency/ranking claims require complete evidence rather than an incomplete sample.
- Explanatory follow-ups reach the response model instead of receiving a generic “reusing previous rows” reply.

## Progress and reliability

The progress panel displays the backend's current step, elapsed time, time on the
step, and recently completed steps. Polls do not overlap or reset progress on a
temporary connection failure. Cancel stops the local request and leaves a visible
stopped response; backend checkpoints stop further work, with in-flight model and
SQL calls bounded by their timeouts.

Model transport calls no longer overwrite table/column selection with
“Understanding.” Failed providers have a temporary cooldown and then recover;
empty outputs fall back to the other configured provider. OpenAI SDK retries are
disabled because the application owns the overall deadline and provider fallback,
consistent with [OpenAI retry guidance](https://developers.openai.com/api/docs/guides/rate-limits).

SQL TRIM sanitization now handles nested numeric expressions such as
`TRIM(COALESCE(amount, '0'))`. It preserves quoted strings, comments and standard
SQL TRIM syntax. Type errors are classified from the error message rather than
the attached SQL. Database answers are withheld if final result validation fails.

Optional tuning settings are documented in `zodiac-api/.env.example`:
`AI_CHAT_PROVIDER`, `AI_LLM_CALL_TIMEOUT_SECONDS`, `AI_RESPONSE_MAX_TOKENS`, and
`AI_JSON_MAX_TOKENS`. Existing keys, databases and model selections were retained.
Restart the API and frontend processes to load the changes.

## Validation

Final targeted checks passed: **112 backend tests**, **56 frontend tests**, and
the standard TypeScript source check. Git whitespace checks also pass.

Run the targeted backend checks from `zodiac-api`:

```powershell
python -m pytest -p no:cacheprovider tests/test_analyst_chat_reliability.py tests/test_llm_first_understanding.py tests/test_adaptive_architecture.py tests/test_followup_routing_golden_cases.py tests/test_four_stage_db_pipeline.py tests/test_adaptive_structured_sql.py tests/test_adaptive_auth.py tests/test_ai_native_pipeline.py tests/test_schema_violations_cast.py -q
```

Run source and frontend checks from `zodiac-front`:

```powershell
npx tsc --noEmit --incremental false
node --experimental-strip-types --test --test-isolation=none src/lib/adaptiveChatContext.test.ts src/lib/analystProgress.test.ts src/lib/apiErrors.test.ts src/lib/followupChips.test.ts src/lib/navConfig.test.ts src/lib/savedAnalyses.test.ts src/lib/analysisTrust.test.ts src/lib/investigationLaunch.test.ts src/lib/pageTitles.test.ts
```

The PostgreSQL nested-numeric-TRIM regression passed against the configured
database before the user selected local-only testing. Model requests from the
sandbox failed to connect; automatic approval rejected external model verification,
and the user chose local tests only. Therefore live model answers, latency and
end-to-end database chat quality remain unverified.

Webpack compilation passed during the build attempt. Full production build
verification was interrupted by exhausted disk space and a worker memory failure;
source TypeScript checking passes. Only generated webpack cache was removed to
recover space. Existing legacy tests that await the synchronous API or expect
general conversation to be rejected are outside this targeted verification.
