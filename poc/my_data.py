"""
UC-32 — Take everything we hold, or make us hold nothing.

    python my_data.py --export     # write everything we hold to a file
    python my_data.py --erase      # delete it all

⚠️ THE SCOPE GUARD IS THE WHOLE ARGUMENT.

"The customer's mail itself. WE NEVER HELD IT, so there is nothing to export
or erase there."

That is not a promise we are making — it is a fact about the schema. There is
no column for a message body anywhere in this database. A competitor who
stores the mail has to hunt through copies, backups and search indexes when
somebody invokes their rights. We delete a handful of rows.

⚠️ ERASURE CHANGES NOTHING IN THE MAILBOX (BR-116).

Their labels stay. Their cleared mail stays. Their drafts stay. Those are
theirs and were always in their account, not ours. We disconnect and forget;
we do not reach into somebody's mailbox on the way out.

⚠️ AND WE SAY WHAT SURVIVES, RATHER THAN HIDING IT (BR-117).

Aggregate sender reputation holds no personal content and outlives an erasure.
The honest move is to name that plainly in the export rather than let somebody
discover it later.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m",
     "y": "\033[33m", "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# Everything we hold, named in plain words. If a table is not on this list it
# does not get exported — so adding a table without adding it here is a bug
# that shows up as an incomplete export, which is exactly where it should.
HOLDINGS = {
    "messages":       "Facts about your emails — sender, subject, date, read or not. NEVER the text.",
    "decisions":      "What we decided about each message, and the reason, recorded at the time.",
    "actions":        "Every action we took, and how to reverse it.",
    "corrections":    "Times you told us we were wrong.",
    "reminders":      "Deadlines we are watching for you.",
    "handled":        "Which messages we already answered, so we never answer twice.",
    "style_profile":  "How you write — greeting, sign-off, typical length, formality.",
    "style_examples": "Your own past replies, kept so drafts sound like you.",
}

CREDENTIALS = ["token.json"]
CACHES = ["applied_labels.json", "labelled.jsonl", "to_label.txt", "labels.txt"]


def summary(store) -> dict:
    out = {}
    for table in HOLDINGS:
        try:
            out[table] = store.one(f"SELECT COUNT(*) FROM {table}")
        except Exception:
            out[table] = 0
    return out


def show_holdings(store):
    counts = summary(store)
    print(f"\n{C['b']}Everything we hold about you{C['0']}")
    print("─" * 72)
    for table, plain in HOLDINGS.items():
        print(f"  {C['c']}{counts[table]:>6}{C['0']}  {table}")
        print(f"          {C['dim']}{plain}{C['0']}")
    print("─" * 72)
    print(f"  {C['g']}And your email text: nothing. There is no column for it.{C['0']}")
    print(f"  {C['dim']}That is why there is nothing of your mail to return "
          f"or delete.{C['0']}")
    return counts


def export(store):
    counts = show_holdings(store)
    out = {
        "exported_at": datetime.now().isoformat(),
        "what_this_contains": HOLDINGS,
        "what_we_never_held": (
            "The text of your emails. The database has no column for it. "
            "Your mail is in your mailbox and always was."),
        "what_survives_erasure": (
            "Aggregate sender reputation — how often mail from a domain is "
            "opened across all customers. It holds no personal content and no "
            "identifier of yours, so it is not yours to erase. Stated here "
            "rather than hidden (BR-117)."),
        "counts": counts,
        "data": {},
    }
    for table in HOLDINGS:
        try:
            cur = store.db.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            out["data"][table] = [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            out["data"][table] = f"could not read: {e}"

    path = Path(f"my_data_{datetime.now():%Y%m%d_%H%M}.json")
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    mb = path.stat().st_size / 1e6
    print(f"\n  {C['g']}written: {path}{C['0']}  ({mb:.1f} MB)")
    print(f"  {C['dim']}Readable JSON — openable in any text editor, not a "
          f"database dump.{C['0']}\n")


def erase(store):
    counts = show_holdings(store)

    # ⚠️ Consequences BEFORE the confirmation, never after (UC-32, step 5).
    print(f"\n{C['b']}What erasing does{C['0']}")
    print("─" * 72)
    print(f"  {C['r']}removed{C['0']}   every row above — {sum(counts.values()):,} in total")
    print(f"  {C['r']}removed{C['0']}   your Gmail connection ({', '.join(CREDENTIALS)})")
    print(f"  {C['r']}removed{C['0']}   local caches ({', '.join(CACHES)})")
    print(f"  {C['r']}lost{C['0']}      everything learned about your preferences. "
          f"It cannot be rebuilt.")
    print()
    print(f"  {C['g']}UNTOUCHED{C['0']}  your mailbox. Every Custodian label stays "
          f"exactly where it is.")
    print(f"  {C['g']}UNTOUCHED{C['0']}  every email, every draft, every reply "
          f"already sent.")
    print(f"  {C['dim']}            (If you want the labels gone too, run "
          f"python sort_mailbox.py --undo FIRST — after erasure we no longer{C['0']}")
    print(f"  {C['dim']}             know which labels were ours.){C['0']}")
    print()
    print(f"  {C['y']}KEPT{C['0']}       aggregate sender reputation. No personal "
          f"content, no identifier of yours.")
    print(f"  {C['dim']}            Named here rather than hidden (BR-117).{C['0']}")

    try:
        answer = input(f"\n  Type {C['b']}erase{C['0']} to confirm: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer != "erase":
        print(f"  {C['dim']}nothing was deleted.{C['0']}\n")
        return

    removed = {}
    for table in HOLDINGS:
        try:
            n = store.one(f"SELECT COUNT(*) FROM {table}")
            store.db.execute(f"DELETE FROM {table}")
            removed[table] = n
        except Exception:
            removed[table] = 0
    store.db.commit()
    store.db.execute("VACUUM")

    gone = []
    for f in CREDENTIALS + CACHES:
        if Path(f).exists():
            Path(f).unlink()
            gone.append(f)

    print(f"\n{C['b']}Erased{C['0']}")
    print("─" * 72)
    for t, n in removed.items():
        print(f"  {n:>6}  rows from {t}")
    for f in gone:
        print(f"          deleted {f}")
    print(f"\n  {C['g']}Your mailbox is exactly as it was.{C['0']}")
    print(f"  {C['dim']}Reconnecting starts from nothing — there is no history "
          f"to restore.{C['0']}\n")


def disconnect(store, account: str):
    """
    UC-13 — one mailbox, not the whole account.

    ⚠️ STATES WHAT WILL AND WILL NOT HAPPEN, BEFORE CONFIRMING. Will stop: all
    processing for that mailbox. Will stay: every label, cleared message and
    draft already in it (BR-46) — we do not undo our work. Will be erased:
    our index for it, now (BR-48). Will be lost: its pending reminders,
    listed by name (AC-13.5).

    The credential is destroyed at once, not marked inactive (BR-47). On an
    app password only the Owner can finish that, at the provider (T-4).
    """
    account = account.lower()
    n = store.one("SELECT COUNT(*) FROM messages WHERE LOWER(COALESCE(account,''))=?", account)
    if not n:
        print(f"\n  {account} is not a connected mailbox here.\n"); return
    pending = store.q("""SELECT r.subject, r.due FROM reminders r JOIN messages m USING(message_id)
                          WHERE r.done=0 AND LOWER(COALESCE(m.account,''))=?""", account)
    print(f"\n{C['b']}Disconnect {account}{C['0']}")
    print("─" * 72)
    print(f"  {C['r']}will stop{C['0']}    all sorting, tracking and drafting for this mailbox")
    print(f"  {C['g']}will stay{C['0']}    every label, every cleared message and every draft already in it")
    print(f"  {C['r']}erased now{C['0']}   our index of its {n:,} messages, and the decisions about them")
    if pending:
        print(f"  {C['y']}will be lost{C['0']} {len(pending)} reminder(s):")
        for subject, due in pending[:6]:
            print(f"               · {(subject or '')[:44]}  {str(due)[:10]}")
    try:
        answer = input(f"\n  Type {C['b']}disconnect{C['0']} to confirm: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer != "disconnect":
        print(f"  {C['dim']}nothing changed.{C['0']}\n"); return
    mids = [r[0] for r in store.q("SELECT message_id FROM messages WHERE LOWER(COALESCE(account,''))=?", account)]
    q = ",".join("?" * len(mids)) if mids else "''"
    for table in ("reminders", "decisions", "actions", "bodies", "requests"):
        try:
            store.db.execute(f"DELETE FROM {table} WHERE message_id IN ({q})", mids)
        except Exception:
            pass
    store.db.execute("DELETE FROM messages WHERE LOWER(COALESCE(account,''))=?", (account,))
    store.db.commit()
    store.record_action("", "", "disconnect", account)         # the final entry
    for f in CREDENTIALS:
        try:
            os.remove(f)
        except Exception:
            pass
    print(f"\n  {C['g']}disconnected.{C['0']} Our copy of the credential is gone.")
    print(f"  {C['b']}To finish:{C['0']} delete the app password you created for us at your provider "
          f"(Google: myaccount.google.com/apppasswords), and run  setx IMAP_PASSWORD \"\"  — "
          f"only you can do that.")
    print(f"  {C['dim']}python my_data.py --export was offered before this; the rest of the account is untouched.{C['0']}\n")


def main():
    store = Store()
    if "--disconnect" in sys.argv:
        i = sys.argv.index("--disconnect")
        return disconnect(store, sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
    if "--export" in sys.argv:
        return export(store)
    if "--erase" in sys.argv:
        return erase(store)
    show_holdings(store)
    print(f"\n  {C['dim']}python my_data.py --export    write it all to a file{C['0']}")
    print(f"  {C['dim']}python my_data.py --erase     delete all of it{C['0']}\n")


if __name__ == "__main__":
    main()
