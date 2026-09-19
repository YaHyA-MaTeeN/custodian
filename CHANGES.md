# Custodian — everything changed in this chat

18–19 September 2026 · project folder `C:\mob_ai`

---

## In one paragraph

We designed the full Custodian web app, then built it for real on top of your working POC. The POC had no way for a website to talk to it, so a new file (`poc/api.py`) was added to serve your existing database and pipeline as data, and a new website (`web/`) was built to show it. Nothing in your existing POC logic was rewritten. After you ran it, three problems came up and were fixed: it couldn't tell you why the mailbox wasn't connecting, it crashed on your real 7,391-message database, and it needed to run on port 3001.

---

## 1. The design

A design canvas called **"Custodian — web app"** with 11 screens, built with your project's own colours and IBM Plex fonts:

| Row | Screens |
|---|---|
| Marketing & onboarding | Landing page · Connect a mailbox · Tone & WhatsApp |
| Daily workflow | Dashboard · Unified inbox · Deadline radar |
| Control & trust | Backlog cleanup · Rules · Activity |
| Reaching you & your data | Weekly digest · Privacy & data |

This lives in Claude as an artifact (claude.ai/code/artifacts), **not** as a file on your computer.

---

## 2. New files on your computer

### `C:\mob_ai\poc\api.py` — new

The data half. It reads your existing `mailbox.db` and pipeline and hands it to the website. It reuses your own code rather than copying it — for example, deciding what kind of email something is calls straight into `web.py`'s own `classify()`.

What it offers:

| Address | What it does |
|---|---|
| `GET /api/health` | Is it running, is the mailbox open, basic counts |
| `GET /api/accounts` | Every mailbox the database has seen |
| `GET /api/overview` | Everything the dashboard shows |
| `GET /api/messages` | The inbox list — filters and search |
| `GET /api/messages/{id}` | One email, with its recorded decisions |
| `POST /api/messages/{id}/score` | Run the pipeline on one email (never drafts, never sends) |
| `GET /api/deadlines` | Reminders and snoozes, sorted by how soon |
| `POST /api/deadlines/{id}/dismiss` | Stop warning about one |
| `GET /api/cleanup` | Junk grouped by sender |
| `GET` / `POST /api/rules` | List or add a correction |
| `DELETE /api/rules/{id}` | Remove a correction |
| `GET /api/activity` | The full action log |
| `POST /api/activity/{id}/undo` | Put one action back |
| `GET /api/digest` | What a digest message would say |
| `GET /api/privacy` | Row counts behind the privacy claims |
| `POST /api/privacy/export` | Write everything held to a JSON file |

Deliberately **not** included: no send, no erase, no delete. Sending belongs on WhatsApp approval; erasing stays at the keyboard (`python my_data.py --erase`); deleting mail stays with you in Gmail.

Options: `python api.py --no-mailbox` (database only), `--port 8100`, `--imap` / `--api` (choose the door).

### `C:\mob_ai\web\` — new (23 files)

The pages half, built with Next.js and TypeScript.

| Page | Address |
|---|---|
| Dashboard | `/` |
| Unified inbox | `/inbox` |
| Deadline radar | `/deadlines` |
| Backlog cleanup | `/cleanup` |
| Rules | `/rules` |
| Activity & undo | `/activity` |
| Digest | `/digest` |
| Privacy & data | `/privacy` |
| Mailboxes | `/connect` |
| Public landing page | `/welcome` |

Files: `package.json`, `tsconfig.json`, `next.config.mjs`, `.env.example`, `README.md`, `app/` (globals.css, layout.tsx and one `page.tsx` per page), `components/` (AppShell, Icons, States), `lib/` (api, format, types).

Two screens from the design were not built: the onboarding pairing screen and the WhatsApp phone mockup, because the POC signs in at the terminal and has no WhatsApp channel yet. `/connect` shows the real connection instead.

### `C:\mob_ai\start-custodian.bat` — new

Double-click to start everything. Opens the API window, the website window (on **port 3001**, because 3000 is your other site), and the browser.

---

## 3. Existing files changed

| File | Change |
|---|---|
| `poc/requirements.txt` | Added two lines at the end: `fastapi` and `uvicorn` |

**Nothing else in your POC was edited.** `web.py`, `store.py`, `connect.py`, `agent.py`, the connectors and the pipeline are exactly as they were. `mailbox.db` was only read, never written, apart from the normal rows the app records when you use Rules, Undo or Dismiss.

---

## 4. Fixes made after you ran it

| Problem you saw | Cause | Fix |
|---|---|---|
| "Cannot reach the Custodian API" | Only the website was running, not the API | Explained; added `start-custodian.bat` to start both |
| Sidebar said "database only" with no reason | The API hid the connection result | API now prints `mailbox : … via …` or `COULD NOT OPEN — reason` at startup, and retries a failed connection after 30 seconds instead of never |
| Crash: `sqlite3.InterfaceError: bad parameter or other API misuse` | Several requests shared one database connection at once; only shows up on a large database | Requests now take turns. Tested with 15 at once on your real database: all succeeded |
| Port 3000 already in use | Your other site | Website now runs on 3001 |

Fixed before you ever saw them: a dashboard chip reading "undefined days", and the API refusing the website if it ran on any port other than 3000.

---

## 5. Things you did on your machine

- Installed `fastapi` and `uvicorn` with pip
- Deleted `poc/token.json` (the Gmail API sign-in, which had expired)

Because `token.json` is gone and `IMAP_PASSWORD` is set, the POC now connects through **IMAP** as login47015@gmail.com. That works and doesn't expire. To go back to the Gmail API door: `python inbox.py --api`.

Cleaned up: the temporary `_scratch` and `_tmp_export` folders created during the work were deleted.

---

## 6. Things learned along the way

- **The 7-day token expiry is real.** Your token was written 11 September and died 18 September. This answers open question #5 in `docs/CONTEXT.md`: pilot users on the Gmail API door will need to reconnect weekly until the app is published.
- **`connectors/gmail.py` line 67 crashes instead of re-asking** when the token dies, because `creds.refresh()` isn't wrapped. A three-line fix was offered, not made.
- **Multi-mailbox is only half live.** Every email records its account and the inbox merges them, but the API opens one mailbox at a time, so live opening and undo only work for the signed-in account.
- **The website does not fetch new mail.** New mail arrives when you run `python scan.py`, `python agent.py`, or `python web.py --watch --port 8001`.

---

## 7. How to run it

Double-click `C:\mob_ai\start-custodian.bat`.

Or by hand, in two windows:

```
cd C:\mob_ai\poc
python api.py
```
```
cd C:\mob_ai\web
npm run dev -- -p 3001
```

Then open http://localhost:3001. Both windows must stay open.

---

## 8. Not done / possible next steps

- Wrap the token refresh in `gmail.py` so an expired sign-in re-prompts instead of crashing
- `python api.py --watch`, so new mail flows in without a third window
- Real multi-mailbox: one connection per account
- A login, before this ever runs anywhere but your own computer
- The mobile-only changes to builds / answer keys / AI scoring — those belong to a different project not connected to this chat
