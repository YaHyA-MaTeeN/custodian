-- Custodian — Postgres schema, v1 (19 September 2026)
--
-- The SQLite schema in store.py, made multi-account. Every table that holds
-- anything about a person carries account_id, and every query the API runs
-- is scoped to it. The one deliberate absence is unchanged: NO body column on
-- messages. The bodies table is the bounded 30-day exception.
--
-- Applied by  python db/migrate.py  — idempotent, safe to re-run.

-- ── accounts and sign-in (UC-01, UC-02) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT,                      -- NULL for provider sign-in only
    confirmed_at  TIMESTAMPTZ,
    data_region   TEXT NOT NULL DEFAULT 'us-east',   -- picked silently (UC-01 BR-04)
    plan          TEXT NOT NULL DEFAULT 'trial',
    digest        TEXT NOT NULL DEFAULT 'weekly',   -- daily | weekly | monthly | never
    digest_last   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS confirmation_tokens (
    token       TEXT PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL,                -- confirm | reset
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

-- ── mailboxes (UC-04 … UC-13) ───────────────────────────────────────────
-- One address can be connected by one account only (UC-10 BR-34).
CREATE TABLE IF NOT EXISTS mailboxes (
    id            BIGSERIAL PRIMARY KEY,
    account_id    BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    address       TEXT UNIQUE NOT NULL,
    provider      TEXT NOT NULL,              -- gmail | outlook | yahoo | zoho | icloud | other
    route         TEXT NOT NULL,              -- app_password | google_signin | microsoft_signin
    host          TEXT,
    access_level  TEXT NOT NULL DEFAULT 'full',        -- full | read only  (BR-229)
    state         TEXT NOT NULL DEFAULT 'connected',   -- connected | paused | disconnected (BR-231)
    state_reason  TEXT,
    folders       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- sent, drafts, spam, trash, archive
    capabilities  JSONB NOT NULL DEFAULT '{}'::jsonb,  -- supports_push, labels, threads, …
    connected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    bookmark      TEXT                        -- history id or highest UID, for polling
);

-- ⚠️ Credentials live in their own table, keyed separately, so a dump of the
-- main tables never includes one (UC-10 BR-32). The value is encrypted by
-- the application before it gets here; this column never holds plaintext.
CREATE TABLE IF NOT EXISTS credentials (
    mailbox_id  BIGINT PRIMARY KEY REFERENCES mailboxes(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                -- app_password | oauth_refresh
    ciphertext  BYTEA NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── messages: the envelope index. No body column. ───────────────────────
CREATE TABLE IF NOT EXISTS messages (
    account_id    BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    mailbox_id    BIGINT NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
    provider_id   TEXT NOT NULL,              -- the door's handle; per mailbox
    message_id    TEXT NOT NULL DEFAULT '',   -- RFC Message-ID; the real key
    thread_id     TEXT NOT NULL DEFAULT '',
    sender        TEXT NOT NULL DEFAULT '',
    sender_name   TEXT NOT NULL DEFAULT '',
    sender_domain TEXT NOT NULL DEFAULT '',
    recipients    TEXT NOT NULL DEFAULT '',
    subject       TEXT NOT NULL DEFAULT '',
    date_raw      TEXT NOT NULL DEFAULT '',
    date_iso      TIMESTAMPTZ,
    size          INTEGER NOT NULL DEFAULT 0,
    unread        BOOLEAN NOT NULL DEFAULT false,
    in_inbox      BOOLEAN NOT NULL DEFAULT true,
    categories    TEXT NOT NULL DEFAULT '',
    unsubscribe   TEXT NOT NULL DEFAULT '',
    one_click     BOOLEAN NOT NULL DEFAULT false,
    list_id       TEXT NOT NULL DEFAULT '',
    bulk          BOOLEAN NOT NULL DEFAULT false,
    auto_sub      TEXT NOT NULL DEFAULT '',
    in_reply_to   TEXT NOT NULL DEFAULT '',
    refs          TEXT NOT NULL DEFAULT '',
    auth_results  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (mailbox_id, provider_id)
);
CREATE INDEX IF NOT EXISTS idx_msg_account_date ON messages(account_id, date_iso DESC);
CREATE INDEX IF NOT EXISTS idx_msg_message_id   ON messages(account_id, message_id);
CREATE INDEX IF NOT EXISTS idx_msg_sender       ON messages(account_id, sender);
CREATE INDEX IF NOT EXISTS idx_msg_thread       ON messages(account_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_msg_reply        ON messages(account_id, in_reply_to);

-- ── the bounded 30-day text store ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS bodies (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    mailbox_id  BIGINT NOT NULL,
    provider_id TEXT NOT NULL,
    text        TEXT NOT NULL,
    chars       INTEGER NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_bodies_at ON bodies(fetched_at);

-- ── decisions, actions, corrections, reminders, handled ─────────────────
CREATE TABLE IF NOT EXISTS decisions (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    stage       TEXT NOT NULL,
    decision    TEXT NOT NULL,
    reason      TEXT NOT NULL,                -- written at the moment (BR-105)
    score       REAL,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, message_id, stage)
);

CREATE TABLE IF NOT EXISTS actions (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    mailbox_id  BIGINT,
    message_id  TEXT NOT NULL DEFAULT '',
    provider_id TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    before      TEXT NOT NULL DEFAULT '',     -- what makes undo possible (BR-108)
    undone      BOOLEAN NOT NULL DEFAULT false,
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_actions ON actions(account_id, at DESC);

CREATE TABLE IF NOT EXISTS corrections (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    scope       TEXT NOT NULL,                -- sender | domain | message | reminder_lead
    target      TEXT NOT NULL,
    was         TEXT NOT NULL DEFAULT '',
    should_be   TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'app',  -- app | mailbox
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_corr ON corrections(account_id, scope, target);

CREATE TABLE IF NOT EXISTS reminders (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    provider_id TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL,                -- remind | snooze
    due         TIMESTAMPTZ NOT NULL,         -- computed in code, never by a model
    subject     TEXT NOT NULL DEFAULT '',
    why         TEXT NOT NULL DEFAULT '',
    done        BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (account_id, message_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_due ON reminders(account_id, due, done);

CREATE TABLE IF NOT EXISTS handled (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    action      TEXT NOT NULL,
    sent_id     TEXT NOT NULL DEFAULT '',
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, message_id, action)
);

-- ── requests and promises (UC-33, UC-45) ────────────────────────────────
CREATE TABLE IF NOT EXISTS requests (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL DEFAULT '',
    provider_id TEXT NOT NULL DEFAULT '',
    mailbox_id  BIGINT,
    direction   TEXT NOT NULL,                -- ask | promise
    what        TEXT NOT NULL,
    who         TEXT NOT NULL DEFAULT '',
    due         TIMESTAMPTZ,                  -- NULL when no date was stated (BR-119)
    evidence    TEXT NOT NULL DEFAULT '',
    confidence  REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'open', -- open | done | dismissed
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_req ON requests(account_id, direction, status, due);

-- ── typed rules and important people (UC-38, UC-44) ─────────────────────
CREATE TABLE IF NOT EXISTS rules (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    sentence    TEXT NOT NULL,
    match_kind  TEXT NOT NULL,                -- sender | domain | subject | person
    match_value TEXT NOT NULL,
    action      TEXT NOT NULL,                -- protect | top | label | clear_approval | forward_drafts | never_reply
    action_arg  TEXT NOT NULL DEFAULT '',
    plain       TEXT NOT NULL DEFAULT '',
    group_id    TEXT NOT NULL DEFAULT '',
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rules ON rules(account_id, match_kind, match_value);

-- ── unsubscribe follow-up (UC-17), people (UC-41), reported (UC-36),
--    away (UC-39), saved recipients (UC-35), voice (UC-42) ────────────────
CREATE TABLE IF NOT EXISTS unsub_requests (
    account_id   BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    sender       TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome      TEXT NOT NULL DEFAULT 'watching',   -- watching | stopped | ignoring
    checked_at   TIMESTAMPTZ,
    PRIMARY KEY (account_id, sender)
);

CREATE TABLE IF NOT EXISTS person_links (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    address     TEXT NOT NULL,
    person      TEXT NOT NULL,
    evidence    TEXT NOT NULL DEFAULT '',
    by_owner    BOOLEAN NOT NULL DEFAULT false,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, address)
);

CREATE TABLE IF NOT EXISTS reported (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, message_id, kind)
);

CREATE TABLE IF NOT EXISTS away (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    since       TIMESTAMPTZ NOT NULL,
    until       TIMESTAMPTZ,
    stated      BOOLEAN NOT NULL DEFAULT false,
    done        BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS saved_recipients (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    address     TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, address)
);

-- Voice: the counted profile and the Owner's overrides, per account. The
-- example vectors go in style_examples with a real vector column when
-- pgvector is enabled; until then they stay as bytes.
CREATE TABLE IF NOT EXISTS style_profile (
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,                -- greeting | set:greeting | group:<domain>:greeting …
    value       TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS style_examples (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT '',
    embedding   BYTEA
);

-- ── audit of the schema itself ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_versions (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    note        TEXT
);
INSERT INTO schema_versions (version, note)
    VALUES (1, 'v1 — accounts, mailboxes, credentials; every table scoped by account_id')
    ON CONFLICT (version) DO NOTHING;
