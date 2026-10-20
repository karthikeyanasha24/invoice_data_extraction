"""Read-only coverage check for SAP SD links used in order-vs-invoice analysis."""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
engine = create_engine(os.environ["DATABASE_URL"])
inspector = inspect(engine)
tables = {t.lower(): t for t in inspector.get_table_names()}


def columns(name: str) -> set[str]:
    table = tables.get(name.lower())
    return {c["name"].lower() for c in inspector.get_columns(table)} if table else set()


for name in ("VBFA", "VBKD", "KONV", "VBAK", "VBAP", "VBRK", "vbrp"):
    cols = columns(name)
    wanted = [c for c in ("mandt", "vbelv", "posnv", "vbeln", "posnn", "vbtyp_n", "vbtyp_v",
                           "knumv", "kposn", "kschl", "kwert", "kbetr", "waers", "prsdt",
                           "posnr", "netwr", "waerk", "aubel", "aupos") if c in cols]
    print(f"{name}: exists={bool(cols)} cols={wanted}")

checks = {
    "VBFA preceding -> VBAP": 'SELECT COUNT(*) total, COUNT(p.vbeln) matched FROM "{vbfa}" f '
                              'LEFT JOIN "{vbap}" p ON p.mandt=f.mandt AND p.vbeln=f.vbelv AND p.posnr=f.posnv',
    "VBFA subsequent -> vbrp": 'SELECT COUNT(*) total, COUNT(r.vbeln) matched FROM "{vbfa}" f '
                               'LEFT JOIN "{vbrp}" r ON r.mandt=f.mandt AND r.vbeln=f.vbeln AND r.posnr=f.posnn',
    "VBKD -> VBAK (header, posnr=000000)": 'SELECT COUNT(*) total, COUNT(k.vbeln) matched FROM "{vbkd}" d '
                                          'LEFT JOIN "{vbak}" k ON k.mandt=d.mandt AND k.vbeln=d.vbeln',
    "KONV -> VBRK via knumv": 'SELECT COUNT(*) total, COUNT(b.knumv) matched FROM "{konv}" c '
                              'LEFT JOIN (SELECT DISTINCT mandt, knumv FROM "{vbrk}") b ON b.mandt=c.mandt AND b.knumv=c.knumv',
    "KONV -> VBAK via knumv": 'SELECT COUNT(*) total, COUNT(o.knumv) matched FROM "{konv}" c '
                              'LEFT JOIN (SELECT DISTINCT mandt, knumv FROM "{vbak}") o ON o.mandt=c.mandt AND o.knumv=c.knumv',
    "VBRK knumv unique": 'SELECT COUNT(*) total, COUNT(DISTINCT (mandt, knumv)) matched FROM "{vbrk}" WHERE knumv IS NOT NULL AND knumv <> \'\'',
    "VBAK knumv unique": 'SELECT COUNT(*) total, COUNT(DISTINCT (mandt, knumv)) matched FROM "{vbak}" WHERE knumv IS NOT NULL AND knumv <> \'\'',
}
names = {k: tables.get(k) for k in ("vbfa", "vbap", "vbrp", "vbkd", "vbak", "konv", "vbrk")}
with engine.connect() as conn:
    conn.execute(text("SET statement_timeout = 60000"))
    for label, sql in checks.items():
        if any(v is None for k, v in names.items() if "{" + k + "}" in sql):
            print(f"{label}: skipped (table missing)")
            continue
        try:
            total, matched = conn.execute(text(sql.format(**names))).one()
            print(f"{label}: total={total} matched={matched}")
        except Exception as error:
            print(f"{label}: error {type(error).__name__}: {str(error)[:200]}")
            conn.rollback()
            conn.execute(text("SET statement_timeout = 60000"))
sys.exit(0)
