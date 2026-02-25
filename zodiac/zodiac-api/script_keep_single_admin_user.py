"""
Remove all users from zodiac_users except id=1 (puspesh@gmail.com) and ensure that user stays admin.
Handles foreign keys by reassigning or nulling references before deleting users.

Usage: python script_keep_single_admin_user.py [--db-url URL] [--dry-run]
"""
import os
import sys
import argparse
from sqlalchemy import create_engine, text

KEEP_USER_ID = 1


def get_db_url():
    try:
        from app.config.config import DATABASE_URL
        return DATABASE_URL
    except ImportError:
        return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/zodiac")


def main():
    parser = argparse.ArgumentParser(description="Keep only user id=1 and remove all other users")
    parser.add_argument("--db-url", type=str, help="Database URL")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL only, do not execute")
    args = parser.parse_args()
    db_url = args.db_url or get_db_url()
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    steps = [
        ("Null out supplier_tokens.created_by for other users", "UPDATE supplier_tokens SET created_by = NULL WHERE created_by IS NOT NULL AND created_by != :keep_id"),
        ("Reassign sat_simple_merged to kept user", "UPDATE sat_simple_merged SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Reassign v2_invoice_documents to kept user", "UPDATE v2_invoice_documents SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Null out v2_correction_cache.created_by_user_id for other users", "UPDATE v2_correction_cache SET created_by_user_id = NULL WHERE created_by_user_id IS NOT NULL AND created_by_user_id != :keep_id"),
        ("Reassign invoice_v2_business_data to kept user", "UPDATE invoice_v2_business_data SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Reassign invoice_business_data to kept user", "UPDATE invoice_business_data SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Reassign zodiac_invoice_success_edi to kept user", "UPDATE zodiac_invoice_success_edi SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Reassign zodiac_invoice_failed_edi to kept user", "UPDATE zodiac_invoice_failed_edi SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Reassign sat_documents to kept user (if column exists)", "UPDATE sat_documents SET user_id = :keep_id WHERE user_id != :keep_id"),
        ("Null out correction_cache.created_by_user_id for other users", "UPDATE correction_cache SET created_by_user_id = NULL WHERE created_by_user_id IS NOT NULL AND created_by_user_id != :keep_id"),
        ("Delete user_customers for other users", "DELETE FROM user_customers WHERE user_id != :keep_id"),
        ("Delete all users except kept one", "DELETE FROM zodiac_users WHERE id != :keep_id"),
        ("Ensure kept user is admin", "UPDATE zodiac_users SET is_admin = true WHERE id = :keep_id"),
    ]

    params = {"keep_id": KEEP_USER_ID}

    if args.dry_run:
        for label, sql in steps:
            print(f"-- {label}")
            print(sql.replace(":keep_id", str(KEEP_USER_ID)))
            print()
        return 0

    engine = create_engine(db_url)
    with engine.connect() as conn:
        # Pre-check: list users that will be removed
        check = conn.execute(
            text("SELECT id, email, username FROM zodiac_users ORDER BY id")
        ).fetchall()
        keep = [r for r in check if r[0] == KEEP_USER_ID]
        remove = [r for r in check if r[0] != KEEP_USER_ID]
        if not keep:
            print(f"Error: User id={KEEP_USER_ID} not found in zodiac_users. Aborting.")
            return 1
        print(f"Keeping: id={keep[0][0]}, email={keep[0][1]}, username={keep[0][2]}")
        if remove:
            print(f"Removing {len(remove)} user(s):")
            for r in remove:
                print(f"  id={r[0]}, email={r[1]}, username={r[2]}")
        else:
            print("No other users to remove. Will only ensure kept user is admin.")
            # Just ensure admin and exit
            conn.execute(text("UPDATE zodiac_users SET is_admin = true WHERE id = :keep_id"), params)
            conn.commit()
            print("Done.")
            return 0

    with engine.connect() as conn:
        for label, sql in steps:
            try:
                result = conn.execute(text(sql), params)
                conn.commit()
                print(f"OK: {label} (rowcount={result.rowcount})")
            except Exception as e:
                if "does not exist" in str(e).lower() or "column" in str(e).lower():
                    print(f"Skip: {label} ({e})")
                    conn.rollback()
                else:
                    print(f"Error: {label} -> {e}")
                    conn.rollback()
                    return 1

    print(f"Done. Only user id={KEEP_USER_ID} remains and is admin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
