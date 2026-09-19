"""
UC-37 — Bring a message back on a day you choose. Not snooze.

    python remind.py                          # what is pending
    python remind.py 4 --on 2026-09-25        # message 4 (as numbered in the mailbox), that day
    python remind.py 4 --on thursday --note "ask about the invoice"
    python remind.py --cancel 4
    python remind.py --check                  # clear reminders whose message you have replied to

⚠️ THE MESSAGE NEVER MOVES (BR-137).

Snoozing hides mail and brings it back later — and hiding mail is the single
thing every rival in this category is hated for. This is a note we keep on
our side: nothing in the mailbox is labelled, moved, flagged or marked. Which
is also why it works identically on every provider.

⚠️ YOUR OWN WORDS COME BACK VERBATIM (BR-139). We never reword the reason
you gave yourself.
"""

import os
import sys
from datetime import datetime, timedelta

from store import Store
from pipeline import stage07_dates

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")


def inbox_rows(store, limit=200):
    """The same numbering the mailbox view and the web page use."""
    rows = store.q("""SELECT message_id, provider_id, sender, sender_name, subject,
                             COALESCE(NULLIF(date_iso,''), date)
                        FROM messages WHERE in_inbox=1
                       ORDER BY date_iso DESC, date DESC LIMIT ?""", limit * 2)
    out, seen = [], set()
    for r in rows:
        if r[0] and r[0] in seen:
            continue
        seen.add(r[0]); out.append(r)
    return out[:limit]


def when(text: str):
    """A date from 'thursday', 'tomorrow', 'next week' or 2026-09-25. Code, not a model."""
    t = (text or "").strip().lower()
    try:
        return datetime.fromisoformat(t).replace(hour=9, minute=0, second=0, microsecond=0)
    except Exception:
        pass
    now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    if t in ("tomorrow",):
        return now + timedelta(days=1)
    if t in ("next week",):
        return now + timedelta(days=7)
    r = stage07_dates.resolve_relative(t, now) if hasattr(stage07_dates, "resolve_relative") else None
    if r:
        return r if isinstance(r, datetime) else datetime.fromisoformat(str(r)[:19])
    import dateparser
    d = dateparser.parse(t, settings={"PREFER_DATES_FROM": "future"})
    return d.replace(hour=9, minute=0, second=0, microsecond=0) if d else None


def show(store):
    print(f"\n{C['b']}Reminders{C['0']}")
    print("─" * 70)
    rows = store.pending_reminders()
    if not rows:
        print("  none pending.\n"); return
    for r in rows:
        mid, pid, kind, due, subject, why = r[:6]
        print(f"  {C['c']}{due[:10]}{C['0']}  {(subject or '')[:44]:44} {C['dim']}{why or ''}{C['0']}")
    print()


def set_one(store, n, on, note):
    rows = inbox_rows(store)
    if not 1 <= n <= len(rows):
        print(f"\n  no message {n}. There are {len(rows)}.\n"); return
    mid, pid, sender, sname, subject, date = rows[n - 1]
    due = when(on)
    if not due:
        print(f"\n  could not read a date from '{on}'.\n"); return
    if due < datetime.now():
        print(f"\n  {C['y']}That date has already passed.{C['0']}\n"); return
    store.add_reminder(message_id=mid, provider_id=pid, kind="remind", due=due,
                       subject=(subject or "")[:80], why=note or "")
    store.record_action(mid, pid, "remind", due.strftime("%Y-%m-%d"))
    print(f"\n  {C['g']}We will bring this back on {due:%A %d %B}.{C['0']}")
    print(f"  {C['dim']}It stays in your inbox until then — we are not hiding it.{C['0']}")
    if note:
        print(f"  {C['dim']}Your note: {note}{C['0']}")
    print()


def cancel(store, n):
    rows = inbox_rows(store)
    if not 1 <= n <= len(rows):
        print(f"\n  no message {n}.\n"); return
    store.clear_reminder(rows[n - 1][0], "remind")
    print(f"\n  reminder cancelled. Nothing in the mailbox was touched.\n")


def check(store):
    """ALT-2: replying to the message clears the reminder."""
    n = 0
    for r in store.pending_reminders():
        mid = r[0]
        if store.already_replied(mid):
            store.clear_reminder(mid, "remind"); n += 1
    print(f"\n  {n} reminder(s) cleared because you already replied.\n")


def main():
    store = Store()
    args = sys.argv[1:]
    if "--check" in args:
        return check(store)
    if "--cancel" in args:
        i = args.index("--cancel")
        return cancel(store, int(args[i + 1]))
    n = next((int(a) for a in args if a.isdigit()), None)
    if n is None:
        return show(store)
    on = args[args.index("--on") + 1] if "--on" in args else "tomorrow"
    note = args[args.index("--note") + 1] if "--note" in args else ""
    set_one(store, n, on, note)


if __name__ == "__main__":
    main()
