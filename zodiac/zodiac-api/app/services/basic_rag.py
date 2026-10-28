"""Free question retrieval and permission-bound memory of verified SQL.

Similarity supplies examples to the local agent. Direct SQL reuse additionally
requires a conservative intent fingerprint; similarity never changes filters.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.orm import Session
from sqlglot import exp, parse

_STOP = frozenset("a an the of to for in on with from me our show list what is are was were please tell give get how much many can you do does this that those these your their about just during did we have had by per".split())
_SYNONYMS = {"revenue": "sales", "turnover": "sales", "billing": "billed", "bill": "billed",
    "invoices": "invoice", "documents": "invoice", "document": "invoice",
    "customers": "customer", "countries": "country",
    "materials": "material", "products": "material", "product": "material", "industries": "industry",
    "profits": "profit", "profitability": "profit", "profitable": "profit",
    "margins": "margin", "costs": "cost", "components": "component",
    "monthly": "month", "quarterly": "quarter", "yearly": "year", "annual": "year",
    "sum": "total", "overall": "total", "aggregate": "total", "highest": "top", "largest": "top",
    "lowest": "bottom", "smallest": "bottom", "versus": "compare", "vs": "compare"}


def intent_tokens(question):
    q = (question or "").lower()
    q = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", q)
    q = re.sub(r"\bbilling documents?\b", "invoice", q)
    q = re.sub(r"\b(?:how many|number of)\b", "count", q)
    q = re.sub(r"\b(?:net|billed)\s+(?:sales|revenue)\b", "sales", q)
    q = re.sub(r"\bhow much\b", "total", q)
    words = re.findall(r"[-+]?\d+(?:\.\d+)?|[^\W\d]\w*|[<>!=]+", q)
    return tuple(_SYNONYMS.get(w, w) for w in words if w not in _STOP)


def fingerprint(question):
    # Preserve every entity, negation, operator, number, and ordering word.
    # Only canonical sales totals can omit the word 'total'.
    tokens = list(intent_tokens(question))
    dimensions = {"customer", "country", "material", "industry", "month", "quarter", "year"}
    if "sales" in tokens and not dimensions.intersection(tokens):
        tokens = [t for t in tokens if t != "total"]
    sensitive = {"not", "no", "without", "except", "excluding", "exclude", "above", "below", "between",
                 "over", "under", "than", "before", "after", "and", "or", "<", ">", "<=", ">=", "!=", "="}
    canonical = dimensions | {"sales", "billed", "invoice", "count", "total", "top", "bottom", "compare", "currency"}
    # Unknown terms and non-year numbers can be entity/threshold values. Keep
    # their attachment to dimensions instead of sorting them into the same bag.
    ordered = bool(sensitive.intersection(tokens)) or any(
        t not in canonical and not re.fullmatch(r'(?:19|20)\d{2}', t) for t in tokens)
    literals = tuple(re.findall(r"['\"]([^'\"]+)['\"]", question or ""))
    return (tuple(tokens) if ordered else tuple(sorted(tokens)), literals)


def readonly_candidate(sql):
    try:
        trees = parse(sql, read="postgres")
        return len(trees) == 1 and isinstance(trees[0], exp.Select) and not any(
            isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Into))
            for node in trees[0].walk())
    except Exception:
        return False


def mixed_currency_billing_total(sql):
    """Detect a direct billed-net sum that collapses multiple currencies.

    Complex investigations keep their own review path. This guards the legacy
    single-SELECT totals that predate currency-aware Basic templates.
    """
    try:
        tree = parse(sql, read="postgres")[0]
        if not isinstance(tree, exp.Select) or len(list(tree.find_all(exp.Select))) != 1:
            return False
        if not {table.name.upper() for table in tree.find_all(exp.Table)}.intersection({"VBRK", "VBRP"}):
            return False
        if not any(column.name.lower() == "netwr" for summation in tree.find_all(exp.Sum)
                   for column in summation.find_all(exp.Column)):
            return False
        currencies = {"waerk", "waers", "rtcur"}
        projected = any(column.name.lower() in currencies for selection in tree.selects
                        for column in selection.find_all(exp.Column))
        grouping = tree.args.get("group")
        grouped = bool(grouping and projected and any(
            column.name.lower() in currencies for column in grouping.find_all(exp.Column)
        ))
        if grouped:
            return False
        where = tree.args.get("where")
        terms = []
        def flatten_and(node):
            if isinstance(node, exp.And):
                flatten_and(node.left)
                flatten_and(node.right)
            else:
                terms.append(node)
        if where:
            flatten_and(where.this)
        single_currency = any(
            isinstance(term, exp.EQ)
            and any(column.name.lower() in currencies for column in term.find_all(exp.Column))
            and any(literal.is_string for literal in term.find_all(exp.Literal))
            for term in terms
        )
        return not single_currency
    except Exception:
        return False


def profit_question_without_profit_sql(question, steps):
    """Keep revenue/clearing totals from being replayed as checked profit.

    A saved profit answer needs a physical profit measure or an explicit
    revenue-minus-cost expression. An alias named ``profit`` alone is not
    evidence of that calculation.
    """
    if "profit" not in intent_tokens(question):
        return False
    for step in steps:
        try:
            tree = parse(str(step.get("sql") or ""), read="postgres")[0]
            for selection in tree.selects:
                expression = selection.this if isinstance(selection, exp.Alias) else selection
                columns = {column.name.lower() for column in expression.find_all(exp.Column)}
                if columns.intersection({"profit", "gross_profit", "net_profit", "profit_amount"}):
                    return False
                if columns.intersection({"cost", "cogs", "expense", "expenses", "wavwr", "vprs"}) \
                        and columns.intersection({"netwr", "revenue", "sales", "net_sales"}) \
                        and any(isinstance(node, exp.Sub) for node in expression.walk()):
                    return False
        except Exception:
            continue
    return True


def _cosine(a, b):
    if len(a) != len(b) or not a or not all(math.isfinite(x) for x in (*a, *b)):
        return 0.0
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0.0


@lru_cache(maxsize=1024)
def _embeddings(url, model, questions):
    from .basic_local_provider import ollama_post
    if "cloud" in model.lower() or "/" in model:
        raise ValueError("Embedding model must be installed locally")
    from .investigation_budget import current_budget
    budget = current_budget()
    if budget:
        budget.checkpoint("schema_retrieval")
    body = ollama_post("/api/embed", {"model": model, "input": list(questions), "truncate": False},
                       min(10, budget.remaining_s()) if budget else 10)
    vectors = tuple(tuple(float(value) for value in row) for row in body["embeddings"])
    if len(vectors) != len(questions) or any(not v or not all(math.isfinite(x) for x in v) for v in vectors):
        raise ValueError("Invalid embeddings")
    return vectors


def retrieve_examples(question, examples, top_k=3, *, use_embeddings=True):
    wanted = set(intent_tokens(question))
    candidates = [dict(e, sql=str(e.get("sql") or "").strip().rstrip(";")) for e in examples or []
                  if e.get("question") and readonly_candidate(str(e.get("sql") or ""))
                  and not mixed_currency_billing_total(str(e.get("sql") or ""))
                  and not profit_question_without_profit_sql(e["question"], e.get("steps") or [e])]
    # Exact canonical matches need no embedding call, even if Ollama is configured.
    exact = [dict(e, similarity=1.0, retrieval="canonical", reusable=True) for e in candidates
             if fingerprint(question) == fingerprint(e["question"])]
    if exact and wanted:
        # Automatic memory copies can lack the original training provenance.
        # Restore it only for identical SQL/source, never a similar query,
        # another database or a planned/multi-query investigation.
        def identity(example):
            return (example.get("source"), parse(example["sql"], read="postgres")[0].sql(dialect="postgres"))
        trained = {identity(e): e for e in reversed(exact) if e.get("training_example")}
        exact = [trained.get(identity(e), e) if not e.get("analysis_plan") and not e.get("steps") else e
                 for e in exact]
        seen_training = set()
        distinct = []
        for example in exact:
            key = example.get("training_example_id")
            if key and key in seen_training:
                continue
            if key:
                seen_training.add(key)
            distinct.append(example)
        return distinct[:top_k]
    if len(wanted) < 2:
        return []
    ranked = []
    documents = [Counter(intent_tokens(e["question"])) for e in candidates]
    average_length = sum(sum(d.values()) for d in documents) / len(documents) if documents else 1
    frequencies = Counter(token for document in documents for token in document)
    for e, document in zip(candidates, documents):
        score = 0.0
        for token in wanted:
            count = document.get(token, 0)
            if count:
                inverse_frequency = math.log(1 + (len(documents) - frequencies[token] + 0.5) / (frequencies[token] + 0.5))
                score += inverse_frequency * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * sum(document.values()) / average_length))
        ranked.append(dict(e, similarity=score / (1 + score), retrieval="bm25", reusable=False))
    ranked.sort(key=lambda e: e["similarity"], reverse=True)
    model = os.getenv("BASIC_EMBED_MODEL", "").strip()
    if model and use_embeddings and ranked:
        try:
            url = os.getenv("BASIC_OLLAMA_URL", "http://127.0.0.1:11434")
            vectors = _embeddings(url, model, (question, *(e["question"] for e in ranked[:6])))
            query = vectors[0]
            # Bound a cold cache's cost. Examples can guide SQL generation but
            # are never executed on semantic similarity alone.
            for e, vector in zip(ranked[:6], vectors[1:]):
                e["similarity"] = _cosine(query, vector)
                e["retrieval"] = "ollama_embedding"
            ranked = [e for e in ranked[:6] if e["similarity"] >= 0.65]
            ranked.sort(key=lambda e: e["similarity"], reverse=True)
        except Exception:
            # Missing runtime/model leaves the offline retriever usable.
            pass
    # Several aliases of one checked SQL should not crowd out other useful
    # examples in the small local model's limited context. This does not
    # change which questions are allowed to replay SQL: only exact fingerprints
    # receive reusable=True above.
    distinct = []
    seen_sql = set()
    for example in ranked:
        if example["similarity"] < 0.20 or example["sql"] in seen_sql:
            continue
        distinct.append(example)
        seen_sql.add(example["sql"])
        if len(distinct) >= top_k:
            break
    return distinct


def recall_sql(question, examples):
    return next((e["sql"] for e in retrieve_examples(question, examples, use_embeddings=False) if e["reusable"]), "")


def adapt_training_year_filter(question, examples):
    """Adapt an unambiguous checked year filter to the requested years.

    The saved question must have the same non-date intent. Only a single SQL
    IN year filter or a full-year, half-open date interval can be changed.
    """
    requested_years = list(dict.fromkeys(re.findall(r"\b(?:19|20)\d{2}\b", question or "")))
    if not requested_years or len(requested_years) > 2:
        return None

    year = r"(?:19|20)\d{2}"
    range_request = bool(len(requested_years) == 2 and re.search(
        rf"\b(?:between\s+{year}\s+(?:and|to)\s+{year}|"
        rf"{year}\s+(?:to|through|thru|until)\s+{year})\b",
        question or "", re.I))
    if range_request:
        first, last = map(int, requested_years)
        if first > last or last - first > 15:
            return None
        target_years = [str(year) for year in range(first, last + 1)]
    else:
        target_years = requested_years

    ignored = {"specific", "sap", "erp", "year", "years", "and", "between", "during",
               "through", "thru", "until"}
    def core(text):
        return {token for token in intent_tokens(text)
                if not re.fullmatch(r"(?:19|20)\d{2}", token) and token not in ignored}

    wanted = core(question)
    if not wanted or not wanted.intersection({"sales", "profit", "margin", "cost", "invoice", "count"}):
        return None

    from sqlglot import exp, parse_one
    for example in examples or []:
        if not example.get("training_example") or not example.get("question"):
            continue
        saved_question = str(example["question"])
        saved_years = list(dict.fromkeys(re.findall(r"\b(?:19|20)\d{2}\b", saved_question)))
        if len(saved_years) > 1 or core(saved_question) != wanted:
            continue
        try:
            tree = parse_one(str(example.get("sql") or ""), read="postgres")
            if not isinstance(tree, exp.Select):
                continue
            if range_request:
                # A sorted detail query with LIMIT can return only the first
                # year of a multi-year range. Require a year-level breakdown.
                grouped = tree.args.get("group")
                year_fields = {"fkdat", "audat", "budat", "bldat", "erdat",
                               "salesyear", "fiscal_year", "year"}
                if not grouped or not any(
                    (isinstance(item, exp.Column) and item.name.lower() in
                     {"salesyear", "fiscal_year", "year"})
                    or (isinstance(item, (exp.Substring, exp.Extract)) and
                        any(col.name.lower() in year_fields for col in item.find_all(exp.Column)))
                    for item in grouped.expressions
                ):
                    continue
            if not saved_years:
                if not re.search(r"\byears?\b", saved_question, re.I) or len(list(tree.find_all(exp.Select))) != 1:
                    continue
                candidates = []
                for condition in tree.find_all(exp.In):
                    refs = {column.name.lower() for column in condition.this.find_all(exp.Column)}
                    if not refs.intersection({"fkdat", "budat", "bldat", "salesyear", "fiscal_year", "year"}):
                        continue
                    literals = list(condition.expressions)
                    if literals and all(isinstance(value, exp.Literal)
                                        and re.fullmatch(r"(?:19|20)\d{2}", str(value.this))
                                        for value in literals):
                        candidates.append(condition)
                if len(candidates) != 1:
                    continue
                candidates[0].set("expressions", [exp.Literal.string(year) for year in target_years])
            else:
                # A saved single-year question can be reused only when its SQL
                # contains exactly one full-year interval on the same SAP date.
                if len(requested_years) == 2 and not range_request:
                    continue
                lower, upper = [], []
                for where in tree.find_all(exp.Where):
                    for condition in where.this.find_all(exp.GTE, exp.LT):
                        if not isinstance(condition.this, exp.Column) or not isinstance(condition.expression, exp.Literal):
                            continue
                        column = condition.this
                        if column.name.lower() not in {"fkdat", "audat", "budat", "bldat", "erdat"}:
                            continue
                        if not re.fullmatch(r"(?:19|20)\d{6}", str(condition.expression.this)):
                            continue
                        if condition.find_ancestor(exp.Or) is not None:
                            continue
                        (lower if isinstance(condition, exp.GTE) else upper).append(condition)
                if len(lower) != 1 or len(upper) != 1:
                    continue
                start, end = lower[0], upper[0]
                start_field, end_field = start.this, end.this
                original_year = int(saved_years[0])
                if (start_field.sql(dialect="postgres") != end_field.sql(dialect="postgres")
                        or start.expression.this != f"{original_year}0101"
                        or end.expression.this != f"{original_year + 1}0101"):
                    continue
                start.set("expression", exp.Literal.string(f"{target_years[0]}0101"))
                end.set("expression", exp.Literal.string(f"{int(target_years[-1]) + 1}0101"))
            adapted = dict(example)
            adapted.update(sql=tree.sql(dialect="postgres"), reusable=True,
                           retrieval="training_year_filter", training_year_adaptation=target_years)
            return adapted
        except Exception:
            continue
    return None


def investigation_steps(payload):
    """Ordered read-only queries that produced one checked answer.

    A missing or writable query rejects the whole investigation so Basic cannot
    replay part of a result as if it were the complete checked answer.
    """
    if payload.get("query_plan", {}).get("conditional_request"):
        # A saved outcome cannot stand in for re-evaluating a branch tomorrow.
        return []
    sets = [item for item in (payload.get("agent_results") or [])
            if isinstance(item, dict) and item.get("kind") == "analysis"]
    if not sets and readonly_candidate(str(payload.get("sql") or "")):
        source = str(payload.get("source") or "business")
        if source not in {"business", "application"}:
            return []
        return [{"sql": str(payload["sql"]).strip().rstrip(";"), "source": source,
                 "purpose": "", "analysis_plan": None}]
    steps = []
    for item in sets:
        sql = str(item.get("sql") or "").strip().rstrip(";")
        if not sql and len(sets) == 1:
            sql = str(payload.get("sql") or "").strip().rstrip(";")
        source = str(item.get("source") or "")
        plan = item.get("analysis_plan")
        if source not in {"business", "application"} or not readonly_candidate(sql):
            return []
        steps.append({"sql": sql, "source": source, "purpose": str(item.get("purpose") or "")[:400],
                      "analysis_plan": plan if isinstance(plan, dict) else None,
                      "primary": bool(payload.get("agent_primary_result_id")) and item.get("id") == payload.get("agent_primary_result_id")})
    question = str(payload.get("query_plan", {}).get("effective_question") or "")
    return steps if 1 <= len(steps) <= 6 and replayable_steps(question, steps) \
        and not profit_question_without_profit_sql(question, steps) else []


def replayable_steps(question, steps):
    """Reject follow-on filters that may embed an earlier result's entity.

    A ranking followed by WHERE product='yesterday's winner' is not a reusable
    method. Independent queries or SQL subqueries/CTEs can be replayed; missing
    dependency information must go back to Agentic.
    """
    if len(steps) <= 1:
        return True
    wording = (question or "").lower()
    for step in steps[1:]:
        try:
            tree = parse(str(step.get("sql") or ""), read="postgres")[0]
            for clause in tree.find_all(exp.Where, exp.Having, exp.Join):
                for literal in clause.find_all(exp.Literal):
                    value = str(literal.this).strip("%_").lower()
                    if not value or value in wording:
                        continue
                    # Explicit year questions can use ISO dates in their SQL.
                    if re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", value) and value[:4] in wording:
                        continue
                    return False
        except Exception:
            return False
    return True


metadata = MetaData()
memory = Table("ai_basic_query_memory", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", Integer, nullable=False, index=True),
    Column("scope_digest", String(64), nullable=False), Column("source", String(32), nullable=False),
    Column("question", Text, nullable=False), Column("sql", Text, nullable=False),
    Column("use_count", Integer, nullable=False), Column("updated_at", String(40), nullable=False))
plans = Table("ai_basic_query_plans", metadata,
    Column("id", String(64), primary_key=True), Column("plan_json", Text, nullable=False))


def save_verified_query(engine, scope, source, question, sql, analysis_plan=None, steps=None):
    from .analyst_drilldown import scope_digest
    if not question or not readonly_candidate(sql):
        return False
    supplied = list(steps or [])
    if profit_question_without_profit_sql(question, supplied or [{"sql": sql}]):
        return False
    if any(not isinstance(step, dict) for step in supplied) or len(supplied) > 6:
        return False
    normalized = []
    for step in supplied:
        sql_step = str(step.get("sql") or "").strip().rstrip(";")
        step_source = str(step.get("source") or "")
        plan = step.get("analysis_plan")
        if step_source not in {"business", "application"} or not readonly_candidate(sql_step):
            return False
        normalized.append({"sql": sql_step, "source": step_source, "purpose": str(step.get("purpose") or "")[:400],
                           "analysis_plan": plan if isinstance(plan, dict) else None,
                           "primary": bool(step.get("primary"))})
    checked = normalized if len(normalized) > 1 else []
    digest = scope_digest(scope)
    identity = json.dumps([(step["source"], step["sql"]) for step in checked]) if checked else sql
    identifier = hashlib.sha256((digest + source + repr(fingerprint(question)) + identity).encode()).hexdigest()
    metadata.create_all(engine, tables=[memory, plans])
    with Session(engine) as session:
        old = session.execute(select(memory.c.id).where(memory.c.id == identifier)).first()
        now = datetime.now(timezone.utc).isoformat()
        if old:
            session.execute(update(memory).where(memory.c.id == identifier).values(
                use_count=memory.c.use_count + 1, updated_at=now))
        else:
            session.execute(insert(memory).values(id=identifier, user_id=scope.user_id,
                scope_digest=digest, source=source, question=question, sql=sql, use_count=1, updated_at=now))
        stored_plan = {"kind": "basic_investigation", "analysis_plan": analysis_plan, "steps": checked} if checked else analysis_plan
        if stored_plan:
            plan_json = json.dumps(stored_plan)
            prior_plan = session.execute(select(plans.c.id).where(plans.c.id == identifier)).first()
            if prior_plan:
                session.execute(update(plans).where(plans.c.id == identifier).values(plan_json=plan_json))
            else:
                session.execute(insert(plans).values(id=identifier, plan_json=plan_json))
        session.commit()
    return True


def load_verified_queries(engine, scope, source, limit=200):
    from .analyst_drilldown import scope_digest
    digest = scope_digest(scope)
    metadata.create_all(engine, tables=[memory, plans])
    with Session(engine) as session:
        statement = select(memory.c.question, memory.c.sql, memory.c.updated_at, plans.c.plan_json).select_from(
            memory.outerjoin(plans, memory.c.id == plans.c.id)).where(
            memory.c.user_id == scope.user_id, memory.c.scope_digest == digest, memory.c.source == source
        ).order_by(memory.c.updated_at.desc())
        if limit is not None:
            statement = statement.limit(min(max(limit, 1), 500))
        rows = session.execute(statement).mappings().all()
        loaded = []
        for row in rows:
            parsed = json.loads(row["plan_json"]) if row["plan_json"] else None
            item = {"question": row["question"], "sql": row["sql"], "analysis_plan": parsed,
                    "source": source, "updated_at": row["updated_at"]}
            if isinstance(parsed, dict) and parsed.get("kind") == "basic_investigation":
                item["analysis_plan"] = parsed.get("analysis_plan")
                item["steps"] = parsed.get("steps") or []
            loaded.append(item)
        return loaded


def load_basic_examples(engine, scope, use_sap):
    # Both logical sources use the process-configured database when SAP mode is
    # disabled (AnalystTools.session("business") falls back to the app DB).
    # Keep checked business examples discoverable in that configuration too;
    # otherwise an exact saved question can miss retrieval and fall through to
    # a model merely because AI_CONTEXT_SOURCE changed after it was saved.
    sources = ["business", "application"]
    examples = [item for source in sources for item in load_verified_queries(engine, scope, source, None)]
    # SQL Training has its own UI and persistence table. Include only examples
    # that were successfully executed and explicitly saved; otherwise Basic
    # would miss them and unnecessarily fall through to the local model.
    try:
        from .basic_sql_training import list_examples
        trained = [item for item in list_examples(engine, scope)
                   if item.get("replayable") and item.get("source") in sources]
        for item in trained:
            examples.append({"question": item["question"], "sql": item["sql"],
                "source": item["source"], "updated_at": item.get("updated_at"),
                "training_example_id": item.get("id"), "training_revision": item.get("revision"),
                "training_example": True})
    except Exception:
        # Training memory is optional; retain the existing verified RAG path if
        # a legacy deployment has not created the SQL Training tables yet.
        pass
    examples = [item for item in examples if not any(
        mixed_currency_billing_total(step.get("sql", "")) for step in (item.get("steps") or [item])
    ) and not profit_question_without_profit_sql(item["question"], item.get("steps") or [item])]
    return sorted(examples, key=lambda item: item.get("updated_at", 0), reverse=True)


def capture_training_reference(payload, engine, scope, question=None):
    """Opaque, server-owned evidence used when a person teaches a question alias."""
    from .analyst_drilldown import store_artifact
    steps = investigation_steps(payload)
    if not steps:
        return
    primary_id = str(payload.get("agent_primary_result_id") or "")
    analyses = [item for item in payload.get("agent_results", []) if item.get("kind") == "analysis"]
    primary = next((item for item in analyses if item.get("id") == primary_id), analyses[-1] if analyses else {})
    primary_sql = str(primary.get("sql") or payload.get("sql") or steps[-1]["sql"]).strip().rstrip(";")
    if not any(step["sql"] == primary_sql for step in steps):
        primary_sql = steps[-1]["sql"]
    effective_question = str(payload.get("query_plan", {}).get("effective_question") or "")
    # Basic must be able to replay the checked query when the user repeats the
    # wording they actually asked. Agentic's effective question can be a
    # rewritten interpretation, so keep it for investigation validation but
    # use the original prompt as the saved Basic question.
    question = str(question or payload.get("question") or effective_question).strip()
    primary_step = next((step for step in steps if step.get("primary")),
                        next(step for step in steps if step["sql"] == primary_sql))
    identifier = store_artifact(engine, scope, {"kind": "basic_training", "question": question,
        "sql": primary_sql, "source": primary_step["source"], "analysis_plan": primary_step.get("analysis_plan"),
        "steps": steps})
    reference = {"id": identifier, "question": question, "queries": len(steps)}
    payload.setdefault("meta", {})["basic_training_reference"] = reference
    payload.setdefault("query_plan", {})["basic_training_reference"] = reference


def teach_verified_question(engine, scope, identifier, question):
    from .analyst_drilldown import load_artifact
    question = question.strip()
    if not 3 <= len(question) <= 2000:
        raise ValueError("Enter a question between 3 and 2000 characters")
    original = load_artifact(engine, scope, identifier)
    if original.get("kind") != "basic_training":
        raise ValueError("Choose a verified result to teach Basic")
    if fingerprint(question) != fingerprint(original["question"]):
        raise ValueError("Keep the same year, amounts, named filters, metric, grouping, ranking, and conditions as the checked result. Run Agentic to check a different question.")
    steps = original.get("steps") or []
    if any(mixed_currency_billing_total(step.get("sql", "")) for step in (steps or [original])):
        raise ValueError("This billed total mixes currencies. Check a result grouped by currency or filtered to one currency before teaching Basic.")
    if profit_question_without_profit_sql(question, steps or [original]):
        raise ValueError("This SQL does not calculate profit. Check a result with an explicit profit measure or revenue-minus-cost calculation before teaching Basic.")
    saved = save_verified_query(engine, scope, original["source"], question, original["sql"], original.get("analysis_plan"), steps)
    if not saved:
        raise ValueError("This result cannot be taught as a read-only query")
    query_count = len(steps) if len(steps) > 1 else 1
    detail = f"all {query_count} checked queries" if query_count > 1 else "the checked query"
    return {"saved": True, "question": question, "model_calls": 0, "queries": query_count,
            "message": f"Basic can now answer this taught question by rerunning {detail} with fresh database results and no model tokens."}
