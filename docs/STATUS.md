# Custodian backend — status

26 September 2026. Everything below is tested, and the test outputs are saved
in the repo.

## Where it stands

A working backend for Gmail users. A person signs up, gets a confirmation
email, connects a mailbox, and from then on the worker reads and labels their
mail every 20 seconds. Every feature is a route the frontend calls, and every
feature can also be reached by typing, through the chat. Nothing irreversible
happens without the person confirming the exact wording.

| Area | State |
|---|---|
| Use cases | 40 of 50 built, 7 partly, 3 billing not started |
| Accounts | sign-up, confirmation email, login, logout, reset; tested end to end |
| Database | Postgres, one private schema per customer, test data migrated |
| API | 83 routes; every irreversible action needs the person's confirmation |
| Per-user mailboxes | each account opens its own mailbox with its own encrypted password; tested with two accounts |
| Worker | always on, reads and labels, never sends or clears |
| Chat | one route, every feature reachable by typing; 22 real sentences tested |
| IMAP | 47 operations proven on a live mailbox |
| Frontend fit | the 30 designed screens checked against the API; all map except billing |

## Documents in the repo

- The design you reviewed, and the current version with your four answers merged in
- Your four questions, answered
- The route contract the frontend is built against
- A README on how to run it
- All 50 use cases, one line each

## Decisions needed

| Decision | From | Unblocks |
|---|---|---|
| Microsoft app registration under our Microsoft 365 (15 minutes, free); only the client ID is needed back | our Microsoft 365 admin | Outlook |
| Payment provider | you | billing |
| One test address each for Yahoo, Zoho, iCloud | anyone | testing those three providers |
