"""
The store, on Postgres — one schema per account, same methods, same SQL.

    set DATABASE_URL and every script uses this instead of mailbox.db.
    CUSTODIAN_STORE=sqlite  forces the old file for one run.
    CUSTODIAN_ACCOUNT=you@x.com  picks the account (default: IMAP_USER).

⚠️ HOW THIRTY SCRIPTS MOVED DATABASES WITHOUT A LINE OF THEIR SQL CHANGING.

Every method in store.Store talks to `self.db` with SQLite's dialect: `?`
placeholders, INSERT OR REPLACE, cursor.lastrowid. PgStore subclasses it and
replaces only `self.db` with a small proxy that translates those three things
on the way through. The per-account tables are created from the very same
SCHEMA string store.py holds, with three type names swapped. So the SQL that
was tested on a real mailbox for two weeks is the SQL that runs on Postgres —
not a second copy that could drift.

⚠️ ONE SCHEMA PER ACCOUNT, AND search_path IS THE SCOPE.

`acct_<id>` is created on first use and set as the search path for this
connection. A query for `messages` can only ever see this account's messages;
there is no WHERE clause to forget. Shared tables (accounts, mailboxes,
credentials, sessions) stay in `public` and are reached by name.

⚠️ WHAT IS DELIBERATELY NOT TRANSLATED. Anything SQLite-only that no script
uses. If a new script writes `sqlite_master` or `PRAGMA`, it will fail loudly
here rather than silently return nothing — which is the right way to find out.
"""

import os
import re
from datetime import datetime

import store as _sqlite

# SQLite → Postgres, for the CREATE TABLE text only.
_DDL_SWAPS = (
    (re.compile(r"INTEGER PRIMARY KEY AUTOINCREMENT", re.I), "BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\bREAL\b"), "DOUBLE PRECISION"),
    (re.compile(r"\bBLOB\b"), "BYTEA"),
)

# Tables whose INSERT needs RETURNING id so cursor.lastrowid keeps working.
_SERIAL = {"actions", "corrections", "requests", "rules", "away"}

# Primary keys, for turning INSERT OR REPLACE into ON CONFLICT … DO UPDATE.
_PK = {
    "messages": ("provider_id",),
    "handled": ("message_id", "action"),
    "reminders": ("message_id", "kind"),
    "decisions": ("message_id", "stage"),
    "bodies": ("message_id",),
    "unsub_requests": ("sender",),
    "person_links": ("address",),
    "reported": ("message_id", "kind"),
    "saved_recipients": ("address",),
    "style_profile": ("key",),
}

# Columns store.py adds by ALTER TABLE at runtime, in the order save() writes them.
_MESSAGE_EXTRAS = ("recipients TEXT", "account TEXT", "date_iso TEXT", "auth_results TEXT")


def _columns_of(table: str, ddl: str) -> list:
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);", ddl, re.S)
    cols = []
    for line in m.group(1).splitlines():
        line = line.split("--")[0].strip().rstrip(",")
        if not line or line.upper().startswith(("PRIMARY KEY", "UNIQUE", "CHECK")):
            continue
        cols.append(line.split()[0])
    return cols


class _Cursor:
    def __init__(self, cur, lastrowid=None):
        self._c = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def __iter__(self):
        return iter(self._c.fetchall())


class _Proxy:
    """Looks like sqlite3.Connection to store.Store; speaks psycopg underneath."""

    def __init__(self, conn, columns: dict):
        self.conn = conn
        self.columns = columns

    def _translate(self, sql: str) -> tuple:
        s = sql.replace("?", "%s")
        m = re.match(r"\s*INSERT OR REPLACE INTO (\w+)\s+VALUES\s*\(", s, re.I)
        if m:
            table = m.group(1)
            pk = _PK.get(table)
            cols = self.columns[table]
            sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk)
            s = re.sub(r"INSERT OR REPLACE INTO", "INSERT INTO", s, count=1, flags=re.I)
            s = s.rstrip().rstrip(";") + f" ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {sets}"
            return s, None
        m = re.match(r"\s*INSERT INTO (\w+)\s*\(", s, re.I)
        if m and m.group(1) in _SERIAL and "RETURNING" not in s.upper():
            return s.rstrip().rstrip(";") + " RETURNING id", m.group(1)
        return s, None

    def execute(self, sql, params=()):
        s, serial = self._translate(sql)
        cur = self.conn.execute(s, tuple(params) if params else None)
        last = cur.fetchone()[0] if serial else None
        return _Cursor(cur, last)

    def executemany(self, sql, rows):
        s, _ = self._translate(sql)
        with self.conn.cursor() as cur:
            cur.executemany(s, [tuple(r) for r in rows])
        return _Cursor(cur)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


class PgStore(_sqlite.SqliteStore):
    def __init__(self, account_email: str = "", url: str = ""):
        import psycopg
        url = url or os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        self.account_email = (account_email or os.environ.get("CUSTODIAN_ACCOUNT")
                              or os.environ.get("IMAP_USER") or "").lower()
        if not self.account_email:
            raise RuntimeError("no account: set CUSTODIAN_ACCOUNT or IMAP_USER")
        self.conn = psycopg.connect(url, connect_timeout=20)
        self.account_id = self._ensure_account()
        self.schema = f"acct_{self.account_id}"
        ddl = self._account_ddl()
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
        self.conn.execute(f"SET search_path TO {self.schema}, public")
        self.conn.execute(ddl)
        columns = {t: _columns_of(t, ddl) for t in _PK}
        # Only the extras the CREATE TABLE text does not already carry — the
        # SQLite schema gained recipients/account/date_iso in its own DDL and
        # auth_results by ALTER; listing one twice gives "multiple assignments
        # to same column" on the upsert.
        for col in _MESSAGE_EXTRAS:
            name = col.split()[0]
            if name not in columns["messages"]:
                self.conn.execute(f"ALTER TABLE messages ADD COLUMN IF NOT EXISTS {col}")
                columns["messages"].append(name)
        self.conn.commit()
        self.db = _Proxy(self.conn, columns)

    # ── account row in public ─────────────────────────────────────────
    def _ensure_account(self) -> int:
        r = self.conn.execute("SELECT id FROM public.accounts WHERE email=%s",
                              (self.account_email,)).fetchone()
        if r:
            return r[0]
        r = self.conn.execute(
            "INSERT INTO public.accounts (email, confirmed_at) VALUES (%s, now()) RETURNING id",
            (self.account_email,)).fetchone()
        self.conn.commit()
        return r[0]

    @staticmethod
    def _account_ddl() -> str:
        from pipeline import stage19_voice
        ddl = _sqlite.SCHEMA + "\n" + stage19_voice.SCHEMA
        for pat, rep in _DDL_SWAPS:
            ddl = pat.sub(rep, ddl)
        return ddl

    # ── the few queries that need a Postgres spelling ────────────────
    def tables(self) -> list:
        return [r[0] for r in self.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s "
            "ORDER BY table_name", (self.schema,)).fetchall()]
