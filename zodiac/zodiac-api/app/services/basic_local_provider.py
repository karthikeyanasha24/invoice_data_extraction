"""Explicitly configured, self-hosted Ollama transport. Never falls back to paid APIs."""
from __future__ import annotations

import json
import os
import time
import uuid
from contextvars import ContextVar
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

_LOCAL = ContextVar("basic_local_agent", default=False)


def local_agent_enabled():
    return bool(os.getenv("BASIC_LOCAL_MODEL", "").strip())


def use_local_agent():
    return _LOCAL.set(True)


def restore_local_agent(token):
    _LOCAL.reset(token)


def local_agent_active():
    return _LOCAL.get()


def local_model():
    model = os.getenv("BASIC_LOCAL_MODEL", "").strip()
    if not model or "cloud" in model.lower() or "/" in model:
        raise ValueError("BASIC_LOCAL_MODEL must name an installed local Ollama model")
    return model


def ollama_endpoint_config():
    """Require an authenticated HTTPS proxy for a remotely hosted Ollama."""
    base = os.getenv("BASIC_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    url = urlsplit(base)
    host = (url.hostname or "").lower()
    if (url.scheme not in {"http", "https"} or not host or url.username or url.password
            or url.query or url.fragment or url.path not in {"", "/"}
            or host == "ollama.com" or host.endswith(".ollama.com")):
        raise ValueError("BASIC_OLLAMA_URL must be your self-hosted Ollama server")
    is_local = host in {"127.0.0.1", "localhost", "::1"}
    if is_local and os.getenv("VERCEL"):
        raise ValueError("A Vercel function cannot use a local Ollama daemon")
    key = os.getenv("BASIC_OLLAMA_API_KEY", "").strip()
    if not is_local and (url.scheme != "https" or not key):
        raise ValueError("Remote Ollama requires an HTTPS endpoint and BASIC_OLLAMA_API_KEY")
    return base, ({"Authorization": "Bearer " + key} if key else {})


def ollama_post(endpoint, payload, timeout):
    base, headers = ollama_endpoint_config()
    # Do not inherit proxy credentials or follow redirects to a hosted provider.
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        response = client.post(base + endpoint, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def casual_local_reply(question: str) -> dict:
    """Use the configured self-hosted model for short Basic conversation."""
    started = time.monotonic()
    model = local_model()
    body = ollama_post("/api/chat", {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Basic, a friendly billing-data assistant. Reply naturally "
                    "in one or two short sentences. For a greeting, greet the user and "
                    "ask what they want to know about billing. Do not mention models, "
                    "tokens, SQL, internal architecture, or capabilities unless asked. "
                    "Do not invent business data. Do not use Markdown."
                ),
            },
            {"role": "user", "content": str(question or "").strip()},
        ],
        "options": {"temperature": 0.3, "num_predict": 64, "num_ctx": 512},
    }, 20)
    message = body.get("message") if isinstance(body, dict) else None
    answer = str((message or {}).get("content") or "").strip()
    if not body.get("done") or not answer:
        raise ValueError("Local model did not complete its casual reply")
    input_tokens = int(body.get("prompt_eval_count") or 0)
    output_tokens = int(body.get("eval_count") or 0)
    return {
        "answer": answer,
        "model": "ollama/" + model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def _messages(instructions, items):
    messages = [{"role": "system", "content": instructions}]
    calls = {}
    for item in items:
        kind = item.get("type")
        if kind == "function_call":
            calls[item["call_id"]] = item["name"]
            call = {"type": "function", "function": {"name": item["name"], "arguments": json.loads(item["arguments"])}}
            if messages[-1].get("tool_calls"):
                messages[-1]["tool_calls"].append(call)
            else:
                messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
            if item.get("_ollama_thinking"):
                messages[-1]["thinking"] = item["_ollama_thinking"]
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_name": calls[item["call_id"]], "content": item["output"]})
        elif item.get("role") in {"user", "assistant"}:
            content = item.get("content", "")
            if isinstance(content, list):
                content = "\n".join(part.get("text", "") for part in content)
            messages.append({"role": item["role"], "content": content})
    return messages


def create_local_response(*, instructions, input, tools, output_schema):
    from .investigation_budget import current_budget
    from .analyst_usage import model_limits

    model = local_model()
    budget = current_budget()
    if budget:
        budget.checkpoint("agent_decision")
        if not budget.allow_llm():
            from .investigation_budget import InvestigationTimeout
            raise InvestigationTimeout("agent_decision", budget.elapsed_s(), cancelled=budget.cancelled)
    allowed = {t["name"]: t for t in tools if t["name"] != "research_public_context"}
    messages = _messages(instructions + "\nUse local database tools only. Return final JSON with this schema: "
                         + json.dumps(output_schema), input)
    limit = model_limits(input, instructions, list(allowed.values()), requested_output=4096, model="ollama/" + model)
    started = time.monotonic()
    body = ollama_post("/api/chat", {
        "model": model, "messages": messages, "stream": False, "think": False,
        "tools": [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
                  for t in allowed.values()],
        "options": {"temperature": 0, "num_predict": limit, "num_ctx": 2048},
    }, min(60, budget.remaining_s()) if budget else 60)
    if not body.get("done") or body.get("done_reason") == "length":
        raise ValueError("Local model did not complete its response")
    message = body.get("message") or {}
    output = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        if function.get("name") not in allowed or not isinstance(function.get("arguments"), dict):
            raise ValueError("Local model requested an unsupported tool")
        output.append({"type": "function_call", "name": function["name"], "call_id": uuid.uuid4().hex,
                       "arguments": json.dumps(function["arguments"])})
    if output and message.get("thinking"):
        output[0]["_ollama_thinking"] = message["thinking"]
    content = str(message.get("content") or "")
    if not output:
        # Reject prose, malformed JSON and extra fields before the agent's evidence validation.
        final = json.loads(content)
        if not isinstance(final, dict) or set(final) != set(output_schema["required"]):
            raise ValueError("Local model did not return the required answer format")
        if (final["kind"] not in output_schema["properties"]["kind"]["enum"]
                or not all(isinstance(final[k], str) for k in ("answer", "summary"))
                or not all(isinstance(final[k], list) and all(isinstance(v, str) for v in final[k])
                           for k in ("result_ids", "followups"))):
            raise ValueError("Local model returned invalid answer fields")
        output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]})
    if budget:
        inp, out = int(body.get("prompt_eval_count") or 0), int(body.get("eval_count") or 0)
        budget.diagnostics.setdefault("model_usage", []).append({
            "provider": "ollama", "model": "ollama/" + model, "purpose": "basic_local_agent",
            "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
            "cached_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0,
            "usage_reported": "prompt_eval_count" in body and "eval_count" in body,
            "estimated_cost_usd": "0", "elapsed_ms": round((time.monotonic() - started) * 1000),
        })
    return SimpleNamespace(output=output, output_text=content)
