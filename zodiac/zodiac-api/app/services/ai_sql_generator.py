from typing import Any, Dict, List

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from .schema_context_builder import build_schema_context


client = OpenAI()


def generate_sql(question: str) -> str:
    """
    Use the OpenAI API to generate a SELECT-only PostgreSQL query
    based on the current schema and a natural-language question.
    """
    schema_context = build_schema_context()

    prompt = f"""
You are a PostgreSQL expert working with SAP billing data.

Generate a SQL query for the user question below.

CRITICAL DATA QUALITY RULES (these are NOT optional — they reflect proven bugs in the database):

1. YEAR FILTERING — NEVER use GJAHR for year filtering.
   The column VBRK.gjahr contains '0000' for ALL rows — it is completely unreliable.
   ALWAYS use VBRK.fkdat (billing date, stored as YYYYMMDD text) for year filtering:
     Correct:  WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000'
     Wrong:    WHERE r.gjahr = '2000'   ← will ALWAYS return 0 rows

2. NETWR IS TEXT — the column vbrp.netwr is stored as TEXT, not numeric.
   ALWAYS cast it like this:
     NULLIF(TRIM(v."netwr"::text), '')::NUMERIC
   Never use SUM(v.netwr) directly — it will fail or silently return NULL.

3. NEGATIVE / LOWEST SALES — individual billing lines can have negative netwr (credit memos).
   "Negative sales" or "lowest sales" = individual LINE ITEMS with netwr < 0, NOT year totals.
   CORRECT — use WHERE on individual rows:
     WHERE NULLIF(TRIM(v."netwr"::text), '')::NUMERIC < 0
   WRONG (returns 0 rows — no year has a negative TOTAL):
     HAVING SUM(NULLIF(TRIM(v."netwr"::text), '')::NUMERIC) < 0
   Example query for "negative sales in year 2000":
     SELECT v."vbeln", v."matnr", r."fkdat",
            NULLIF(TRIM(v."netwr"::text), '')::NUMERIC AS netwr
     FROM vbrp v
     JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
     WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000'
       AND NULLIF(TRIM(v."netwr"::text), '')::NUMERIC < 0
     ORDER BY NULLIF(TRIM(v."netwr"::text), '')::NUMERIC ASC

4. JOIN RULE — always join with LPAD to handle leading-zero differences:
     ON LPAD(TRIM(v."vbeln"), 10, '0') = LPAD(TRIM(r."vbeln"), 10, '0')

5. TABLE CASING — uppercase SAP tables need double quotes in PostgreSQL:
     "VBRK"  "KNA1"  "MAKT"
   Exception: vbrp (lowercase, no quotes needed)

Other rules:
- Use ONLY the tables and columns listed in the schema.
- PostgreSQL syntax only (LIMIT not TOP, :: for cast, ILIKE for case-insensitive).
- SELECT queries ONLY (no INSERT/UPDATE/DELETE/DDL).
- Always include LIMIT 50 unless the question asks for aggregates/totals.
- Always ORDER BY the main metric DESC or ASC depending on context.

Schema:
{schema_context}

Question:
{question}

Return ONLY the SQL. No explanation, no markdown.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    sql = (response.choices[0].message.content or "").strip()
    return sql


def run_sql(db: Session, sql: str) -> List[Dict[str, Any]]:
    """
    Execute a generated SQL query safely against the given SQLAlchemy Session.
    Only SELECT statements are allowed.
    """
    lowered = sql.strip().lower()
    if not lowered.startswith("select"):
        raise ValueError("Only SELECT statements are allowed")

    # Basic safety: reject obviously dangerous keywords
    forbidden = [" update ", " delete ", " insert ", " drop ", " alter ", " truncate "]
    if any(k in lowered for k in forbidden):
        raise ValueError("Refusing to execute potentially dangerous SQL")

    # Escape :: PostgreSQL cast syntax — SQLAlchemy text() treats :word as a bind param.
    safe_sql = sql.replace('::', r'\:\:')
    result = db.execute(text(safe_sql)).mappings().all()
    return [dict(row) for row in result]


