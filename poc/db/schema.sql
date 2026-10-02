-- Custodian — Postgres schema, v2 (19 September 2026)
--
-- ⚠️ ONE SCHEMA PER ACCOUNT.
--
-- The shared tables below live in `public`: who the accounts are, their
-- sessions, their mailboxes and the encrypted credentials for them. Everything
-- ABOUT a person's mail — messages, decisions, actions, corrections,
-- reminders, requests, rules, people, voice — lives in that account's own
-- Postgres schema, `acct_<id>`, created by pg_store.PgStore the first time
-- the account is used, from the very same table definitions the POC runs on.
--
-- Why: one customer's data is physically separated from every other's (the
-- privacy pitch made structural rather than a WHERE clause nobody must
-- forget), and every existing script keeps its SQL unchanged. The cost is one
-- schema per account, which is fine to several thousand accounts.
--
-- Applied by  python db/migrate.py  — idempotent, safe to re-run.

-- v1 put the per-account tables in public with an account_id column. Nothing
-- was ever written to them. They are removed so the two designs cannot be
-- confused. Only ever touches public.*; account schemas are never dropped here.
DROP TABLE IF EXISTS public.style_examples, public.style_profile, public.saved_recipients,
    public.away, public.reported, public.person_links, public.unsub_requests, public.rules,
    public.requests, public.handled, public.reminders, public.corrections, public.actions,
    public.decisions, public.bodies, public.messages CASCADE;

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

-- ⚠️ Credentials live in their own table so a dump of anything else never
-- includes one (UC-10 BR-32). The value is encrypted by the application
-- before it gets here; this column never holds plaintext.
CREATE TABLE IF NOT EXISTS credentials (
    mailbox_id  BIGINT PRIMARY KEY REFERENCES mailboxes(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                -- app_password | oauth_refresh
    ciphertext  BYTEA NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── audit of the schema itself ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_versions (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    note        TEXT
);
INSERT INTO schema_versions (version, note)
    VALUES (2, 'v2 — one schema per account; public holds accounts, sessions, mailboxes, credentials')
    ON CONFLICT (version) DO NOTHING;

-- ── v3: subscriptions (UC-03, UC-48, UC-49) and region moves (UC-47) ────
-- One row per account. The state machine lives in billing.py; this table is
-- its memory. `customer` is the payment provider's reference, never a card.
CREATE TABLE IF NOT EXISTS subscriptions (
    account_id    BIGINT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    plan          TEXT NOT NULL,                 -- personal | work
    state         TEXT NOT NULL,                 -- trial | awaiting_confirm | active | paused | cancelled | ended
    customer      TEXT,                          -- provider reference
    trial_ends_at TIMESTAMPTZ,
    period_end    TIMESTAMPTZ,                   -- the paid-up-to date
    next_plan     TEXT,                          -- a downgrade waiting for the billing date (UC-48)
    paused_at     TIMESTAMPTZ,
    grace_until   TIMESTAMPTZ,                   -- 15 days to pay (UC-03)
    cancel_at     TIMESTAMPTZ,                   -- runs to here, then ends (UC-49)
    anchor_day    INTEGER NOT NULL DEFAULT 1,    -- the billing day of the month; never moves
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing_events (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,
    detail      TEXT
);

-- UC-47: a request to move an account's data to another region. The move
-- itself is an operations task (copy the schema, verify, switch, erase the
-- old copy: all or nothing); this records that it was asked and its outcome.
CREATE TABLE IF NOT EXISTS region_moves (
    id           BIGSERIAL PRIMARY KEY,
    account_id   BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    from_region  TEXT NOT NULL,
    to_region    TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'requested',   -- requested | done | failed | withdrawn
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    note         TEXT
);

INSERT INTO schema_versions (version, note)
    VALUES (3, 'v3 — subscriptions, billing_events, region_moves')
    ON CONFLICT (version) DO NOTHING;
