"""
Print all rows from zodiac_users with all fields.
Usage: python script_show_users.py [--db-url URL]
"""
import os
import sys
import argparse
from sqlalchemy import create_engine, text


def get_db_url():
    try:
        from app.config.config import DATABASE_URL
        return DATABASE_URL
    except ImportError:
        return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/zodiac")


def main():
    parser = argparse.ArgumentParser(description="Show all data from zodiac_users table")
    parser.add_argument("--db-url", type=str, help="Database URL")
    parser.add_argument("--full", action="store_true", help="Do not truncate long values")
    args = parser.parse_args()
    db_url = args.db_url or get_db_url()
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM zodiac_users ORDER BY id"))
        rows = result.fetchall()
        col_names = result.keys()

    if not rows:
        print("No rows in zodiac_users.")
        return 0

    max_cell = 9999 if args.full else 50
    cols = list(col_names)
    widths = [min(max(len(str(c)), 4), max_cell) for c in cols]
    for row in rows:
        for i, v in enumerate(row):
            if i < len(widths):
                s = str(v) if v is not None else ""
                widths[i] = min(max(widths[i], len(s) if len(s) <= max_cell else max_cell), max_cell)

    # Header
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(sep)
    print("|" + "|".join(f" {str(c).ljust(widths[i])} " for i, c in enumerate(cols)) + "|")
    print(sep)

    # Rows
    for row in rows:
        cells = []
        for i, v in enumerate(row):
            if i >= len(widths):
                break
            s = str(v) if v is not None else ""
            if len(s) > widths[i]:
                s = s[: widths[i] - 2] + ".."
            cells.append(f" {s.ljust(widths[i])} ")
        while len(cells) < len(cols):
            cells.append(" " * (widths[len(cells)] + 2))
        print("|" + "|".join(cells[: len(cols)]) + "|")
    print(sep)
    print(f"Total: {len(rows)} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
