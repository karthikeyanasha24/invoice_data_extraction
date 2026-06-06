"""
Script 3: Push XML Files to the Supplier Intake API
-----------------------------------------------------
1. Fetches the supplier token from the API
2. Pulls XML documents from the database (one of each type)
3. Pushes them to POST /api/v1/sat/supplier-intake-files
4. Reports the full result

Usage:
    pip install psycopg2-binary requests
    python 3_push_files_to_api.py
"""

import os
import sys
import json
import tempfile

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests --quiet")
    import requests

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary --quiet")
    import psycopg2
    from psycopg2.extras import RealDictCursor

# ── CONFIG ──────────────────────────────────────────────────────────────────
DATABASE_URL  = "postgresql://neondb_owner:npg_FfAphoyd1r2H@ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
SUPPLIER_RFC  = "IIA040805DZ4"
BASE_URL      = "https://zodiac-back.vercel.app/api/v1"
TOKEN_URL     = f"{BASE_URL}/supplier-tokens/retrieve?supplier_rfc={SUPPLIER_RFC}"
INTAKE_URL    = f"{BASE_URL}/sat/supplier-intake-files"
# ────────────────────────────────────────────────────────────────────────────


def get_token():
    print(f"Fetching token for RFC {SUPPLIER_RFC}...")
    resp = requests.get(TOKEN_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token")
    if not token:
        raise ValueError(f"No token in response: {data}")
    print(f"  Token: {token[:20]}...")
    return token


def get_xml_files_from_db():
    """Pull one XML per doc_type from the database."""
    print("\nConnecting to database to fetch XML files...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT DISTINCT ON (doc_type)
            doc_type, supplier_rfc, xml_content
        FROM sat_documents
        WHERE xml_content IS NOT NULL AND xml_content != ''
        ORDER BY doc_type, received_at DESC
    """)
    rows = cur.fetchall()
    conn.close()

    files = {}
    for row in rows:
        doc_type = row["doc_type"]
        xml = row["xml_content"]
        print(f"  Found: {doc_type} for RFC {row['supplier_rfc']} ({len(xml)} chars)")
        files[doc_type] = xml

    if not files:
        print("  No XML content found in DB.")
    return files


def push_files(token, xml_files):
    """Push all XML files to the intake API."""
    print(f"\nPushing {len(xml_files)} file(s) to {INTAKE_URL}...")

    headers = {"Authorization": f"Bearer {token}"}

    # Build multipart form-data with all files
    file_handles = []
    files_payload = []
    tmp_files = []

    for doc_type, xml_content in xml_files.items():
        filename = f"{doc_type}.xml"
        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w", encoding="utf-8")
        tmp.write(xml_content)
        tmp.close()
        tmp_files.append(tmp.name)
        fh = open(tmp.name, "rb")
        file_handles.append(fh)
        files_payload.append(("files", (filename, fh, "application/xml")))
        print(f"  Queued: {filename}")

    try:
        resp = requests.post(
            INTAKE_URL,
            headers=headers,
            files=files_payload,
            timeout=30
        )
    finally:
        for fh in file_handles:
            fh.close()
        for tmp in tmp_files:
            os.unlink(tmp)

    return resp


def main():
    print("=" * 60)
    print("Supplier Intake API — File Push Test")
    print("=" * 60)

    # Step 1: Get token
    try:
        token = get_token()
    except Exception as e:
        print(f"Failed to get token: {e}")
        sys.exit(1)

    # Step 2: Get XML from DB
    try:
        xml_files = get_xml_files_from_db()
    except Exception as e:
        print(f"DB error: {e}")
        sys.exit(1)

    if not xml_files:
        print("Nothing to push.")
        sys.exit(0)

    # Step 3: Push
    try:
        resp = push_files(token, xml_files)
    except Exception as e:
        print(f"Push failed: {e}")
        sys.exit(1)

    # Step 4: Report
    print(f"\n{'='*60}")
    print(f"HTTP Status: {resp.status_code}")
    try:
        result = resp.json()
        print(json.dumps(result, indent=2))

        # Summary
        print(f"\n{'='*60}")
        if result.get("success"):
            print(f"SUCCESS — {result.get('message', '')}")
            print(f"  Total:      {result.get('total_files', '?')}")
            print(f"  Successful: {result.get('successful_count', '?')}")
            print(f"  Failed:     {result.get('failed_count', '?')}")
            print("\nDocuments processed:")
            for r in result.get("results", []):
                status = "OK" if r.get("success") else "FAIL"
                print(f"  [{status}] {r.get('filename','?')} — {r.get('doc_type','?')} — portal_ref: {r.get('portal_ref_id','?')}")
        else:
            print(f"FAILED: {result.get('message', resp.text)}")
    except Exception:
        print(resp.text)


if __name__ == "__main__":
    main()
