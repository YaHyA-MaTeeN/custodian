# Custodian backend — handover

2 October 2026. Written for whoever continues this work. Read this first,
then `README.md` (how to run it) and `docs/API.md` (the route contract).

## At a glance

**To run it:** see `HOW-TO-RUN.md` (one page).

**Done** — working and tested:

- Mail over IMAP, tested on Gmail (47 operations)
- The 16-step pipeline that reads and labels every email
- 41 of the 50 use cases: cleanup, unsubscribe, reminders, requests and
  promises, catch-up, today's list, replies, rules, people, calendar, and more
- Accounts: sign-up with a real confirmation email, login, reset
- The API: 94 routes; nothing permanent without the person's confirmation
- Each user's own mailbox, password encrypted
- The worker: reads new mail all day, never sends or deletes
- The chat: every feature reachable by typing
- Subscriptions: trial, confirm, plan change, pause, cancel (logic only)
- Calendar: Google, iCloud, Yahoo, Zoho and others

**Left** — in order:

1. Connect a real payment company (subscription logic is ready; 3 functions to fill)
2. Deploy to a server (nothing is deployed)
3. Outlook: the company registers the app with Microsoft, then test it
4. Test Yahoo, Zoho, iCloud with one real account each
5. "Sign in with Google / Microsoft" for the account
6. Moving a user's data between regions (request is recorded; the move is manual)
7. Search inside message text (today: sender, subject, date)

---

## 1 · What you are receiving

The server side of an email assistant. A person signs up, connects a mailbox
over IMAP, and the system reads, sorts and labels their mail, shows what needs
attention, and lets them act on it from a web frontend or by typing in a chat.
Nothing is ever deleted, and nothing irreversible happens without the person
confirming the exact wording.

| Part | Where | State |
|---|---|---|
| Pipeline, 16 stages, rules first and models at the leaves | `poc/pipeline/` | built, tested on a live Gmail mailbox |
| Mail connectors: IMAP + SMTP for all providers, Gmail API as an option | `poc/connectors/` | Gmail tested (47 operations); others untested |
| Store: one SQL, SQLite for dev and Postgres for multi-user | `poc/store.py`, `poc/pg_store.py`, `poc/db/` | built; schema version 3 |
| Accounts: sign-up, confirmation email, login, reset | `poc/auth.py`, `poc/api_auth.py`, `poc/mailer.py` | built, tested end to end |
| API, 94 routes, confirm gate on irreversible actions | `poc/api.py`, `poc/api_mvp.py` | built, tested |
| Per-user mailbox connections from an encrypted vault | `poc/mailboxes.py` | built, tested with two accounts |
| Always-on worker | `poc/worker.py` | built; reads and labels, never sends or clears |
| Chat, every feature reachable by typing | `poc/chat_engine.py` | built on Gemini, 22 sentences tested |
| Calendar: Google, plus CalDAV for iCloud, Yahoo, Zoho and others | `poc/calendar_sync.py`, `poc/calendar_caldav.py` | built; CalDAV tested against a local Radicale server, not yet against a real iCloud/Yahoo account |
| Subscriptions: trial, confirm, plan change, pause, cancel | `poc/billing.py` | state machine built and tested; **no real payment provider connected** |
| The 50 use cases as scripts | `poc/*.py` (one per feature) | see `docs/use-cases-in-brief.md` |

About 20,000 lines of Python. No frontend in this repository; the frontend is
built separately against `docs/API.md`.

## 2 · What was personal and is NOT in this repository

Everything below lived in the previous developer's own accounts or on their
laptop, through environment variables only. None of it is in the code or the
history you receive. **You must create your own of each.**

| Thing | What to do |
|---|---|
| Postgres database (was a personal Neon project) | Create your own Postgres (Neon or any). Set `DATABASE_URL`. Run `python db/migrate.py` from `poc/`. It starts empty. |
| Test mailbox (was a personal Gmail) | Use a company test mailbox with an app password: `IMAP_USER`, `IMAP_PASSWORD`. |
| Sender for confirmation emails | `MAIL_FROM`, `MAIL_PASSWORD` (falls back to the IMAP pair). Move to a transactional service before real users; only `poc/mailer.py` changes. |
| Gemini key | Your own from Google AI Studio: `GEMINI_API_KEY`. |
| Vault key | Generate once and keep it safe: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` → `CUSTODIAN_SECRET`. Lose it and every stored mailbox password is unreadable. |
| Microsoft app registration (Outlook) | Register under the company's Microsoft 365 (steps in section 6) → `OUTLOOK_CLIENT_ID`. Personal Microsoft accounts cannot register apps. |
| Google OAuth client (optional Gmail API door, calendar) | Your own `credentials.json` from Google Cloud, placed in `poc/`. Not needed for the IMAP door. |
| The two local models | `poc/classifier/` and `poc/pii_model/` are not in the repo (1.6 GB). Without them the pipeline uses Gemini for classification and regex plus known names for redaction, and still works. To have them: retrain with `train_classifier.py` / `train_pii.py` (or the `kaggle_*` versions) on your own labelled mail. |
| Local mailbox index, labelled training data, test outputs | Personal data from the old test mailbox. Not handed over. `python scan.py` builds a fresh index from your test mailbox. |

## 3 · Environment variables

| Variable | Needed for | Notes |
|---|---|---|
| `IMAP_USER`, `IMAP_PASSWORD` | single-user mode; tests | an app password, never a normal password |
| `GEMINI_API_KEY` | reading requests, drafting, typed rules, chat | free tier is enough for development |
| `DATABASE_URL` | accounts mode (multi-user) | Postgres. Unset = single-user on a local SQLite file |
| `CUSTODIAN_SECRET` | the credential vault | Fernet key; required to connect mailboxes in accounts mode |
| `CUSTODIAN_STORE=sqlite` | forcing single-user mode while `DATABASE_URL` is set | development convenience |
| `MAIL_FROM`, `MAIL_PASSWORD`, `APP_URL` | confirmation and reset emails | `APP_URL` is where the links point |
| `OUTLOOK_CLIENT_ID` | Outlook sign-in | from the Microsoft app registration |
| `CUSTODIAN_BILLING=off` | turning the subscription gate off | default is on in accounts mode |
| `PLAN_PERSONAL_PRICE`, `PLAN_WORK_PRICE`, `PLAN_CURRENCY` | plan prices | placeholders: 12.00, 20.00, GBP |
| `STRIPE_SECRET_KEY` | selects the real payment provider | the provider class is a stub; see section 5 |
| `CALDAV_URL`, `CALDAV_USER`, `CALDAV_PASSWORD` | single-user calendar on a CalDAV server | optional; by default the calendar uses the mailbox address and app password. In accounts mode the vault credential is used |

## 4 · First hour: get it running and prove it

From `poc/`, after setting the variables:

```
pip install -r requirements.txt
python scan.py                  index the test mailbox (single-user)
python api.py --port 8000       then open http://localhost:8000/docs
python api_smoke.py             read routes answer; gated actions refuse
python chat_smoke.py            22 sentences through the chat
python worker.py --once         one pass of the worker
```

With `DATABASE_URL` and `CUSTODIAN_SECRET` set (accounts mode):

```
python db/migrate.py            creates the shared tables, schema version 3
python auth_smoke.py            sign-up → confirm → login → reset
python mail_smoke.py            a real confirmation email arrives
python mailbox_smoke.py         per-account mailbox isolation
python billing_smoke.py         the whole subscription life, 21 checks
```

With no setup at all:

```
python calendar_smoke.py        CalDAV calendar against a local server, 20 checks
```

Each test deletes what it created. Outputs are written to `poc/test_runs/`.

## 5 · What is not finished, in order of importance

1. **Payment provider.** `billing.py` is the complete state machine (card
   first, 7-day trial with cleanup locked, day-7 confirmation before any
   charge, upgrade now, downgrade at the billing date, failed renewal pauses,
   15 days to pay, cancel runs to the period end, ended disconnects) and it
   passes its lifecycle test with a stand-in provider that moves no money.
   To take real payments, implement the three methods of `StripeProvider`
   (`attach_card`, `charge`, `replace_card`) and add a webhook route that
   calls `billing.tick()` or the matching transition when a renewal fails.
   Nothing else changes.
2. **Deployment.** Nothing is deployed. One small server running `api.py`
   and `worker.py` beside the database is enough to start. The database
   should be in the same region as the server.
3. **Outlook.** The sign-in flow (`poc/outlook.py`, device-code) and token
   login over IMAP are written and untested, waiting on the Microsoft
   registration (section 6).
4. **Yahoo, Zoho, iCloud.** Server addresses and the connect checks are in.
   No real account of each has been connected. Needs one test address per
   provider and an afternoon.
5. **Sign in to the account with Google or Microsoft.** Only email and
   password exist. Needs an OAuth web client.
6. **Data region move (UC-47).** The request is recorded
   (`/api/privacy/region`); the move itself is a manual operations task:
   copy the account's schema to the new region, verify, switch, erase the old.
7. **Calendar on real CalDAV accounts and Outlook.** CalDAV is proven against a
   standard server; one real iCloud or Yahoo account would confirm it. Outlook's
   calendar needs Microsoft Graph, after the same registration as Outlook mail.
8. **Search inside message text.** Search covers sender, subject and date.
9. **Push instead of polling.** The worker polls each mailbox every 20
   seconds. IMAP IDLE and Gmail push would cut the server count at scale.
10. **Rule conflicts.** Two typed rules that disagree about the same message
   are not detected.
11. **Cosmetic, chat.** In answers that quote an email, a restored name is
    sometimes shortened or doubled by the redaction round trip.

## 6 · Registering the app with Microsoft (for Outlook)

Someone with an admin login to the company's Microsoft 365:

1. portal.azure.com → App registrations → New registration.
2. Name: Custodian. Account types: "Accounts in any organizational directory
   and personal Microsoft accounts". No redirect URI.
3. Copy the Application (client) ID.
4. Authentication → Advanced settings → Allow public client flows → Yes.
5. API permissions → Add → APIs my organization uses → Office 365 Exchange
   Online → Delegated → `IMAP.AccessAsUser.All` and `SMTP.Send`.
6. Set `OUTLOOK_CLIENT_ID`, then `python outlook.py --connect <address>`.

The client ID is not a secret. No client secret is needed for this flow.

## 7 · Rules the code keeps, and you should too

- **Nothing is ever deleted from a mailbox.** Trash is a move.
- **The approval gate is code, not a prompt** (`pipeline/stage13_approval.py`).
  Every irreversible action needs the confirm token of the exact wording the
  person saw. Over HTTP: preview route, then action route with the token.
- **What the user types is an instruction; what an email says is data.**
  They never share a code path, so an email cannot instruct the system.
- **Nothing leaves the server unredacted.** Hosted model calls go through
  `pipeline/stage10_redact.py`; names come back only on our side.
- **Sensitive senders are never opened** (`pipeline/stage03_sensitive.py`
  sees sender and subject only).
- **One customer, one schema.** A query for one account cannot name another's.
- **Credentials live in the environment or the vault.** Never in code, the
  repo, logs or documents.
- **A recipient for a forward comes from the user, never from an email.**
- **The worker and the chat never do anything irreversible.**

## 8 · Map of the code

```
poc/
  api.py            the FastAPI app and the first 21 routes
  api_auth.py       sessions, auth routes, per-account store
  api_mvp.py        every other route: features, chat, billing, mailboxes
  auth.py           password hashing, tokens, sessions, throttling
  billing.py        subscription state machine and provider interface
  mailer.py         confirmation and reset emails over SMTP
  mailboxes.py      per-account IMAP connections from the vault, pooled
  chat_engine.py    the chat: intent from the model, answer from our code
  worker.py         the always-on process
  store.py          the SQL and the SQLite backend
  pg_store.py       the same SQL on Postgres, one schema per account
  db/               schema.sql (shared tables), migrate.py
  connect.py        which mail server for an address; opening a mailbox
  connectors/       imap.py, gmail.py, base.py
  pipeline/         the stages, the model calls, redaction, the gate
  prompts.md        every instruction given to a model, editable as text
  <feature>.py      one script per use case: pile, brand, unsubscribe,
                    storage, spam_rescue, remind, important, asks, people,
                    forward_batch, rules, threads, catchup, today, cleanup,
                    digest, voice, calendar_sync (+ calendar_caldav),
                    upgrade, outlook, my_data
  *_smoke.py        the tests listed in section 4
docs/
  API.md                               the route contract
  STATUS.md                            one-page status
  Custodian-Backend-Design.pdf         design, components, flows, schema, costs
  Custodian-Backend-Review-Answers.pdf coverage table, schema, API-vs-own-server costs
  Custodian-IMAP-Tests.pdf             the IMAP proof
  use-cases-in-brief.md                all 50 use cases, one line each, with status
```

## 9 · Use-case coverage

41 built and tested. 9 partly:

| Use case | What exists | What is missing |
|---|---|---|
| UC-02 Sign in | email and password, sessions | Google / Microsoft sign-in to the account |
| UC-03 Start a subscription | trial, lock, day-7 confirm, pause, 15-day grace, end | a real payment provider |
| UC-48 Change plan | upgrade now, downgrade at the billing date, date fixed | same |
| UC-49 Cancel | runs to period end, then disconnects, nothing undone | same |
| UC-05 Outlook | sign-in flow and token login written | Microsoft registration; a test |
| UC-06, 07, 08 Yahoo, Zoho, iCloud | servers known, password-shape checks | a real account of each to test |
| UC-47 Data region | region shown, move request recorded | the move itself |
