# Custodian backend — status

26 September 2026. One page. Every line has a file or a saved test run behind
it; paths are in the repo, https://github.com/YaHyA-MaTeeN/custodian

## Where it stands

A working backend for Gmail users. A person signs up, gets a confirmation
email, connects a mailbox, and from then on the worker reads and labels their
mail every 20 seconds. Every feature is a route the frontend calls, and every
feature can also be reached by typing, through the chat. Nothing irreversible
happens without the person confirming the exact wording.

| Area | State | Proof |
|---|---|---|
| Use cases | 40 of 50 built, 7 partly, 3 billing not started | `docs/Custodian-Backend-Review-Answers.pdf` §1 |
| Accounts | sign-up, confirmation email, login, logout, reset | `poc/test_runs/auth_smoke_*`, `mail_smoke_*` |
| Database | Postgres, one schema per customer, test data migrated | `poc/db/schema.sql`, `docs/Custodian-Backend-Review-Answers.pdf` §4 |
| API | 83 routes, confirm gate on every irreversible action | `poc/api_smoke.py` |
| Per-user mailboxes | each account opens its own mailbox from the encrypted vault | `poc/test_runs/mailbox_smoke_*` |
| Worker | always on, reads and labels, never sends or clears | `poc/worker.py` |
| Chat | one route, every feature reachable by typing; 22 real sentences tested | `poc/test_runs/chat_smoke_*` |
| IMAP | 47 operations proven on a live mailbox | `docs/Custodian-IMAP-Tests.pdf` |
| Frontend fit | the 30 designed screens checked route by route; all map except billing | `docs/API.md` |

## Documents

| Need | File |
|---|---|
| The design you reviewed | `docs/Custodian-Backend-Design-v0.1-as-sent.pdf` |
| Current design, your four answers merged in | `docs/Custodian-Backend-Design.pdf` |
| Your four questions, answered | `docs/Custodian-Backend-Review-Answers.pdf` |
| Route contract for the frontend | `docs/API.md` |
| How to run it | `README.md` |
| All 50 use cases, one line each | `docs/use-cases-in-brief.md` |

## Decisions needed

| Decision | From | Unblocks |
|---|---|---|
| Microsoft app registration under our Microsoft 365 (15 minutes, free); only the client ID is needed back | our Microsoft 365 admin | Outlook |
| Payment provider | you | billing: UC-03, 48, 49 |
| Hosting region (proposal: Singapore, one small server, about €15 a month to start) | you | deployment |
| One test address each for Yahoo, Zoho, iCloud | anyone | testing those three providers |
