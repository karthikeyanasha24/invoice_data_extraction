"""Standalone terminal chat — general questions via OpenAI and/or Gemini.

Reads OPEN_AI_KEY and GOOGLE_API_KEY from zodiac-api/.env.
Does not query SAP, the adaptive API, or print secrets.

Usage (from zodiac-api):
  python scripts/general_ask.py
  python scripts/general_ask.py --provider gemini
  python scripts/general_ask.py --provider openai   # falls back to Gemini if OpenAI has no credits
  python scripts/general_ask.py --provider both
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_OPENAI_MODEL = os.getenv("AI_FAST_MODEL") or "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_CHAT_MODEL") or "gemini-2.5-flash"


def _openai_key() -> str:
    return (os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()


def _google_key() -> str:
    return (os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or "").strip()


def _is_openai_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "insufficient_quota" in text or "credit_balance_exhausted" in text or (
        "429" in text and "credit" in text
    )


def ask_openai(question: str, model: str, history: list[dict[str, str]]) -> str:
    from openai import OpenAI

    key = _openai_key()
    if not key:
        raise RuntimeError("OPEN_AI_KEY is not set in .env")
    client = OpenAI(api_key=key)
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    kwargs: dict = {"model": model, "messages": messages}
    # gpt-5 family often rejects temperature / max_tokens
    if not str(model).lower().startswith("gpt-5"):
        kwargs["temperature"] = 0.4
        kwargs["max_tokens"] = 1200
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def ask_gemini(question: str, model: str, history: list[dict[str, str]]) -> str:
    import json
    import urllib.error
    import urllib.request

    key = _google_key()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set in .env")
    contents: list[dict] = []
    for turn in history:
        role = "user" if turn["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": turn["content"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})
    body = json.dumps(
        {
            "system_instruction": {"parts": [{"text": "You are a helpful assistant."}]},
            "contents": contents,
        }
    ).encode()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    cands = payload.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    parts = (((cands[0] or {}).get("content") or {}).get("parts") or [])
    text = "".join(str(p.get("text") or "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini empty text: {payload}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask general questions in the terminal.")
    parser.add_argument(
        "--provider",
        choices=("openai", "gemini", "both"),
        default="gemini",
        help="Which LLM to use (default: gemini — OpenAI key currently has no credits).",
    )
    parser.add_argument("--model", default="", help="Override OpenAI model.")
    parser.add_argument("--gemini-model", default="", help="Override Gemini model.")
    parser.add_argument("question", nargs="*", help="Optional one-shot question (else interactive).")
    args = parser.parse_args()

    openai_model = args.model or DEFAULT_OPENAI_MODEL
    gemini_model = args.gemini_model or DEFAULT_GEMINI_MODEL
    providers = ["openai", "gemini"] if args.provider == "both" else [args.provider]

    if "openai" in providers and not _openai_key():
        print("OPEN_AI_KEY missing in .env", file=sys.stderr)
        return 1
    if "gemini" in providers and not _google_key():
        print("GOOGLE_API_KEY missing in .env", file=sys.stderr)
        return 1

    history: list[dict[str, str]] = []

    def run_one(q: str) -> None:
        q = q.strip()
        if not q:
            return
        last_answer = ""
        for p in providers:
            try:
                if p == "openai":
                    answer = ask_openai(q, openai_model, history)
                    label = f"OpenAI ({openai_model})"
                else:
                    answer = ask_gemini(q, gemini_model, history)
                    label = f"Gemini ({gemini_model})"
            except Exception as exc:
                if p == "openai" and _is_openai_quota_error(exc) and _google_key() and args.provider != "both":
                    print(
                        "\nOpenAI has no credits left. Switching to Gemini for this chat.\n"
                    )
                    try:
                        answer = ask_gemini(q, gemini_model, history)
                        label = f"Gemini ({gemini_model})"
                    except Exception as gexc:
                        print(f"\n[gemini] ERROR: {type(gexc).__name__}: {gexc}\n")
                        continue
                else:
                    if p == "openai" and _is_openai_quota_error(exc):
                        print(
                            "\n[openai] No credits remaining. "
                            "Use: python scripts/general_ask.py --provider gemini\n"
                        )
                    else:
                        print(f"\n[{p}] ERROR: {type(exc).__name__}: {exc}\n")
                    continue
            print(f"\n{label}:\n{answer}\n")
            if not last_answer:
                last_answer = answer
        history.append({"role": "user", "content": q})
        if last_answer:
            history.append({"role": "assistant", "content": last_answer})

    oneshot = " ".join(args.question).strip()
    if oneshot:
        run_one(oneshot)
        return 0

    print("General chat (not SAP / not AI Analyst).")
    print(f"Provider: {args.provider}  |  quit with empty line or :q")
    print()
    while True:
        try:
            q = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q or q in {":q", ":quit", "exit"}:
            return 0
        if q == ":clear":
            history.clear()
            print("(history cleared)")
            continue
        run_one(q)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
