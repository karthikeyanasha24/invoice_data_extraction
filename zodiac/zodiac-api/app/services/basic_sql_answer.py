"""Credit-free answers. No paid model, including for questions Basic cannot cover."""
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
    examples = "\n".join(f"- {item}" for item in _EXAMPLE_QUESTIONS)
    if re.search(r"(?i)questions", question or ""):
        return "Basic can run these without API credits:\n" + examples
    return (
        "Basic retrieves verified questions and runs billing queries without API credits. Try one of these:\n"
        + examples
        + "\nEquivalent questions reuse a verified query with the same filters and fresh database results. "
        "A configured Basic model can investigate new questions using retrieved examples and database tools. Teach a checked query to answer that question again without model tokens."
    )


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
    local_agent: Callable[[list[dict]], dict] | None = None,
) -> dict[str, Any]:
    from .four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
    from .investigation_budget import block_paid_models, paid_models_blocked, restore_paid_models
    from .schema_intelligence_registry import get_schema_registry
    from .semantic_requirements import enrich_semantic_with_requirements

    if _ABOUT.search(question or ""):
        answer = basic_scope_reply(question)
        return _payload(question, "SUCCESS", answer, "", [], mode="general_chat")

    token = block_paid_models()
    try:
        question = prepare_basic_question(question)
        semantic = enrich_semantic_with_requirements(question)
        tables = [
            str(item.get("table") or "")
            for item in get_schema_registry().lightweight_table_catalog(include_operational=False)
            if item.get("table")
        ]
        ctx = VerifiedDbContext(question=question, tables=tables, semantic_requirements=semantic, prior_sql=previous_sql or "")
        from .basic_rag import retrieve_examples
        retrieved = retrieve_examples(question, prior_examples, use_embeddings=False)
        sql = next((e["sql"] for e in retrieved if e["reusable"]), "")
        reused = bool(sql)
        if not sql:
            sql = pipeline3_sql_generation(question, ctx, templates_only=True) or ""
        if not sql.strip():
            if local_agent is not None:
                retrieved = retrieve_examples(question, prior_examples)
                return _run_local(local_agent, retrieved)
            return _uncovered(question)
        if not paid_models_blocked():
            raise RuntimeError("Basic mode failed to block paid models")
        executed = execute(sql.strip().rstrip(";")) or {}
        if not executed.get("ok"):
            answer = "Basic mode did not call a model. The saved query was rejected by the database. " + str(executed.get("error") or "") + " " + _SWITCH
            if local_agent is not None:
                return _run_local(local_agent, retrieved)
            return _payload(question, "CANNOT_ANSWER", answer, executed.get("sql") or sql, [])
        rows = executed.get("rows") or []
        if rows:
            source_note = "a similar question you already asked" if reused else "a saved query pattern"
            answer = f"Verified database result: {len(rows)} row(s). Basic reused {source_note} and did not call a model."
            status = "SUCCESS"
        else:
            answer = "No matching records were found in the connected data for this request. Basic mode did not call a model."
            status = "SUCCESS_EMPTY"
        result = _payload(question, status, answer, executed.get("sql") or sql, rows, executed.get("source") or "business", sql)
        result["sql_status"] = "executed"
        result["meta"]["result_truncated"] = bool(executed.get("truncated"))
        result["meta"]["retrieval"] = {"reused": reused, "examples": len(retrieved),
                                      "method": retrieved[0]["retrieval"] if retrieved else "none"}
        if executed.get("analysis_plan") and result.get("agent_results"):
            result["agent_results"][0]["analysis_plan"] = executed["analysis_plan"]
        return result
    finally:
        restore_paid_models(token)


def _run_local(local_agent, retrieved):
    from .basic_local_provider import use_local_agent, restore_local_agent
    local_token = use_local_agent()
    try:
        result = local_agent(retrieved)
        result.setdefault("query_plan", {})["analysis_method"] = "basic"
        meta = result.setdefault("meta", {})
        meta.update(analysis_method="basic", credits_used=False)
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
        meta["model_calls"] = result.get("llm_calls", 0)
        meta["retrieval"] = {"examples": len(retrieved), "method": retrieved[0]["retrieval"] if retrieved else "none"}
        return result
    finally:
        restore_local_agent(local_token)


def _uncovered(question: str) -> dict[str, Any]:
    answer = (
        "Basic found no taught query or billing pattern for this request. Its model is not configured. "
        "Configure Basic's free-tier model, or teach it a checked query, to answer this question. " + _SWITCH
    )
    return _payload(question, "SUCCESS", answer, "", [], mode="general_chat")


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
    if rows and sql:
        body["agent_results"] = [{
            "id": "result_1", "kind": "analysis", "source": source,
            "unscoped_sql": unscoped or sql, "sql": sql, "rows": rows,
        }]
        body["agent_primary_result_id"] = "result_1"
    return body
