"""
Storage.

Note what is missing: there is no column for a message body. That is the
privacy claim expressed in the schema rather than in a policy page. An email
is read, acted on, and the text is dropped; what persists is typed facts.

SQLite for the proof of concept. Postgres in production — same shape.
"""

import os
import sqlite3
from connectors.base import Envelope


def iso_date(raw: str) -> str:
    """
    The RFC date header, turned into something that sorts.

    ⚠️ Returns "" rather than a guess when it cannot parse. An unparseable
    date sorting to the bottom is honest; inventing today's date for it would
    put unknown mail at the top of every list.
    """
    if not raw:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(raw)
        if d.tzinfo is not None:
            d = d.replace(tzinfo=None)
        return d.isoformat()
    except Exception:
        return ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id    TEXT,              -- the RFC header. Our real key.
    provider_id   TEXT PRIMARY KEY,  -- the mailbox's own id. A handle.
    thread_id     TEXT,
    sender        TEXT,
    sender_name   TEXT,
    sender_domain TEXT,
    subject       TEXT,
    date          TEXT,
    size          INTEGER,
    unread        INTEGER,
    in_inbox      INTEGER,
    categories    TEXT,
    unsubscribe   TEXT,
    one_click     INTEGER,
    list_id       TEXT,
    bulk          INTEGER,
    auto_sub      TEXT,
    in_reply_to   TEXT,
    refs          TEXT,
    recipients    TEXT,              -- the To/Cc line. Added last on purpose:
                                     -- ALTER TABLE appends, so an existing
                                     -- database migrates without a rebuild.
    account       TEXT,              -- UC-27 - which mailbox this came from.
                                     -- BR-98: never ambiguous, never inferred.
    date_iso      TEXT               -- ⚠️ THE SORTABLE DATE.
                                     -- `date` holds the raw RFC header, e.g.
                                     -- "Wed, 9 Jun 2021 10:04:00 +0500".
                                     -- Sorting THAT as text sorts alphabetically:
                                     -- every "Wed, 9 ..." lands together and
                                     -- 2021 sits beside 2025. Every "newest
                                     -- first" query in the project was wrong
                                     -- and looked plausible, which is the worst
                                     -- combination. This column is ISO, so
                                     -- text order IS time order.
    -- deliberately: no body column
);
-- What we have already DONE, so a second run does not do it twice.
-- Separate from `messages` on purpose: a message is a fact about the mailbox,
-- an action is a fact about us, and the two have different lifetimes.
CREATE TABLE IF NOT EXISTS handled (
    message_id  TEXT,
    action      TEXT,
    sent_id     TEXT,
    at          TEXT,
    PRIMARY KEY (message_id, action)
);
-- Reminders and snoozes. Both are "show me this again at a time", so they are
-- one table with a kind, not two tables that would drift apart.
CREATE TABLE IF NOT EXISTS reminders (
    message_id  TEXT,
    provider_id TEXT,
    kind        TEXT,          -- 'remind' or 'snooze'
    due         TEXT,          -- ISO. Computed in code, never by a model.
    subject     TEXT,
    why         TEXT,
    done        INTEGER DEFAULT 0,
    PRIMARY KEY (message_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_due ON reminders(due, done);
-- Every decision, with the reason recorded AT THE TIME it was made (BR-105).
-- Reconstructing a reason afterwards is guessing; this is the record.
CREATE TABLE IF NOT EXISTS decisions (
    message_id  TEXT,
    stage       TEXT,
    decision    TEXT,
    reason      TEXT,
    score       REAL,
    at          TEXT,
    PRIMARY KEY (message_id, stage)
);

-- Every action we took, with the state before it, which is what makes undo
-- possible at all (BR-108). An undo is itself an action and lands here too
-- (BR-109) - history is never silently rewritten.
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  TEXT,
    provider_id TEXT,
    action      TEXT,
    detail      TEXT,
    before      TEXT,
    undone      INTEGER DEFAULT 0,
    at          TEXT
);

-- What the Owner told us we got wrong. Weighted far above any passive signal
-- and applied immediately, not after a retraining cycle (BR-106).
CREATE TABLE IF NOT EXISTS corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT,      -- 'sender' | 'domain' | 'message'
    target      TEXT,
    was         TEXT,
    should_be   TEXT,
    source      TEXT,      -- 'app' | 'mailbox'
    at          TEXT
);
-- UC-27 / the mailbox view. Bodies for a BOUNDED window only.
--
-- ⚠️ THIS IS THE ONE PLACE MESSAGE TEXT IS KEPT, AND IT IS DELIBERATELY SMALL.
--
-- The plan is: headers for everything ever, bodies for the last 30 days, and
-- of those only the ones worth reading. Everything older is fetched live when
-- the Owner clicks it — which takes about two seconds and costs 5 quota units.
--
-- That bound is the whole design. "We hold 30 days of your important mail" is
-- a sentence a customer can weigh. "We hold all your mail" is not, and it is
-- what BR-103 warns about. Retention is enforced in code by trim_bodies(),
-- not by a policy page.
CREATE TABLE IF NOT EXISTS bodies (
    message_id  TEXT PRIMARY KEY,
    provider_id TEXT,
    account     TEXT,
    text        TEXT,
    chars       INTEGER,
    fetched_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_body_at ON bodies(fetched_at);

-- ── UC-33 / UC-45 · what people asked of the Owner, and what the Owner
-- promised. One table, one `direction` column: "ask" (they asked us) or
-- "promise" (we told them). Same shape, same machinery, pointed both ways.
-- Only the extracted fields are kept. The body was read once and discarded.
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  TEXT,
    provider_id TEXT,
    account     TEXT,
    direction   TEXT,          -- 'ask' | 'promise'
    what        TEXT,          -- the request, in the sender's words
    who         TEXT,          -- 'me' | 'sender' | 'third party' | an address
    due         TEXT,          -- ISO, or '' when no date was stated (BR-119: never guessed)
    evidence    TEXT,          -- the sentence it came from (feature 33)
    confidence  REAL,
    status      TEXT DEFAULT 'open',   -- open | done | dismissed
    at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_req ON requests(direction, status, due);

-- ── UC-38 / UC-44 · rules typed in plain English, and the "this person
-- matters" set. A rule stores the ORIGINAL sentence and what we made of it,
-- so a wrong reading can be traced (BR-141). Matching afterwards uses the
-- interpreted fields only — no AI (BR-143).
CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence    TEXT,          -- what the Owner typed, verbatim
    match_kind  TEXT,          -- 'sender' | 'domain' | 'subject' | 'person'
    match_value TEXT,
    action      TEXT,          -- 'protect' | 'label' | 'clear_approval' | 'forward_drafts' | 'top'
    action_arg  TEXT,
    plain       TEXT,          -- the interpretation shown back and confirmed
    group_id    TEXT,          -- UC-44: rules created together are removed together
    at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_rule ON rules(match_kind, match_value);

-- ── UC-17 · every unsubscribe request, so weeks later we can say whether
-- the sender actually stopped (BR-66) instead of assuming success.
CREATE TABLE IF NOT EXISTS unsub_requests (
    sender      TEXT PRIMARY KEY,
    requested_at TEXT,
    outcome     TEXT DEFAULT 'watching',   -- watching | stopped | ignoring
    checked_at  TEXT
);

-- ── UC-41 · one person, several addresses. Links carry their evidence so
-- a wrong merge can be split (BR-158). Addresses and counts only — never
-- content, never a phone number (BR-159).
CREATE TABLE IF NOT EXISTS person_links (
    address     TEXT PRIMARY KEY,
    person      TEXT,          -- the canonical address for the group
    evidence    TEXT,          -- why they were linked
    by_owner    INTEGER DEFAULT 0,
    at          TEXT
);

-- ── UC-36 · which unread-important messages have already been reported,
-- so each is raised once and never again (BR-135).
CREATE TABLE IF NOT EXISTS reported (
    message_id  TEXT,
    kind        TEXT,
    at          TEXT,
    PRIMARY KEY (message_id, kind)
);

-- ── UC-39 · an absence the Owner stated, or that we inferred. Cleared once
-- the catch-up is done.
CREATE TABLE IF NOT EXISTS away (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    since       TEXT,
    until       TEXT,
    stated      INTEGER DEFAULT 0,
    done        INTEGER DEFAULT 0
);

-- ── UC-35 · recipients the Owner chose themselves. The ONLY source a batch
-- forward may take an address from (BR-129).
CREATE TABLE IF NOT EXISTS saved_recipients (
    address     TEXT PRIMARY KEY,
    label       TEXT,
    at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_corr ON corrections(scope, target);
CREATE INDEX IF NOT EXISTS idx_act  ON actions(at);
CREATE INDEX IF NOT EXISTS idx_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_reply  ON messages(in_reply_to);
"""


class Store:
    """
    The store — whichever database is configured.

    ⚠️ ONE NAME, TWO BACKENDS. With DATABASE_URL set this hands back a
    PgStore on Postgres (one schema per account); without it, the SQLite
    file the POC has always used. Every script says `Store()` and never
    learns which — the same rule the connectors follow for mailboxes.
    CUSTODIAN_STORE=sqlite forces the file for a single run.
    """
    def __new__(cls, path="mailbox.db"):
        if cls is Store and os.environ.get("DATABASE_URL") \
                and os.environ.get("CUSTODIAN_STORE", "pg").lower() != "sqlite":
            from pg_store import PgStore
            return PgStore()
        return SqliteStore(path)


class SqliteStore:
    def __init__(self, path="mailbox.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        # ⚠️ Migration for databases created before `recipients` existed.
        # Cheap, idempotent, and it runs before anything reads the table.
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(messages)")}
        if "recipients" not in cols:
            self.db.execute("ALTER TABLE messages ADD COLUMN recipients TEXT")
        if "account" not in cols:
            self.db.execute("ALTER TABLE messages ADD COLUMN account TEXT")
        if "date_iso" not in cols:
            self.db.execute("ALTER TABLE messages ADD COLUMN date_iso TEXT")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_diso "
                            "ON messages(date_iso)")
        if "auth_results" not in cols:
            self.db.execute("ALTER TABLE messages ADD COLUMN auth_results TEXT")
        self.db.commit()

    def have(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT provider_id FROM messages")}

    def save(self, envelopes: list[Envelope]) -> int:
        rows = [(
            e.message_id, e.provider_id, e.thread_id,
            e.sender, e.sender_name, e.sender_domain,
            e.subject, e.date, e.size,
            int(e.unread), int(e.in_inbox), ",".join(e.categories),
            e.unsubscribe, int(e.one_click), e.list_id,
            int(e.bulk), e.auto_submitted, e.in_reply_to, e.references,
            e.recipients, e.account, iso_date(e.date), e.auth_results,
        ) for e in envelopes]
        self.db.executemany(
            "INSERT OR REPLACE INTO messages VALUES (" + ",".join("?" * 23) + ")", rows)
        self.db.commit()
        return len(rows)

    # ── UC-29 · decisions and their reasons ────────────────────────────

    def record_decision(self, message_id, stage, decision, reason, score=None) -> None:
        """
        ⚠️ Called at the moment the decision is made, never afterwards (BR-105).

        A reason reconstructed later is a guess dressed as a record. If the
        reason is not written here, in the same breath as the decision, then
        "why did it do that" has no honest answer.
        """
        from datetime import datetime
        self.db.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?)",
                        (message_id or "", stage, decision, reason,
                         score, datetime.now().isoformat()))
        self.db.commit()

    def decision_for(self, message_id: str) -> list:
        return self.db.execute(
            "SELECT stage, decision, reason, score, at FROM decisions "
            "WHERE message_id=? ORDER BY at", (message_id or "",)).fetchall()

    # ── UC-29 · corrections ────────────────────────────────────────────

    def add_correction(self, scope, target, was, should_be, source="app") -> None:
        from datetime import datetime
        self.db.execute(
            "INSERT INTO corrections (scope,target,was,should_be,source,at) "
            "VALUES (?,?,?,?,?,?)",
            (scope, (target or "").lower(), was, should_be, source,
             datetime.now().isoformat()))
        self.db.commit()

    def correction_for(self, sender: str, domain: str = "") -> dict | None:
        """
        ⚠️ The most recent correction wins, and it is consulted BEFORE any
        model output is trusted (BR-106). Applied immediately — there is no
        retraining cycle to wait for, because this is a lookup, not a weight.
        """
        r = self.db.execute(
            "SELECT scope,target,should_be,at FROM corrections "
            "WHERE (scope='sender' AND target=?) OR (scope='domain' AND target=?) "
            "ORDER BY id DESC LIMIT 1",
            ((sender or "").lower(), (domain or "").lower())).fetchone()
        if not r:
            return None
        return {"scope": r[0], "target": r[1], "should_be": r[2], "at": r[3]}

    def all_corrections(self) -> list:
        return self.db.execute(
            "SELECT id,scope,target,was,should_be,source,at FROM corrections "
            "ORDER BY id DESC").fetchall()

    # ── UC-30 · the audit log ──────────────────────────────────────────

    def record_action(self, message_id, provider_id, action, detail="", before="") -> int:
        """
        ⚠️ `before` is the state we are about to change, and it is the whole
        point of the row. Without it the log says what happened but not how to
        put it back — which is a history, not an undo (BR-108).
        """
        from datetime import datetime
        cur = self.db.execute(
            "INSERT INTO actions (message_id,provider_id,action,detail,before,undone,at) "
            "VALUES (?,?,?,?,?,0,?)",
            (message_id or "", provider_id or "", action, detail, before,
             datetime.now().isoformat()))
        self.db.commit()
        return cur.lastrowid

    # ⚠️ NOT called history() — `history(address, me)` already exists for sender
    # history, and a second method with the same name silently replaces the
    # first. Python does not warn; the gate would just start returning rows of
    # actions where it expected a dict of counts.
    def action_history(self, limit: int = 50) -> list:
        return self.db.execute(
            "SELECT id,message_id,provider_id,action,detail,before,undone,at "
            "FROM actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def mark_undone(self, action_id: int) -> None:
        self.db.execute("UPDATE actions SET undone=1 WHERE id=?", (action_id,))
        self.db.commit()

    # ── the mailbox view · bounded body cache ──────────────────────────

    def cache_body(self, message_id, provider_id, account, text) -> None:
        """Keep one body. Only ever called for mail inside the window."""
        from datetime import datetime
        self.db.execute("INSERT OR REPLACE INTO bodies VALUES (?,?,?,?,?,?)",
                        (message_id or "", provider_id, account, text,
                         len(text or ""), datetime.now().isoformat()))
        self.db.commit()

    def body(self, message_id: str) -> str:
        r = self.db.execute("SELECT text FROM bodies WHERE message_id=?",
                            (message_id or "",)).fetchone()
        return r[0] if r else ""

    def has_body(self, message_id: str) -> bool:
        return bool(self.db.execute(
            "SELECT 1 FROM bodies WHERE message_id=? LIMIT 1",
            (message_id or "",)).fetchone())

    def trim_bodies(self, days: int = 30) -> int:
        """
        ⚠️ THE RETENTION RULE, ENFORCED IN CODE.

        A promise to delete after 30 days that lives only in a policy document
        is not a promise, it is an intention. This runs on every open of the
        mailbox view, so the window cannot quietly widen through neglect.
        """
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        n = self.one("SELECT COUNT(*) FROM bodies WHERE fetched_at < ?", cutoff)
        if n:
            self.db.execute("DELETE FROM bodies WHERE fetched_at < ?", (cutoff,))
            self.db.commit()
        return n

    def body_stats(self) -> dict:
        r = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(chars),0) FROM bodies").fetchone()
        return {"count": r[0], "chars": r[1], "mb": r[1] / 1e6}

    def add_reminder(self, message_id, provider_id, kind, due, subject, why="") -> None:
        """
        ⚠️ `due` arrives already computed, as a real datetime. Stage 7 works it
        out in code. Nothing here parses "next Tuesday" — that is the one job
        this project never hands to a model, because encoders score below
        random chance on date arithmetic.
        """
        self.db.execute("INSERT OR REPLACE INTO reminders VALUES (?,?,?,?,?,?,0)",
                        (message_id, provider_id, kind,
                         due.isoformat() if hasattr(due, "isoformat") else str(due),
                         subject, why))
        self.db.commit()

    def due_reminders(self, now=None) -> list:
        """Anything whose time has come and has not been shown yet."""
        from datetime import datetime
        now = (now or datetime.now()).isoformat()
        return self.db.execute(
            "SELECT message_id, provider_id, kind, due, subject, why "
            "FROM reminders WHERE done=0 AND due<=? ORDER BY due", (now,)).fetchall()

    def clear_reminder(self, message_id: str, kind: str) -> None:
        self.db.execute("UPDATE reminders SET done=1 WHERE message_id=? AND kind=?",
                        (message_id, kind))
        self.db.commit()

    def pending_reminders(self) -> list:
        return self.db.execute(
            "SELECT message_id, provider_id, kind, due, subject, why "
            "FROM reminders WHERE done=0 ORDER BY due").fetchall()

    def already_replied(self, message_id: str) -> str:
        """
        Have we already answered this exact message? Returns when, or "".

        Keyed on Message-ID, not the provider's id, so this survives a mailbox
        migration for the same reason everything else is keyed that way.
        """
        r = self.db.execute(
            "SELECT at FROM handled WHERE message_id=? AND action='send'",
            (message_id or "",)).fetchone()
        return r[0] if r else ""

    def mark_replied(self, message_id: str, sent_id: str = "") -> None:
        """
        ⚠️ Written AFTER the send succeeds, never before.

        The two failure directions are not equal. Recording first and crashing
        means a message never gets answered — annoying. Sending first and
        crashing means we might answer twice — which puts a duplicate email in
        someone else's inbox. Of the two, only the second is visible to a
        stranger, so the risk is taken on our side.
        """
        from datetime import datetime
        self.db.execute(
            "INSERT OR REPLACE INTO handled VALUES (?,?,?,?)",
            (message_id or "", "send", sent_id, datetime.now().isoformat()))
        self.db.commit()

    def history(self, address: str, me: str = "") -> dict:
        """
        What this person and this mailbox have actually done to each other.

        ⚠️ `replied` counts mail WE SENT TO THEM, which needs the To line.
        Counting only messages FROM an address can never answer "have I
        written back to this person" — and that is the heaviest single
        feature in the reply gate, so leaving it always-false quietly
        removed 27% of the gate's evidence.
        """
        addr = (address or "").lower()
        sent, opened = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(1-unread),0) FROM messages WHERE sender=?",
            (addr,)).fetchone()
        replied = self.db.execute(
            "SELECT COUNT(*) FROM messages WHERE sender=? AND LOWER(recipients) LIKE ?",
            ((me or "").lower(), f"%{addr}%")).fetchone()[0] if me else 0
        return {"sent": sent or 0, "opened": opened or 0, "replied": replied or 0}

    # ── UC-33 / UC-45 · requests and promises ──────────────────────────

    def add_request(self, message_id, provider_id, account, direction,
                    what, who, due, evidence, confidence) -> int:
        from datetime import datetime
        # One record per (message, what). A rescan of the same message
        # replaces rather than duplicates.
        self.db.execute("DELETE FROM requests WHERE message_id=? AND what=?",
                        (message_id or "", what))
        cur = self.db.execute(
            "INSERT INTO requests (message_id, provider_id, account, direction, what, "
            "who, due, evidence, confidence, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (message_id or "", provider_id or "", account or "", direction, what,
             who, due or "", evidence or "", float(confidence or 0),
             datetime.now().isoformat()))
        self.db.commit()
        return cur.lastrowid

    def open_requests(self, direction: str = None) -> list:
        sql = ("SELECT r.id, r.message_id, r.direction, r.what, r.who, r.due, "
               "r.evidence, r.confidence, m.sender, m.sender_name, m.subject, "
               "m.recipients, m.date_iso FROM requests r LEFT JOIN messages m "
               "USING(message_id) WHERE r.status='open'")
        args = ()
        if direction:
            sql += " AND r.direction=?"; args = (direction,)
        sql += " ORDER BY CASE WHEN r.due='' THEN 1 ELSE 0 END, r.due"
        return self.db.execute(sql, args).fetchall()

    def set_request_status(self, request_id: int, status: str) -> None:
        self.db.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
        self.db.commit()

    def has_request(self, message_id: str) -> bool:
        return bool(self.db.execute(
            "SELECT 1 FROM requests WHERE message_id=? LIMIT 1",
            (message_id or "",)).fetchone())

    # ── UC-38 / UC-44 · rules ───────────────────────────────────────────

    def add_rule(self, sentence, match_kind, match_value, action, action_arg="",
                 plain="", group_id="") -> int:
        from datetime import datetime
        cur = self.db.execute(
            "INSERT INTO rules (sentence, match_kind, match_value, action, action_arg, "
            "plain, group_id, at) VALUES (?,?,?,?,?,?,?,?)",
            (sentence, match_kind, (match_value or "").lower(), action, action_arg,
             plain, group_id, datetime.now().isoformat()))
        self.db.commit()
        return cur.lastrowid

    def rules(self) -> list:
        return self.db.execute(
            "SELECT id, sentence, match_kind, match_value, action, action_arg, plain, "
            "group_id, at FROM rules ORDER BY id").fetchall()

    def rules_for(self, sender: str, domain: str = "", subject: str = "") -> list:
        """
        Every rule that matches this message. No AI here — BR-143.

        ⚠️ The most specific wins (BR-145): a sender rule before a domain rule
        before a subject rule. Returned in that order so the caller can take
        the first, or show the conflict.
        """
        s, d = (sender or "").lower(), (domain or "").lower()
        subj = (subject or "").lower()
        out = []
        for r in self.rules():
            _, _, kind, value, *_ = r
            if kind in ("sender", "person") and value == s:
                out.append((0, r))
            elif kind == "domain" and value and (d == value or d.endswith("." + value)):
                out.append((1, r))
            elif kind == "subject" and value and value in subj:
                out.append((2, r))
        return [r for _, r in sorted(out, key=lambda x: x[0])]

    def remove_rule(self, rule_id: int) -> None:
        self.db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        self.db.commit()

    def remove_rule_group(self, group_id: str) -> int:
        n = self.db.execute("DELETE FROM rules WHERE group_id=?", (group_id,)).rowcount
        self.db.commit()
        return n

    def is_protected(self, sender: str, domain: str = "") -> bool:
        """UC-44: never in the pile, never unsubscribed, never swept."""
        return any(r[4] in ("protect", "top") for r in self.rules_for(sender, domain))

    # ── UC-17 · unsubscribe follow-up ──────────────────────────────────

    def note_unsubscribe(self, sender: str) -> None:
        from datetime import datetime
        self.db.execute("INSERT OR REPLACE INTO unsub_requests VALUES (?,?,?,?)",
                        ((sender or "").lower(), datetime.now().isoformat(),
                         "watching", ""))
        self.db.commit()

    def unsubscribes(self, outcome: str = None) -> list:
        sql = "SELECT sender, requested_at, outcome, checked_at FROM unsub_requests"
        args = ()
        if outcome:
            sql += " WHERE outcome=?"; args = (outcome,)
        return self.db.execute(sql + " ORDER BY requested_at", args).fetchall()

    def set_unsubscribe_outcome(self, sender: str, outcome: str) -> None:
        from datetime import datetime
        self.db.execute("UPDATE unsub_requests SET outcome=?, checked_at=? WHERE sender=?",
                        (outcome, datetime.now().isoformat(), (sender or "").lower()))
        self.db.commit()

    # ── UC-36 · reported once ──────────────────────────────────────────

    def was_reported(self, message_id: str, kind: str) -> bool:
        return bool(self.db.execute("SELECT 1 FROM reported WHERE message_id=? AND kind=?",
                                    (message_id or "", kind)).fetchone())

    def mark_reported(self, message_id: str, kind: str) -> None:
        from datetime import datetime
        self.db.execute("INSERT OR REPLACE INTO reported VALUES (?,?,?)",
                        (message_id or "", kind, datetime.now().isoformat()))
        self.db.commit()

    # ── UC-41 · people ─────────────────────────────────────────────────

    def link_addresses(self, address: str, person: str, evidence: str,
                       by_owner: bool = False) -> None:
        from datetime import datetime
        self.db.execute("INSERT OR REPLACE INTO person_links VALUES (?,?,?,?,?)",
                        ((address or "").lower(), (person or "").lower(), evidence,
                         int(by_owner), datetime.now().isoformat()))
        self.db.commit()

    def person_of(self, address: str) -> str:
        r = self.db.execute("SELECT person FROM person_links WHERE address=?",
                            ((address or "").lower(),)).fetchone()
        return r[0] if r else (address or "").lower()

    def addresses_of(self, person: str) -> list:
        p = self.person_of(person)
        rows = self.db.execute(
            "SELECT address, evidence, by_owner FROM person_links WHERE person=?",
            (p,)).fetchall()
        return rows or [(p, "the only address", 0)]

    def split_person(self, address: str) -> None:
        self.db.execute("DELETE FROM person_links WHERE address=?", ((address or "").lower(),))
        self.db.commit()

    # ── UC-35 · the Owner's own recipient list ─────────────────────────

    def save_recipient(self, address: str, label: str = "") -> None:
        from datetime import datetime
        self.db.execute("INSERT OR REPLACE INTO saved_recipients VALUES (?,?,?)",
                        ((address or "").lower(), label, datetime.now().isoformat()))
        self.db.commit()

    def saved_recipients(self) -> list:
        return self.db.execute(
            "SELECT address, label FROM saved_recipients ORDER BY label, address").fetchall()

    # ── UC-39 · away ───────────────────────────────────────────────────

    def set_away(self, since: str, until: str, stated: bool = True) -> None:
        self.db.execute("INSERT INTO away (since, until, stated) VALUES (?,?,?)",
                        (since, until, int(stated)))
        self.db.commit()

    def pending_away(self):
        return self.db.execute(
            "SELECT id, since, until, stated FROM away WHERE done=0 "
            "ORDER BY id DESC LIMIT 1").fetchone()

    def finish_away(self, away_id: int) -> None:
        self.db.execute("UPDATE away SET done=1 WHERE id=?", (away_id,))
        self.db.commit()

    def q(self, sql: str, *args):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, *args):
        r = self.db.execute(sql, args).fetchone()
        return r[0] if r else 0
