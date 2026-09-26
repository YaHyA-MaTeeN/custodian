# Custodian backend — status

One page. Updated 26 September 2026. Everything here has a file or a saved
test run behind it; paths are relative to the repo root.

## Where it stands

A working backend for Gmail users, on one laptop plus a hosted Postgres.
Sign-up with a real confirmation email, connect a mailbox, and from then on
the worker reads and labels mail every 20 seconds. Every feature is a route
the frontend calls. Nothing irreversible happens without the person
confirming the exact wording. Repo: https://github.com/YaHyA-MaTeeN/custodian

| Area | State | Proof |
|---|---|---|
| Use cases | 40 of 50 built, 7 partly, 3 billing not started | `docs/Custodian-Backend-Review-Answers.pdf` §1 |
| Accounts | sign-up, confirmation email, login, logout, reset | `poc/test_runs/auth_smoke_*`, `mail_smoke_*` |
| Database | Postgres on Neon, one schema per customer, data migrated | `poc/db/schema.sql`, `docs/Custodian-Backend-Review-Answers.pdf` §4 |
| API | 82 routes, confirm gate on every irreversible action | `poc/test_runs/`, `python api_smoke.py` |
| Per-user mailboxes | opened from the encrypted vault, pooled | `poc/test_runs/mailbox_smoke_*` |
| Worker | always on, reads and labels, never sends or clears | `python worker.py --once` |
| IMAP | 47 operations proven on a live mailbox | `docs/Custodian-IMAP-Tests.pdf` |
| Frontend fit | Umar's 30 screens checked route by route; all map except billing | `docs/API.md` |

## Documents, and which one to open

| Need | File |
|---|---|
| The design sir reviewed | `docs/Custodian-Backend-Design-v0.1-as-sent.pdf` |
| Current design (v0.1 + his four answers merged) | `docs/Custodian-Backend-Design.pdf` |
| His four questions, answered separately | `docs/Custodian-Backend-Review-Answers.pdf` |
| Route contract for the frontend | `docs/API.md` |
| Plain-words guide to everything, with likely questions | `docs/BRIEFING.md` |
| How to run it | `README.md` |
| All 50 use cases in one line each | `docs/use-cases-in-brief.md` |

## Waiting on decisions

| Decision | Whose | Blocks |
|---|---|---|
| Microsoft app registration under OCloud's Microsoft 365 (15 min, free); only the client ID is needed back | OCloud admin | Outlook |
| Payment provider | sir | billing: UC-03, 48, 49 and four frontend screens |
| Hosting region (proposal: Singapore, one €11 server, about €15/month to start) | sir | deployment |
| Test addresses for Yahoo, Zoho, iCloud | anyone | moving those three from "partly" to "tested" |

## Next, in order

1. Deploy to one small server once the region is agreed.
2. Chat: 50-sentence test set, pick the model, add the route.
3. Outlook test the day the client ID arrives.
4. Billing once a provider is chosen.

## Known limits, stated

Only Gmail tested among providers. Search covers sender, subject and date,
not message text. IMAP cannot push or snooze; the worker polls. The
confirmation sender is a Gmail mailbox on the free tier for now. The
one-schema-per-customer layout needs revisiting around 10,000 customers.
