"""
Script 2: AI Natural Language → SQL Query Runner
--------------------------------------------------
Two-step pipeline:
  Step 1 — AI reads table names + column list (tiny prompt) and picks which tables it needs.
  Step 2 — AI gets full schema (with sample values) for only those tables and writes SQL.

This means no keyword guessing — the AI decides what it needs on its own.

Usage:
    pip install psycopg2-binary openai
    python 2_ai_db_query.py
"""

import json
import os
import sys

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary --quiet")
    import psycopg2
    from psycopg2.extras import RealDictCursor

try:
    from openai import OpenAI
except ImportError:
    os.system(f"{sys.executable} -m pip install openai --quiet")
    from openai import OpenAI

# ── CONFIG ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_FfAphoyd1r2H@ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
)
OPENAI_API_KEY = "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"
SCHEMA_FILE   = "db_schema.json"
MODEL         = "gpt-4o"
MAX_TABLES    = 12    # max tables to pass to SQL generation step
MAX_ROWS      = 50    # max rows returned
# ────────────────────────────────────────────────────────────────────────────


def load_schema(path=SCHEMA_FILE):
    if not os.path.exists(path):
        print(f"Schema file '{path}' not found. Run Script 1 first.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── STEP 1: AI picks which tables it needs ──────────────────────────────────

def build_table_index(schema_data):
    """
    Compact index: table name + column names + key sample values (short ones only).
    Used in Step 1 so AI can pick the right tables.
    """
    lines = []
    for tname, tdata in schema_data["tables"].items():
        col_parts = []
        for c in tdata["columns"]:
            samples = tdata.get("sample_values", {}).get(c["name"], [])
            short_samples = [str(s) for s in samples if len(str(s)) < 40][:2]
            hint = f"[{', '.join(short_samples)}]" if short_samples else ""
            col_parts.append(f"{c['name']}{hint}")
        lines.append(f"{tname}: {', '.join(col_parts)}")
    return "\n".join(lines)


def ai_pick_tables(client, table_index, question):
    """
    Ask the AI to look at the full table+column index and return
    the names of tables needed to answer the question.
    Returns a list of table names.
    """
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a database expert. You will be given a list of table names and their columns.\n"
                    "Your job: identify which tables are needed to answer the user's question.\n"
                    "Reply with ONLY a JSON array of table name strings, e.g. [\"table1\", \"table2\"].\n"
                    "No explanation, no markdown, just the JSON array.\n\n"
                    "TABLE INDEX (table_name: column1, column2, ...):\n"
                    + table_index
                )
            },
            {
                "role": "user",
                "content": f"Question: {question}"
            }
        ]
    )
    raw = response.choices[0].message.content.strip()
    # Parse JSON array
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(raw)


# ── STEP 2: Build full schema for selected tables ───────────────────────────

def build_full_schema_prompt(schema_data, table_names):
    """
    Full schema with sample values for the selected tables only.
    """
    lines = [
        "You are a PostgreSQL expert. Use ONLY the tables and columns listed below.",
        "Use sample values to understand what data is in each column.\n",
        "DATABASE SCHEMA:",
        "=" * 60
    ]
    for tname in table_names:
        if tname not in schema_data["tables"]:
            continue
        table = schema_data["tables"][tname]
        pk = ", ".join(table["primary_keys"]) if table["primary_keys"] else "none"
        lines.append(f"\nTABLE: {tname}  [PK: {pk}, rows: {table['row_count']}]")
        for col in table["columns"]:
            sample = table.get("sample_values", {}).get(col["name"])
            if sample:
                # Skip columns with very long values (xml, json, blobs)
                clean = [str(s) for s in sample[:3] if len(str(s)) < 80]
                sample_str = f"  →  e.g. {', '.join(clean)}" if clean else ""
            else:
                sample_str = ""
            lines.append(f"  {col['name']}  {col['type']}{sample_str}")
        if table["foreign_keys"]:
            for fk in table["foreign_keys"]:
                lines.append(f"  FK: {fk['column']} → {fk['references_table']}.{fk['references_column']}")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def generate_sql(client, schema_prompt, question):
    """Step 2: Generate SQL from the focused schema."""
    system = (
        schema_prompt
        + "\n\nINSTRUCTIONS:\n"
        + "- Return ONLY the raw SQL query. No markdown, no ```sql fences, no explanation, no preamble.\n"
        + "- Always double-quote table and column names.\n"
        + f"- Add LIMIT {MAX_ROWS} unless the user explicitly asks for all records.\n"
        + "- Sample values shown are EXAMPLES ONLY. Always write the SQL even if the user's value is not in the samples.\n"
        + "- Map plain-English terms to column values using the samples as a guide: e.g. 'credit note' → doc_type = 'CREDIT_NOTE', 'invoice' → doc_type = 'INVOICE'.\n"
        + "- NEVER reply CANNOT_ANSWER unless the schema has absolutely no relevant table or column for the question.\n"
        + "- If unsure, write the best SQL you can with the available columns.\n"
    )
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": f"Question: {question}"}
        ]
    )
    return response.choices[0].message.content.strip()


# ── DB execution ─────────────────────────────────────────────────────────────

def execute_sql(conn, sql):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def summarize_result(client, question, sql, rows):
    rows_text = json.dumps(rows[:MAX_ROWS], indent=2, default=str)
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": "You are a data analyst. Answer the question from the SQL result concisely."},
            {"role": "user", "content": (
                f"Question: {question}\nSQL: {sql}\nResult ({len(rows)} rows):\n{rows_text}"
            )}
        ]
    )
    return response.choices[0].message.content.strip()


def print_table(rows):
    if not rows:
        print("  (no rows returned)")
        return
    headers = list(rows[0].keys())
    widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    sep = " | "
    header = sep.join(h.ljust(widths[h]) for h in headers)
    print("\n  " + header)
    print("  " + "-" * len(header))
    for row in rows:
        print("  " + sep.join(str(row.get(h, "")).ljust(widths[h]) for h in headers))
    print(f"\n  Total: {len(rows)} row(s)")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading schema...")
    schema_data  = load_schema()
    table_index  = build_table_index(schema_data)
    total_tables = schema_data["metadata"]["total_tables"]
    print(f"Schema loaded: {total_tables} tables\n")

    client = OpenAI(api_key=OPENAI_API_KEY)

    print("Connecting to database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("Connected.\n")
    except Exception as e:
        print(f"DB connection failed: {e}")
        sys.exit(1)

    print("=" * 60)
    print("AI Database Query — ask anything in plain English.")
    print("Type 'exit' to stop.")
    print("=" * 60 + "\n")

    while True:
        try:
            question = input("Your question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit", "q"):
            print("Bye!")
            break

        # ── Step 1: AI picks tables ───────────────────────────────────────
        print("\n[Step 1] AI selecting relevant tables...")
        try:
            selected = ai_pick_tables(client, table_index, question)
            selected = selected[:MAX_TABLES]  # cap just in case
            print(f"  Selected: {', '.join(selected)}")
        except Exception as e:
            print(f"  Table selection failed: {e}")
            continue

        # ── Step 2: AI writes SQL ─────────────────────────────────────────
        print("[Step 2] Generating SQL...")
        try:
            schema_prompt = build_full_schema_prompt(schema_data, selected)
            sql = generate_sql(client, schema_prompt, question)
        except Exception as e:
            print(f"  SQL generation failed: {e}\n")
            continue

        if "CANNOT_ANSWER" in sql.strip().upper() and not sql.strip().upper().startswith("SELECT"):
            print("  AI could not answer this question from the schema.\n")
            continue

        print(f"\nSQL:\n  {sql}\n")

        # ── Execute ───────────────────────────────────────────────────────
        print("Executing...")
        try:
            rows = execute_sql(conn, sql)
        except Exception as e:
            conn.rollback()
            print(f"  SQL error: {e}\n")
            continue

        print_table(rows)

        if rows:
            print("\nAI Summary:")
            try:
                print(f"  {summarize_result(client, question, sql, rows)}")
            except Exception as e:
                print(f"  (summary error: {e})")

        print()

    conn.close()


if __name__ == "__main__":
    main()
