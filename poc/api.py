"""
The JSON door.

    pip install fastapi uvicorn
    python api.py                 # http://127.0.0.1:8000
    python api.py --no-mailbox    # database only, no mailbox connection
    python api.py --port 8100

⚠️ WHY THIS EXISTS, NEXT TO web.py AND NOT INSTEAD OF IT.

web.py renders HTML for a person. This renders JSON for the web app in ../web.
Same database, same pipeline, same decisions — a second presentation, never a
second opinion. Where a judgement is needed about a message, this file calls
straight into web.py's own classify(), because two copies of that logic would
eventually disagree and nobody would know which screen was right.

⚠️ IT READS. THE FEW THINGS IT WRITES ARE THE ONES A HUMAN JUST ASKED FOR.

Corrections (UC-29) and undo (UC-30) write, because the Owner pressed
something. Nothing here sends mail, and there is no code path that could:
the send functions are not imported. BR-91 is kept by absence, not by a flag.

⚠️ THE MAILBOX CONNECTION IS OPTIONAL AND LAZY.

Everything except opening one old message answers out of SQLite. So the API
starts, and stays up, with no network, no token and no Gmail — which is also
what makes it testable. A connector is opened on first real need and reused.
"""

import argparse
import json
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError:                                    # pragma: no cover
    sys.exit("\n  FastAPI is not installed.\n\n    pip install fastapi uvicorn\n")

import connect
import web                        # ⚠️ for its classify() — see the header
from store import Store

WINDOW_DAYS = 30

STORE: Store | None = None
CONN = None
CONN_TRIED = False
CONN_TRIED_AT = 0.0
CONN_ERROR = ""
NO_MAILBOX = False
_LOCK = threading.Lock()          # one IMAP conversation, one thread at a time


# ══════════════════════════ wiring ══════════════════════════


def store() -> Store:
    global STORE
    if STORE is None:
        STORE = Store()
        STORE.trim_bodies(WINDOW_DAYS)      # retention runs on start, as in web.py
        web.STORE = STORE                   # classify() reads through this
    return STORE


def conn(required: bool = True):
    """
    Open the mailbox on first need, once, and remember the failure too.

    ⚠️ A failed connection is cached deliberately. Retrying an expired token on
    every request turns one broken login into a hundred slow ones, and the
    Owner still sees the same error at the end of it.
    """
    global CONN, CONN_TRIED, CONN_ERROR
    if NO_MAILBOX:
        if required:
            raise HTTPException(503, "started with --no-mailbox: no mailbox is open")
        return None
    import time
    global CONN_TRIED_AT
    if CONN is None and (not CONN_TRIED or time.time() - CONN_TRIED_AT > 30):
        CONN_TRIED = True
        CONN_TRIED_AT = time.time()
        try:
            CONN = connect.open_mailbox(quiet=True)
            web.CONN = CONN
            CONN_ERROR = ""
        except Exception as e:
            CONN_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
    if CONN is None and required:
        raise HTTPException(503, f"no mailbox connection: {CONN_ERROR or 'not opened'}")
    return CONN


app = FastAPI(title="Custodian API", version="0.1.0",
              description="JSON over the Custodian POC. Reads the same database "
                          "and the same pipeline decisions the terminal does.")

# The web app is served from another port on the same machine.
#
# ⚠️ Any localhost port, not port 3000 only. Next picks 3001 by itself when
# 3000 is busy, and a hard-coded port turns that into a browser CORS error
# that names neither the cause nor the fix. The regex still refuses every
# origin that is not this machine.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def one_request_at_a_time():
    """
    ⚠️ ONE SQLite CONNECTION MEANS ONE REQUEST AT A TIME.

    Store opens a single connection and every endpoint shares it. FastAPI runs
    sync endpoints in a thread pool, so a dashboard that fetches three things
    at once had three threads inside one connection — which SQLite reports as
    "bad parameter or other API misuse", from whichever call happened to be
    unlucky. It never appeared in testing because a ten-message database
    finishes before the second thread arrives; a 7,000-message one does not.

    Capping the pool at one thread serialises every request behind the
    connection they all share. For a local, single-user app reading SQLite
    that is the honest shape of the thing — the same reason the mailbox is
    already behind a lock. The day this moves to Postgres, a connection pool
    replaces this line.
    """
    try:
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = 1
    except Exception as e:                                   # pragma: no cover
        print(f"  note: could not serialise requests ({e}) — "
              f"expect intermittent database errors under load")


# ══════════════════════════ shared shapes ══════════════════════════


def iso(v) -> str:
    """RFC date or ISO date in, something a browser can parse out, or ''."""
    if not v:
        return ""
    try:
        return datetime.fromisoformat(str(v)[:19]).isoformat()
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(str(v))
            return d.replace(tzinfo=None).isoformat()
        except Exception:
            return ""


def inbox_rows(limit: int = 300) -> list:
    """
    The inbox, newest first, one row per message.

    ⚠️ BR-99 — a message that reached two of the Owner's addresses is shown
    once. web.rows() already does that de-duplication, so it is called rather
    than repeated here.
    """
    web.STORE = store()
    rows = web.rows(limit=limit)
    s = store()
    if hasattr(s, "prefetch"):               # Postgres: bulk-load what classify() asks per row
        me = ""
        try:
            c = conn(required=False)
            me = c.account_email() if c else ""
        except Exception:
            pass
        s.prefetch(rows, me)
    return rows


def row_to_dict(r, held: bool | None = None) -> dict:
    (mid, pid, sender, sname, subject, date, unread,
     account, auto_sub, unsub, bulk, cats) = r
    kind, why = web.classify(r)
    return {
        "id": pid,
        "messageId": mid or "",
        "account": account or "",
        "sender": sender or "",
        "senderName": sname or "",
        "subject": subject or "",
        "date": iso(date),
        "dateRaw": str(date or ""),
        "unread": bool(unread),
        "kind": kind,                       # reply | filed | machine | dormant | private | unseen
        "why": why,
        "held": store().has_body(mid) if held is None else held,
        "unsubscribe": bool(unsub),
        "categories": [c for c in (cats or "").split(",") if c],
    }


# ══════════════════════════ what is connected ══════════════════════════


@app.get("/api/health")
def health():
    """Is anything listening, and what can the mailbox behind it do."""
    s = store()
    c = conn(required=False)
    caps = {}
    if c is not None:
        for name in ("supports_push", "supports_labels", "supports_categories",
                     "supports_threads", "supports_search"):
            caps[name.replace("supports_", "")] = bool(getattr(c, name, False))
    return {
        "ok": True,
        "mailbox": {
            "connected": c is not None,
            "account": c.account_email() if c is not None else "",
            "door": getattr(c, "name", "") if c is not None else "",
            "capabilities": caps,
            "error": CONN_ERROR,
            "disabled": NO_MAILBOX,
        },
        "counts": {
            "messages": s.one("SELECT COUNT(*) FROM messages"),
            "bodies": s.body_stats()["count"],
            "decisions": s.one("SELECT COUNT(*) FROM decisions"),
            "corrections": s.one("SELECT COUNT(*) FROM corrections"),
            "actions": s.one("SELECT COUNT(*) FROM actions"),
        },
        "retentionDays": WINDOW_DAYS,
    }


@app.get("/api/accounts")
def accounts():
    """
    Every mailbox the database has seen mail from (UC-27, BR-98).

    The POC signs in to one at a time; the shape is already plural because the
    product is, and a screen written against a single account would have to be
    rewritten the day the second one connects.
    """
    s = store()
    live = conn(required=False)
    live_addr = live.account_email().lower() if live is not None else ""
    out = []
    for acct, n, last in s.q(
            "SELECT COALESCE(NULLIF(account,''),'unknown'), COUNT(*), "
            "MAX(COALESCE(NULLIF(date_iso,''), date)) "
            "FROM messages GROUP BY 1 ORDER BY 2 DESC"):
        out.append({
            "account": acct,
            "messages": n,
            "lastSeen": iso(last),
            "live": acct.lower() == live_addr,
            "door": getattr(live, "name", "") if acct.lower() == live_addr else "",
        })
    return {"accounts": out}


# ══════════════════════════ the dashboard ══════════════════════════


@app.get("/api/overview")
def overview():
    """
    Everything the home screen shows, in one request.

    ⚠️ Counts come with their denominator. "0 need a reply" is a lie by
    omission when the truth is "nothing has been scored yet" — so `scored`
    travels with `needsReply`, exactly as the HTML view does it.
    """
    s = store()
    rows = inbox_rows()
    items = [row_to_dict(r) for r in rows]

    ids = {r[0] for r in rows if r[0]}
    scored = sum(1 for m in ids if any(d[0] == "9" for d in s.decision_for(m)))

    kinds: dict[str, int] = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1

    week = (datetime.now() - timedelta(days=7)).isoformat()
    handled_week = s.one("SELECT COUNT(*) FROM actions WHERE at > ?", week)

    # ⚠️ Shaped by the same function the deadline screen uses. Built by hand
    # here once, this list came out missing `daysLeft`, and the dashboard
    # cheerfully rendered "undefined days" next to a real deadline.
    watched = [r for r in reminder_list() if not r["done"]]
    due = [r for r in watched if (r["daysLeft"] is None or r["daysLeft"] <= 0)]
    pending = [r for r in watched if r not in due]

    needs_you = [it for it in items if it["kind"] == "reply"][:6]

    return {
        "stats": {
            "headersHeld": s.one("SELECT COUNT(*) FROM messages"),
            "bodiesHeld": s.body_stats()["count"],
            "bodiesMb": round(s.body_stats()["mb"], 2),
            "needsReply": kinds.get("reply", 0),
            "scored": scored,
            "handledWithoutAsking": kinds.get("machine", 0) + kinds.get("dormant", 0),
            "actionsThisWeek": handled_week,
            "decisions": s.one("SELECT COUNT(*) FROM decisions"),
            "corrections": s.one("SELECT COUNT(*) FROM corrections"),
        },
        "needsYou": needs_you,
        "remindersDue": due,
        "remindersPending": pending[:6],
        "recentActivity": activity(limit=6)["actions"],
    }


# ══════════════════════════ the unified inbox (UC-27, UC-28) ═══════════


@app.get("/api/messages")
def messages(view: str = Query("all", pattern="^(all|people|reply|held|machine)$"),
             account: str = "",
             q: str = "",
             limit: int = Query(120, ge=1, le=500)):
    """
    One merged list across every account (UC-27), filtered the same four ways
    the HTML view offers, plus envelope search (UC-28, BR-102).

    ⚠️ Search is envelope-only — sender, subject, account. Searching inside
    message text would mean holding the words of every message, which is the
    open decision BR-103 parks, and this endpoint is not the place to settle it.
    """
    rows = inbox_rows(limit=400)
    items = [row_to_dict(r) for r in rows]

    if view == "reply":
        items = [i for i in items if i["kind"] == "reply"]
    elif view == "people":
        # An allow-list. Written as "not machines" it silently admits every new
        # kind of non-person nobody thought of yet.
        items = [i for i in items if i["kind"] in ("reply", "filed", "unseen")]
    elif view == "held":
        items = [i for i in items if i["held"]]
    elif view == "machine":
        items = [i for i in items if i["kind"] in ("machine", "dormant")]

    if account:
        items = [i for i in items if i["account"].lower() == account.lower()]

    if q:
        needle = q.lower()
        items = [i for i in items
                 if needle in i["subject"].lower()
                 or needle in i["sender"].lower()
                 or needle in i["senderName"].lower()
                 or needle in i["account"].lower()]

    return {"total": len(items), "view": view, "query": q,
            "messages": items[:limit]}


@app.get("/api/messages/{provider_id}")
def message(provider_id: str, fetch: bool = True):
    """
    One message, with its decisions and its reasons (BR-105, UC-29 step 1.1).

    ⚠️ Sensitive mail is refused here, not filtered in the browser. A screen
    that decides what not to show has already been sent the thing it is hiding.
    """
    s = store()
    r = s.q("""SELECT message_id, provider_id, sender, sender_name, subject,
                      COALESCE(NULLIF(date_iso,''), date), unread,
                      COALESCE(account,'?'), auto_sub, unsubscribe, bulk, categories
                 FROM messages WHERE provider_id=?""", provider_id)
    if not r:
        raise HTTPException(404, "no such message")
    row = r[0]
    out = row_to_dict(row)
    mid = row[0]

    out["decisions"] = [
        {"stage": st, "decision": dec, "reason": why, "score": sc, "at": iso(at)}
        for st, dec, why, sc, at in s.decision_for(mid)
    ]

    if out["kind"] == "private":
        out["body"] = ""
        out["bodySource"] = "never opened — sensitive by sender and subject"
        out["blocked"] = True
        return out

    out["blocked"] = False
    text = s.body(mid)
    if text:
        out["body"] = text
        out["bodySource"] = f"from the {WINDOW_DAYS}-day store — instant"
        return out

    if not fetch:
        out["body"] = ""
        out["bodySource"] = "not held — ask again with fetch=true to open it live"
        return out

    # Older than the window: fetched live, shown, and forgotten again.
    from pipeline import stage02_strip
    t0 = datetime.now()
    try:
        with _LOCK:
            raw = connect.fetch_verified(conn(), provider_id, mid)
        out["body"] = stage02_strip.strip(raw)["text"]
        out["bodySource"] = (f"fetched live in "
                             f"{(datetime.now() - t0).total_seconds():.1f}s — not stored")
    except HTTPException:
        raise
    except Exception as e:
        out["body"] = ""
        out["bodySource"] = f"could not fetch: {str(e)[:120]}"
    return out


@app.post("/api/messages/{provider_id}/score")
def score(provider_id: str):
    """
    Run the pipeline over one message, now, and return what it decided.

    ⚠️ want_draft is False and there is no parameter to change it. A web
    request has nobody at the keyboard to approve anything, and the approval
    gate does not get skipped because asking would be inconvenient — the same
    rule the background watcher in web.py lives by.
    """
    import agent
    s = store()
    c = conn()

    envs = list(c.fetch_envelopes([provider_id]))
    if not envs:
        raise HTTPException(404, "the mailbox does not know that id")
    env = envs[0]
    s.save([env])

    import contextlib
    import io
    trace = io.StringIO()
    with _LOCK, contextlib.redirect_stdout(trace):
        try:
            result = agent.run_one(c, s, env, agent.known_names(s), False, [])
        except Exception as e:
            raise HTTPException(500, f"pipeline failed: {str(e)[:200]}")

    return {
        "id": provider_id,
        "result": {k: v for k, v in (result or {}).items() if isinstance(v, (str, int, float))},
        "decisions": [
            {"stage": st, "decision": dec, "reason": why, "score": sc, "at": iso(at)}
            for st, dec, why, sc, at in s.decision_for(env.message_id)
        ],
        # The terminal trace, kept because it is the honest record of what ran.
        "trace": trace.getvalue()[-8000:],
    }


# ══════════════════════════ deadlines (UC-23, UC-24) ══════════════════════


def reminder_list() -> list[dict]:
    """
    Every reminder and snooze, shaped once.

    One shape, one place: the dashboard and the deadline screen show the same
    rows, and two builders would eventually disagree about what "soon" means.
    """
    s = store()
    now = datetime.now()
    out = []
    for mid, pid, kind, due, subject, why, done in s.q(
            "SELECT message_id, provider_id, kind, due, subject, why, done "
            "FROM reminders ORDER BY due"):
        when = None
        try:
            when = datetime.fromisoformat(str(due)[:19])
        except Exception:
            pass
        days = (when - now).days if when else None
        out.append({
            "messageId": mid, "id": pid, "kind": kind,
            "due": iso(due), "daysLeft": days,
            "subject": subject or "", "why": why or "",
            "done": bool(done),
            "urgency": ("past" if days is not None and days < 0 else
                        "today" if days == 0 else
                        "soon" if days is not None and days <= 3 else
                        "week" if days is not None and days <= 7 else "later"),
        })
    return out


@app.get("/api/deadlines")
def deadlines():
    """
    Commitments with a date, and when we mean to say something about them.

    Lead time is per kind, not a fixed offset (BR-87) — stage 16 worked it out
    when the commitment was recorded, so this only reads.
    """
    out = reminder_list()
    return {"deadlines": out,
            "due": [d for d in out
                    if not d["done"] and (d["daysLeft"] is None or d["daysLeft"] <= 0)]}


@app.post("/api/deadlines/{message_id}/dismiss")
def dismiss_deadline(message_id: str, kind: str = "remind"):
    """Stop warning about this one. Recorded, like everything else."""
    s = store()
    s.clear_reminder(message_id, kind)
    s.record_action(message_id, "", "dismiss_reminder", f"{kind} dismissed", before=kind)
    return {"ok": True}


# ══════════════════════════ cleanup (the backlog) ══════════════════════════


@app.get("/api/cleanup")
def cleanup(limit: int = Query(20, ge=1, le=100)):
    """
    The backlog, grouped by who sent it — one decision per sender, not per
    message.

    ⚠️ Nothing here deletes, and no endpoint in this file does. The product
    groups; the Owner presses delete in their own mailbox. That is sir's rule
    and it is also why every action we do take is reversible.
    """
    s = store()
    items = [row_to_dict(r) for r in inbox_rows(limit=400)]

    groups: dict[str, dict] = {}
    for it in items:
        if it["kind"] not in ("machine", "dormant"):
            continue
        key = it["sender"].lower()
        g = groups.setdefault(key, {
            "sender": it["sender"], "name": it["senderName"] or it["sender"],
            "domain": it["sender"].split("@")[-1],
            "count": 0, "kind": it["kind"], "why": it["why"],
            "unsubscribe": it["unsubscribe"], "samples": [], "accounts": set(),
        })
        g["count"] += 1
        g["accounts"].add(it["account"])
        if len(g["samples"]) < 3:
            g["samples"].append({"id": it["id"], "subject": it["subject"],
                                 "date": it["date"]})

    out = sorted(groups.values(), key=lambda g: -g["count"])[:limit]
    for g in out:
        g["accounts"] = sorted(a for a in g["accounts"] if a)

    return {
        "groups": out,
        "totalGrouped": sum(g["count"] for g in out),
        "note": "Nothing is deleted here. Custodian groups; you press delete.",
    }


# ══════════════════════════ rules and corrections (UC-29) ══════════════════


class NewRule(BaseModel):
    scope: str = "sender"          # sender | domain | message
    target: str
    was: str = ""
    should_be: str


@app.get("/api/rules")
def rules():
    """
    Everything the Owner has told us we got wrong, newest first.

    These ARE the settings. There is no preferences screen anywhere in this
    product: a rule is a sentence about a mistake, recorded where the mistake
    happened (UC-29 scope guard).
    """
    s = store()
    out = [{"id": i, "scope": sc, "target": t, "was": w, "shouldBe": sb,
            "source": src, "at": iso(at)}
           for i, sc, t, w, sb, src, at in s.all_corrections()]
    return {"rules": out}


@app.post("/api/rules")
def add_rule(rule: NewRule):
    """
    Record a correction. It applies from the next message on — immediately,
    not after a retraining cycle (BR-106), because it is a lookup and not a
    weight.
    """
    if rule.scope not in ("sender", "domain", "message"):
        raise HTTPException(400, "scope must be sender, domain or message")
    if not rule.target.strip() or not rule.should_be.strip():
        raise HTTPException(400, "target and should_be are both required")
    s = store()
    s.add_correction(rule.scope, rule.target.strip(), rule.was.strip(),
                     rule.should_be.strip(), source="app")
    s.record_action("", "", "correction",
                    f"{rule.scope} {rule.target} → {rule.should_be}",
                    before=rule.was)
    return {"ok": True, "rules": rules()["rules"]}


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int):
    """
    Forget a correction.

    ⚠️ Deleting the rule does not un-say it — the action log keeps the fact
    that it existed, because history is added to, never rewritten (BR-109).
    """
    s = store()
    row = s.q("SELECT scope,target,should_be FROM corrections WHERE id=?", rule_id)
    if not row:
        raise HTTPException(404, "no such rule")
    s.db.execute("DELETE FROM corrections WHERE id=?", (rule_id,))
    s.db.commit()
    s.record_action("", "", "correction_removed",
                    f"{row[0][0]} {row[0][1]} → {row[0][2]}", before=str(rule_id))
    return {"ok": True, "rules": rules()["rules"]}


# ══════════════════════════ activity and undo (UC-30) ══════════════════════

PLAIN = {
    "label": "filed", "archive": "archived", "mark_read": "marked read",
    "trash": "moved to trash", "send": "sent a reply", "draft": "wrote a draft",
    "remind": "set a reminder", "snooze": "snoozed", "undo": "reversed",
    "unsubscribe": "unsubscribed from", "rescue_from_spam": "rescued from spam",
    "correction": "learned a correction", "correction_removed": "forgot a correction",
    "dismiss_reminder": "dismissed a reminder",
}

# Reversing these puts a message back. The rest either never left, or left for
# good — and the ones that left for good are exactly the ones that asked first.
REVERSIBLE = {"label", "archive", "mark_read", "trash", "rescue_from_spam",
              "draft", "remind", "snooze"}


@app.get("/api/activity")
def activity(limit: int = Query(60, ge=1, le=300)):
    """Every action, across every mailbox, in plain words (BR-110)."""
    s = store()
    out = []
    for aid, mid, pid, action, detail, before, undone, at in s.action_history(limit):
        out.append({
            "id": aid, "messageId": mid, "providerId": pid,
            "action": action, "verb": PLAIN.get(action, action),
            "detail": detail or "", "before": before or "",
            "undone": bool(undone), "at": iso(at),
            "reversible": action in REVERSIBLE and not undone,
        })
    return {"actions": out,
            "reversible": sum(1 for a in out if a["reversible"])}


@app.post("/api/activity/{action_id}/undo")
def undo(action_id: int):
    """
    Put one thing back (UC-30).

    ⚠️ Send, forward and unsubscribe are refused, not attempted. They reached
    another person; there is no call that unreaches them, and saying so plainly
    is better than a spinner that fails. That is the reason they asked for a
    yes in the first place.
    """
    s = store()
    row = next((r for r in s.action_history(500) if r[0] == action_id), None)
    if not row:
        raise HTTPException(404, "no action with that number")
    aid, mid, pid, action, detail, before, undone, at = row
    if undone:
        raise HTTPException(409, "that action was already reversed")
    if action in ("send", "forward", "unsubscribe"):
        raise HTTPException(
            409, "this cannot be reversed — it reached another person. "
                 "That is exactly why it asked for your yes first.")

    # ⚠️ ONE COPY OF UNDO, in history.reverse_action, through the connector.
    #
    # This used to call the Gmail client directly and answered "this door
    # cannot reverse mailbox actions yet" over IMAP — which, with token.json
    # gone, is now the default door. The connectors carry the reversals now,
    # so the same button works on both.
    import history
    c = None if action in ("remind", "snooze") else conn()
    with _LOCK:
        try:
            what = history.reverse_action(c, s, row)
        except ValueError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            raise HTTPException(502, f"the mailbox refused: {str(e)[:160]}")
    return {"ok": True, "undone": aid, "what": what, "actions": activity()["actions"]}


# ══════════════════════════ the digest (UC-31) ══════════════════════════


@app.get("/api/digest")
def digest(days: int = Query(7, ge=1, le=90)):
    """
    What one digest message would say, if it were due now.

    ⚠️ BR-112 — nothing to report means no message. `worthSending` is that rule,
    answered here rather than left to the screen, so every channel agrees about
    when silence is the correct output.
    """
    s = store()
    since = (datetime.now() - timedelta(days=days)).isoformat()

    acted: dict[str, int] = {}
    for action, n in s.q("SELECT action, COUNT(*) FROM actions WHERE at > ? "
                         "GROUP BY 1 ORDER BY 2 DESC", since):
        acted[PLAIN.get(action, action)] = n

    items = [row_to_dict(r) for r in inbox_rows(limit=400)]
    needs_reply = [i for i in items if i["kind"] == "reply"]
    quiet = sum(1 for i in items if i["kind"] in ("machine", "dormant"))

    ahead = [d for d in deadlines()["deadlines"]
             if not d["done"] and d["daysLeft"] is not None and 0 <= d["daysLeft"] <= 30]

    corrections = s.q("SELECT scope,target,should_be,at FROM corrections "
                      "WHERE at > ? ORDER BY id DESC", since)

    sections = {
        "sortedAndCleared": acted,
        "needsReply": needs_reply[:8],
        "handledQuietly": quiet,
        "deadlinesAhead": ahead[:8],
        "learned": [{"scope": a, "target": b, "shouldBe": c, "at": iso(d)}
                    for a, b, c, d in corrections][:5],
    }
    worth = bool(acted or needs_reply or ahead or corrections)
    return {
        "periodDays": days,
        "generatedAt": datetime.now().isoformat(),
        "worthSending": worth,
        "silenceIsCorrect": not worth,
        "sections": sections,
    }


# ══════════════════════════ privacy and data (UC-32) ══════════════════════


@app.get("/api/privacy")
def privacy():
    """
    Everything we hold, said plainly, plus what has actually left this machine.

    ⚠️ The depths are counted from the database, not asserted. A privacy page
    that quotes its own marketing is worth nothing; this one can be checked
    against the rows underneath it.
    """
    s = store()
    import my_data

    # ⚠️ my_data.summary() counts the same tables and already tolerates one
    # that does not exist yet — the voice tables are created by stage 19 the
    # first time it runs. Counting them here by hand would crash on a fresh
    # database, which is exactly the state a new user is in.
    counts = my_data.summary(s)
    holdings = [{"table": t, "plain": plain, "rows": counts.get(t, 0)}
                for t, plain in my_data.HOLDINGS.items()]

    total = s.one("SELECT COUNT(*) FROM messages") or 1
    opened = s.body_stats()["count"]
    escalated = s.q(
        "SELECT message_id, stage, decision, reason, at FROM decisions "
        "WHERE LOWER(reason) LIKE '%escalat%' OR LOWER(decision) LIKE '%gemini%' "
        "ORDER BY at DESC LIMIT 20")

    return {
        "holdings": holdings,
        "depths": [
            {"depth": 1, "sees": "sender and subject only — never opened",
             "count": max(total - opened, 0),
             "share": round(max(total - opened, 0) / total * 100, 1)},
            {"depth": 3, "sees": "full message, on this machine only",
             "count": opened, "share": round(opened / total * 100, 1)},
            {"depth": 4, "sees": "full message, names removed, sent to a rented model",
             "count": len(escalated),
             "share": round(len(escalated) / total * 100, 2)},
        ],
        "passport": [
            {"messageId": m, "stage": st, "what": dec, "reason": why, "at": iso(at)}
            for m, st, dec, why, at in escalated
        ],
        "neverHeld": ("The text of your emails. The schema has no column for it — "
                      "the bodies table holds a bounded window and trims itself."),
        "retentionDays": WINDOW_DAYS,
    }


@app.post("/api/privacy/export")
def export():
    """
    Write everything we hold to a readable file (BR-114).

    The file lands next to the database, on the Owner's own machine. Nothing is
    uploaded anywhere to produce it.
    """
    s = store()
    import my_data

    out = {
        "exported_at": datetime.now().isoformat(),
        "what_this_contains": my_data.HOLDINGS,
        "what_we_never_held": ("The text of your emails. The database has no "
                               "column for it. Your mail is in your mailbox and "
                               "always was."),
        "counts": my_data.summary(s),
        "data": {},
    }
    for table in my_data.HOLDINGS:
        try:
            cur = s.db.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            out["data"][table] = [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            # A table that does not exist yet is reported as such rather than
            # silently missing from the export (BR-114 — everything we hold).
            out["data"][table] = f"not created yet: {e}"

    path = Path(f"my_data_{datetime.now():%Y%m%d_%H%M}.json")
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return {"ok": True, "path": str(path.resolve()),
            "sizeMb": round(path.stat().st_size / 1e6, 2),
            "counts": out["counts"]}


# ⚠️ There is no erase endpoint, and that is deliberate.
#
# Erasure removes the mailbox connection and everything learned, and it cannot
# be taken back. UC-32 E1 says an erasure request is exactly what an attacker
# would send, and this API has no idea who is on the other end of it. It stays
# where identity is certain: `python my_data.py --erase`, at the keyboard.


# ══════════════════════════ the 19 September surfaces ══════════════════════
#
# Read-only views over what the new scripts record. Each calls the script's
# own builder so the browser and the terminal can never disagree.

@app.get("/api/today")
def api_today():
    """UC-43. One ordered list, nothing decided here."""
    import today
    items = today.build(store())
    return {"items": [{"kind": k, "text": t, "note": n, "messageId": m} for k, t, n, m in items]}


@app.get("/api/asks")
def api_asks():
    """UC-33 / UC-45. Open requests and promises."""
    s = store()
    def row(r):
        rid, mid, d, what, who, due, ev, conf, sender, sname, subject, to, date = r
        return {"id": rid, "direction": d, "what": what, "who": who, "due": due,
                "evidence": ev, "confidence": conf, "sender": sender, "senderName": sname,
                "subject": subject, "messageId": mid}
    return {"asks": [row(r) for r in s.open_requests("ask")],
            "promises": [row(r) for r in s.open_requests("promise")]}


@app.get("/api/pile")
def api_pile():
    """UC-15. The pile, grouped and explained. Clearing stays at the keyboard."""
    import pile
    me = ""
    try:
        c = conn(required=False)
        me = c.account_email() if c else ""
    except Exception:
        pass
    groups, held, excluded = pile.build(store(), me)
    return {"groups": [{k: v for k, v in g.items() if k != "ids"} | {"count": g["count"]}
                       for g in groups],
            "heldBack": held, "excludedSenders": excluded,
            "note": "Clearing is done in the terminal — python pile.py --clear — after a typed yes."}


@app.get("/api/typed-rules")
def api_typed_rules():
    """UC-38 / UC-44. Rules typed in plain English and important-person sets."""
    return {"rules": [{"id": rid, "sentence": s_, "matchKind": k, "matchValue": v,
                       "action": a, "actionArg": arg, "plain": p, "group": g, "at": at}
                      for rid, s_, k, v, a, arg, p, g, at in store().rules()]}


# ══════════════════════════ running it ══════════════════════════


def main():
    global NO_MAILBOX
    p = argparse.ArgumentParser(description="JSON API over the Custodian POC")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--no-mailbox", action="store_true",
                   help="database only — never open the mailbox")
    p.add_argument("--reload", action="store_true")
    a = p.parse_args()
    NO_MAILBOX = a.no_mailbox

    # ⚠️ Open the mailbox HERE, in front of the person starting it.
    #
    # Opening it lazily on the first request made a failed sign-in invisible:
    # the terminal looked healthy, and the only sign of trouble was the web app
    # quietly saying "database only" with the reason nowhere a person looks.
    s = store()
    print(f"\n  database : {s.one('SELECT COUNT(*) FROM messages'):,} messages")
    if NO_MAILBOX:
        print("  mailbox  : not opened (--no-mailbox)")
    else:
        c = conn(required=False)
        if c is not None:
            print(f"  mailbox  : {c.account_email()} via {getattr(c, 'name', '?')}")
        else:
            print(f"  mailbox  : COULD NOT OPEN \u2014 {CONN_ERROR}")
            print("             Everything still works, reading the database only.")
            print("             IMAP door  : needs IMAP_USER and IMAP_PASSWORD set")
            print("             Gmail door : needs token.json (python inbox.py --api)")

    import uvicorn
    print(f"\n  Custodian API on http://{a.host}:{a.port}")
    print(f"  interactive docs at http://{a.host}:{a.port}/docs")
    if NO_MAILBOX:
        print("  database only — no mailbox will be opened")
    print("  Ctrl+C to stop.\n")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
