"""
UC-30 — Everything the system has done, and how to reverse it.

    python history.py              # what happened, newest first
    python history.py --undo 14    # reverse action 14

⚠️ WHY UNDO IS CHEAP FOR US AND IMPOSSIBLE FOR A COMPETITOR.

We only ever MOVE things. Nothing is deleted, so every action is reversible by
definition rather than by effort. A product that deletes has to build a
recovery system; we only have to remember what the state was before.

⚠️ AN UNDO IS ITSELF AN ACTION (BR-109).

It is written into the log as its own entry rather than erasing the original.
A history that quietly rewrites itself is not a record, and the whole value of
this screen is that the Owner can trust what it says.

⚠️ WHAT WE CANNOT DO, AND SAY SO.

Mail the Owner deleted themselves is in the provider's trash. We never touched
it and cannot restore it. Pretending otherwise would be the one failure this
feature cannot survive.
"""

import json
import os
import sys
from datetime import datetime

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# Plain words, because BR-110 says the log is readable without technical
# knowledge. "apply_label" is our word; "filed under" is theirs.
PLAIN = {
    "label":            "filed under",
    "archive":          "archived",
    "mark_read":        "marked as read",
    "trash":            "moved to trash",
    "send":             "sent a reply to",
    "forward":          "forwarded to",
    "unsubscribe":      "unsubscribed from",
    "rescue_from_spam": "rescued from spam",
    "draft":            "wrote a draft to",
    "remind":           "set a reminder for",
    "snooze":           "snoozed until",
    "undo":             "reversed",
}


def show(store):
    rows = store.action_history(60)
    if not rows:
        print(f"\n  {C['dim']}Nothing has been done yet.{C['0']}\n")
        return

    print(f"\n{C['b']}What the system has done{C['0']}")
    print("─" * 70)
    for aid, mid, pid, action, detail, before, undone, at in rows:
        when = at[:16].replace("T", "  ")
        mark = f"{C['dim']}[undone]{C['0']}" if undone else ""
        verb = PLAIN.get(action, action)
        print(f"  {C['dim']}{aid:>3}{C['0']}  {when}  {verb} {C['c']}{detail[:44]}{C['0']} {mark}")
        if before and not undone:
            print(f"       {C['dim']}before: {before[:60]}{C['0']}")

    live = sum(1 for r in rows if not r[6])
    print("─" * 70)
    print(f"  {len(rows)} action(s), {live} still reversible")
    print(f"  {C['dim']}python history.py --undo <number>{C['0']}\n")


def reverse_action(conn, store, row) -> str:
    """
    Reverse one recorded action, on whichever door is open. Returns a plain
    sentence saying what happened. Raises ValueError when it cannot.

    ⚠️ THE ONE COPY OF UNDO. history.py (keyboard) and api.py (browser) both
    call this. It goes through the connector's reversal methods, never through
    a provider's client directly, so it works on both doors.

    ⚠️ The stored provider_id belongs to the door that recorded it. On the
    other door — or after the message has moved folders on IMAP — the
    connector finds the message again by Message-ID. That is why message_id
    is passed alongside the id everywhere below.
    """
    aid, mid, pid, action, detail, before, undone, at = row
    if undone:
        raise ValueError(f"action {aid} was already reversed")
    if action in ("send", "forward", "unsubscribe"):
        raise ValueError("this cannot be reversed — it reached another person. "
                         "That is exactly why it asked for your yes first.")
    if action in ("correction", "correction_removed", "dismiss_reminder"):
        raise ValueError("corrections are changed in Rules, not undone here")

    if action in ("remind", "snooze"):
        store.clear_reminder(mid, action)
    else:
        import connect
        live = connect.live_id(conn, pid, mid) or pid
        if action == "label":
            conn.remove_label(live, before, mid)
        elif action == "archive":
            conn.unarchive(live, mid)
        elif action == "mark_read":
            conn.mark_unread(live, mid)
        elif action == "trash":
            conn.untrash(live, mid)
        elif action == "rescue_from_spam":
            conn.unrescue(live, mid)
        elif action == "draft":
            conn.delete_draft(detail, mid)
        else:
            raise ValueError(f"no reversal defined for '{action}'")

    store.mark_undone(aid)
    # ⚠️ The undo is its own entry. History is added to, never rewritten.
    store.record_action(mid, pid, "undo", f"reversed action {aid} ({action})",
                        before=detail)
    return f"reversed action {aid}: {PLAIN.get(action, action)} {detail}".strip()


def undo(store, action_id: int):
    row = next((r for r in store.action_history(500) if r[0] == action_id), None)
    if not row:
        print(f"\n  no action numbered {action_id}.\n")
        return
    aid, mid, pid, action, detail, before, undone, at = row
    if undone:
        print(f"\n  action {aid} was already reversed.\n")
        return

    # ⚠️ Say what will happen BEFORE doing it (UC-30 main flow, step 3).
    print(f"\n{C['b']}Reversing action {aid}{C['0']}")
    print("─" * 70)
    print(f"  what happened : {PLAIN.get(action, action)} {detail}")
    print(f"  when          : {at[:16].replace('T', ' ')}")
    print(f"  state before  : {before or '(not recorded)'}")

    if action in ("send", "forward", "unsubscribe"):
        print(f"\n  {C['r']}This cannot be reversed.{C['0']}")
        print(f"  {C['dim']}That is exactly why it asked for your yes first.{C['0']}\n")
        return

    try:
        answer = input(f"\n  Reverse it? type yes: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "no"
    if answer != "yes":
        print("  nothing changed.\n")
        return

    import connect
    conn = connect.open_mailbox(quiet=True) if action not in ("remind", "snooze") else None
    try:
        reverse_action(conn, store, row)
    except ValueError as e:
        print(f"  {C['y']}{e}{C['0']}\n")
        return
    except Exception as e:
        print(f"  {C['r']}could not reverse it: {str(e)[:70]}{C['0']}\n")
        return
    print(f"\n  {C['g']}reversed.{C['0']} Logged as its own entry.")
    print(f"  {C['dim']}Should this also become a correction? "
          f"python correct.py{C['0']}\n")


def main():
    store = Store()
    if "--undo" in sys.argv:
        i = sys.argv.index("--undo")
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            return undo(store, int(sys.argv[i + 1]))
        print("\n  which one? python history.py --undo 14\n")
        return
    show(store)


if __name__ == "__main__":
    main()
