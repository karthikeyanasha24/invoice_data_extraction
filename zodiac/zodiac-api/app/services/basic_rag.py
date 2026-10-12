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
    if len(wanted) < 2:
        return []
    candidates = [dict(e, sql=str(e.get("sql") or "").strip().rstrip(";")) for e in examples or []
                  if e.get("question") and readonly_candidate(str(e.get("sql") or ""))]
    # Exact canonical matches need no embedding call, even if Ollama is configured.
    exact = [dict(e, similarity=1.0, retrieval="canonical", reusable=True) for e in candidates
             if fingerprint(question) == fingerprint(e["question"])]
    if exact:
        return exact[:top_k]
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
    if model and use_embeddings and ranked and not os.getenv("VERCEL"):
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
    return [e for e in ranked if e["similarity"] >= 0.20][:top_k]


def recall_sql(question, examples):
    return next((e["sql"] for e in retrieve_examples(question, examples, use_embeddings=False) if e["reusable"]), "")


metadata = MetaData()
memory = Table("ai_basic_query_memory", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", Integer, nullable=False, index=True),
    Column("scope_digest", String(64), nullable=False), Column("source", String(32), nullable=False),
    Column("question", Text, nullable=False), Column("sql", Text, nullable=False),
    Column("use_count", Integer, nullable=False), Column("updated_at", String(40), nullable=False))
plans = Table("ai_basic_query_plans", metadata,
    Column("id", String(64), primary_key=True), Column("plan_json", Text, nullable=False))


def save_verified_query(engine, scope, source, question, sql, analysis_plan=None):
    from .analyst_drilldown import scope_digest
    if not question or not readonly_candidate(sql):
        return False
    digest = scope_digest(scope)
    identifier = hashlib.sha256((digest + source + repr(fingerprint(question)) + sql).encode()).hexdigest()
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
        if analysis_plan:
            plan_json = json.dumps(analysis_plan)
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
        rows = session.execute(select(memory.c.question, memory.c.sql, plans.c.plan_json).select_from(
            memory.outerjoin(plans, memory.c.id == plans.c.id)).where(
            memory.c.user_id == scope.user_id, memory.c.scope_digest == digest, memory.c.source == source
        ).order_by(memory.c.updated_at.desc()).limit(min(max(limit, 1), 500))).mappings().all()
        return [{"question": row["question"], "sql": row["sql"],
                 "analysis_plan": json.loads(row["plan_json"]) if row["plan_json"] else None} for row in rows]


def capture_training_reference(payload, engine, scope):
    """Opaque, server-owned evidence used when a person teaches a question alias."""
    from .analyst_drilldown import store_artifact
    sets = [r for r in payload.get("agent_results", []) if r.get("kind") == "analysis"]
    if len(sets) > 1 or payload.get("query_plan", {}).get("conditional_request"):
        return
    source = sets[0].get("source") if sets else None
    if not source or not readonly_candidate(payload.get("sql", "")):
        return
    question = str(payload.get("query_plan", {}).get("effective_question") or "")
    identifier = store_artifact(engine, scope, {"kind": "basic_training", "question": question,
        "sql": payload["sql"], "source": source, "analysis_plan": sets[0].get("analysis_plan") if sets else None})
    reference = {"id": identifier, "question": question}
    payload.setdefault("meta", {})["basic_training_reference"] = reference
    payload.setdefault("query_plan", {})["basic_training_reference"] = reference


def _teaching_constraints(question):
    guarded = {"customer", "country", "material", "industry", "month", "quarter", "year",
        "top", "bottom", "count", "average", "not", "no", "without", "except", "excluding",
        "above", "below", "before", "after", "compare", "usd", "eur", "dem", "gbp", "inr", "jpy", "chf"}
    return sorted(t for t in intent_tokens(question) if t in guarded or re.fullmatch(r'[-+]?\d+(?:\.\d+)?', t))


def teach_verified_question(engine, scope, identifier, question):
    from .analyst_drilldown import load_artifact
    question = question.strip()
    if not 3 <= len(question) <= 2000:
        raise ValueError("Enter a question between 3 and 2000 characters")
    original = load_artifact(engine, scope, identifier)
    if original.get("kind") != "basic_training":
        raise ValueError("Choose a verified single-query result to teach Basic")
    if _teaching_constraints(question) != _teaching_constraints(original["question"]):
        raise ValueError("Keep the same year, amounts, currency, grouping, ranking, and conditions as the checked result. Run a new analysis to teach a different scope.")
    # Named filters in the checked wording must survive a teaching alias too.
    ignored = {"show", "please", "what", "which", "how", "give", "get", "list", "find", "tell", "total",
               "sales", "revenue", "billed", "top", "bottom", "compare", "customers", "customer", "country",
               "materials", "material", "products", "product", "industry", "profit", "profits", "margin"}
    named = {word.lower() for word in re.findall(r'\b[A-Z][A-Za-z]+\b', original["question"]) if word.lower() not in ignored}
    if not named.issubset(set(intent_tokens(question))):
        raise ValueError("Keep the named filters from the checked result when teaching its question wording")
    saved = save_verified_query(engine, scope, original["source"], question, original["sql"], original.get("analysis_plan"))
    if not saved:
        raise ValueError("This result cannot be taught as a read-only query")
    return {"saved": True, "question": question, "model_calls": 0,
            "message": "Basic can now answer this taught question with fresh database results and no model tokens."}
