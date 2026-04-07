"""
Ask OpenAI a question. Loads API key from .env (OPEN_AI_KEY), same as the API config.

Usage:
  python ask_openai.py "Your question here"
  python ask_openai.py   # prompts for a question
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def main() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    api_key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit(
            "Missing OPEN_AI_KEY (or OPENAI_API_KEY) in .env — "
            f"expected {env_path}"
        )

    question = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""
    if not question:
        question = input("Question: ").strip()
    if not question:
        sys.exit("No question provided.")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": question},
        ],
    )
    answer = response.choices[0].message.content
    print(answer or "")


if __name__ == "__main__":
    main()
