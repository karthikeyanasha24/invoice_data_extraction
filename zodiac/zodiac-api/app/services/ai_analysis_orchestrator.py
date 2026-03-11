from __future__ import annotations

from typing import Any, Dict, List

import json
import logging

from sqlalchemy.orm import Session

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover - runtime/env dependent
    OpenAI = None  # type: ignore

from .sap_sql_agent import SqlAgentResult, run_sap_sql_agent


logger = logging.getLogger(__name__)


def _get_openai_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. `pip install openai` is required.")
    return OpenAI()


def _summarize_result(question: str, result: SqlAgentResult) -> str:
    """
    Use an LLM to turn SQL + rows into a human-readable answer.
    """
    client = _get_openai_client()

    rows_preview: List[Dict[str, Any]] = result.rows[:50]
    rows_json = json.dumps(rows_preview, default=str)

    prompt = f"""
You are a data analyst.

User question:
{question}

SQL executed:
{result.sql}

Result rows (JSON sample):
{rows_json}

Explain the answer clearly using only the numbers and data in the rows above.
Do not invent any numbers or facts that are not present in the rows.
If the rows are empty, say that no data was found for this question.
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        top_p=1,
        max_tokens=600,
    )
    answer = (resp.choices[0].message.content or "").strip()
    return answer


def run_analysis(question: str, session: Session) -> str:
    """
    Minimal orchestrator:
        1. Run the SQL agent.
        2. If no rows, return a simple message.
        3. Otherwise, summarize rows with another LLM call.
    """
    result = run_sap_sql_agent(question, session)

    if not result.rows:
        logger.info("No data found for question: %s", question)
        return "No data found for this question."

    logger.info("Summarizing %s row(s) for question: %s", len(result.rows), question)
    return _summarize_result(question, result)

