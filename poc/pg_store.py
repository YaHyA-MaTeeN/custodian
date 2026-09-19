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

    def __init__(self, conn, columns: dict, on_commit=None):
        self.conn = conn
        self.columns = columns
        self.on_commit = on_commit

    @staticmethod
    def _placeholders(sql: str) -> str:
        """
        ? → %s, but only OUTSIDE quoted strings; % → %% everywhere.

        ⚠️ Two real queries broke the naive replace. LIKE '%Waiting%' has a
        literal % that psycopg reads as a placeholder; and web.py's
        COALESCE(account,'?') has a literal ? inside quotes. Both surfaced as
        "the query has 2 placeholders but 1 parameters were passed" on Neon.
        So the text is walked once, tracking whether we are inside '…'
        (with '' as the escape), and only bare ? are converted.
        """
        out, inside, i = [], False, 0
        while i < len(sql):
            ch = sql[i]
            if ch == "'":
                if inside and i + 1 < len(sql) and sql[i + 1] == "'":
                    out.append("''"); i += 2; continue
                inside = not inside
                out.append(ch)
            elif ch == "%":
                out.append("%%")
            elif ch == "?" and not inside:
                out.append("%s")
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    def _translate(self, sql: str) -> tuple:
        s = self._placeholders(sql)
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
        if self.on_commit:
            self.on_commit()

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
        # ⚠️ The DDL is ~40 statements; over the network that is 3.7 s on
        # every Store(). Once the schema has its tables, skip it — one
        # count instead of forty round trips. CUSTODIAN_DDL=1 forces it.
        have = self.conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s",
            (self.schema,)).fetchone()[0]
        if have < 16 or os.environ.get("CUSTODIAN_DDL"):
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
        self._memo = {}
        self.db = _Proxy(self.conn, columns, on_commit=self._memo.clear)

    # ── a memo for the read-heavy lookups ────────────────────────────
    #
    # ⚠️ THE SQLITE FILE HAD NO LATENCY. NEON HAS ~100 ms A QUERY.
    #
    # The mailbox page calls history(), decision_for(), is_protected() and
    # has_body() for every row — a few thousand tiny queries that cost
    # nothing on a local file and minutes across the internet. Each is a pure
    # read keyed on its arguments, so the answer is kept for the life of this
    # store object and thrown away on every commit (any write could change
    # it). Same answers, one round trip instead of hundreds.

    def _memoised(self, key, compute):
        if key in self._memo:
            return self._memo[key]
        v = compute()
        self._memo[key] = v
        return v

    def history(self, address, me=""):
        return self._memoised(("history", (address or "").lower(), (me or "").lower()),
                              lambda: super(PgStore, self).history(address, me))

    def decision_for(self, message_id):
        return self._memoised(("decision", message_id or ""),
                              lambda: super(PgStore, self).decision_for(message_id))

    def has_body(self, message_id):
        return self._memoised(("has_body", message_id or ""),
                              lambda: super(PgStore, self).has_body(message_id))

    def correction_for(self, sender, domain=""):
        return self._memoised(("correction", (sender or "").lower(), (domain or "").lower()),
                              lambda: super(PgStore, self).correction_for(sender, domain))

    def rules(self):
        return self._memoised(("rules",), lambda: super(PgStore, self).rules())

    def prefetch(self, rows, me: str = "") -> None:
        """
        Load, in FOUR queries, everything the page will ask for row by row.

        ⚠️ Measured on Neon: history() 750 ms, decision_for() 270 ms,
        has_body() 300 ms — per row, 200 rows a page. That is the mailbox
        view taking four minutes to open. Fetching the same facts for every
        row at once and filling the memo turns it into four round trips.
        The per-row methods are untouched; they simply find their answers
        already there.

        `rows` are the tuples rows() returns: (message_id, provider_id,
        sender, …). Anything else passed here is ignored.
        """
        mids = sorted({r[0] for r in rows if r and r[0]})
        senders = sorted({(r[2] or "").lower() for r in rows if r and len(r) > 2 and r[2]})
        me = (me or "").lower()
        if not mids:
            return
        # decisions, all at once
        dec = {m: [] for m in mids}
        for mid, st, d, why, sc, at in self.conn.execute(
                "SELECT message_id, stage, decision, reason, score, at FROM decisions "
                "WHERE message_id = ANY(%s) ORDER BY at", (mids,)).fetchall():
            dec.setdefault(mid, []).append((st, d, why, sc, at))
        for m, v in dec.items():
            self._memo[("decision", m)] = v
        # bodies held
        held = {r[0] for r in self.conn.execute(
            "SELECT message_id FROM bodies WHERE message_id = ANY(%s)", (mids,)).fetchall()}
        for m in mids:
            self._memo[("has_body", m)] = m in held
        # sender history: sent/opened per sender in one query; replied from
        # our own outgoing mail's recipient lines, counted in Python
        stats = {s: (0, 0) for s in senders}
        for s, n, opened in self.conn.execute(
                "SELECT sender, COUNT(*), COALESCE(SUM(1-unread),0) FROM messages "
                "WHERE sender = ANY(%s) GROUP BY sender", (senders,)).fetchall():
            stats[s] = (n or 0, opened or 0)
        recips = [r[0].lower() for r in self.conn.execute(
            "SELECT COALESCE(recipients,'') FROM messages WHERE sender=%s", (me,)).fetchall()] if me else []
        for s in senders:
            n, opened = stats[s]
            replied = sum(1 for line in recips if s in line) if me else 0
            self._memo[("history", s, me)] = {"sent": n, "opened": opened, "replied": replied}
            # web.classify() asks history(sender) with no account, so that key
            # must be filled too or every row still pays two round trips.
            self._memo[("history", s, "")] = {"sent": n, "opened": opened, "replied": 0}
        # corrections: the table is small — load once, answer per key in memory
        corr = self.conn.execute(
            "SELECT scope, target, should_be, at FROM corrections ORDER BY id DESC").fetchall()
        for r in rows:
            s = (r[2] or "").lower() if len(r) > 2 else ""
            d = s.split("@")[-1] if "@" in s else ""
            hit = next((c for c in corr if (c[0] == "sender" and c[1] == s)
                        or (c[0] == "domain" and c[1] == d)), None)
            self._memo[("correction", s, d)] = (
                {"scope": hit[0], "target": hit[1], "should_be": hit[2], "at": hit[3]} if hit else None)

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

    # ── mailboxes in public (UC-10 BR-34, BR-36) ────────────────────────
    def register_mailbox(self, conn_) -> int:
        """
        Record a connected mailbox against this account: which door, what it
        can do, its access level. One address belongs to one account only;
        a second account trying the same address is refused here.
        """
        import json
        address = (conn_.account_email() or "").lower()
        name = getattr(conn_, "name", "")
        provider = ("gmail" if "gmail" in name or "imap.gmail" in getattr(conn_, "host", "")
                    else "outlook" if "office365" in getattr(conn_, "host", "")
                    else "other")
        route = "google_signin" if name == "gmail" else "app_password"
        caps = {k: bool(getattr(conn_, k, False)) for k in
                ("supports_push", "supports_labels", "supports_categories",
                 "supports_threads", "supports_send")}
        level = conn_.access_level() if hasattr(conn_, "access_level") else "full"
        r = self.conn.execute("SELECT id, account_id FROM public.mailboxes WHERE address=%s",
                              (address,)).fetchone()
        if r and r[1] != self.account_id:
            raise PermissionError("This email address is already connected to a different account.")
        if r:
            self.conn.execute(
                "UPDATE public.mailboxes SET route=%s, host=%s, access_level=%s, capabilities=%s, "
                "state='connected', state_reason=NULL WHERE id=%s",
                (route, getattr(conn_, "host", ""), level, json.dumps(caps), r[0]))
            mid = r[0]
        else:
            mid = self.conn.execute(
                "INSERT INTO public.mailboxes (account_id, address, provider, route, host, "
                "access_level, capabilities) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (self.account_id, address, provider, route, getattr(conn_, "host", ""),
                 level, json.dumps(caps))).fetchone()[0]
        self.conn.commit()
        return mid

    def mailboxes(self) -> list:
        return self.conn.execute(
            "SELECT address, provider, route, access_level, state, connected_at "
            "FROM public.mailboxes WHERE account_id=%s ORDER BY id", (self.account_id,)).fetchall()

    # ── the few queries that need a Postgres spelling ────────────────
    def tables(self) -> list:
        return [r[0] for r in self.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s "
            "ORDER BY table_name", (self.schema,)).fetchall()]
