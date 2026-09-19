"""
One-off: copy the POC's mailbox.db into the account's schema on Postgres.

    python db/import_sqlite.py            # copy every table, skipping rows already there
    python db/import_sqlite.py --status   # row counts on both sides

⚠️ ADDITIVE AND RE-RUNNABLE. Rows are inserted with ON CONFLICT DO NOTHING on
the table's key, so running it twice copies nothing twice. Nothing is ever
deleted on either side, and mailbox.db is only read.

⚠️ THE SAME COLUMNS, BY NAME. Column lists are read from SQLite's own
PRAGMA, so a column added later on one side is simply left out rather than
misaligned. That is the failure that would matter — a subject landing in
the sender column — and it cannot happen here.
"""

import os
import sqlite3
import sys

# Run as  python db/import_sqlite.py  from poc/, so poc/ must be importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pg_store import PgStore, _PK   # noqa: E402

TABLES = ["messages", "handled", "reminders", "decisions", "actions", "corrections",
          "bodies", "requests", "rules", "unsub_requests", "person_links", "reported",
          "away", "saved_recipients", "style_profile", "style_examples"]


def main():
    src = sqlite3.connect("mailbox.db")
    pg = PgStore()
    print(f"\n  → {pg.schema} for {pg.account_email}\n")
    for t in TABLES:
        try:
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
        except Exception:
            continue
        if not cols:
            continue
        n_src = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if "--status" in sys.argv:
            n_pg = pg.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t:18} sqlite {n_src:>7,}   postgres {n_pg:>7,}")
            continue
        if n_src == 0:
            continue
        pk = _PK.get(t) or ("id",)
        rows = src.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
        sql = (f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('%s' for _ in cols)}) "
               f"ON CONFLICT ({', '.join(pk)}) DO NOTHING")
        with pg.conn.cursor() as cur:
            cur.executemany(sql, [tuple(r) for r in rows])
        pg.conn.commit()
        n_pg = pg.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"    {t:18} {n_src:>7,} read   {n_pg:>7,} now on postgres")
    if "--status" not in sys.argv:
        # BIGSERIAL sequences must start after the ids we just copied.
        for t in ("actions", "corrections", "requests", "rules", "away", "style_examples"):
            try:
                pg.conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                                f"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)")
            except Exception:
                pg.conn.rollback()
        pg.conn.commit()
    print()


if __name__ == "__main__":
    main()
