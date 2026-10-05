"""LLM-first turn understanding — structured intent before capability execution.

The model proposes intent; the application selects safe capabilities and
enforces JWT / TrustedAiExecutionScope / SQL safety / result validation.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
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
    "resolved_question: standalone English query, or null when no database query is needed\n"
    "turn_relation: new_request|clarification_answer|followup\n"
    "context_source: none|pending_request|prior_request|prior_result\n"
    "Rules:\n"
    "- Read the entire user message, including late constraints and multiple requested parts. "
    "A long message is not an error or a reason to answer just the first clause. "
    "Preserve every requested comparison, relationship, exclusion, and output requirement "
    "in the resolved question. Distinguish quoted examples from the actual request.\n"
    "- An unanswered analytical clarification is a pending REQUEST, not a query result. "
    "When the user answers its choices, sets its source/grain/format, or accepts its "
    "defaults, set turn_relation=clarification_answer and context_source=pending_request. "
    "Resolve the whole pending request plus the reply into resolved_question, preserving "
    "its metric, predicates, periods, limits and requested relationships unless the user "
    "changes them. A selection to be computed by that request needs no prior result rows. "
    "Do not turn an answer to a choice into a new unrelated count or ranking. "
    "If another material choice remains, retain the resolved request and ask only for it.\n"
    "- context_source=prior_result means the user selects an entity/document from an "
    "already returned result (for example its leader or one of its rows). That requires "
    "verified result evidence; a pending request cannot supply those IDs or values. "
    "context_source=prior_request means reusing requested filters/periods, not row values. "
    "An unrelated new question uses turn_relation=new_request and context_source=none; "
    "do not inherit pending choices into it. Never treat a previous failure as results.\n"
    "- A follow-up that only asks what a prior answer meant or what you said "
    "→ conversation, requires_database=false. A follow-up that asks to retrieve, "
    "calculate, compare, rank, filter, or add database details → analytics/investigation, "
    "requires_database=true.\n"
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
    "- Prefer reasonable, schema-grounded defaults over clarification. Ask only "
    "when a missing choice materially changes the answer and cannot be inferred "
    "from the request, conversation, or schema. State non-blocking assumptions "
    "briefly instead of asking a questionnaire. For a ranking with no named "
    "dimension, use the most direct transactional grain supported by the request; "
    "default to 10 rows. Use calendar periods unless fiscal periods are requested. "
    "For a comparison, return both period values and the requested change measures; "
    "do not assume the result increased or decreased unless the user says so.\n"
    "- A uniquely dated transaction/document belongs to one calendar period. "
    "Do not resolve a period comparison as finding the same document ID in two "
    "different periods. Keep document-level rankings as separate period cohorts; "
    "align amounts across periods only using a stable entity the user specified "
    "or a supported relationship. For selected documents and their linked documents, "
    "compute the selection first and follow its verified relationships, without "
    "claiming a prior result is required. If a stable comparison dimension is "
    "missing, preserve the separate cohorts or ask one material question; never "
    "invent a same-document cross-period match.\n"
    "- 'Most negative' means ascending order by a verified numeric measure with a "
    "less-than-zero filter. Keep negative/credit amounts when the user asks for "
    "negative values. Do not ask whether to include them.\n"
    "- Referential follow-ups ('those results', 'that country', 'which of those "
    "columns', 'the one you just mentioned') use the latest relevant conversation "
    "and verified result sample. Resolve references from that evidence before asking.\n"
    "- For a database follow-up, populate resolved_question as one complete, "
    "standalone query that combines the current request with only the prior metric, "
    "filters, grain, and entities needed to resolve its references. Preserve explicit "
    "limits and periods. Do not invent IDs, columns, totals, or SQL; if the verified "
    "context is insufficient, leave the unresolved detail out and explain the limitation.\n"
    "- A request to run an analysis that mentions verified columns/schema is still "
    "an analytics request; it is not a request to count or list schema columns.\n"
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
    "You are BridgeEDI AI Analyst. Respond clearly in the user's requested language. "
    "For general knowledge, writing, coding, explanations, and reasoning, use your "
    "general knowledge and adapt the format, language, and detail to the user's request. "
    "Read and answer every material part of long or compound messages. For a detailed request, "
    "give a complete, well organized explanation with concrete examples when helpful; do not "
    "force it into a short summary. Keep simple greetings and single facts brief. "
    "Apply user-authored communication preferences in conversation_context.user_preferences "
    "and other clearly stated user preferences in the recent user turns when their stated "
    "scope includes the current request. Preserve their requested format, "
    "language, tone, and level of detail even when the topic changes. Later user changes "
    "supersede earlier preferences, and a specific instruction in the current message "
    "takes precedence. Use the user's actual words as the preference evidence; do not "
    "infer preferences from the length or format of previous assistant answers. "
    "For connected database claims, use only provided evidence and conversation context. "
    "Do not invent database numbers, table counts, or query results. "
    "Do not offer unverified SQL templates or placeholder identifiers as if they were "
    "the next step of an executed database analysis. When a user asks for additional "
    "database details, route it as a database analysis rather than answering with a draft query. "
    "Only name physical columns when they are supported by supplied schema evidence or "
    "verified prior SQL. Do not add unrequested column guesses. "
    "Do not mention internal pipelines, classifiers, or prompts. "
    "If capability facts are provided, ground your answer in them and do not "
    "claim capabilities that are not listed. "
    "For broad questions such as 'What can you help me analyze?', answer in at most "
    "two short sentences and mention no more than three example task types unless the user "
    "asks for detail, examples, or a multi-part explanation. Do not "
    "include schema counts, implementation details, a full domain catalog, or setup "
    "questions unless the user asks for those details. "
    "When the user asks you to simplify or explain your previous answer in plain language, "
    "rewrite the previous answer with everyday words, one short sentence, and no examples "
    "unless requested. "
    "If schema_semantics are provided, treat them as authoritative physical-field labels "
    "and prefer them over remembered or guessed SAP field meanings. "
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
    "the already-loaded schema catalog (no business-row SQL) — do not list tables again. "
    "Stored result rows may be a sample: respect result_scope.truncated, distinguish "
    "a sample from the complete query result, and do not infer full totals, frequencies, "
    "or rankings from an incomplete sample."
)


@dataclass
class TurnUnderstanding:
    intent: str = "conversation"
    goal: str = ""
    resolved_question: Optional[str] = None
    turn_relation: str = "new_request"
    context_source: str = "none"
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
    prior_rows: Optional[List[Dict[str, Any]]] = None,
    current_question: str = "",
) -> str:
    parts: List[str] = []
    plan = prior_plan if isinstance(prior_plan, dict) else {}
    from .pending_analysis import pending_analysis_context

    pending = pending_analysis_context(plan, prior_question, prior_status)
    if pending:
        parts.append("Pending analytical request (unexecuted intent, not verified rows): " + json.dumps(pending, default=str, ensure_ascii=False))
    inv = plan.get("investigation_state") if isinstance(plan.get("investigation_state"), dict) else {}
    recent = plan.get("recent_turns") or inv.get("recent_turns") or []
    if isinstance(recent, list) and recent:
        from .chat_memory import relevant_conversation, user_conversation_preferences

        preferences = user_conversation_preferences(recent)
        if preferences:
            parts.append("User-authored conversation preferences (chronological): " + json.dumps(preferences, ensure_ascii=False))

        lines: List[str] = []
        for item in relevant_conversation(current_question, recent):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {content[:1400]}")
        if lines:
            parts.append("Recent conversation:\n" + "\n".join(lines)[-12000:])
        asks_which_period_was_recent = bool(
            re.search(
                r"\b(period|year|month|quarter|date|time)\b.{0,60}\b(most recently|latest|last)\b",
                current_question,
                re.I,
            )
        )
        asks_latest_period = bool(
            re.search(
                r"\b(most recently|latest|last)\b.{0,30}\b(period|year|month|quarter|date|time)\b",
                current_question,
                re.I,
            )
        )
        if asks_which_period_was_recent or asks_latest_period:
            for item in reversed(recent):
                if not isinstance(item, dict) or item.get("role") != "user":
                    continue
                content = str(item.get("content") or "").strip()
                if re.search(r"\b(?:19|20)\d{2}\b|\b(year|month|quarter|date|period|last|latest)\b", content, re.I):
                    parts.append(f"Most recent prior user request specifying a time period: {content[:600]}")
                    break
    if prior_question:
        parts.append(f"Previous user message: {prior_question[:32000]}")
    if prior_summary:
        parts.append(f"Previous assistant answer: {prior_summary[:1200]}")
    last_mode = str(plan.get("last_mode") or "")
    if not last_mode and inv:
        last_mode = str(inv.get("mode") or "")
    if last_mode:
        parts.append(f"Previous mode: {last_mode}")
    if prior_status:
        parts.append(f"Previous answer_status: {prior_status}")
    if re.search(r"\b(sql|query)\b", current_question or "", re.I):
        prior_sql = str(inv.get("last_sql") or plan.get("last_sql") or "").strip()
        if prior_sql:
            from .chat_memory import compact_sql_lineage

            lineage = compact_sql_lineage(prior_sql)
            if lineage:
                parts.append(
                    "Previous verified SQL structure (literal values redacted; use it to answer "
                    f"table/column recall only): {lineage}"
                )
    if prior_rows:
        artifact = plan.get("result_artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        try:
            sample = json.dumps(
                [row for row in prior_rows[:5] if isinstance(row, dict)],
                default=str,
                ensure_ascii=False,
            )[:2400]
        except (TypeError, ValueError):
            sample = "[]"
        if sample != "[]":
            row_count = artifact.get("row_count")
            truncated = bool(artifact.get("truncated"))
            parts.append(
                "Previous verified result sample (use only to resolve references; "
                "this may be a partial sample): "
                f"row_count={row_count if row_count is not None else 'unknown'}, "
                f"truncated={str(truncated).lower()}, rows={sample}"
            )
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
    count_word = r"(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
    has_limit = bool(re.search(rf"\b(?:top|bottom|first|last)\s+{count_word}\b", ql)) or bool(
        re.search(rf"\b(?:which|what)?\s*{count_word}\s+(?:customers?|countries|products?|materials?|vendors?|suppliers?)\b", ql)
    )
    has_superlative = bool(
        re.search(r"\b(highest|lowest|smallest|largest|minimum|maximum|most|least|best|worst|biggest)\b", ql)
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
    if has_superlative and has_metric and has_dim:
        return True

    # A time-bounded numeric ranking with an explicit measure predicate is
    # answerable at the closest supported transactional grain. Do not block it
    # for optional grouping, currency, or presentation choices.
    has_period = bool(re.search(r"\b(?:19|20)\d{2}\b|\b(last|this)\s+(?:year|quarter|month)\b", ql))
    return bool(has_superlative and has_metric and has_period)


_ASSISTANT_REF = re.compile(
    r"\b(you|your|you're|you are|didn'?t you|did you)\b",
    re.I,
)
_PRIOR_DEIXIS = re.compile(
    r"\b("
    r"above|previous|prior|earlier|"
    r"that answer|this answer|the (last|previous) (answer|result|response)|most recently|"
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
_HISTORY_RECALL = re.compile(
    r"\b(?:what|which|when|where|how many|how much)\b.{0,100}\b(?:"
    r"asked|mentioned|counted|queried|ran|returned|used|said|answered|"
    r"result|response|answer|query|sql|table|column|period|year|month|"
    r"count|number|metric|value|total|filter|time)\b",
    re.I,
)


def is_prior_turn_discourse(question: str, *, has_prior: bool) -> bool:
    """True when the user is talking about the previous assistant turn.

    Generic: process/recall of a prior answer, not a new catalog or SQL ask.
    """
    if not has_prior:
        return False
    q = question or ""
    process = bool(_PROCESS_OR_RECALL.search(q))
    if _PRIOR_DEIXIS.search(q) and _HISTORY_RECALL.search(q):
        process = True
    # Direct questions about the just-used query/table/column often omit a
    # pronoun such as "that". With conversation history present, SQL lineage
    # wording itself is enough to recognize this as recall rather than a fresh
    # global schema-count request.
    if re.search(r"\b(sql|query)\b", q, re.I) and _HISTORY_RECALL.search(q):
        process = True
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


def is_referential_database_action(question: str, *, has_prior: bool) -> bool:
    """Recognize requests to fetch or calculate more data from a prior result."""
    if not has_prior or is_prior_turn_discourse(question, has_prior=True):
        return False
    q = question or ""
    # Schema/catalog follow-ups refer to prior metadata, not to a ranked entity
    # or document result. Let the metadata capability resolve them from the
    # connected catalog instead of demanding an analytical result anchor.
    if re.search(r"\b(schema|catalog|table names?|columns?|fields?|data dictionary)\b", q, re.I):
        return False
    reference_text = re.sub(
        r"\b(?:this|previous|prior)\s+(?:(?:\d+|one|two|three|complete|full|calendar|fiscal)\s+)*"
        r"(?:years?|months?|quarters?|weeks?|days?)(?:['’]s)?\b",
        "", q, flags=re.I,
    )
    # A possessive can point to an entity introduced in the *same* sentence,
    # rather than to a prior chat result (for example, "for each invoice ...
    # its linked order"). Keep the possessive follow-up cue for other cases,
    # but remove it when a nearby quantified business entity supplies the
    # antecedent. Other explicit cues such as "those documents" still apply.
    reference_text = re.sub(
        r"\b(?:each|every|per)\s+(?:of\s+)?(?:the\s+)?"
        r"[\w'-]+(?:\s+[\w'-]+){0,2}\b[^.!?]{0,240}\b(?:its|their)\b",
        lambda match: re.sub(r"\b(?:its|their)\b", "", match.group(0), flags=re.I),
        reference_text,
        flags=re.I,
    )
    # Demonstratives can refer to a cohort selected earlier in the same
    # request ("show the ten lowest invoices ... compare those invoices").
    # Remove that cue only when the same business entity is named before the
    # demonstrative; otherwise it remains a conversational reference.
    local_entity_patterns = (
        r"(?:billing\s+)?invoices?",
        r"(?:billing\s+)?documents?",
        r"sales\s+orders?",
        r"orders?",
        r"customers?",
        r"countries?",
        r"materials?",
        r"products?",
        r"vendors?",
        r"suppliers?",
    )
    for entity_pattern in local_entity_patterns:
        demonstrative = re.search(
            rf"\b(?:these|those|that|same)\s+(?:selected\s+)?(?:{entity_pattern})\b",
            reference_text,
            re.I,
        )
        if demonstrative and re.search(entity_pattern, reference_text[:demonstrative.start()], re.I):
            reference_text = (
                reference_text[:demonstrative.start()]
                + re.sub(r"\b(?:these|those|that|same)\b", "", demonstrative.group(0), flags=re.I)
                + reference_text[demonstrative.end():]
            )
    refers_to_prior = bool(
        re.search(r"\b(this|these|those|that|same|above|previous|prior|earlier|its|their)\b", reference_text, re.I)
        or re.search(
            r"\b(?:the\s+(?:top|first|second|last|selected)|leading|highest[-\s]ranked|lowest[-\s]ranked)\s+"
            r"(?:customer|country|material|product|vendor|supplier|document|invoice|order)\b",
            reference_text, re.I,
        )
    )
    requests_data = bool(
        re.search(
            r"\b(add|include|show|list|get|return|retrieve|find|compare|calculate|count|"
            r"break\s+down|rank|filter|group|expand|drill\s+down|give|highest|lowest|"
            r"higher|lower|difference|more|less|exceed|largest|smallest|top|bottom)\b",
            q,
            re.I,
        )
    )
    mentions_business_data = bool(
        re.search(
            r"\b(invoices?|billing|documents?|orders?|sales|revenue|customers?|countr(?:y|ies)|"
            r"materials?|products?|vendors?|suppliers?|amounts?|dates?|years?|results?|rows?)\b",
            q,
            re.I,
        )
    )
    return refers_to_prior and requests_data and mentions_business_data


def has_same_turn_entity_antecedent(question: str) -> bool:
    """Whether a demonstrative business-entity reference is anchored in this request."""
    q = question or ""
    for entity_pattern in (
        r"(?:billing\s+)?invoices?",
        r"(?:billing\s+)?documents?",
        r"sales\s+orders?",
        r"orders?",
        r"customers?",
        r"countries?",
        r"materials?",
        r"products?",
        r"vendors?",
        r"suppliers?",
    ):
        demonstrative = re.search(
            rf"\b(?:these|those|that|same)\s+(?:selected\s+)?(?:{entity_pattern})\b",
            q,
            re.I,
        )
        if demonstrative and re.search(entity_pattern, q[:demonstrative.start()], re.I):
            return True
    return False


def compact_prior_result(
    rows: Optional[List[Dict[str, Any]]],
    summary: str = "",
    *,
    result_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact prior analytical rows for conversation (no raw dict dumps)."""
    safe_rows = [row for row in (rows or []) if isinstance(row, dict)]
    scope = result_scope if isinstance(result_scope, dict) else {}
    try:
        row_count = max(0, int(scope.get("row_count")))
    except (TypeError, ValueError):
        row_count = len(safe_rows)
    if row_count == 0 and safe_rows:
        row_count = len(safe_rows)
    out: Dict[str, Any] = {
        "summary": (summary or "")[:1200],
        "row_count": row_count,
        "sample_row_count": len(safe_rows),
        "truncated": bool(scope.get("truncated")) or row_count > len(safe_rows),
    }
    if not safe_rows:
        return out
    keys = [str(k) for k in list(safe_rows[0].keys())[:6]]
    preview: List[str] = []
    for row in safe_rows[:6]:
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
        resolved_question=(
            str(data["resolved_question"]).strip()[:32000]
            if data.get("resolved_question") not in (None, "")
            else None
        ),
        turn_relation=str(data.get("turn_relation") or "new_request") if data.get("turn_relation") in {"new_request", "clarification_answer", "followup"} else "new_request",
        context_source=str(data.get("context_source") or "none") if data.get("context_source") in {"none", "pending_request", "prior_request", "prior_result"} else "none",
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
    prior_rows: Optional[List[Dict[str, Any]]] = None,
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
        f"Conversation context:\n{_context_block(prior_question=prior_question, prior_summary=prior_summary, prior_plan=prior_plan, prior_status=prior_status, prior_rows=prior_rows, current_question=q)}\n\n"
        f"Available capabilities (facts, not the answer):\n{json.dumps(caps, default=str)[:1800]}\n\n"
        f"Current user message:\n{q}\n"
    )
    logger.info("[understanding] understanding_model_called question_len=%s prior=%s", len(q), bool(prior_question or prior_summary))
    try:
        data, provider = analyze_json(_UNDERSTAND_SYSTEM, user)
        if not isinstance(data, dict):
            raise RuntimeError("understanding model returned non-object JSON")
    except Exception as model_error:
        from .pending_analysis import pending_analysis_context

        if pending_analysis_context(prior_plan, prior_question, prior_status):
            # A lexical fallback cannot resolve a choice against a pending
            # request. Report the model failure instead of misreading the reply
            # as a new query or blaming the absence of executed result rows.
            raise RuntimeError("The model could not resolve the pending analytical request") from model_error
        # Keep supported data questions usable during a model outage. This
        # fallback only chooses the governed database capability; the schema,
        # semantic parser, SQL validators, and database still determine facts.
        # General conversation remains model-backed instead of returning an
        # invented canned response.
        from ..adaptive_nl_sql_hardening import (
            is_capability_or_help_question,
            is_greeting_or_chitchat,
            question_requires_database,
        )
        from .database_metadata import classify_metadata_operation

        has_prior = bool(prior_question or prior_summary or prior_plan)
        metadata_plan = classify_metadata_operation(q)
        if is_capability_or_help_question(q):
            data = {
                "intent": "capability",
                "goal": q,
                "requires_database": False,
                "requires_metadata": False,
                "clarification_needed": False,
            }
        elif is_greeting_or_chitchat(q):
            data = {
                "intent": "greeting",
                "goal": q,
                "requires_database": False,
                "requires_metadata": False,
                "clarification_needed": False,
            }
        elif metadata_plan is not None and not is_prior_turn_discourse(q, has_prior=has_prior):
            data = {
                "intent": "metadata",
                "goal": q,
                "requires_database": False,
                "requires_metadata": True,
                "operation": metadata_plan.operation.lower(),
                "clarification_needed": False,
            }
        elif question_requires_database(q) or is_referential_database_action(q, has_prior=has_prior):
            intent = "investigation" if re.search(
                r"\b(why|driver|cause|contribut|explain)\b", q, re.I
            ) else "analytics"
            data = {
                "intent": intent,
                "goal": q,
                "resolved_question": None,
                "requires_database": True,
                "requires_metadata": False,
                "requires_conversation_context": has_prior,
                "clarification_needed": False,
            }
        else:
            logger.warning(
                "[understanding] model unavailable; no safe local route for this message: %s",
                type(model_error).__name__,
            )
            raise
        provider = "local_schema_semantics_fallback"
        logger.warning(
            "[understanding] model unavailable; routed supported request using local semantics: %s",
            type(model_error).__name__,
        )
    result = _coerce_understanding(data, provider=provider)
    result.understanding_model_called = provider != "local_schema_semantics_fallback"
    result = apply_prior_discourse_override(
        result,
        q,
        has_prior=bool(prior_question or prior_summary or prior_plan),
    )
    from .database_metadata import classify_metadata_operation

    metadata_plan = classify_metadata_operation(q)
    if metadata_plan is not None and not is_prior_turn_discourse(
        q, has_prior=bool(prior_question or prior_summary or prior_plan)
    ):
        result.intent = "metadata"
        result.requires_database = False
        result.requires_metadata = True
        result.operation = metadata_plan.operation.lower()
        result.clarification_needed = False
        result.clarification_question = None
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
    from ..investigation_budget import checkpoint
    checkpoint("PREPARING_ANSWER")
    recent_turns = (
        ((evidence or {}).get("recent_turns") if isinstance(evidence, dict) else None)
        or []
    )
    from .chat_memory import user_conversation_preferences

    preference_turns = list(recent_turns) if isinstance(recent_turns, list) else []
    # The previous conversational user message can still carry an instruction
    # when a caller has no complete history. Never use an analytical paraphrase
    # or assistant acknowledgement to invent a remembered preference.
    if prior_question and not preference_turns:
        preference_turns.append({"role": "user", "content": prior_question})
    preferences = user_conversation_preferences(preference_turns)
    if isinstance(recent_turns, list):
        from .chat_memory import relevant_conversation

        recent_turns = relevant_conversation(question, recent_turns)
    schema_facts = _schema_semantics_evidence(question, recent_turns)
    if schema_facts:
        evidence = {**(evidence or {}), "schema_semantics": schema_facts}
    payload = {
        "understanding": {
            "intent": understanding.intent,
            "goal": understanding.goal,
        },
        "capability_facts": evidence if evidence is not None else (
            capability_facts() if understanding.intent == "capability" else None
        ),
        "conversation_context": {
            "previous_user": (prior_question or "")[:32000],
            "previous_assistant": (prior_summary or "")[:6000],
            "recent_turns": recent_turns,
            "user_preferences": preferences,
            "prior_result": (
                (evidence or {}).get("prior_result") if isinstance(evidence, dict) else None
            ),
        },
        "current_user_message": question or "",
    }
    logger.info(
        "[understanding] response_model_called intent=%s has_capability_facts=%s",
        understanding.intent,
        bool(payload.get("capability_facts")),
    )
    from ..analyst_model_policy import analyst_model_task
    with analyst_model_task("answer"):
        text, provider = complete_text(
            _RESPONSE_SYSTEM,
            (
                "Rewrite the previous explanation in one short, plain-language sentence. "
                "Use everyday words and do not add examples.\n"
                if _is_simplification_followup(question, understanding.intent)
                else "Produce the assistant reply for the user.\n"
            )
            + json.dumps(payload, default=str),
        )
    reply = (text or "").strip()
    if not reply:
        raise RuntimeError("response model returned empty text")
    if _is_broad_capability_question(question, understanding.intent):
        # Keep broad capability answers conversational even if a provider ignores
        # the response-length instruction. Content remains model generated and
        # grounded; this only removes unsolicited counts and excess detail.
        reply = re.sub(r"\([^)]*\b\d+\b[^)]*\)", "", reply)
        reply = re.sub(r"\s{2,}", " ", reply).strip()
        reply = re.sub(r"\s+([,.;!?])", r"\1", reply)
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", reply) if part.strip()]
        reply = " ".join(sentences[:2])
    elif _is_simplification_followup(question, understanding.intent):
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", reply) if part.strip()]
        reply = sentences[0] if sentences else reply
        words = reply.split()
        if len(words) > 24:
            reply = " ".join(words[:24]).rstrip(",;:—- ") + "…"
    return reply, provider


def _is_broad_capability_question(question: str, intent: str) -> bool:
    if intent != "capability":
        return False
    q = (question or "").strip().lower()
    if re.search(r"\b(all|every|each|detailed|in\s+detail|exhaustive|full\s+list)\b", q):
        return False
    return bool(
        re.search(
            r"\bwhat\s+can\s+(?:you|i)\s+(?:help|analy[sz]e|answer|do)\b|"
            r"\bwhat\s+(?:do|can)\s+you\s+(?:analy[sz]e|help\s+me\s+with|answer)\b|"
            r"\bwhat\s+can\s+i\s+ask\b",
            q,
        )
    )


def _is_simplification_followup(question: str, intent: str) -> bool:
    # Plain language can still be thorough. Only enforce a short rewrite when
    # the user has not also asked for detail or multiple explanatory parts.
    if re.search(r"\b(?:detailed|in\s+detail|thorough|comprehensive|step\s+by\s+step|examples?|all\s+(?:parts|details))\b", question or "", re.I):
        return False
    return intent in {"conversation", "knowledge", "capability"} and bool(
        re.search(
            r"\b(simpler|simplify|more\s+simply|plain\s+language|less\s+technical|shorter|"
            r"explain\s+(?:it|that|this)\s+simply)\b",
            question or "",
            re.I,
        )
    )


def _schema_semantics_evidence(question: str, recent_turns: Any) -> List[str]:
    """Retrieve column labels from the repository's schema mappings for grounding."""
    context_parts = [question or ""]
    if isinstance(recent_turns, list):
        context_parts.extend(
            str(item.get("content") or "")
            for item in recent_turns
            if isinstance(item, dict)
        )
    context = "\n".join(context_parts)
    ordered_terms = [
        token for token in re.findall(r"[a-z0-9_]{3,}", (question or "").lower())
        if token not in _MEMORY_LANGUAGE_STOP_WORDS
    ]
    terms = set(ordered_terms)
    if not terms:
        return []
    try:
        from ...data_catalog.physical import load_physical_schema

        schema = load_physical_schema() or {}
    except Exception:
        return []
    mapping_dir = Path(__file__).resolve().parents[2] / "table_mapping"
    from .database_metadata import _table_semantics, _topic_table_score

    table_roles = {table: _table_semantics(table) for table in schema}
    current_mentions = {
        table for table in schema if re.search(rf"\b{re.escape(str(table))}\b", question or "", re.I)
    }
    selected_tables = set(current_mentions)
    if not selected_tables:
        ranked_tables = sorted(
            ((_topic_table_score(" ".join(terms), table, role), table) for table, role in table_roles.items()),
            reverse=True,
        )
        best = ranked_tables[0][0] if ranked_tables else 0
        selected_tables.update(table for score, table in ranked_tables[:4] if score >= max(2.0, best - 3.0))
    selected_tables.update(
        table for table in schema if re.search(rf"\b{re.escape(str(table))}\b", context, re.I)
    )
    scored: List[tuple[int, int, int, float, str]] = []
    for table in schema:
        if table not in selected_tables:
            continue
        path = mapping_dir / f"{str(table).upper()}.json"
        try:
            mappings = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        known_columns = {
            str(col.get("col") or col.get("name") or "").lower()
            if isinstance(col, dict)
            else str(col).lower()
            for col in (schema.get(table) or [])
        }
        for column, description in (mappings or {}).items():
            col = str(column)
            if col.lower() not in known_columns or not description or str(description).startswith("["):
                continue
            label_tokens = set(re.findall(r"[a-z0-9_]{3,}", str(description).lower().replace("_", " ")))
            overlap = len(terms & label_tokens)
            if overlap:
                ordered_label = re.findall(r"[a-z0-9]+", str(description).lower().replace("_", " "))
                prefix_match = max(
                    (
                        length
                        for length in range(1, min(len(ordered_terms), len(ordered_label)) + 1)
                        if ordered_label[:length] == ordered_terms[:length]
                    ),
                    default=0,
                )
                precision = overlap / max(1, len(label_tokens))
                # Prefer a direct label match and primary field names over a
                # longer specialized variant such as a list/cancelled document.
                meaning = str(description).replace("_", " ")
                scored.append((overlap, prefix_match, -len(col), precision, f"{table}.{col}: {meaning}"))
    scored.sort(key=lambda item: item[:4], reverse=True)
    roles = [
        f"{table} table role: {table_roles[table]['description']}; grain: {table_roles[table]['grain']}"
        for table in sorted(
            selected_tables,
            key=lambda table: (-_topic_table_score(" ".join(terms), table, table_roles[table]), table),
        )
        if table_roles[table]["description"]
    ]
    return [fact for _overlap, _prefix, _length, _precision, fact in scored[:6]] + roles[:6]


_MEMORY_LANGUAGE_STOP_WORDS = frozenset(
    {"about", "and", "are", "available", "between", "column", "columns", "could", "data", "difference", "does", "explain", "field", "fields", "for", "from", "have", "how", "in", "into", "is", "me", "of", "on", "please", "show", "store", "table", "the", "those", "this", "what", "which", "with", "you"}
)


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
    from .pending_analysis import pending_analysis_plan

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
            "pending_analysis": pending_analysis_plan(question, understanding),
        },
        "suggested_followups": [
            "Show the top customers by billed sales.",
            "How many sales orders are there?",
        ],
    }
