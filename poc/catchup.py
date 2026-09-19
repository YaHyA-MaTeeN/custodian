"""
UC-39 — Back from time away: what still needs you, and what sorted itself out.

    python catchup.py                    # infer the absence from your own quiet days
    python catchup.py --since 2026-09-12 # you say when you were away from
    python catchup.py --mark-read        # after reviewing: mark the other groups read (asks)

⚠️ THE VALUABLE PART IS WHAT SORTED ITSELF OUT.

Four hundred emails after a week off is where people give up. What still
needs them is usually a handful. Everything answered by someone else, or
already expired, is mail they can safely never read — and no other tool
tells them which that is.

Four groups, always in this order (BR-149): still needs you · answered by
someone else · expired · for information. Bulk mail is counted, never listed.
When unsure, "still needs you" (BR-152) — reading one extra message costs
little; missing one does not.

⚠️ NOTHING CHANGES ON ITS OWN (BR-151). No archive, no move, no read marker
without the Owner's click. --mark-read is that click, and it asks first.
"""

import os
import sys
from datetime import datetime, timedelta

import connect
from store import Store
from pipeline import stage03_sensitive, stage04_headers

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

MIN_DAYS = 2               # everyone misses a weekend


def infer_since(store) -> str:
    """
    BR-148: absence from the Owner's own activity — the last day anything was
    opened, or sent. Not from the mail arriving.
    """
    last_open = store.one("SELECT MAX(date_iso) FROM messages WHERE unread=0 AND in_inbox=1")
    last_sent = store.one("SELECT MAX(date_iso) FROM messages WHERE sender=("
                          "SELECT account FROM messages WHERE account!='' LIMIT 1)")
    last = max(x for x in (last_open, last_sent, "") if x)
    return str(last)[:19] if last else ""


def groups(store, me, since) -> dict:
    rows = store.q("""SELECT message_id, provider_id, sender, sender_name, sender_domain, subject,
                             date_iso, bulk, unsubscribe, auto_sub, in_reply_to, thread_id, unread
                        FROM messages WHERE in_inbox=1 AND date_iso > ? ORDER BY date_iso""", since)
    out = {"needs": [], "answered": [], "expired": [], "info": [], "bulk": 0, "unsure": 0}
    now = datetime.now()
    for mid, pid, sender, sname, domain, subject, date, bulk, unsub, auto, irt, tid, unread in rows:
        if bulk or unsub or auto:
            out["bulk"] += 1; continue
        if stage03_sensitive.check(sender, subject or "", domain or "")["sensitive"]:
            out["info"].append((mid, sender, sname, subject, date)); continue
        if not unread:
            continue                                     # EX-3: read elsewhere
        # Answered by someone else: a later message in the same thread from a
        # third party (BR-150) — never a guess that it probably does not matter.
        later = store.q("""SELECT sender FROM messages WHERE (in_reply_to=? OR (thread_id!='' AND thread_id=?))
                             AND date_iso > ? AND sender!=? AND sender!=?""",
                        mid, tid or "-", date, sender, (me or "").lower())
        if later:
            out["answered"].append((mid, sender, sname, subject, date)); continue
        # Expired: a recorded commitment whose date has passed.
        due = store.one("SELECT due FROM reminders WHERE message_id=? ORDER BY due LIMIT 1", mid)
        if due and str(due)[:19] < now.isoformat()[:19]:
            out["expired"].append((mid, sender, sname, subject, date)); continue
        # Needs you: a recorded decision said so, or a request is open, or we
        # cannot tell (BR-152 — when unsure, here).
        d = [x for x in store.decision_for(mid) if x[0] == "9"]
        asked = store.has_request(mid)
        if asked or (d and d[-1][1] == "needs a reply"):
            out["needs"].append((mid, sender, sname, subject, date))
        elif d:
            out["info"].append((mid, sender, sname, subject, date))
        else:
            out["needs"].append((mid, sender, sname, subject, date)); out["unsure"] += 1
    return out


def main():
    store = Store()
    args = sys.argv[1:]
    since = args[args.index("--since") + 1] if "--since" in args else infer_since(store)
    if not since:
        print("\n  nothing to go on yet.\n"); return
    days = (datetime.now() - datetime.fromisoformat(since[:19])).days
    if days < MIN_DAYS and "--since" not in args:
        print(f"\n  You were last active {days} day(s) ago. Nothing to catch up on.\n"); return
    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()
    g = groups(store, me, since)
    total = sum(len(g[k]) for k in ("needs", "answered", "expired", "info")) + g["bulk"]

    print(f"\n{C['b']}You've been away {days} days. {total} messages arrived.{C['0']}")
    print("─" * 72)
    print(f"  {C['c']}{len(g['needs'])} still need you.{C['0']}  {len(g['answered'])} were answered by someone else.  "
          f"{len(g['expired'])} have expired.  {len(g['info'])} are for information.  "
          f"{C['dim']}{g['bulk']} bulk, counted not listed.{C['0']}")
    if g["unsure"]:
        print(f"  {C['dim']}We weren't sure about {g['unsure']} of these, so we put them in 'still needs you'.{C['0']}")
    print(f"\n  {C['b']}Still needs you{C['0']}")
    for mid, sender, sname, subject, date in g["needs"][:15]:
        print(f"    {(date or '')[:10]}  {(subject or '(no subject)')[:44]:44} {C['dim']}{(sname or sender)[:22]}{C['0']}")
    for key, title in (("answered", "Answered by someone else"), ("expired", "Expired")):
        if g[key]:
            print(f"\n  {C['dim']}{title} — {len(g[key])}{C['0']}")
            for mid, sender, sname, subject, date in g[key][:5]:
                print(f"    {C['dim']}{(date or '')[:10]}  {(subject or '')[:44]}{C['0']}")

    rest = g["answered"] + g["expired"] + g["info"]
    if "--mark-read" in args and rest:
        print(f"\n  Mark the other {len(rest)} as read? Nothing is deleted.")
        try:
            typed = input("  type yes: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            typed = ""
        if typed == "yes":
            n = 0
            for mid, *_ in rest:
                pid = store.one("SELECT provider_id FROM messages WHERE message_id=?", mid)
                try:
                    conn.mark_read(connect.live_id(conn, pid, mid) or pid, mid)
                    store.record_action(mid, pid, "mark_read", "catch-up"); n += 1
                except Exception:
                    pass
            print(f"  {C['g']}{n} marked read.{C['0']} python history.py --undo reverses any.")
    elif rest:
        print(f"\n  {C['dim']}python catchup.py --mark-read   marks the other {len(rest)} read, after your yes.{C['0']}")
    print()


if __name__ == "__main__":
    main()
