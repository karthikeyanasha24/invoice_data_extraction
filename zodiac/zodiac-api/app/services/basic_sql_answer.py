"""Model-free replay and SQL patterns, with optional Basic-only model hints."""
from __future__ import annotations

import re
from typing import Any, Callable

_SWITCH = "Agentic can also investigate this request using API credits."
_ABOUT = re.compile(
    r"(?i)\b("
    r"hard(?:ed)?\s*-?\s*coded?|"
    r"are you (?:an? )?(?:ai|llm|bot|model)|"
    r"how (?:do|does) (?:you|this|basic) work|"
    r"what can (?:you|basic) (?:answer|do)|"
    r"do you use (?:a |an )?(?:model|llm|credits|api)|"
    r"(?:list|give|show).{0,40}questions|"
    r"questions to ask|sample questions|example questions"
    r")\b"
)
_EXAMPLE_QUESTIONS = (
    "total billed sales in 2001",
    "billed sales by year",
    "billed sales by month in 2001",
    "billed sales by quarter in 2001",
    "top 10 customers by billed sales in 2001",
    "top countries by billed sales",
    "top materials by billed sales",
    "compare billed sales in 2001 and 2002",
    "how many billing documents in 2001",
    "how many billing documents by year",
    "list customer names",
    "list customers in Germany",
    "customers above the average billed sales",
    "top billing items by billed sales",
    "customers and industries by billed sales",
    "billed sales by customer in 2001",
    "sales by country",
    "billed sales for Germany in 2001",
    "how much did we bill in 2001",
    "customers with no billing in 2001",
)


def basic_scope_reply(question: str) -> str:
    from .basic_question_catalog import DATABASE_QUESTIONS
    examples = "\n".join(f"- {item}" for item in (*_EXAMPLE_QUESTIONS, *(q for _, q in DATABASE_QUESTIONS)))
    if re.search(r"(?i)questions", question or ""):
        return "Basic can run these without API credits:\n" + examples
    return (
        "Basic retrieves verified questions and runs billing queries without API credits. Try one of these:\n"
        + examples
        + "\nEquivalent questions reuse a verified query with the same filters and fresh database results. "
        "New questions use the configured Basic model. If no Basic model is configured and paid fallback is enabled, Agentic may run and use credits. Save a checked result with Reuse it in Basic Model to answer that question again without model tokens."
    )


def continue_basic_question(question: str, previous: str) -> str:
    """Turn a short follow-up into a complete billing question. Full questions stay unchanged."""
    q = re.sub(r"\s+", " ", (question or "").strip())
    prev = re.sub(r"\s+", " ", (previous or "").strip())
    if not q or not prev:
        return q
    ql = q.lower()
    pronoun = bool(re.search(r"\b(?:it|that|those|them|same|this)\b", ql))
    fragment = bool(pronoun or re.match(
        r"(?:by|per|break|compare|what about|same for|and|in|for|show(?:\s+(?:that|it))?)\b",
        ql,
    ))
    short = len(q.split()) <= 8
    if not fragment:
        return q
    years = re.findall(r"\b(?:19|20)\d{2}\b", q)
    prev_years = re.findall(r"\b(?:19|20)\d{2}\b", prev)
    if re.search(r"\bcompare\b", ql) and (pronoun or short):
        year = years[0] if years else ""
        prior = prev_years[-1] if prev_years else ""
        if len(prev_years) == 1 and year and prior != year:
            # Preserve the metric, entities, currency, ranking, and grouping.
            # Never turn a profit comparison into billed sales or invent a year.
            return "compare " + re.sub(r"\b" + prior + r"\b", f"{prior} and {year}", prev, count=1)
        return q
    grains = (
        ("quarter", r"\bquarters?\b|\bquarterly\b"),
        ("month", r"\bmonths?\b|\bmonthly\b"),
        ("year", r"\byears?\b|\byearly\b"),
        ("customer", r"\bcustomers?\b"),
        ("country", r"\bcountr(?:y|ies)\b"),
        ("material", r"\bmaterials?\b"),
        ("industry", r"\bindustr(?:y|ies)\b"),
    )
    grain = next((name for name, pattern in grains if re.search(pattern, ql)), None)
    if grain and (pronoun or re.match(r"(?:by|per|break|show|and)\b", ql) or short):
        same_kind = (
            r"\bby\s+(?:months?|quarters?|years?)\b"
            if grain in {"month", "quarter", "year"}
            else r"\bby\s+(?:customers?|countr(?:y|ies)|materials?|industr(?:y|ies))\b"
        )
        base = re.sub(same_kind, f"by {grain}", prev, count=1, flags=re.I)
        if not re.search(rf"\bby\s+{grain}s?\b", base, re.I):
            base = f"{base} by {grain}"
        return base
    if years and (pronoun or short) and not re.search(r"\b(?:sales|revenue|billing|billed|invoice|customer|order)\b", ql):
        if prev_years:
            return re.sub(r"\b(?:19|20)\d{2}\b", years[0], prev, count=1)
        return f"{prev} in {years[0]}"
    currency = re.search(r"\b(?:in|for)\s+(?:currency\s+)?([A-Z]{3})\b", q)
    if currency and (pronoun or short):
        return f"{prev} in {currency.group(1)}"
    country = re.search(
        r"\b(?:in|for)\s+(Germany|France|Italy|Spain|United States|USA|United Kingdom|UK)\b",
        q,
        re.I,
    )
    if country and (pronoun or short):
        return f"{prev} for {country.group(1)}"
    if pronoun and short:
        return f"{prev}. {q}"
    return q


def prepare_basic_question(question: str) -> str:
    """Map everyday billing phrases onto the words the saved patterns recognize."""
    q = question or ""
    if re.search(r"\b(?:how many|number of|count)\b", q, re.I):
        return q
    if re.search(r"\bhow much\b", q, re.I) and re.search(r"\bbill", q, re.I) and not re.search(r"\b(?:sales|revenue)\b", q, re.I):
        return re.sub(r"\bbill(?:ed|ing|s)?\b", "billed sales", q, count=1, flags=re.I)
    return q


def recall_saved_sql(question: str, examples: list[dict] | None) -> str:
    """Free retrieval with conservative intent and filter matching."""
    from .basic_rag import recall_sql
    return recall_sql(question, examples)


def run_basic_sql_answer(
    question: str,
    *,
    execute: Callable[[str], dict],
    previous_question: str = "",
    previous_sql: str = "",
    prior_examples: list[dict] | None = None,
    local_agent: Callable[..., dict] | None = None,
    field_lookup: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    from .four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
    from .investigation_budget import block_paid_models, paid_models_blocked, restore_paid_models
    from .schema_intelligence_registry import get_schema_registry
    from .semantic_requirements import enrich_semantic_with_requirements

    if _ABOUT.search(question or ""):
        answer = basic_scope_reply(question)
        return _payload(question, "SUCCESS", answer, "", [], mode="general_chat")

    if previous_question and re.search(r"\bcompare\b.*\b(?:it|that|those|them)\b.*\byear\b", question, re.I) and not re.search(r"\b(?:19|20)\d{2}\b", question):
        return _payload(question, "CLARIFICATION", "Which year should I compare with the previous result? Include the year, for example: compare it with 2002.", "", [], mode="clarification")

    token = block_paid_models()
    try:
        resolved = continue_basic_question(question, previous_question)
        if resolved != (question or "").strip():
            previous_sql = ""
        question = prepare_basic_question(resolved)
        semantic = enrich_semantic_with_requirements(question)
        tables = [
            str(item.get("table") or "")
            for item in get_schema_registry().lightweight_table_catalog(include_operational=False)
            if item.get("table")
        ]
        ctx = VerifiedDbContext(question=question, tables=tables, semantic_requirements=semantic, prior_sql=previous_sql or "")
        from .basic_rag import mixed_currency_billing_total, profit_question_without_profit_sql, retrieve_examples, replayable_steps
        def safe_examples(embeddings=False):
            candidates = retrieve_examples(question, prior_examples, use_embeddings=embeddings)
            return [example for example in candidates if not any(
                mixed_currency_billing_total(step.get("sql", ""))
                for step in (example.get("steps") or [example])
            )]

        retrieved = safe_examples()
        reused_example = next((e for e in retrieved if e["reusable"]), None)
        taught_steps = [step for step in (reused_example or {}).get("steps") or [] if isinstance(step, dict)]
        if len(taught_steps) > 1:
            if not replayable_steps(question, taught_steps):
                if local_agent is not None:
                    return _run_local(local_agent, retrieved)
                return _uncovered(question)
            replay = _replay_investigation(question, taught_steps, execute)
            if replay.get("answer_status") == "CANNOT_ANSWER" and local_agent is not None:
                return _run_local(local_agent, retrieved)
            return replay
        sql = reused_example["sql"] if reused_example else ""
        reused = bool(sql)
        if not sql:
            sql = pipeline3_sql_generation(question, ctx, templates_only=True) or ""
        if sql and profit_question_without_profit_sql(question, [{"sql": sql}]):
            # The generic measure template can otherwise treat an AR clearing
            # amount as "highest profit". Require a real profit calculation.
            sql = ""
        if not sql.strip():
            if local_agent is not None:
                retrieved = safe_examples(embeddings=True)
                field_hint = field_lookup(question) if field_lookup else None
                return _run_local(local_agent, retrieved, field_hint)
            return _uncovered(question)
        if not paid_models_blocked():
            raise RuntimeError("Basic mode failed to block paid models")
        executed = (_invoke_execute(execute, sql.strip().rstrip(";"), reused_example) if reused_example
                    else execute(sql.strip().rstrip(";"))) or {}
        if not executed.get("ok"):
            answer = "Basic mode did not call a model. The saved query was rejected by the database. " + str(executed.get("error") or "") + " " + _SWITCH
            if local_agent is not None:
                return _run_local(local_agent, retrieved)
            return _payload(question, "CANNOT_ANSWER", answer, executed.get("sql") or sql, [])
        rows = executed.get("rows") or []
        if rows:
            method_note = ("Basic reused a similar question you already asked" if reused
                           else "Basic ran a supported SQL pattern")
            answer = f"Verified database result: {len(rows)} row(s). {method_note} and did not call a model."
            status = "SUCCESS"
        else:
            answer = "No matching records were found in the connected data for this request. Basic mode did not call a model."
            status = "SUCCESS_EMPTY"
        result = _payload(question, status, answer, executed.get("sql") or sql, rows, executed.get("source") or "business", sql)
        result["sql_status"] = "executed"
        result["meta"]["result_truncated"] = bool(executed.get("truncated"))
        result["meta"]["retrieval"] = {"reused": reused, "examples": len(retrieved),
                                      "method": retrieved[0]["retrieval"] if retrieved else "none"}
        from .analyst_evidence import grounded_answer
        if rows:
            count_row = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
            count_key = next((key for key in ("billing_document_count", "sales_order_count")
                              if key in count_row and len(count_row) == 1), None)
            if count_key is not None:
                label = "billing documents" if count_key == "billing_document_count" else "sales orders"
                result["answer"] = result["summary"] = (
                    f"{count_row[count_key]} {label} match the requested filters.\n\n"
                    f"Verified database count. {method_note} and did not call a model."
                )
            else:
                result["answer"] = result["summary"] = grounded_answer([
                    {"rows": rows, "truncated": bool(executed.get("truncated"))}
                ]) + "\n\n" + answer
        if executed.get("analysis_plan") and result.get("agent_results"):
            result["agent_results"][0]["analysis_plan"] = executed["analysis_plan"]
        return result
    finally:
        restore_paid_models(token)


def _invoke_execute(execute, sql, step):
    import inspect
    # Detect the callback signature before running it. Retrying on TypeError
    # could execute SQL twice when the error originated inside the executor.
    try:
        inspect.signature(execute).bind(sql, step)
    except TypeError:
        return execute(sql) or {}
    return execute(sql, step) or {}


def _replay_investigation(question, steps, execute):
    """Rerun every checked query from a taught investigation. No model call."""
    results = []
    for index, step in enumerate(steps, start=1):
        sql = str(step.get("sql") or "").strip().rstrip(";")
        executed = _invoke_execute(execute, sql, {**step, "checked_investigation": True})
        if not executed.get("ok"):
            answer = "Basic mode did not call a model. A checked query in this taught investigation was rejected by the database. " + str(executed.get("error") or "") + " " + _SWITCH
            return _payload(question, "CANNOT_ANSWER", answer, executed.get("sql") or sql, [])
        rows = executed.get("rows") or []
        results.append({
            "id": f"result_{index}",
            "kind": "analysis",
            "source": step.get("source") or executed.get("source") or "business",
            "purpose": step.get("purpose") or "",
            "unscoped_sql": sql,
            "sql": executed.get("sql") or sql,
            "rows": rows,
            "row_count": len(rows),
            "analysis_plan": executed.get("analysis_plan") or step.get("analysis_plan"),
            "truncated": bool(executed.get("truncated")),
            "primary": bool(step.get("primary")),
        })
    primary = next((item for item in results if item["primary"]), results[-1])
    total_rows = sum(len(item["rows"]) for item in results)
    if total_rows:
        answer = (
            f"Verified database result: {len(results)} checked queries, {total_rows} row(s). "
            "Basic reused a similar question you already asked and did not call a model."
        )
        status = "SUCCESS"
    else:
        answer = "No matching records were found in the connected data for this request. Basic mode did not call a model."
        status = "SUCCESS_EMPTY"
    result = _payload(question, status, answer, primary["sql"], primary["rows"], primary["source"], primary["unscoped_sql"])
    result["sql_status"] = "executed"
    result["agent_results"] = results
    result["agent_primary_result_id"] = primary["id"]
    result["meta"]["retrieval"] = {"reused": True, "examples": 1, "method": "canonical", "queries": len(results)}
    result["meta"]["result_truncated"] = any(item["truncated"] for item in results)
    from .analyst_evidence import grounded_answer
    result["answer"] = result["summary"] = grounded_answer(results) + "\n\n" + answer
    return result


def _run_local(local_agent, retrieved, field_hint=None):
    from .basic_local_provider import use_local_agent, restore_local_agent
    local_token = use_local_agent()
    try:
        if field_hint is not None:
            result = local_agent(retrieved, field_hint)
        else:
            result = local_agent(retrieved)
        result.setdefault("query_plan", {})["analysis_method"] = "basic"
        meta = result.setdefault("meta", {})
        gemini_called = bool(isinstance(field_hint, dict) and field_hint.get("called"))
        meta.update(analysis_method="basic", credits_used=gemini_called)
        if isinstance(field_hint, dict) and field_hint.get("field"):
            meta["gemini_field_lookup"] = {key: field_hint.get(key) for key in ("called", "status", "field")}
        if meta.get("provider") not in {"local_catalog", "local_calculator"}:
            from .basic_hosted_provider import basic_provider
            meta["provider"] = basic_provider()
        if meta.get("provider") == "groq":
            meta.update(free_quota_used=True, cost_basis="operator-declared Groq free plan")
            from .investigation_budget import current_budget
            budget = current_budget()
            failure = str((budget.diagnostics.get("basic_provider_error") if budget else None) or "")
            if result.get("answer_status") == "CANNOT_ANSWER" and failure.startswith("Basic's"):
                result["answer"] = result["summary"] = failure
        elif (meta.get("provider") == "ollama"
              and result.get("answer_status") == "CANNOT_ANSWER"
              and result.get("failure_class") == "UNDERSTANDING_MODEL_FAILED"):
            result["answer"] = result["summary"] = (
                "Basic's local Ollama model could not complete this new question. "
                "Checked questions and supported SQL patterns still work without a model call. "
                "Try a simpler question or teach Basic a checked Agentic answer."
            )
        result["llm_calls"] = int(result.get("llm_calls") or 0) + int(gemini_called)
        meta["model_calls"] = result["llm_calls"]
        if gemini_called:
            from .analyst_usage import usage_summary
            meta["usage"] = usage_summary()
        meta["retrieval"] = {"examples": len(retrieved), "method": retrieved[0]["retrieval"] if retrieved else "none"}
        return result
    finally:
        restore_local_agent(local_token)


def _uncovered(question: str) -> dict[str, Any]:
    answer = (
        "Basic found no taught query or billing pattern for this request. Its model is not configured. "
        "Configure Basic's model, or teach it a checked query, to answer this question. " + _SWITCH
    )
    result = _payload(question, "SUCCESS", answer, "", [], mode="general_chat")
    result["meta"]["needs_agent"] = True
    return result


def _payload(question: str, status: str, answer: str, sql: str, rows: list, source: str = "business", unscoped: str = "", mode: str = "database_analysis") -> dict[str, Any]:
    body = {
        "pipeline": "basic_sql",
        "mode": mode,
        "answer_status": status,
        "answer": answer,
        "summary": answer,
        "sql": sql,
        "data": rows,
        "rowCount": len(rows),
        "llm_calls": 0,
        "query_plan": {"effective_question": question, "analysis_method": "basic"},
        "meta": {"analysis_method": "basic", "model_calls": 0, "credits_used": False, "usage": {"total_tokens": 0, "calls": []}},
    }
    if sql and status.startswith("SUCCESS"):
        body["agent_results"] = [{
            "id": "result_1", "kind": "analysis", "source": source,
            "unscoped_sql": unscoped or sql, "sql": sql, "rows": rows,
        }]
        body["agent_primary_result_id"] = "result_1"
    return body
