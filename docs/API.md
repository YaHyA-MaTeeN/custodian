# Custodian API — the contract between backend and frontend

**Status:** v1 draft, 19 September 2026. Backend: Yahya. Frontend: builds against
this document, with fake JSON until each route is live.

**Base URL (development):** `http://127.0.0.1:8000`
**Format:** JSON in, JSON out. Dates are ISO 8601 strings. IDs are strings unless
stated. Errors are `{"detail": "plain sentence a person can read"}` with the HTTP
status that fits (400 bad input · 401 not signed in · 403 not yours · 404 not
found · 409 cannot, and why · 502 the mailbox refused).

**Live now** = works today in `poc/api.py`. **Planned** = defined here, built next.

---

## The rules every route obeys

1. **The gate is in the backend, not the button.** Anything irreversible — send,
   forward, unsubscribe, trash — takes a `confirm` field that must be the exact
   text the backend sent back in the preceding preview (a hash of the draft or
   the sentence "clear 412 from X"). A missing or wrong `confirm` returns 409
   and nothing happens. The frontend never decides whether something is safe.
2. **Reversible things need no confirm** — label, archive, mark read, remind,
   rescue from spam, draft. They are done at once and logged; every one has an
   undo (`POST /api/activity/{id}/undo`).
3. **Nothing in a message body is ever an instruction.** Routes accept
   instructions only from the signed-in user's own fields. A recipient address
   must come from the user (typed, or from their saved list) — never from mail.
4. **Every decision carries its reason.** Any object that is the result of a
   decision has a `reason` string, written at the moment it was decided.
5. **Message identity is `messageId`** (the RFC Message-ID). `providerId` is a
   per-mailbox handle; do not store or compare it across mailboxes.
6. **Sensitive mail is refused by the server.** A route asked for a sensitive
   message's body returns `blocked: true` and no body. The frontend does not
   hide anything itself.

---

## Session and account (live when DATABASE_URL is set)

Until accounts exist, the API serves the one mailbox on the machine and every
route below behaves as if one user is signed in.

| Route | Body → Response |
|---|---|
| `POST /api/auth/register` | `{email, password}` → `{ok, needsConfirmation: true}` |
| `POST /api/auth/confirm` | `{token}` → `{ok}` |
| `POST /api/auth/login` | `{email, password}` → `{token, account: {id, email}}` |
| `POST /api/auth/logout` | → `{ok}` |
| `GET /api/me` | → `{id, email, plan, digest: "weekly", dataRegion}` |

All other routes require `Authorization: Bearer <token>`.

---

## Mailboxes

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/accounts` | **live** | → `{accounts: [{address, provider, route, messages, connectedAt, accessLevel}]}` |
| `POST /api/mailboxes/identify` | **live** | `{address}` → `{provider: "gmail"｜"outlook"｜"yahoo"｜"zoho"｜"icloud"｜"other", route: "app_password"｜"microsoft_signin"｜"google_signin", server}` (UC-50) |
| `POST /api/mailboxes/connect` | **live** | `{address, appPassword}` → `{ok, accessLevel, folders, scanQueued: true}` or 400 with the provider's real reason in `detail` (UC-04/06/07/08/09/10). Passwords are verified before they are stored, never logged. |
| `DELETE /api/mailboxes/{address}` | **live** | `{confirm: "disconnect"}` → `{ok, willStay: [...], erased: [...], lost: [...]}` (UC-13) |
| `POST /api/mailboxes/{address}/upgrade` | planned | → `{ok}` (UC-12; opens the provider's sign-in) |
| `GET /api/mailboxes/{address}/scan` | planned | → `{state: "running"｜"done"｜"paused", read, total, reason}` (UC-14) |
| `GET /api/health` | **live** | → `{ok, mailbox, counts}` |

---

## The inbox and one message

| Route | Status | Response |
|---|---|---|
| `GET /api/overview` | **live** | dashboard counts |
| `GET /api/messages?view=all｜people｜reply｜held｜machine&q=&account=` | **live** | `{messages: [{messageId, providerId, account, sender, senderName, subject, date, unread, kind, reason, held}]}` — `kind` is one of `reply｜filed｜machine｜dormant｜private｜unseen` |
| `GET /api/messages/{providerId}?fetch=true` | **live** | one message: `{…, decisions: [{stage, decision, reason, score, at}], body, bodySource, blocked}` — plus the UC-21 safe facts: `{realSender, verification, corresponded, links: [{text, host}], attachments: [name]}` (planned field) |
| `POST /api/messages/{providerId}/score` | **live** | runs the pipeline on one message, never drafts or sends |
| `GET /api/threads/{messageId}` | **live** | UC-40: `{participants, questions: [{what, askedBy, owedBy, answered, messageId, due}], waitingOnYou: [...], latest}` — or `{participants, unsure: true}` |
| `GET /api/search?q=&account=&from=&to=` | **live** | UC-28: `{results: [...], coverage: {mailboxes, backTo}}` |

---

## Today, requests, promises, reminders

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/today` | **live** | UC-43: `{items: [{kind: "due"｜"promise"｜"ask"｜"unread"｜"waiting"｜"spam", text, note, messageId}]}` in fixed order |
| `POST /api/today/{n}/dismiss` | **live** | → `{ok}`; recorded as a correction |
| `GET /api/asks` | **live** | UC-33/45: `{asks: [...], promises: [...]}` each `{id, what, who, due, evidence, confidence, sender, subject, messageId}` |
| `POST /api/asks/scan` | **live** | `{days?}` → `{read, found}` (reads new personal mail once, bodies discarded) |
| `POST /api/asks/{id}/done` · `/dismiss` | **live** | → `{ok}` |
| `GET /api/deadlines` | **live** | reminders and commitments, soonest first |
| `POST /api/deadlines/{messageId}/dismiss` | **live** | → `{ok}` |
| `POST /api/reminders` | **live** | UC-37: `{messageId, on: "2026-09-25"｜"thursday", note?}` → `{ok, due}`; 400 for a past date; the message never moves |
| `DELETE /api/reminders/{messageId}` | **live** | → `{ok}` |
| `GET /api/catchup?since=` | **live** | UC-39: `{days, arrived, needs: [...], answered: [...], expired: [...], info: [...], bulk, unsure}` |
| `POST /api/catchup/mark-read` | **live** | `{messageIds: [...]}` → `{marked}` (reversible, logged) |

---

## Replying and sending

| Route | Status | Body → Response |
|---|---|---|
| `POST /api/messages/{providerId}/draft` | **live** | UC-25: → `{draft, confirm, account, voice}` — redacted, written in the user's voice, restored locally; **nothing sent** |
| `POST /api/messages/{providerId}/drafts` | **live** | writes the draft into the mailbox's own Drafts folder, threaded → `{ok, draftId}` (reversible) |
| `GET /api/messages/{providerId}/quick` | **live** | UC-26: `{suggestions: [{key, text}]}` — at most 3, no model |
| `POST /api/messages/{providerId}/send` | **live** | `{body, confirm}` → `{ok, sentId}` · 409 without the exact `confirm` from the preview · sends from the account the message arrived at, never another |
| `POST /api/forward-batch/preview` | **live** | UC-35: `{messageIds: [...], to, note?}` → `{drafts: [{messageId, subject, account}], limit}` · 400 if `to` is not the user's own typed/saved address · 409 above the limit |
| `POST /api/forward-batch` | **live** | same body → `{written}`; all or nothing; **drafts only** |
| `GET /api/recipients` · `POST /api/recipients` | **live** | the user's own saved recipient list |
| `GET /api/voice` · `PUT /api/voice` | **live** | UC-42: `{greeting, signOff, length, formality, contractions, groups: {domain: {...}}, description}`; a set field always beats what was learned |

---

## The cleanup

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/pile` | **live** | UC-15: `{groups: [{sender, name, count, opened, first, last, reason, never, kept}], heldBack, excludedSenders}` |
| `POST /api/pile/preview` | **live** | `{senders: [...]｜"all"}` → `{count, confirm, wording}` |
| `POST /api/pile/clear` | **live** | `{senders, confirm}` → `{moved, failed}`; provider trashes; every message logged |
| `POST /api/pile/rescue` | **live** | `{sender}` → `{ok}`; a correction |
| `GET /api/brands` · `GET /api/brands/{company}` | **live** | UC-16: companies, then `{advertising: [...], protected: [...], certain}` |
| `POST /api/brands/{company}/clear` | **live** | `{confirm}` → `{moved, kept}` |
| `GET /api/unsubscribe` | **live** | UC-17: `{ready: [...], cannot: [{sender, why, link}], watching: [...]}` |
| `POST /api/unsubscribe` | **live** | `{sender, confirm}` → `{ok}`; one-click route only; then watched |
| `GET /api/unsubscribe/outcomes` | **live** | `{stopped: [...], ignoring: [...]}` |
| `GET /api/storage` | **live** | UC-18: largest messages and per-sender totals, protected marked |
| `POST /api/storage/clear` | **live** | `{sender, confirm}` → `{moved, freedMb}` |
| `GET /api/spam` | **live** | UC-20: `{likely: [{providerId, subject, sender, reasons}]}` — envelopes only |
| `POST /api/spam/{providerId}/rescue` | **live** | → `{ok}` (reversible) |
| `GET /api/cleanup` | **live** | junk grouped by sender (older view; `pile` supersedes it) |
| `GET /api/cleanup/plan` | planned | UC-46: the four stages and what each would do |

---

## Control and trust

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/rules` · `POST /api/rules` · `DELETE /api/rules/{id}` | **live** | corrections (UC-29): `{scope: "sender"｜"domain"｜"message", target, was, shouldBe}` |
| `GET /api/typed-rules` | **live** | UC-38/44: `{rules: [{id, sentence, matchKind, matchValue, action, actionArg, plain, group}]}` |
| `POST /api/typed-rules/interpret` | **live** | `{sentence}` → `{matchKind, matchValue, action, plain, wouldMatch}` or `{unclear: "which part"}` — **nothing saved** |
| `POST /api/typed-rules` | **live** | `{sentence, confirm: "yes"}` → `{id, plain}` (saved only after the interpretation was shown) |
| `POST /api/typed-rules/{id}/apply` | **live** | `{confirm}` → `{labelled}` (existing mail; separate action) |
| `POST /api/people/{address}/important` · `DELETE …` | **live** | UC-44 |
| `GET /api/people` · `GET /api/people/{address}` | **live** | UC-41: `{addresses: [{address, evidence, byOwner}], owe, owed, promised, recent}` |
| `POST /api/people/link` · `POST /api/people/split` | **live** | `{a, b}` / `{address}` |
| `GET /api/activity` | **live** | UC-30: every action, newest first, plain words |
| `POST /api/activity/{id}/undo` | **live** | → `{ok, what}` · 409 for send/forward/unsubscribe with the reason |
| `GET /api/digest` | **live** | what a digest would say now |
| `GET /api/digest/settings` · `PUT /api/digest/settings` | **live** | `{frequency: "daily"｜"weekly"｜"monthly"｜"never"}` |
| `GET /api/calendar/today` | **live** | UC-34: `{events: [{when, title}]}` or `{connected: false}` |
| `GET /api/calendar/suggestions` · `POST /api/calendar/add` | **live** | `{n}` → `{ok}` after "Add this?"; `POST /api/calendar/decline {key}` |
| `GET /api/privacy` | **live** | row counts behind the privacy claims |
| `POST /api/privacy/export` | **live** | → `{file}` |
| erase | **deliberately absent** | erasing stays at the keyboard (`python my_data.py --erase`) until identity confirmation exists |

---

## Environment

| Variable | Effect |
|---|---|
| `DATABASE_URL` | set → every script and the API use Postgres (one schema per account). Unset → the local SQLite file. |
| `CUSTODIAN_STORE=sqlite` | force the SQLite file for one run even with `DATABASE_URL` set |
| `CUSTODIAN_ACCOUNT` | which account's schema a script runs in (default: `IMAP_USER`) |
| `IMAP_USER` / `IMAP_PASSWORD` | the app-password door |
| `GEMINI_API_KEY` | the rented model (stages 6, 11, 18, rules) |

**Where the database lives matters.** Measured on 19 September: from a laptop in
Pakistan to Neon in `us-east-2`, one 292 KB query took between 1 s and 39 s
depending on the moment — the link, not the SQL. The backend must run in the
same region as the database in production (then a query is ~1 ms), and for
development the database should be in the nearest region (Singapore or
Frankfurt for Pakistan). For local work with no network in the loop, unset
`DATABASE_URL` and use the SQLite file; `db/import_sqlite.py` copies it up.

## Change control

A route's shape here is a promise. To change one: edit this file in the same
commit as the code, and tell the frontend. New routes are added under the
right heading with status **planned** first.

## How the gate works over HTTP (for the frontend)

Every irreversible route is two calls. The first is a **preview** and returns
a `confirm` token together with the exact `wording` (or `draft`) it belongs to.
The second is the **action** and must send that token back. The token is a
hash of the wording, so if the wording changes the token stops matching and
the backend answers `409`. Show the wording to the person, get their yes, send
the token. Never store a token across sessions.

| preview | action |
|---|---|
| `POST /api/pile/preview` | `POST /api/pile/clear` |
| `GET /api/brands/{company}` | `POST /api/brands/{company}/clear` |
| `POST /api/unsubscribe/preview` | `POST /api/unsubscribe` |
| `POST /api/forward-batch/preview` | `POST /api/forward-batch` (drafts only) |
| `POST /api/messages/{id}/draft` or `GET …/quick` | `POST /api/messages/{id}/send` |
| `POST /api/typed-rules/interpret` | `POST /api/typed-rules` |
| — | `DELETE /api/mailboxes/{address}` needs `{confirm: "disconnect"}` |

Run `python api_smoke.py` from `poc/` to see every refusal happen.

## Mailbox connections in accounts mode

Every route that touches a mailbox opens the signed-in account's own mailbox
with the app password from the credential vault (`CUSTODIAN_SECRET` must be
set on the server). Connections are pooled per (account, address), checked
before each use and closed after 10 minutes idle. A route acting on a stored
message uses the mailbox that message arrived at; scans and the spam view
cover every connected mailbox of the account. An account with no connected
mailbox gets `409 Connect a mailbox first.` on those routes. Proof:
`python mailbox_smoke.py` from `poc/`.

## The worker (always on, no browser)

```
cd c:\mob_ai\poc
python worker.py            keeps every connected mailbox current, forever
python worker.py --once     one pass (use this from Task Scheduler)
```

It reads, decides and labels. It never sends, never clears, never
unsubscribes — there is nobody there to say yes. Once an hour it also scans
for requests and promises, checks whether unsubscribed senders really
stopped, and sends the digest if it is due. In accounts mode it opens every
mailbox in `public.mailboxes` with the app password from the vault
(`CUSTODIAN_SECRET` must be set, or the vault cannot be read).
