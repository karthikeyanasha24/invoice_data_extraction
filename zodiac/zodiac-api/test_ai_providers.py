"""
Smoke-test AI providers using the same .env as zodiac-api (no secrets in this file).

Usage (from zodiac-api directory):
  python test_ai_providers.py

Uses one tiny prompt per provider to minimize cost. Prints WORKING or FAILED for each.

OpenAI model resolution (same order as app config): LANGGRAPH_OPENAI_MODEL,
OPENAI_MODEL, OPENAI_CHAT_MODEL, else default gpt-5. Uses openai_chat_params
for GPT-5 (max_completion_tokens, temperature rules). OpenRouter defaults to
openai/gpt-5 unless OPENROUTER_TEST_MODEL is set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Resolve `app.*` imports (same layout as running the API from zodiac-api/)
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.utils.openai_chat_params import (  # noqa: E402
    openai_chat_temperature_kwargs,
    openai_completion_limit_kwargs,
)

PROMPT = 'Reply with exactly the single word: OK'


def _smoke_output_token_cap(model: str, *, openrouter: bool = False) -> int:
    """GPT-5 / reasoning models may use much of the budget before visible text."""
    m = (model or "").lower()
    if "gpt-5" in m or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
        # OpenRouter billing often caps max_tokens lower than direct OpenAI.
        return 1024 if openrouter else 4096
    return 128


def _resolved_openai_model() -> str:
    """Match zodiac-api app/config: LANGGRAPH_OPENAI_MODEL, OPENAI_MODEL, then OPENAI_CHAT_MODEL, else gpt-5."""
    for key in ("LANGGRAPH_OPENAI_MODEL", "OPENAI_MODEL", "OPENAI_CHAT_MODEL"):
        v = os.getenv(key, "").strip()
        if v:
            return v
    return "gpt-5"


def _load_env() -> Path:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    return root


def _print_result(name: str, ok: bool, detail: str = "") -> None:
    status = "WORKING" if ok else "FAILED"
    line = f"  [{name}] {status}"
    if detail:
        line += f" - {detail}"
    print(line)


def test_openai() -> None:
    key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY") or "").strip()
    if not key:
        _print_result("OpenAI", False, "no OPENAI_API_KEY or OPEN_AI_KEY in .env")
        return
    try:
        from openai import OpenAI

        model = _resolved_openai_model()
        client = OpenAI(api_key=key)
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You follow instructions exactly."},
                {"role": "user", "content": PROMPT},
            ],
            **openai_chat_temperature_kwargs(model, 0.0),
            **openai_completion_limit_kwargs(model, _smoke_output_token_cap(model)),
        )
        text = (r.choices[0].message.content or "").strip()
        _print_result("OpenAI", bool(text), f"model={model!r} preview={text[:80]!r}")
    except Exception as e:
        _print_result("OpenAI", False, str(e))


def test_google() -> None:
    key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GEMINI_API_KEY")
        or ""
    ).strip()
    if not key:
        _print_result("Google Gemini", False, "no GOOGLE_API_KEY (or GOOGLE_GEMINI_API_KEY)")
        return
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model_name = os.getenv("GEMINI_TEST_MODEL", "gemini-2.0-flash")
        model = genai.GenerativeModel(model_name)
        r = model.generate_content(
            PROMPT,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=32,
                temperature=0,
            ),
        )
        text = (r.text or "").strip()
        _print_result("Google Gemini", bool(text), f"model={model_name!r} preview={text[:80]!r}")
    except Exception as e:
        _print_result("Google Gemini", False, str(e))


def test_anthropic() -> None:
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        _print_result("Anthropic", False, "no ANTHROPIC_API_KEY in .env")
        return
    try:
        import anthropic

        model = os.getenv("ANTHROPIC_TEST_MODEL", "claude-3-5-haiku-20241022")
        client = anthropic.Anthropic(api_key=key)
        r = client.messages.create(
            model=model,
            max_tokens=32,
            temperature=0,
            system="You follow instructions exactly.",
            messages=[{"role": "user", "content": PROMPT}],
        )
        text = (r.content[0].text or "").strip() if r.content else ""
        _print_result("Anthropic", bool(text), f"model={model!r} preview={text[:80]!r}")
    except Exception as e:
        _print_result("Anthropic", False, str(e))


def test_openrouter() -> None:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        _print_result("OpenRouter", False, "no OPENROUTER_API_KEY in .env")
        return
    try:
        from openai import OpenAI

        model = os.getenv("OPENROUTER_TEST_MODEL", "").strip() or "openai/gpt-5"
        client = OpenAI(
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
        )
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You follow instructions exactly."},
                {"role": "user", "content": PROMPT},
            ],
            **openai_chat_temperature_kwargs(model, 0.0),
            **openai_completion_limit_kwargs(model, _smoke_output_token_cap(model, openrouter=True)),
        )
    except Exception as e:
        _print_result("OpenRouter", False, str(e))


def main() -> None:
    env_dir = _load_env()
    print(f"Loaded .env from: {env_dir / '.env'}")
    print(f"Test prompt for each provider: {PROMPT!r}\n")
    print("Question: Can each API return a non-empty model response?")
    print("Answers:\n")
    test_openai()
    test_google()
    test_anthropic()
    test_openrouter()
    print("\nDone.")


if __name__ == "__main__":
    main()
