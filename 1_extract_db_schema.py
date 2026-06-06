"""
Script 1: DB Schema Extractor
------------------------------
Connects to PostgreSQL and extracts all tables, columns, data types,
constraints, foreign keys, and sample row counts.
Saves everything to db_schema.json — this file is used by Script 2 (AI query).

Usage:
    pip install psycopg2-binary python-dotenv
    python 1_extract_db_schema.py
"""

import json
import os
import sys
from datetime import datetime

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Installing psycopg2-binary...")
    os.system(f"{sys.executable} -m pip install psycopg2-binary --quiet")
    import psycopg2
    from psycopg2.extras import RealDictCursor

# ── CONFIG ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_FfAphoyd1r2H@ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
)
OUTPUT_FILE = "db_schema.json"
# ────────────────────────────────────────────────────────────────────────────


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def extract_schema(conn):
    schema = {}
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Get all user tables
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)
    tables = [row["table_name"] for row in cur.fetchall()]
    print(f"Found {len(tables)} tables: {', '.join(tables)}\n")

    for table in tables:
        print(f"  Extracting: {table}")
        table_info = {
            "columns": [],
            "primary_keys": [],
            "foreign_keys": [],
            "indexes": [],
            "row_count": 0,
            "sample_values": {}
        }

        # 2. Columns + types + nullable + default
        cur.execute("""
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position;
        """, (table,))
        for col in cur.fetchall():
            col_type = col["data_type"]
            if col["character_maximum_length"]:
                col_type += f"({col['character_maximum_length']})"
            table_info["columns"].append({
                "name": col["column_name"],
                "type": col_type,
                "nullable": col["is_nullable"] == "YES",
                "default": col["column_default"]
            })

        # 3. Primary keys
        cur.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = %s
            ORDER BY kcu.ordinal_position;
        """, (table,))
        table_info["primary_keys"] = [r["column_name"] for r in cur.fetchall()]

        # 4. Foreign keys
        cur.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name  AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = %s;
        """, (table,))
        for fk in cur.fetchall():
            table_info["foreign_keys"].append({
                "column": fk["column_name"],
                "references_table": fk["foreign_table"],
                "references_column": fk["foreign_column"]
            })

        # 5. Indexes
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s;
        """, (table,))
        for idx in cur.fetchall():
            table_info["indexes"].append({
                "name": idx["indexname"],
                "definition": idx["indexdef"]
            })

        # 6. Row count
        try:
            cur.execute(f'SELECT COUNT(*) as cnt FROM "{table}";')
            table_info["row_count"] = cur.fetchone()["cnt"]
        except Exception:
            table_info["row_count"] = -1

        # 7. Sample distinct values for each column (top 5, for AI context)
        for col in table_info["columns"]:
            col_name = col["name"]
            try:
                cur.execute(
                    f'SELECT DISTINCT "{col_name}" FROM "{table}" '
                    f'WHERE "{col_name}" IS NOT NULL LIMIT 5;'
                )
                samples = [str(r[col_name]) for r in cur.fetchall()]
                if samples:
                    table_info["sample_values"][col_name] = samples
            except Exception:
                pass

        schema[table] = table_info

    cur.close()
    return schema


def build_output(schema):
    return {
        "metadata": {
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "database": "neondb",
            "total_tables": len(schema)
        },
        "tables": schema
    }


def main():
    print("Connecting to database...")
    try:
        conn = get_connection()
        conn.autocommit = True  # each query is independent; one failure won't abort the rest
        print("Connected.\n")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    schema = extract_schema(conn)
    conn.close()

    output = build_output(schema)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nSchema saved to: {OUTPUT_FILE}")
    print(f"Tables extracted: {len(schema)}")
    for tname, tdata in schema.items():
        print(f"  {tname}: {len(tdata['columns'])} columns, {tdata['row_count']} rows")


if __name__ == "__main__":
    main()
