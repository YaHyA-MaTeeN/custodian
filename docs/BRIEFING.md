# Custodian backend — the briefing

Read this before you sit with sir. It explains the whole thing in plain
words, in the order questions usually come, and tells you which file proves
each claim. Every path is relative to `c:\mob_ai`.

How to use it: read parts 1 to 4 once, slowly. Skim 5 to 9. Keep 10 open on
your phone during the meeting.

---

## 1 · What Custodian is, in one paragraph

Custodian is an email assistant. A person connects their mailbox. Custodian
reads every email, decides what it is (a person asking for something, a
newsletter, a receipt, spam that is really important), labels it, and shows
the person a short list of what needs attention today. It can draft replies
in the person's own writing style, clean out thousands of bulk emails,
unsubscribe from senders, set reminders, and track what people asked of you
and what you promised them. It never deletes anything and never sends
anything without the person reading the exact text and saying yes.

You are building the **backend**: the server side. Umar builds the
**frontend**: the screens. The backend does all the thinking; the screens
only show and ask.

---

## 2 · The five days: what you reported, and what stands behind it

| Day | You reported | What actually exists |
|---|---|---|
| 1 | Reviewed the 50 use cases and started implementing them; fixed undo over IMAP and a Gmail token bug; set up Postgres with per-account separation and moved data in | 42 scripts in `poc/` (one per feature), tested on your Gmail. `poc/history.py` undo. `poc/db/schema.sql`, `poc/pg_store.py`, `poc/db/import_sqlite.py`. Your 7,391 messages are in Neon. |
| 2 | Completed the backend design doc with diagrams; proposed the DB architecture; resource estimates | `docs/Custodian-Backend-Design-v0.1.pdf` (what he has). Source `docs/backend-design.html`. |
| 3 | Built and tested accounts: sign-up, confirm, login, logout, reset; wrote the API contract | `poc/auth.py`, `poc/api_auth.py`, proof `poc/auth_smoke.py`, output in `poc/test_runs/auth_smoke_*.txt`. Contract `docs/API.md`. |
| 4 | Answered his four questions: 40/50 use cases, schema per customer, API vs own servers, full DB schema | `docs/Custodian-Backend-Review-Answers.pdf` |
| 5 | Fixed the API to open each user's own mailbox from the vault; implemented feature routes with preview-and-confirm; pushed to GitHub | `poc/mailboxes.py`, `poc/api_mvp.py`, proof `poc/mailbox_smoke.py`, output `poc/test_runs/mailbox_smoke_*.txt`. Repo https://github.com/YaHyA-MaTeeN/custodian |

Not yet reported, in reserve: the worker (`poc/worker.py`), the performance
work on the slow database link, the chat (a terminal prototype only).

---

## 3 · The big picture: one email's journey

Read this left to right. Every email takes this path.

```
Mail server (Gmail)  →  Connector  →  Store  →  Pipeline  →  three outputs
                        (IMAP)       (database)  (16 stages)   1. a decision + reason in the database
                                                               2. a label in the mailbox
                                                               3. a line on the person's screen (via the API)
```

- The **worker** is the process that runs this all day without a browser.
- The **API** is how the screen asks for results and asks for actions.
- The **gate** sits in front of every action that cannot be undone.

If sir asks "walk me through what happens when an email arrives", say:

> "The worker notices a new message. The connector fetches its headers over
> IMAP. The store saves them. The pipeline runs: strip the quoted text, check
> whether the sender is sensitive, verify the headers, decide person or
> machine, decide if a reply is needed, find dates, find requests. It applies
> a label and writes the decision with its reason. The screen reads that
> from the API."

---

## 4 · The parts, one by one

### 4.1 · Connectors: the doors to a mailbox

**What it is.** The code that talks to the mail server. There are two doors.

- **IMAP** (`poc/connectors/imap.py`). The universal standard. Works for
  Gmail, Outlook, Yahoo, Zoho, iCloud, anything. Needs an app password. This
  is the default door now, on sir's instruction.
- **Gmail API** (`poc/connectors/gmail.py`). Google's own door. Only Gmail.
  Needs Google sign-in. Kept as an optional door.

**Why IMAP.** One door for every provider, no Google approval process, and it
can do everything the Gmail API can except two things: push notification
(we poll every 20 seconds instead) and snooze.

**Sending.** IMAP cannot send. Sending goes over SMTP with the same app
password. Tested: a real email sent in about 5 seconds.

**Proof.** `docs/Custodian-IMAP-Tests.pdf` — 47 tests on your Gmail: read
every folder, label, archive, trash, rescue from spam, mark read, send,
draft, forward, undo. Outputs in `poc/test_runs/audit_imap_*.txt`.

**If he asks "what did we give up with IMAP":** push and snooze. Everything
else was tested and works.

### 4.2 · The store and the database

**What it is.** Where Custodian keeps what it knows. Two backends, same code:

- **SQLite** — a file on your laptop, `poc/mailbox.db`. Used for development.
- **Postgres on Neon** — a hosted database on the internet. Used for the MVP.

`poc/store.py` writes the SQL once. `poc/pg_store.py` translates it for
Postgres. Nothing else changes.

**Per-account separation.** The database has two layers:

- `public` — six small shared tables: accounts, sessions, confirmation
  tokens, mailboxes, credentials, schema versions. Who the customers are.
- `acct_<id>` — one private area per **customer** with sixteen tables:
  messages, bodies, decisions, actions, corrections, reminders, requests,
  rules, and so on. Everything about that customer's mail.

A customer with three mailboxes still has one area; a column on each message
says which mailbox it came from. "Per account" means per customer, not per
mailbox. Why: one customer's queries physically cannot see another's data.

**What is never stored.** Message bodies are kept only for 30 days, in their
own table, then trimmed. Passwords are never stored in plain text. Nothing is
ever deleted from a mailbox; trash is a move the person can undo.

**Files.** `poc/db/schema.sql` (shared tables), `poc/db/migrate.py` (applies
it), `poc/db/import_sqlite.py` (copied your laptop data into Neon, counts
matched). Full column list: `docs/Custodian-Backend-Review-Answers.pdf`
section 4.

**Measured.** 7,391 messages take 7.5 MB, about 1 KB per message.

### 4.3 · The pipeline: how a decision is made

**What it is.** Sixteen steps, in a fixed order, in `poc/pipeline/`. Rules
first, models only where rules cannot decide. Simple words per stage:

| Stage | File | What it does |
|---|---|---|
| 2 | `stage02_strip.py` | Removes the quoted old conversation so only the new text remains |
| 3 | `stage03_sensitive.py` | Looks at sender and subject only. Bank, doctor, lawyer, HR: never opened |
| 4 | `stage04_headers.py` | Reads what the sender declared (bulk, auto-reply, unsubscribe) and the SPF/DKIM verification stamp |
| 5 | `stage05_forms.py` | Recognises receipts, bookings, invoices by their layout |
| 7 | `stage07_dates.py` | Finds dates and deadlines |
| 8 | (model) | Classifies: person or machine, what they want, does it need a reply |
| 9 | `stage09_gate.py` | Scores whether the person will act on it; the "needs a reply" decision |
| 10 | `stage10_redact.py` | Hides names and personal details before anything goes to a hosted model, restores them after |
| 13 | `stage13_approval.py` | The gate. Nothing irreversible without a yes bound to the exact text |
| 15 | `stage15_unsubscribe.py` | One-click unsubscribe only, never opens web pages |
| 16 | `stage16_commitments.py` | Turns a date into a reminder |
| 17 | `stage17_quick.py` | Three fixed one-word answers, no AI |
| 18 | `stage18_requests.py` | Finds what was asked, of whom, by when |
| 19 | `stage19_voice.py` | Learns how the person writes, from their sent mail |

**The principle.** The model decides, the code acts. A model never touches
the mailbox. It returns a small answer; code does the labelling.

**If he asks "where is the AI":** stages 8 and 18 and reply drafting. The
rest is rules. About 70 percent of mail never reaches a model.

### 4.4 · The models

Three models, and the difference matters for cost.

| Model | Job | Where it runs | Size |
|---|---|---|---|
| Classifier | Stage 8: what kind of message, needs a reply? | Our server, CPU | 278 million parameters, 550 MB, 66 ms per message |
| Name spotter | Stage 10: find names to hide | Our server, CPU | 278 million parameters, 1.1 GB, 69 ms per message |
| Gemini Flash-Lite | Reading requests, choosing deadlines, drafting replies, interpreting typed rules | Google, over the network | not ours, paid per token |

**Why the small ones stay with us.** They cost nothing extra to run and the
name spotter's whole job is to find the private parts before anything leaves.

**Why Gemini stays hosted.** Renting a GPU costs about $580 a month whether
used or not. Gemini costs about $0.19 per user per month. The API is cheaper
until roughly 20,000 users.

**Privacy rule.** Gemini only ever sees redacted text: names replaced by
placeholders, restored locally afterwards. The rule is code, not a prompt.

**Files.** `poc/pipeline/model.py`, `poc/pipeline/local_classifier.py`,
`poc/pipeline/local_pii.py`. Model files in `poc/classifier/` and
`poc/pii_model/` (not in git, too big).

### 4.5 · Accounts and sign-in

**What it is.** `poc/auth.py` and `poc/api_auth.py`. Sign-up with email and
password, confirmation token, login that returns a session token, logout,
password reset.

**Security choices to mention.** Passwords are hashed with scrypt, never
stored. Wrong password and unknown email get the same message, so nobody can
discover which emails have accounts. Failed logins are throttled. A password
reset kills every session. Signing in gives access to the account only, not
to any mailbox; connecting a mailbox is a separate step with its own password.

**Honest limit.** No email is actually sent yet. The confirmation and reset
tokens come back in the response. Sending them needs an email service (the
proposal names a free tier).

**Proof.** `poc/auth_smoke.py`: 14 steps, all expected codes, output in
`poc/test_runs/auth_smoke_*.txt`.

### 4.6 · The API and the gate

**What it is.** `poc/api.py` + `poc/api_auth.py` + `poc/api_mvp.py`. 79
routes. A route is one thing the screen can ask: "give me today's list",
"draft a reply to this", "clear these senders". The full list with inputs
and outputs is `docs/API.md`. Umar builds against that document.

**The gate over HTTP.** Every irreversible action is two calls:

1. **Preview**: returns the exact wording, for example "trash 6,683 messages
   from 91 senders", plus a `confirm` token which is a fingerprint of that
   wording.
2. **Action**: must send the token back. The server recomputes the
   fingerprint. If the wording changed, the token no longer fits, and the
   server answers 409, refused.

So the screen cannot delete, unsubscribe, send or forward without the person
seeing the exact thing. Applies to: clear the pile, clear a brand,
unsubscribe, send a reply, batch forward, create a typed rule. Disconnecting
a mailbox needs the literal word "disconnect".

**Proof.** `poc/api_smoke.py`: read routes return 200; every gated action
without a token returns 409.

### 4.7 · Per-user mailbox connections and the vault (day 5)

**The problem.** The API used to open one mailbox, yours, at startup. A
second user would have seen your mail.

**The fix.** `poc/mailboxes.py`. When a person connects a mailbox, the app
password is verified against the mail server and stored encrypted in the
`credentials` table. The encryption key lives only in the server's
environment (`CUSTODIAN_SECRET`), never in the database, so a copy of the
database is useless on its own. When that person calls a mailbox route, the
API takes the password out of the vault, opens their mailbox over IMAP, and
keeps the connection pooled for ten minutes of idle time. A route acting on
a message uses the mailbox that message arrived at.

**Proof.** `poc/mailbox_smoke.py`. It creates a throwaway second account,
connects your Gmail under your account through the API, switches off the
server's own mailbox, and shows that a mailbox route still works (so it came
from the vault) while the second account is refused. Then it deletes what it
created. Output in `poc/test_runs/mailbox_smoke_*.txt`.

### 4.8 · The worker

**What it is.** `poc/worker.py`. One process, no browser. Every 20 seconds,
for each connected mailbox: fetch new mail, run the pipeline, label. When
nothing new, work through three older messages. Once an hour: scan for
requests and promises, check whether unsubscribed senders really stopped,
send the digest if due.

**What it cannot do.** Send or clear. There is nobody there to say yes.

**Run it.** `cd c:\mob_ai\poc` then `python worker.py`. Send yourself an
email; within 20 seconds a line says "1 new".

### 4.9 · The chat: where it stands

**The decision.** There will be a chat. You and sir agreed that. It is not
built for the website yet, and that is deliberate, not forgotten.

**What exists today.** A terminal prototype, `poc/chat.py`. You type a
sentence like "anything from linkedin?" or "email ali and ask if he got the
report". Gemini is shown a fixed menu of actions our code allows right now
and picks one. It cannot pick anything off the menu, and "send" is not on
the menu until a draft exists. The gate still applies: nothing irreversible
happens without the typed yes. What you type is treated as an instruction;
what is inside an email is treated as data; the two never share a code path,
so an email cannot talk the chat into doing something.

**What does not exist.** A chat route in the API, so Umar has nothing to
call yet. No memory of previous turns. No handling of two requests in one
sentence.

**How it will be built.** The chat is a receptionist for a building that
already has fifteen rooms (the features). It has two jobs: hear which room
the person wants, and hear the details (a name, a date, a sender). Then the
backend walks them to the room; the room does the work. If the room is an
irreversible one, the chat returns the preview wording and confirm token
like every other route. Replies come from templates, not free-form writing.

**The open question: which model does the hearing.** Three options:

| Option | Cost | Needs | Handles messy sentences |
|---|---|---|---|
| Our two small models, retrained on example sentences | about nothing | a few hundred labelled example sentences first | well for short one-intent sentences; asks back on two-part ones |
| A half-billion instruction model, local | a bigger server | no examples | better |
| Gemini, hosted | about $0.03 per user per month | nothing | best |

**Recommendation.** Go small. The menu is only fifteen rooms and the
sentences people type to an email assistant are short. Small keeps the
person's words on our server, costs nothing per message, and reuses models
we have already trained once. Gemini stays for drafting replies, where
writing quality matters.

**How to decide honestly.** Write 50 real test sentences with the correct
answer for each. Run all three. Pick the smallest that scores well enough
(above about 90 percent on choosing the right room). This is why it is
parked: choosing by measurement, not by opinion.

**If sir asks "why not just use Gemini for the chat, it is cheap?"** Cost is
not the reason. Privacy and dependency are: the person's typed words would
leave our server on every turn, and the feature would stop if Google did.
The test decides; if small scores badly, we move up one size.

**If he asks "does it handle any sentence?"** It handles the sentences the
product is for. Two-part sentences get a question back. Questions with no
room behind them, like "why is Ali angry", get "I can't do that yet" rather
than an invented answer.

---

## 5 · The use cases

50 use cases from Umar's documents, in `docs/use-cases-in-brief.md` (one to
three lines each) and `docs/Custodian-Use-Case-Review.pdf` (full review).

| Status | Count | Which |
|---|---|---|
| Built, run on the test mailbox | 40 | all the features |
| Partly | 7 | Outlook, Yahoo, Zoho, iCloud flows (untested), calendar (Google only), provider sign-in, data move |
| Not built | 3 | billing: subscription, change plan, cancel |

The full table with a note per use case is section 1 of
`docs/Custodian-Backend-Review-Answers.pdf`.

Each feature is one script in `poc/`, callable from the terminal and from
the API: `pile.py`, `brand.py`, `unsubscribe.py`, `storage.py`,
`spam_rescue.py`, `remind.py`, `important.py`, `asks.py`, `people.py`,
`forward_batch.py`, `rules.py`, `threads.py`, `catchup.py`, `today.py`,
`cleanup.py`, `digest.py`, `voice.py`, `calendar_sync.py`.

---

## 6 · Tests and proofs

Every proof run is saved as text in `poc/test_runs/` with its date.

| Script | Proves | Output |
|---|---|---|
| `poc/audit_imap.py` | 47 IMAP operations on the live mailbox, inbox count unchanged before and after | `audit_imap_*.txt` |
| `poc/verify_doc.py` | Umar's IMAP-vs-API document, 16 claims checked | `verify_doc_*.txt` |
| `poc/limits_imap.py` | IMAP rate and connection limits, 2.3 percent of the daily cap used | `limits_imap_*.txt` |
| `poc/auth_smoke.py` | Accounts flow, 14 steps | `auth_smoke_*.txt` |
| `poc/api_smoke.py` | Routes respond, gate refuses without a token | run it live |
| `poc/mailbox_smoke.py` | Per-user mailbox from the vault, second account refused | `mailbox_smoke_*.txt` |
| `poc/worker.py --once` | One pass of the worker: 3 older messages, 0 errors | run it live |

The IMAP tests are written up step by step in `docs/Custodian-IMAP-Tests.pdf`.

---

## 7 · The documents

| File | What it is | Sent to sir? |
|---|---|---|
| `docs/Custodian-Backend-Design-v0.1.pdf` | The design draft: requirements, components, flows, DB layout, resources, decisions | yes, day 2 |
| `docs/Custodian-Backend-Review-Answers.pdf` | His four questions answered: coverage, schema per customer, API vs own servers, full schema | yes, day 4 |
| `docs/Custodian-Backend-Design-v0.2.pdf` | v0.1 with the answers merged in | no |
| `docs/API.md` | The route contract for the frontend | not yet; send to Umar |
| `docs/Custodian-IMAP-Tests.pdf` | The IMAP proof, six steps | earlier |
| `docs/Custodian-Use-Case-Review.pdf` | All 50 use cases explained, problems, verdicts | earlier |
| `docs/Custodian-Doc1-Components.pdf`, `Doc2-Technology.pdf`, `Doc3-Code.pdf` | The POC described three ways | earlier |
| `docs/use-cases-in-brief.md` | 50 use cases in one to three lines each | no |

---

## 8 · Costs and resources, the numbers to remember

| Users | Servers | Monthly total |
|---|---|---|
| 10 | one 4 vCPU / 8 GB | about €15 |
| 100 | same one server | about €50 |
| 1,000 | three servers | about €350 |
| 10,000 | about 24 servers | about €3,000 |

Assumptions: 120 emails per user per day, 70 percent settled by rules,
about 26 Gemini calls per user per day. The two local models are a fixed
cost of about 3 GB of memory. What grows with users is Gemini (about $0.19
per user per month) and watching mailboxes (one worker server per 500 users
while polling; push would cut that).

Proposed start: one €11 server in Singapore, Neon free tier, Gemini free
tier, a free email tier for confirmations, bodies kept 30 days. About €11 to
15 a month until roughly 25 users.

---

## 9 · Honest limits: say these before he finds them

- Only Gmail is tested. Yahoo, Zoho, iCloud should work over standard IMAP
  but have not been tried. Outlook needs a Microsoft app registration.
- No confirmation emails are sent yet; tokens come back in the response.
- The chat has no API route; a terminal prototype only.
- Search covers sender, subject and date, not message text.
- IMAP cannot push or snooze; the worker polls every 20 seconds.
- Nothing is deployed. Everything runs on your laptop and the Neon database.
- The Neon database is in US East, far from Pakistan; a query can take 1 to
  3 seconds. Moving it to Singapore is proposed, not done.
- Billing (3 use cases) is not started.
- The one-schema-per-customer design is fine to a few thousand customers
  and needs revisiting at 10,000 (160,000 tables).

---

## 10 · Questions he is likely to ask, with short answers

**"How does a new email get processed?"** Worker notices it, connector
fetches headers over IMAP, store saves, pipeline runs 16 stages, label
applied, decision and reason recorded, screen reads it via the API.

**"Where does the AI run?"** Two small models on our server for classifying
and for hiding names. Gemini, hosted, for reading requests and drafting,
and only on redacted text.

**"Why IMAP and not the Gmail API?"** One door for every provider, no
Google approval, and everything tested works except push and snooze.

**"How do you stop it from deleting or sending by mistake?"** The gate.
Two calls: preview with exact wording and a token, then action with the
token. The server refuses without it. Nothing is ever deleted, trash is a
move.

**"How is one customer's data kept from another's?"** One private schema
per customer in Postgres. The connection is pointed at the customer's
schema from the session. There is no query that takes a customer id from
the caller.

**"Where are passwords kept?"** Account passwords: hashed, never stored.
Mailbox app passwords: encrypted in their own table, key only in the
server's environment, verified against the mail server before storing.

**"What happens when a user connects their mailbox?"** Address typed, the
backend says which provider and which route. Password pasted, the backend
checks its shape, logs in for real, stores it encrypted, records the
mailbox and what the server can do. The worker starts reading it on its
next pass.

**"How did you test the per-user connections without a second user?"** The
test script creates a throwaway second account, runs the checks, and
deletes it. Only my mailbox is real.

**"How many use cases are done?"** 40 built, 7 partly, 3 billing not
started.

**"What does it cost?"** About €15 a month to start, about €0.30 per user
per month at scale. Small models ours, Gemini hosted; that mix is the
cheapest.

**"Can I see it?"** Yes: see part 11.

**"What is not done?"** Part 9, say it before he asks.

**"What is next?"** Deploy to one small server in Singapore, connect the
email service for confirmations, write the 50-sentence chat test and build
the chat route on whichever model passes, try the other providers.

**"Where is the chat?"** A terminal prototype exists and works with the
gate. The website route is parked until the model is chosen by a
50-sentence test. Recommendation is our own small models, retrained.

---

## 11 · If he wants to see it live

Open PowerShell. Every command starts from the same folder.

```
cd c:\mob_ai\poc
```

| To show | Run | What appears |
|---|---|---|
| The worker noticing mail | `python worker.py` then email yourself | "1 new" within 20 seconds; Ctrl+C to stop |
| The accounts flow | `python auth_smoke.py` | 14 lines, all expected codes |
| Per-user mailbox from the vault | `python mailbox_smoke.py` | connect 200, spam route 200 from the vault, other account 409 |
| The gate refusing | `python api_smoke.py` | 409 on every action without a token |
| Today's list | `python today.py` | the ordered list |
| The pile | `python pile.py` | senders grouped with counts and reasons |
| Requests found | `python asks.py` | who asked what, by when |
| The chat prototype | `python chat.py` | type a sentence |
| The API itself | `python api.py` then open http://localhost:8000/docs | every route, clickable |

The repository: https://github.com/YaHyA-MaTeeN/custodian. The design
draft he has: `docs/Custodian-Backend-Design-v0.1.pdf`. His answers:
`docs/Custodian-Backend-Review-Answers.pdf`.
