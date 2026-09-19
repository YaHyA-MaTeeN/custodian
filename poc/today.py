"""
UC-43 — Work through today. One list, in the only order that makes sense.

    python today.py
    python today.py --dismiss 3      # not a real item — recorded as a correction

⚠️ NOTHING NEW IS DECIDED HERE (BR-166). Every item was found by another
use case, which keeps its own rules: deadlines by stage 16, promises and
requests by stage 18, unread-important by UC-36, spam rescues by UC-20.
This screen only gathers them and orders them.

⚠️ FIXED ORDER (BR-167): due today · promises you made · requests of you ·
unread and important · waiting on others · rescued from spam. Deadlines
first, because a missed deadline is the one thing that cannot be recovered.

⚠️ AN EMPTY LIST IS THE GOAL (BR-169), not a failure.
"""

import os
import sys
from datetime import datetime, timedelta

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

STALE_DAYS = 3             # UC-36: important and still unread after this long


def unread_important(store) -> list:
    """UC-36. Ranked important by us, still unread, older than STALE_DAYS, not yet reported."""
    cutoff = (datetime.now() - timedelta(days=STALE_DAYS)).isoformat()[:19]
    rows = store.q("""SELECT m.message_id, m.sender, m.sender_name, m.subject, m.date_iso
                        FROM messages m JOIN decisions d USING(message_id)
                       WHERE m.in_inbox=1 AND m.unread=1 AND d.stage='9'
                         AND d.decision='needs a reply' AND m.date_iso < ?
                       ORDER BY m.date_iso""", cutoff)
    return [r for r in rows if not store.was_reported(r[0], "unread_important")]


def build(store) -> list:
    today = datetime.now().date().isoformat()
    items = []
    # 1 · due today (or overdue)
    for mid, pid, kind, due, subject, why in store.pending_reminders():
        if str(due)[:10] <= today:
            items.append(("due", f"{subject[:50]}", f"{kind} · {str(due)[:10]}", mid))
    # 2 · promises you made, coming due
    for r in store.open_requests("promise"):
        rid, mid, d, what, who, due, *_ = r
        items.append(("promise", f"you told {who[:20]}: {what[:40]}", due[:10] or "no date", mid))
    # 3 · requests of you
    for r in store.open_requests("ask"):
        rid, mid, d, what, who, due, ev, conf, sender, sname, subject, *_ = r
        if who == "me":
            items.append(("ask", f"{(sname or sender or '')[:18]}: {what[:40]}", due[:10] or "no date", mid))
    # 4 · unread and important
    for mid, sender, sname, subject, date in unread_important(store):
        days = (datetime.now() - datetime.fromisoformat(date[:19])).days if date else 0
        items.append(("unread", f"{(subject or '')[:50]}", f"{days} days unread · {(sname or sender)[:18]}", mid))
    # 5 · waiting on others (from UC-22 when it has run — it labels; we read the label log)
    for r in store.q("""SELECT message_id, detail, at FROM actions WHERE action='label'
                         AND detail LIKE '%Waiting%' AND undone=0 ORDER BY at DESC LIMIT 10"""):
        items.append(("waiting", f"still no reply: {(r[1] or '')[:40]}", str(r[2])[:10], r[0]))
    # 6 · rescued from spam
    for r in store.q("""SELECT message_id, detail, at FROM actions WHERE action='rescue_from_spam'
                         AND undone=0 AND at > ? ORDER BY at DESC""",
                     (datetime.now() - timedelta(days=7)).isoformat()):
        items.append(("spam", f"rescued: {(r[1] or '')[:44]}", str(r[2])[:10], r[0]))
    order = {"due": 0, "promise": 1, "ask": 2, "unread": 3, "waiting": 4, "spam": 5}
    items.sort(key=lambda x: order[x[0]])
    return items


LABEL = {"due": "DUE", "promise": "PROMISED", "ask": "ASKED", "unread": "UNREAD",
         "waiting": "WAITING", "spam": "SPAM"}


def main():
    store = Store()
    args = sys.argv[1:]
    items = build(store)
    if "--dismiss" in args:
        n = int(args[args.index("--dismiss") + 1])
        if 1 <= n <= len(items):
            kind, text, note, mid = items[n - 1]
            if kind == "unread":
                store.mark_reported(mid, "unread_important")
            sender = store.one("SELECT sender FROM messages WHERE message_id=?", mid)
            if sender:
                store.add_correction("sender", sender, was=kind, should_be="dismissed", source="app")
            print("\n  dismissed, and recorded as a correction.\n")
        return

    due = sum(1 for i in items if i[0] == "due")
    print(f"\n{C['b']}Good {'morning' if datetime.now().hour < 12 else 'afternoon'}.{C['0']} "
          f"{due} thing{'s' if due != 1 else ''} due today.")
    print("─" * 72)
    if not items:
        print(f"  {C['g']}Nothing needs you right now.{C['0']}\n"); return
    for i, (kind, text, note, mid) in enumerate(items[:10], 1):
        colour = C["r"] if kind == "due" else C["c"] if kind in ("promise", "ask") else C["dim"]
        print(f"  {i:>2}. {colour}{LABEL[kind]:>8}{C['0']}  {text:52} {C['dim']}{note}{C['0']}")
    if len(items) > 10:
        print(f"  {C['dim']}… and {len(items) - 10} more{C['0']}")
    for kind, text, note, mid in items:
        if kind == "unread":
            store.mark_reported(mid, "unread_important")        # BR-135: once, never again
    print(f"\n  {C['dim']}reply: python send_mail.py · later: python remind.py N --on … · "
          f"dismiss: python today.py --dismiss N{C['0']}\n")


if __name__ == "__main__":
    main()
