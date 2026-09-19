"""
UC-17 — Stop a sender for real, and find out whether they actually stopped.

    python unsubscribe.py                      # who can be stopped, who cannot
    python unsubscribe.py news@shop.com        # stop one sender (asks for your yes)
    python unsubscribe.py --check              # weeks later: did they stop, or ignore us?

⚠️ ONLY THE MACHINE-READABLE ROUTE (BR-63).

A sender that publishes List-Unsubscribe-Post can be stopped with one
standard request and no page opened. A sender that only offers a link in the
message body is marked "cannot be stopped this way" and the link is handed to
the Owner — we never click through a stranger's page, because that executes
whatever the page asks and a tracking link confirms the address is live.

⚠️ IRREVERSIBLE, SO IT STOPS AT THE GATE.

You cannot un-unsubscribe. Stage 13 treats it like a send: an exact typed yes,
every time, one sender at a time (BR-65). Anyone the Owner has ever replied
to, and anyone marked important, is never offered here (BR-55, UC-44).

⚠️ AND WE CHECK, RATHER THAN ASSUME (BR-66).

Every request is recorded. --check looks two weeks later at whether mail from
that sender kept arriving, and says "stopped" or "ignoring" — never "done".
"""

import os
import sys
from datetime import datetime, timedelta

import connect
from store import Store
from pipeline import stage13_approval, stage15_unsubscribe as unsub

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

WATCH_DAYS = 14


def candidates(store, me: str) -> list:
    """
    Senders with an unsubscribe header, most mail first, with what we can do.

    Returns rows of (sender, name, count, opened, can_one_click, https, mailto).
    Excludes anyone replied to and anyone protected — those are never offered.
    """
    rows = store.q("""SELECT sender, MAX(sender_name), COUNT(*), COALESCE(SUM(1-unread),0),
                             MAX(unsubscribe), MAX(one_click), MAX(sender_domain)
                        FROM messages
                       WHERE unsubscribe != '' AND in_inbox = 1
                       GROUP BY sender ORDER BY COUNT(*) DESC""")
    out = []
    for sender, name, n, opened, header, one_click, domain in rows:
        if store.history(sender, me)["replied"] > 0:
            continue                                   # BR-55 — never offered
        if store.is_protected(sender, domain):
            continue                                   # UC-44
        o = unsub.options(header, bool(one_click))
        out.append((sender, name or "", n, opened, o["can_one_click"],
                    o["https"], o["mailto"]))
    return out


def show(store, me):
    print(f"\n{C['b']}Senders you could stop{C['0']}")
    print("─" * 72)
    rows = candidates(store, me)
    if not rows:
        print("  none — every sender with an unsubscribe header is one you have "
              "replied to or marked important.\n")
        return
    ready = [r for r in rows if r[4]]
    linkonly = [r for r in rows if not r[4]]
    if ready:
        print(f"\n  {C['g']}READY — one standard request, no page opened{C['0']}")
        for sender, name, n, opened, *_ in ready[:25]:
            print(f"    {n:>5}  {C['dim']}{opened:>4} opened{C['0']}  {(name or sender)[:40]:40} {C['dim']}{sender}{C['0']}")
    if linkonly:
        print(f"\n  {C['y']}CANNOT BE STOPPED THIS WAY — they only offer a web page or an email{C['0']}")
        print(f"  {C['dim']}We will not open a stranger's page for you. The link is yours to click; "
              f"or we can file their mail away instead — that is filing, not stopping.{C['0']}")
        for sender, name, n, opened, _, https, mailto in linkonly[:15]:
            how = "web page" if https else ("by email" if mailto else "no method")
            print(f"    {n:>5}  {(name or sender)[:40]:40} {C['dim']}{how}{C['0']}")
    watching = store.unsubscribes()
    if watching:
        print(f"\n  {C['dim']}{len(watching)} request(s) recorded — "
              f"python unsubscribe.py --check  tells you who actually stopped.{C['0']}")
    print(f"\n  {C['dim']}python unsubscribe.py <address>   to stop one.{C['0']}\n")


def stop_one(conn, store, me, sender):
    sender = sender.lower()
    row = store.q("SELECT MAX(unsubscribe), MAX(one_click), MAX(sender_name), MAX(sender_domain), "
                  "COUNT(*) FROM messages WHERE sender=?", sender)
    if not row or not row[0][0]:
        print(f"\n  {sender} publishes no unsubscribe header. Nothing we can send.\n")
        return
    header, one_click, name, domain, n = row[0]
    if store.history(sender, me)["replied"] > 0:
        print(f"\n  {C['y']}You have replied to {sender} before, so this is not offered "
              f"(BR-55). Unsubscribing cannot be undone by us.{C['0']}\n")
        return
    if store.is_protected(sender, domain):
        print(f"\n  {C['y']}{sender} is marked important. Not offered.{C['0']}\n")
        return
    o = unsub.options(header, bool(one_click))
    print(f"\n{C['b']}Stop {name or sender}{C['0']}  {C['dim']}{n} messages{C['0']}")
    print("─" * 72)
    print(f"  {unsub.describe(o)}")
    if not o["can_one_click"]:
        if o["https"]:
            print(f"  {C['dim']}link: {o['https'][:90]}{C['0']}")
        print(f"\n  {C['y']}Nothing sent. We can file their mail away instead — "
              f"python sort_mailbox.py labels it — but that is filing, not stopping.{C['0']}\n")
        return

    print(f"\n  {C['r']}This cannot be undone by us. Only the sender can put you back.{C['0']}")
    ap = stage13_approval.Approval("unsubscribe", draft=f"unsubscribe {sender}")
    try:
        typed = input(f"  Stop {sender}? type yes: ").strip()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    ok, why = ap.grant(typed)
    if not ok:
        print(f"  {why}. Nothing sent.\n")
        return

    pid = store.one("SELECT provider_id FROM messages WHERE sender=? ORDER BY date_iso DESC LIMIT 1", sender)
    r = stage13_approval.execute(conn, "unsubscribe", pid, draft="", approval=ap,
                                 extra={"unsubscribe": header, "one_click": bool(one_click)})
    if r["done"]:
        store.note_unsubscribe(sender)
        store.record_action("", pid, "unsubscribe", sender)
        print(f"\n  {C['g']}request sent.{C['0']} We will watch for {WATCH_DAYS} days and tell you "
              f"whether {sender} actually stopped.\n")
    else:
        print(f"\n  {C['r']}not done:{C['0']} {r['reason']}\n")


def check(store):
    """BR-66. A request is a success only if the mail actually stopped."""
    print(f"\n{C['b']}Did they stop?{C['0']}")
    print("─" * 72)
    rows = store.unsubscribes()
    if not rows:
        print("  no unsubscribe requests recorded yet.\n")
        return
    now = datetime.now()
    for sender, requested_at, outcome, checked_at in rows:
        since = datetime.fromisoformat(requested_at)
        days = (now - since).days
        after = store.one("SELECT COUNT(*) FROM messages WHERE sender=? AND date_iso > ?",
                          sender, requested_at)
        if days < WATCH_DAYS and after == 0:
            print(f"  {C['dim']}watching{C['0']}  {sender:44} {days} day(s), nothing since")
            continue
        if after == 0:
            store.set_unsubscribe_outcome(sender, "stopped")
            print(f"  {C['g']}stopped {C['0']}  {sender:44} nothing in {days} days")
        else:
            store.set_unsubscribe_outcome(sender, "ignoring")
            print(f"  {C['r']}ignoring{C['0']}  {sender:44} {after} more since the request — "
                  f"we can file their mail away instead")
    print()


def main():
    store = Store()
    if "--check" in sys.argv:
        return check(store)
    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()
    target = next((a for a in sys.argv[1:] if "@" in a), None)
    if target:
        stop_one(conn, store, me, target)
    else:
        show(store, me)


if __name__ == "__main__":
    main()
