"""
Apply the Postgres schema to the database in DATABASE_URL.

    python db/migrate.py            # create anything missing; safe to re-run
    python db/migrate.py --status   # what is there

⚠️ IDEMPOTENT. Every statement in schema.sql is CREATE … IF NOT EXISTS or an
INSERT … ON CONFLICT DO NOTHING, so running this twice does nothing the
second time. A change to an existing table is a new, numbered migration
file — never an edit to a statement that already ran somewhere.

⚠️ THE URL IS NEVER PRINTED. Not on success, not in an error. The host and
database name are shown so you know where you are; the password is not.
"""

import os
import re
import sys
from pathlib import Path


def url() -> str:
    u = os.environ.get("DATABASE_URL", "")
    if not u:
        sys.exit("\n  DATABASE_URL is not set. setx DATABASE_URL \"postgresql://…\" and reopen the terminal.\n")
    return u


def where(u: str) -> str:
    """host/dbname only — the part it is safe to say out loud."""
    m = re.search(r"@([^/?]+)/([^?]+)", u)
    return f"{m.group(1)}/{m.group(2)}" if m else "(unparseable url)"


def main():
    import psycopg
    u = url()
    print(f"\n  database: {where(u)}")
    with psycopg.connect(u, connect_timeout=20) as conn:
        if "--status" in sys.argv:
            rows = conn.execute("""SELECT table_name, (xpath('/row/c/text()', query_to_xml(
                                       format('select count(*) as c from %I', table_name), false, true, '')))[1]::text::int
                                     FROM information_schema.tables
                                    WHERE table_schema='public' ORDER BY table_name""").fetchall()
            for t, n in rows:
                print(f"    {t:22} {n:>8,} rows")
            v = conn.execute("SELECT max(version) FROM schema_versions").fetchone()[0] \
                if any(t == "schema_versions" for t, _ in rows) else None
            print(f"  schema version: {v}\n")
            return
        sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        before = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
        conn.execute(sql)
        conn.commit()
        after = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
        v = conn.execute("SELECT max(version) FROM schema_versions").fetchone()[0]
        print(f"  tables: {before} → {after}   schema version: {v}\n")


if __name__ == "__main__":
    main()
