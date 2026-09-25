# Custodian — backend

The server side of an email assistant: reads a person's mailbox over IMAP,
sorts and labels it, and exposes every feature as a JSON API for the web
frontend. Nothing is ever deleted, and nothing irreversible happens without
the person confirming the exact wording.

- API contract for the frontend: [`docs/API.md`](docs/API.md)
- Design: [`docs/Custodian-Backend-Design-v0.1.pdf`](docs/Custodian-Backend-Design-v0.1.pdf)
- Plain-words guide to everything: [`docs/BRIEFING.md`](docs/BRIEFING.md)

## Run it locally in single-user mode (what the frontend needs)

Single-user mode uses one Gmail mailbox and a local SQLite file. No accounts,
no sign-in: every route serves that one mailbox. Good enough to build every
screen against.

1. Python 3.12. Then, from the repo root:
   ```
   cd poc
   pip install -r requirements.txt
   ```
2. A Gmail **app password** for a test mailbox (Google Account → Security →
   2-Step Verification on → App passwords). Never a normal password.
3. A free Gemini key from https://aistudio.google.com/apikey.
4. Set them once, in PowerShell, then reopen the terminal:
   ```
   setx IMAP_USER "the-test-address@gmail.com"
   setx IMAP_PASSWORD "the 16 character app password"
   setx GEMINI_API_KEY "the key"
   ```
5. Index the mailbox once (a few minutes for a big one):
   ```
   python scan.py
   ```
6. Start the API:
   ```
   python api.py --port 8000
   ```
   Open http://localhost:8000/docs for every route, clickable. Any
   `http://localhost:<port>` origin is allowed, so the frontend runs on any port.

The two local models (`classifier/`, `pii_model/`) are not in the repo; without
them the pipeline uses Gemini for classification, which is fine for frontend work.

## Accounts mode (multi-user, Postgres)

Set `DATABASE_URL` (Postgres) and `CUSTODIAN_SECRET` (a Fernet key), run
`python db/migrate.py`, and every route needs `Authorization: Bearer <token>`
from `/api/auth/login`. Details in `docs/API.md`, section "Session and account".

## Proofs

Every test writes its output to `poc/test_runs/`. From `poc/`:

| script | proves |
|---|---|
| `python api_smoke.py` | read routes answer; every gated action refuses without its confirm token |
| `python auth_smoke.py` | sign-up → confirm → login → logout → reset, 14 steps (accounts mode) |
| `python mail_smoke.py` | a real confirmation email arrives and its link confirms the account |
| `python mailbox_smoke.py` | each account opens its own mailbox from the vault; another account is refused |
| `python audit_imap.py` | 47 IMAP operations on the live mailbox, inbox count unchanged |
| `python worker.py --once` | one pass of the always-on worker |

## Never in this repo

`credentials.json`, `token.json`, `settings.json`, `mailbox.db`, model folders,
`test_runs/`, and any password or key. All of those come from the environment.
