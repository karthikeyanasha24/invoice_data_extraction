"""LLM-first turn understanding — structured intent before capability execution.

The model proposes intent; the application selects safe capabilities and
enforces JWT / TrustedAiExecutionScope / SQL safety / result validation.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .llm_provider import analyze_json, complete_text

logger = logging.getLogger("zodiac-api.adaptive_analyst.understanding")

INTENTS = frozenset({
    "conversation",
    "knowledge",
    "capability",
    "metadata",
    "analytics",
    "investigation",
    "clarification",
    "cannot_answer",
    "greeting",
})

_UNDERSTAND_SYSTEM = (
    "You are the understanding stage of BridgeEDI AI Analyst. "
    "Read the user message and conversation context. "
    "Return ONE JSON object only (no markdown) with exactly these keys:\n"
    "intent: one of conversation|knowledge|capability|metadata|analytics|"
    "investigation|clarification|cannot_answer|greeting\n"
    "goal: short English paraphrase of what the user wants\n"
    "requires_database: boolean (true only if SAP/business fact rows are needed)\n"
    "requires_metadata: boolean (true if schema/catalog introspection is needed)\n"
    "requires_conversation_context: boolean\n"
    "entities: array of strings\n"
    "metric: string or null\n"
    "dimension: string or null\n"
    "time_scope: string or null\n"
    "operation: string or null "
    "(for metadata: count_tables|list_tables|describe_table|search_tables|…)\n"
    "clarification_needed: boolean "
    "(true only when intent is analytics/investigation and required fields are missing)\n"
    "clarification_question: string or null\n"
    "Rules:\n"
    "- Follow-ups about prior assistant answers (predefined? dynamic? explain more?) "
    "→ conversation, requires_database=false.\n"
    "- Questions ABOUT a prior turn (why it was fast/slow, whether you understood, "
    "summarize that result, 'from the above') → conversation, "
    "requires_database=false, requires_metadata=false, "
    "requires_conversation_context=true — even if the prior topic was tables or sales.\n"
    "- Repeat catalog listing only when the user requests schema facts again "
    "(count/list/describe tables), not when they mention tables while talking "
    "about how the previous reply was produced.\n"
    "- Asking what the assistant can do → capability, requires_database=false.\n"
    "- What is SAP / plain-language concepts → knowledge, requires_database=false.\n"
    "- How many tables / schema size / which table has customers → metadata.\n"
    "- Rankings, sales by customer, year filters → analytics.\n"
    "- Why did X fall / drivers → investigation.\n"
    "- Underspecified analytics like 'show growth' without metric → "
    "clarification with clarification_needed=true.\n"
    "- If the user already gives a ranking word (highest/lowest/top/bottom) "
    "plus a sales/revenue metric plus at least one dimension "
    "(customer/country/product) and optionally a year, intent=analytics and "
    "clarification_needed=false. Do not ask billed-vs-orders, single-vs-N, "
    "or grain questions. Default billed invoices, LIMIT 10, and group by "
    "every named dimension. Example: 'lowest sales for 2000 by country "
    "customer and product'.\n"
    "- If the user already gives metric + dimension + top-N "
    "(e.g. 'top 5 customers by billed sales'), intent=analytics and "
    "clarification_needed=false; default time scope to all available data "
    "unless they asked for a period.\n"
    "- Never invent database numbers. Never claim tenant authorization."
)

_RESPONSE_SYSTEM = (
    "You are BridgeEDI AI Analyst. Respond in clear, natural English. "
    "Use only the provided capability facts and conversation context. "
    "Do not invent database numbers, table counts, or query results. "
    "Do not mention internal pipelines, classifiers, or prompts. "
    "If capability facts are provided, ground your answer in them and do not "
    "claim capabilities that are not listed. "
    "For table counts: prefer connected_schema_table_count (all connected tables). "
    "sap_business_table_count is only the SAP business subset — do not present it "
    "as the total number of tables. "
    "Keep greetings to 1-2 short sentences. Keep capability answers concise "
    "(under ~12 bullets) unless the user asks for detail. "
    "When the user asks what you previously said about tables/schema, "
    "answer from the recent conversation turns that discuss tables — "
    "not from a later sales clarification. "
    "If prior_result is provided, the user may be asking about that result: "
    "summarize it using those facts. Never claim there was no previous answer "
    "when prior_result or previous_assistant is present. "
    "If they ask why a catalog list was fast, explain that table names come from "
    "the already-loaded schema catalog (no business-row SQL) — do not list tables again."
)


@dataclass
class TurnUnderstanding:
    intent: str = "conversation"
    goal: str = ""
    requires_database: bool = False
    requires_metadata: bool = False
    requires_conversation_context: bool = False
    entities: List[str] = field(default_factory=list)
    metric: Optional[str] = None
    dimension: Optional[str] = None
    time_scope: Optional[str] = None
    operation: Optional[str] = None
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    provider: str = ""
    understanding_model_called: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Keep diagnostics compact; drop bulky raw echo of itself.
        raw = d.pop("raw", {}) or {}
        d["raw_keys"] = sorted(raw.keys())[:20]
        return d


def capability_facts() -> Dict[str, Any]:
    """Structured capability metadata for the response model (not a canned paragraph)."""
    facts: Dict[str, Any] = {
        "available_capabilities": {
            "general_conversation": True,
            "general_knowledge": True,
            "database_metadata": True,
            "business_analytics": True,
            "rankings": True,
            "comparisons": True,
            "trends": True,
            "investigation": True,
            "tables": True,
            "charts": True,
        },
        "notes": [
            "Answers use governed SQL over the migrated SAP extract when data is required.",
            "Unqualified 'sales' ranking uses billed invoices unless sales orders are requested.",
            "The assistant does not invent row counts or revenue figures.",
            "When stating how many tables exist, use connected_schema_table_count (live schema), "
            "not sap_business_table_count alone.",
        ],
    }
    try:
        from ...data_catalog.physical import has_table, load_physical_schema, sap_business_tables

        bits = []
        if has_table("VBAK"):
            bits.append("sales orders (VBAK/VBAP)")
        if has_table("VBRK"):
            bits.append("billing/invoices (VBRK/VBRP)")
        if has_table("EKKO"):
            bits.append("purchasing (EKKO/EKPO)")
        if has_table("AFKO"):
            bits.append("production (AFKO/AFPO)")
        if has_table("KNA1"):
            bits.append("customers (KNA1)")
        if has_table("MARA"):
            bits.append("products/materials (MARA/MAKT)")
        if has_table("BKPF"):
            bits.append("finance postings (BKPF/BSEG)")
        physical = load_physical_schema() or {}
        facts["connected_schema_table_count"] = len(physical)
        facts["sap_business_table_count"] = len(sap_business_tables())
        facts["domains_present"] = bits
    except Exception as exc:
        logger.warning("[understanding] capability_facts catalog read failed: %s", exc)
        facts["connected_schema_table_count"] = None
        facts["sap_business_table_count"] = None
        facts["domains_present"] = []
    return facts


def _context_block(
    *,
    prior_question: str = "",
    prior_summary: str = "",
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_status: str = "",
) -> str:
    parts: List[str] = []
    plan = prior_plan if isinstance(prior_plan, dict) else {}
    inv = plan.get("investigation_state") if isinstance(plan.get("investigation_state"), dict) else {}
    recent = inv.get("recent_turns") or plan.get("recent_turns") or []
    if isinstance(recent, list) and recent:
        lines: List[str] = []
        for item in recent[-10:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {content[:700]}")
        if lines:
            parts.append("Recent conversation:\n" + "\n".join(lines))
    if prior_question:
        parts.append(f"Previous user message: {prior_question[:500]}")
    if prior_summary:
        parts.append(f"Previous assistant answer: {prior_summary[:1200]}")
    last_mode = str(plan.get("last_mode") or "")
    if not last_mode and inv:
        last_mode = str(inv.get("mode") or "")
    if last_mode:
        parts.append(f"Previous mode: {last_mode}")
    if prior_status:
        parts.append(f"Previous answer_status: {prior_status}")
    if inv.get("metric"):
        parts.append(f"Active metric: {inv.get('metric')}")
    if inv.get("time_period"):
        parts.append(f"Active time_period: {inv.get('time_period')}")
    return "\n".join(parts) if parts else "(no prior conversation context)"


def is_sufficiently_specified_ranking(question: str) -> bool:
    """True when ranking + metric + dimension is already present.

    Explicit top-N is not required: highest/lowest defaults to LIMIT 10.
    """
    ql = (question or "").strip().lower()
    has_limit = bool(re.search(r"\b(?:top|bottom)\s+\d+\b", ql)) or bool(
        re.search(r"\b\d+\s+customers?\b", ql)
    )
    has_superlative = bool(
        re.search(r"\b(highest|lowest|smallest|largest|minimum|maximum)\b", ql)
    )
    has_dim = bool(
        re.search(
            r"\b(customers?|countries|country|products?|materials?|industr(?:y|ies)|regions?)\b",
            ql,
        )
    )
    has_metric = bool(
        re.search(r"\b(billed|billing|invoice|revenue|sales)\b", ql)
    )
    if has_limit and has_dim and has_metric:
        return True
    return bool(has_superlative and has_dim and has_metric)


_ASSISTANT_REF = re.compile(
    r"\b(you|your|you're|you are|didn'?t you|did you)\b",
    re.I,
)
_PRIOR_DEIXIS = re.compile(
    r"\b("
    r"above|previous|prior|earlier|"
    r"that answer|this answer|the (last|previous) (answer|result|response)|"
    r"my question|from the above"
    r")\b",
    re.I,
)
_PROCESS_OR_RECALL = re.compile(
    r"\b("
    r"how come|wonder(?:ing)?|"
    r"so (quickly|fast)|took time|response times?|"
    r"summarize|summarise|summary|"
    r"properly|understand(?:ing)?|get my question|"
    r"how (?:can|did|do) you"
    r")\b",
    re.I,
)
_CATALOG_RELIST = re.compile(
    r"\b("
    r"(?:list|show|display|enumerate)\s+(?:(me|out|all)\s+)*(?:the\s+)?(?:all\s+)?tables?"
    r"|how many tables"
    r")\b",
    re.I,
)
_PROCESS_MANNER = re.compile(r"\b(quickly|fast|slow|time|wonder)\b", re.I)


def is_prior_turn_discourse(question: str, *, has_prior: bool) -> bool:
    """True when the user is talking about the previous assistant turn.

    Generic: process/recall of a prior answer, not a new catalog or SQL ask.
    """
    if not has_prior:
        return False
    q = question or ""
    process = bool(_PROCESS_OR_RECALL.search(q))
    if _PRIOR_DEIXIS.search(q) and re.search(
        r"\b(summarize|summarise|mean|explain|say about)\b", q, re.I
    ):
        process = True
    if _ASSISTANT_REF.search(q) and _PRIOR_DEIXIS.search(q):
        process = True
    if not process:
        return False
    if _CATALOG_RELIST.search(q) and not _PROCESS_MANNER.search(q):
        return False
    return True


def apply_prior_discourse_override(
    understanding: TurnUnderstanding,
    question: str,
    *,
    has_prior: bool,
) -> TurnUnderstanding:
    """Keep process/recall of a prior turn on the conversation path."""
    if not is_prior_turn_discourse(question, has_prior=has_prior):
        return understanding
    understanding.intent = "conversation"
    understanding.requires_database = False
    understanding.requires_metadata = False
    understanding.requires_conversation_context = True
    understanding.clarification_needed = False
    understanding.clarification_question = None
    return understanding


def compact_prior_result(
    rows: Optional[List[Dict[str, Any]]],
    summary: str = "",
) -> Dict[str, Any]:
    """Compact prior analytical rows for conversation (no raw dict dumps)."""
    out: Dict[str, Any] = {
        "summary": (summary or "")[:1200],
        "row_count": len(rows or []),
    }
    if not rows:
        return out
    keys = [str(k) for k in list(rows[0].keys())[:6]]
    preview: List[str] = []
    for row in rows[:6]:
        if not isinstance(row, dict):
            continue
        preview.append(
            "; ".join(f"{k}={row.get(k)}" for k in keys if k in row)
        )
    out["preview"] = preview
    return out


def _normalize_intent(raw: str) -> str:
    t = re.sub(r"[^a-z_]", "", (raw or "").strip().lower().replace("-", "_").replace(" ", "_"))
    aliases = {
        "general_conversation": "conversation",
        "general_chat": "conversation",
        "chat": "conversation",
        "general_knowledge": "knowledge",
        "capability_meta": "capability",
        "help": "capability",
        "database_metadata": "metadata",
        "schema": "metadata",
        "business": "analytics",
        "business_analytics": "analytics",
        "analytical": "analytics",
        "query": "analytics",
        "clarify": "clarification",
        "hi": "greeting",
        "hello": "greeting",
    }
    t = aliases.get(t, t)
    return t if t in INTENTS else "conversation"


def _coerce_understanding(data: Dict[str, Any], *, provider: str) -> TurnUnderstanding:
    intent = _normalize_intent(str(data.get("intent") or "conversation"))
    entities = data.get("entities") or []
    if isinstance(entities, str):
        entities = [entities]
    if not isinstance(entities, list):
        entities = []
    requires_db = bool(data.get("requires_database"))
    requires_meta = bool(data.get("requires_metadata"))
    if intent == "metadata":
        requires_meta = True
        requires_db = False
    if intent in {"conversation", "knowledge", "capability", "greeting"}:
        requires_db = False
        requires_meta = False
    if intent in {"analytics", "investigation"}:
        requires_db = True
    clar_needed = bool(data.get("clarification_needed"))
    if intent == "clarification":
        clar_needed = True
    return TurnUnderstanding(
        intent=intent,
        goal=str(data.get("goal") or "")[:500],
        requires_database=requires_db,
        requires_metadata=requires_meta,
        requires_conversation_context=bool(data.get("requires_conversation_context")),
        entities=[str(e)[:80] for e in entities if e][:12],
        metric=(str(data["metric"])[:80] if data.get("metric") not in (None, "") else None),
        dimension=(str(data["dimension"])[:80] if data.get("dimension") not in (None, "") else None),
        time_scope=(str(data["time_scope"])[:80] if data.get("time_scope") not in (None, "") else None),
        operation=(str(data["operation"])[:80] if data.get("operation") not in (None, "") else None),
        clarification_needed=clar_needed,
        clarification_question=(
            str(data["clarification_question"])[:400]
            if data.get("clarification_question") not in (None, "")
            else None
        ),
        provider=provider,
        understanding_model_called=True,
        raw=data if isinstance(data, dict) else {},
    )


def understand_turn(
    question: str,
    *,
    prior_question: str = "",
    prior_summary: str = "",
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_status: str = "",
    capability_context: Optional[Dict[str, Any]] = None,
) -> TurnUnderstanding:
    """LLM understanding stage. Raises on model/infrastructure failure."""
    q = (question or "").strip()
    if not q:
        return TurnUnderstanding(
            intent="clarification",
            goal="empty message",
            clarification_needed=True,
            clarification_question="What would you like to know?",
            understanding_model_called=False,
        )

    caps = capability_context if isinstance(capability_context, dict) else capability_facts()
    user = (
        f"Conversation context:\n{_context_block(prior_question=prior_question, prior_summary=prior_summary, prior_plan=prior_plan, prior_status=prior_status)}\n\n"
        f"Available capabilities (facts, not the answer):\n{json.dumps(caps, default=str)[:1800]}\n\n"
        f"Current user message:\n{q[:1500]}\n"
    )
    logger.info("[understanding] understanding_model_called question_len=%s prior=%s", len(q), bool(prior_question or prior_summary))
    data, provider = analyze_json(_UNDERSTAND_SYSTEM, user)
    if not isinstance(data, dict):
        raise RuntimeError("understanding model returned non-object JSON")
    result = _coerce_understanding(data, provider=provider)
    result = apply_prior_discourse_override(
        result,
        q,
        has_prior=bool(prior_question or prior_summary or prior_plan),
    )
    logger.info(
        "[understanding] understanding_result intent=%s requires_db=%s requires_meta=%s clar=%s provider=%s",
        result.intent,
        result.requires_database,
        result.requires_metadata,
        result.clarification_needed,
        provider,
    )
    return result


def generate_grounded_response(
    question: str,
    understanding: TurnUnderstanding,
    *,
    prior_question: str = "",
    prior_summary: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    """Response model for conversation / knowledge / capability. Returns (text, provider)."""
    payload = {
        "understanding": {
            "intent": understanding.intent,
            "goal": understanding.goal,
        },
        "capability_facts": evidence if evidence is not None else (
            capability_facts() if understanding.intent == "capability" else None
        ),
        "conversation_context": {
            "previous_user": (prior_question or "")[:500],
            "previous_assistant": (prior_summary or "")[:1200],
            "recent_turns": (
                ((evidence or {}).get("recent_turns") if isinstance(evidence, dict) else None)
                or []
            ),
            "prior_result": (
                (evidence or {}).get("prior_result") if isinstance(evidence, dict) else None
            ),
        },
        "current_user_message": (question or "")[:1500],
    }
    logger.info(
        "[understanding] response_model_called intent=%s has_capability_facts=%s",
        understanding.intent,
        bool(payload.get("capability_facts")),
    )
    text, provider = complete_text(
        _RESPONSE_SYSTEM,
        "Produce the assistant reply for the user.\n"
        + json.dumps(payload, default=str)[:7000],
    )
    reply = (text or "").strip()
    if not reply:
        raise RuntimeError("response model returned empty text")
    return reply, provider


def technical_understanding_failure(question: str, err: BaseException) -> Dict[str, Any]:
    """Infrastructure / model failure — never a business-metric clarification."""
    msg = (
        "I couldn't complete understanding of your message due to a temporary "
        "model/service failure. Please try again in a moment."
    )
    logger.warning(
        "[understanding] technical failure: %s: %s",
        type(err).__name__,
        str(err)[:300],
    )
    return {
        "mode": "error",
        "route": "understanding",
        "status": "cannot_answer",
        "answer_status": "CANNOT_ANSWER",
        "type": "pipeline_error",
        "failure_class": "UNDERSTANDING_MODEL_FAILED",
        "sql": "",
        "data": [],
        "rowCount": 0,
        "summary": msg,
        "answer": msg,
        "keyFindings": [],
        "charts": [],
        "pipeline": "adaptive_orchestrator",
        "sql_generation_method": "understanding_failed",
        "llm_calls": 1,
        "question": (question or "")[:500],
        "meta": {
            "understanding_model_called": True,
            "failure_class": "UNDERSTANDING_MODEL_FAILED",
            "error_type": type(err).__name__,
        },
        "query_plan": {
            "last_mode": "understanding_error",
            "understanding": {"error": type(err).__name__},
        },
    }


def analytics_clarification_payload(question: str, understanding: TurnUnderstanding) -> Dict[str, Any]:
    """Clarification only after understanding established analytics intent with gaps."""
    msg = (understanding.clarification_question or "").strip() or (
        "I need a clearer business metric or dimension. "
        "Try something like: \"Show top 10 customers by billing revenue\" or "
        "\"How many sales orders are there?\""
    )
    return {
        "mode": "clarification",
        "route": "clarification",
        "status": "clarification",
        "answer_status": "CLARIFICATION",
        "type": "clarification",
        "sql": "",
        "data": [],
        "rowCount": 0,
        "summary": msg,
        "answer": msg,
        "keyFindings": [],
        "charts": [],
        "pipeline": "adaptive_orchestrator",
        "sql_generation_method": "understanding_clarification",
        "llm_calls": 1,
        "question": (question or "")[:500],
        "meta": {
            "understanding_model_called": True,
            "selected_capability": "clarification",
            "understanding": understanding.to_public_dict(),
            "failure_class": "CLARIFICATION",
        },
        "query_plan": {
            "last_mode": "clarification",
            "understanding": understanding.to_public_dict(),
        },
        "suggested_followups": [
            "Show the top customers by billed sales.",
            "How many sales orders are there?",
        ],
    }
