# How to run

Windows, Python 3.12. All commands from the `poc` folder.

## 1. Install

```
cd poc
pip install -r requirements.txt
```

## 2. Set three things (once, then reopen the terminal)

```
setx IMAP_USER "test-mailbox@gmail.com"
setx IMAP_PASSWORD "the 16-character Gmail app password"
setx GEMINI_API_KEY "key from aistudio.google.com/apikey"
```

The app password comes from Google Account → Security → 2-Step Verification
→ App passwords. Never a normal password.

## 3. Run

```
python scan.py              read the mailbox once (a few minutes)
python api.py --port 8000   start the backend
```

Open http://localhost:8000/docs to see and try every route.

To keep reading new mail in the background, in a second terminal:

```
python worker.py
```

## 4. Check it works

```
python api_smoke.py         routes answer; permanent actions refuse without a yes
python chat_smoke.py        22 sentences through the chat
python calendar_smoke.py    calendar, no setup needed
```

## Multi-user mode (optional)

Needs a Postgres database. Set two more things, then create the tables:

```
setx DATABASE_URL "postgresql://..."
setx CUSTODIAN_SECRET "<run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">"
python db/migrate.py
```

Now every route needs a login. Tests for this mode: `auth_smoke.py`,
`mail_smoke.py`, `mailbox_smoke.py`, `billing_smoke.py`.

More detail: `HANDOVER.md`. Every route: `docs/API.md`.
