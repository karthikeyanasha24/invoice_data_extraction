"""Consolidate local analyst settings without printing or replacing secrets."""
from pathlib import Path
import re

path = Path(__file__).resolve().parents[1] / ".env"
lines = path.read_text(encoding="utf-8-sig").splitlines()
canonical_key_present = any(re.match(r"\s*OPENAI_API_KEY\s*=\s*\S", line) for line in lines)
updates = {
    "AI_CHAT_PROVIDER": "openai",
    "AI_ANALYST_MODEL": "gpt-6.1-sol",
    "AI_ANALYST_ALLOW_PROVIDER_FALLBACK": "false",
    "AI_LLM_CALL_TIMEOUT_SECONDS": "60",
    "AI_ANALYST_ANSWER_MAX_TOKENS": "8000",
    "AI_ANALYST_PLANNING_MAX_TOKENS": "6000",
    "AI_ANALYST_UNDERSTANDING_MAX_TOKENS": "3000",
    "ADAPTIVE_INVESTIGATION_LIMIT_SECONDS": "180",
    "ENABLE_MULTI_MODEL": "false",
    "OPENAI_MODEL": "gpt-6.1-sol",
}
obsolete = {
    "AI_PREFER_GEMINI", "AI_NATIVE_OPENAI_MODEL", "AI_JSON_MAX_TOKENS", "AI_RESPONSE_MAX_TOKENS",
    "LANGGRAPH_OPENAI_MODEL", "LANGGRAPH_SQL_MODEL", "LANGGRAPH_ANSWER_MODEL",
}
out = []
seen = set()
removed = set()
for line in lines:
    match = re.match(r"\s*([A-Z_][A-Z_0-9]*)\s*=", line)
    if match:
        key = match[1]
        if key in obsolete or key in updates:
            removed.add(key)
            continue
        if key == "OPEN_AI_KEY":
            if canonical_key_present:
                continue
            # Preserve the existing key value; standardize its name.
            line = line.replace("OPEN_AI_KEY", "OPENAI_API_KEY", 1)
            key = "OPENAI_API_KEY"
        if key in seen:
            continue
        seen.add(key)
    if re.match(r"\s*#\s*DATABASE_URL=", line):
        continue
    if line.startswith("#") and any(text in line for text in ("gpt-5", "gpt-4o-first")):
        continue
    out.append(line)
out.extend(["", "# Conversational analyst: one provider and explicit model authority."])
out.extend(f"{key}={value}" for key, value in updates.items())
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("Updated local analyst setting names:", ", ".join(updates))
print("Removed redundant setting names:", ", ".join(sorted(removed - updates.keys())))
print("Existing database and API credential values preserved; no values logged.")
