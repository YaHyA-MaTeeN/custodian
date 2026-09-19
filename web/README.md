# Custodian — the web app

The screens that sit on top of the POC pipeline. Two processes, one machine:

    poc/api.py    JSON over the existing database, pipeline and connectors
    web/          Next.js app that reads that JSON

Nothing here re-decides anything. Every reason you see on a screen was written
by the pipeline at the moment it decided, and `api.py` calls straight into
`web.py`'s own `classify()` rather than keeping a second copy of that logic.

---

## Running it

**1 — the API** (from the `poc` folder, where `mailbox.db` lives):

```bash
pip install fastapi uvicorn
python api.py                 # http://127.0.0.1:8000, opens the mailbox
python api.py --no-mailbox    # database only — no token, no network needed
python api.py --port 8100
```

Interactive docs are at `http://127.0.0.1:8000/docs`.

**2 — the web app** (from the `web` folder):

```bash
npm install
npm run dev                   # http://localhost:3000
```

If the API is on a different port, point the app at it:

```bash
# web/.env.local
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8100
```

For a production build: `npm run build && npm start`.

---

## The screens

| Route | What it shows | Reads |
|---|---|---|
| `/` | Dashboard — what was handled, what needs you, what is due | `/api/overview` |
| `/inbox` | One merged list across every account, with the reason on every row, plus the decisions recorded for the message you open | `/api/messages` |
| `/deadlines` | Commitments with a date, grouped by how close they are | `/api/deadlines` |
| `/cleanup` | The backlog grouped by sender — one decision per sender | `/api/cleanup` |
| `/rules` | Corrections. These are the settings; there is no preferences screen | `/api/rules` |
| `/activity` | Every action in plain words, with undo where undo is possible | `/api/activity` |
| `/digest` | What one digest message would say, if it were due now | `/api/digest` |
| `/privacy` | Row counts behind the privacy claim, and what has left the machine | `/api/privacy` |
| `/connect` | Which door is open, what it can do, what the permission allows | `/api/health` |
| `/welcome` | The public page | — |

---

## Three things the app deliberately cannot do

**It cannot send.** There is no send endpoint and no send button. Approval for
anything that leaves under the Owner's name belongs on WhatsApp, where the
person actually is; a second approval surface here would be a second place for
a wrong yes to happen.

**It cannot erase.** `POST /api/privacy/export` exists, erasure does not. An
erasure request is exactly what an attacker would send and a web page cannot
tell who is on the other end of it, so it stays at the keyboard:
`python my_data.py --erase`.

**It cannot delete mail.** Cleanup groups senders so one decision clears many
messages. The deleting stays with you, in your own mailbox.

---

## Notes for whoever picks this up next

- **The API starts without a mailbox.** Every screen except opening an old
  message answers out of SQLite, so `--no-mailbox` gives you a working app with
  no token, no network and no Gmail — which is also how it is tested.
- **One IMAP conversation at a time.** Anything that touches the connector goes
  through a lock. Two threads sharing one IMAP connection does not produce
  slow, it produces corrupt.
- **Counts travel with their denominator.** "0 need a reply" and "nothing has
  been scored yet" are different facts, and the dashboard says which one it is.
- **Moving to Postgres changes nothing here.** The API talks to `Store`, and
  `Store` is the only thing that knows it is SQLite today.
