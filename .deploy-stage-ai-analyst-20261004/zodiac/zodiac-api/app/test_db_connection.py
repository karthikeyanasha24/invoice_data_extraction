import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text

from .database import engine


def _humanize(text: str) -> str:
    """Very small helper to turn column/table names into readable labels."""
    return text.replace("_", " ").replace("-", " ").strip()


def main() -> None:
    """
    Simple, read-only DB diagnostics + schema snapshot script.

    - Loads the same .env as the API
    - Uses the shared SQLAlchemy engine
    - Prints:
        * Effective DATABASE_URL (masked)
        * Server version (if available)
        * Current database name (for Postgres)
        * List of tables visible to this user
    - Additionally writes a JSON mapping file with all tables/columns:
        * db_table_mapping.json (in the zodiac-api/app folder)
    """
    load_dotenv()

    print("=" * 80)
    print("🔎 Zodiac DB connection diagnostics")
    print("=" * 80)

    # Show which URL SQLAlchemy is using (with password hidden)
    try:
        url = engine.url
        safe_url = url.hide_password() if hasattr(url, "hide_password") else str(url)
        print(f"📡 Engine URL: {safe_url}")
    except Exception as e:
        print(f"⚠️ Could not read engine URL: {e}")

    try:
        with engine.connect() as conn:
            print("✅ Connected to database successfully.")

            # Try to detect current database name (Postgres)
            db_name = None
            try:
                result = conn.execute(text("SELECT current_database();"))
                db_name = result.scalar()
            except Exception:
                # Not Postgres or no permission; ignore
                pass

            if db_name:
                print(f"🗄️ Current database: {db_name}")

            # Optional: server version
            try:
                result = conn.execute(text("SELECT version();"))
                version = result.scalar()
                print(f"🧩 Server version: {version}")
            except Exception:
                pass

        # Use SQLAlchemy inspector to list tables and columns
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print("\n📋 Tables visible to this connection:")
        if not tables:
            print("  (no tables found)")
        else:
            for t in sorted(tables):
                print(f"  - {t}")

        # Build a simple mapping structure for AI-friendly table/column descriptions
        mapping: dict[str, dict[str, dict[str, str]]] = {}
        for table_name in sorted(tables):
            cols = inspector.get_columns(table_name)
            mapping[table_name] = {
                "meta": {
                    "description": f"{_humanize(table_name)} table",
                },
                "columns": {
                    c["name"]: f"{_humanize(table_name)} – {_humanize(c['name'])}"
                    for c in cols
                },
            }

        out_path = Path(__file__).resolve().parent / "db_table_mapping.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)

        print(f"\n📝 Wrote table/column mapping to: {out_path}")
        print("   This file can be used by the sap_sql_agent / AI layer to understand")
        print("   which tables and headers exist, and to map natural-language queries")
        print("   onto the right columns.")

        print("\n✅ DB diagnostics completed.")
    except Exception as e:
        print("❌ Failed to connect to database or inspect schema.")
        print(f"Error: {e}")


if __name__ == "__main__":
    main()


