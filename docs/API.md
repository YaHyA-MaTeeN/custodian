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

## Session and account (planned)

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
| `POST /api/mailboxes/identify` | planned | `{address}` → `{provider: "gmail"｜"outlook"｜"yahoo"｜"zoho"｜"icloud"｜"other", route: "app_password"｜"microsoft_signin"｜"google_signin", server}` (UC-50) |
| `POST /api/mailboxes/connect` | planned | `{address, appPassword}` → `{ok, accessLevel, folders, scanQueued: true}` or 400 with the provider's real reason in `detail` (UC-04/06/07/08/09/10). Passwords are verified before they are stored, never logged. |
| `DELETE /api/mailboxes/{address}` | planned | `{confirm: "disconnect"}` → `{ok, willStay: [...], erased: [...], lost: [...]}` (UC-13) |
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
| `GET /api/threads/{messageId}` | planned | UC-40: `{participants, questions: [{what, askedBy, owedBy, answered, messageId, due}], waitingOnYou: [...], latest}` — or `{participants, unsure: true}` |
| `GET /api/search?q=&account=&from=&to=` | planned | UC-28: `{results: [...], coverage: {mailboxes, backTo}}` |

---

## Today, requests, promises, reminders

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/today` | **live** | UC-43: `{items: [{kind: "due"｜"promise"｜"ask"｜"unread"｜"waiting"｜"spam", text, note, messageId}]}` in fixed order |
| `POST /api/today/{n}/dismiss` | planned | → `{ok}`; recorded as a correction |
| `GET /api/asks` | **live** | UC-33/45: `{asks: [...], promises: [...]}` each `{id, what, who, due, evidence, confidence, sender, subject, messageId}` |
| `POST /api/asks/scan` | planned | `{days?}` → `{read, found}` (reads new personal mail once, bodies discarded) |
| `POST /api/asks/{id}/done` · `/dismiss` | planned | → `{ok}` |
| `GET /api/deadlines` | **live** | reminders and commitments, soonest first |
| `POST /api/deadlines/{messageId}/dismiss` | **live** | → `{ok}` |
| `POST /api/reminders` | planned | UC-37: `{messageId, on: "2026-09-25"｜"thursday", note?}` → `{ok, due}`; 400 for a past date; the message never moves |
| `DELETE /api/reminders/{messageId}` | planned | → `{ok}` |
| `GET /api/catchup?since=` | planned | UC-39: `{days, arrived, needs: [...], answered: [...], expired: [...], info: [...], bulk, unsure}` |
| `POST /api/catchup/mark-read` | planned | `{messageIds: [...]}` → `{marked}` (reversible, logged) |

---

## Replying and sending

| Route | Status | Body → Response |
|---|---|---|
| `POST /api/messages/{providerId}/draft` | planned | UC-25: → `{draft, confirm, account, voice}` — redacted, written in the user's voice, restored locally; **nothing sent** |
| `POST /api/messages/{providerId}/drafts` | planned | writes the draft into the mailbox's own Drafts folder, threaded → `{ok, draftId}` (reversible) |
| `GET /api/messages/{providerId}/quick` | planned | UC-26: `{suggestions: [{key, text}]}` — at most 3, no model |
| `POST /api/messages/{providerId}/send` | planned | `{body, confirm}` → `{ok, sentId}` · 409 without the exact `confirm` from the preview · sends from the account the message arrived at, never another |
| `POST /api/forward-batch/preview` | planned | UC-35: `{messageIds: [...], to, note?}` → `{drafts: [{messageId, subject, account}], limit}` · 400 if `to` is not the user's own typed/saved address · 409 above the limit |
| `POST /api/forward-batch` | planned | same body → `{written}`; all or nothing; **drafts only** |
| `GET /api/recipients` · `POST /api/recipients` | planned | the user's own saved recipient list |
| `GET /api/voice` · `PUT /api/voice` | planned | UC-42: `{greeting, signOff, length, formality, contractions, groups: {domain: {...}}, description}`; a set field always beats what was learned |

---

## The cleanup

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/pile` | **live** | UC-15: `{groups: [{sender, name, count, opened, first, last, reason, never, kept}], heldBack, excludedSenders}` |
| `POST /api/pile/preview` | planned | `{senders: [...]｜"all"}` → `{count, confirm, wording}` |
| `POST /api/pile/clear` | planned | `{senders, confirm}` → `{moved, failed}`; provider trashes; every message logged |
| `POST /api/pile/rescue` | planned | `{sender}` → `{ok}`; a correction |
| `GET /api/brands` · `GET /api/brands/{company}` | planned | UC-16: companies, then `{advertising: [...], protected: [...], certain}` |
| `POST /api/brands/{company}/clear` | planned | `{confirm}` → `{moved, kept}` |
| `GET /api/unsubscribe` | planned | UC-17: `{ready: [...], cannot: [{sender, why, link}], watching: [...]}` |
| `POST /api/unsubscribe` | planned | `{sender, confirm}` → `{ok}`; one-click route only; then watched |
| `GET /api/unsubscribe/outcomes` | planned | `{stopped: [...], ignoring: [...]}` |
| `GET /api/storage` | planned | UC-18: largest messages and per-sender totals, protected marked |
| `POST /api/storage/clear` | planned | `{sender, confirm}` → `{moved, freedMb}` |
| `GET /api/spam` | planned | UC-20: `{likely: [{providerId, subject, sender, reasons}]}` — envelopes only |
| `POST /api/spam/{providerId}/rescue` | planned | → `{ok}` (reversible) |
| `GET /api/cleanup` | **live** | junk grouped by sender (older view; `pile` supersedes it) |
| `GET /api/cleanup/plan` | planned | UC-46: the four stages and what each would do |

---

## Control and trust

| Route | Status | Body → Response |
|---|---|---|
| `GET /api/rules` · `POST /api/rules` · `DELETE /api/rules/{id}` | **live** | corrections (UC-29): `{scope: "sender"｜"domain"｜"message", target, was, shouldBe}` |
| `GET /api/typed-rules` | **live** | UC-38/44: `{rules: [{id, sentence, matchKind, matchValue, action, actionArg, plain, group}]}` |
| `POST /api/typed-rules/interpret` | planned | `{sentence}` → `{matchKind, matchValue, action, plain, wouldMatch}` or `{unclear: "which part"}` — **nothing saved** |
| `POST /api/typed-rules` | planned | `{sentence, confirm: "yes"}` → `{id, plain}` (saved only after the interpretation was shown) |
| `POST /api/typed-rules/{id}/apply` | planned | `{confirm}` → `{labelled}` (existing mail; separate action) |
| `POST /api/people/{address}/important` · `DELETE …` | planned | UC-44 |
| `GET /api/people` · `GET /api/people/{address}` | planned | UC-41: `{addresses: [{address, evidence, byOwner}], owe, owed, promised, recent}` |
| `POST /api/people/link` · `POST /api/people/split` | planned | `{a, b}` / `{address}` |
| `GET /api/activity` | **live** | UC-30: every action, newest first, plain words |
| `POST /api/activity/{id}/undo` | **live** | → `{ok, what}` · 409 for send/forward/unsubscribe with the reason |
| `GET /api/digest` | **live** | what a digest would say now |
| `GET /api/digest/settings` · `PUT /api/digest/settings` | planned | `{frequency: "daily"｜"weekly"｜"monthly"｜"never"}` |
| `GET /api/calendar/today` | planned | UC-34: `{events: [{when, title}]}` or `{connected: false}` |
| `GET /api/calendar/suggestions` · `POST /api/calendar/add` | planned | `{n}` → `{ok}` after "Add this?"; `POST /api/calendar/decline {key}` |
| `GET /api/privacy` | **live** | row counts behind the privacy claims |
| `POST /api/privacy/export` | **live** | → `{file}` |
| erase | **deliberately absent** | erasing stays at the keyboard (`python my_data.py --erase`) until identity confirmation exists |

---

## Change control

A route's shape here is a promise. To change one: edit this file in the same
commit as the code, and tell the frontend. New routes are added under the
right heading with status **planned** first.
