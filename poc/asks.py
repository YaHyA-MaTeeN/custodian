"""
UC-33 and UC-45 — What people asked of you, and what you promised them.

    python asks.py                    # everything open, nearest date first
    python asks.py --scan             # read new personal mail for requests (UC-33)
    python asks.py --promises         # read your recent sent mail for promises (UC-45)
    python asks.py --done 4           # you did it
    python asks.py --dismiss 4        # it was never a real request — recorded as a correction

⚠️ NEW MAIL ONLY, NEVER THE BACKLOG. --scan reads messages that arrived after
the last scan (or the last 3 days on first run). Ten years of history is not
read for requests: the cost is real and the requests are stale.

⚠️ THE CHEAP FILTER RUNS FIRST. Bulk mail is ruled out from the envelope,
sensitive mail is never opened, and only messages our own classifier says
need a response reach the paid model — on redacted text (stage 18).

⚠️ A PROMISE MADE FOR SOMEONE ELSE IS NOT TRACKED (UC-45 EX-2). "My colleague
will send it" is not the Owner's promise. And delivering closes it (BR-177):
a later message in the same thread from the Owner with an attachment or
"attached / here it is" marks the promise done.
"""

import os
import re
import sys
from datetime import datetime, timedelta

import connect
from store import Store
from pipeline import (stage02_strip, stage03_sensitive, stage04_headers,
                      local_classifier, stage18_requests)

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

DELIVERED = re.compile(r"\b(attached|here it is|here you go|please find|sending it now|"
                       r"as promised|done)\b", re.I)


def _since(store, key: str, default_days: int) -> str:
    last = store.one("SELECT MAX(at) FROM requests WHERE direction=?", key)
    if last:
        return str(last)[:19]
    return (datetime.now() - timedelta(days=default_days)).isoformat()[:19]


def scan_incoming(conn, store, me, limit=40, days=None):
    """UC-33. New personal mail → requests of the Owner."""
    since = ((datetime.now() - timedelta(days=days)).isoformat()[:19]
             if days else _since(store, "ask", 3))
    rows = store.q("""SELECT provider_id, message_id, sender, sender_name, sender_domain,
                             subject, date_iso, bulk, unsubscribe, auto_sub, in_reply_to, account
                        FROM messages WHERE in_inbox=1 AND date_iso > ?
                       ORDER BY date_iso DESC LIMIT ?""", since, limit)
    print(f"\n{C['b']}Reading new mail for requests{C['0']}  {C['dim']}since {since[:16]}{C['0']}")
    print("─" * 72)
    looked = found = 0
    from connectors.base import Envelope
    for pid, mid, sender, sname, domain, subject, date, bulk, unsub, auto, irt, account in rows:
        if store.has_request(mid):
            continue
        if bulk or unsub or auto:
            continue                                            # BR-118
        if stage03_sensitive.check(sender, subject or "", domain or "")["sensitive"]:
            continue
        if sender.lower() == (me or "").lower():
            continue
        try:
            raw = connect.fetch_verified(conn, pid, mid)
        except Exception:
            continue
        text = stage02_strip.strip(raw)["text"]
        if not text.strip():
            continue
        # Cheap gate: our own classifier says whether this even asks anything.
        if local_classifier.available():
            lab = local_classifier.classify(text, subject or "", sender)
            if lab.get("intent") != "needs a response from you" and lab.get("confidence", 0) > 0.7:
                continue
        looked += 1
        items = stage18_requests.extract(text, subject, "incoming")
        for it in items:
            who = {"me": "me", "sender": sender, "third party": "third party"}[it["who"]]
            store.add_request(mid, pid, account, "ask", it["what"], who, it["due"],
                              it["evidence"], it["confidence"])
            found += 1
            flag = f"{C['c']}you{C['0']}" if who == "me" else f"{C['dim']}{who}{C['0']}"
            print(f"  {flag:>8}  {it['what'][:52]:52} {C['dim']}{it['due'][:10] or 'no date'}{C['0']}")
    print(f"\n  {looked} message(s) read once, {found} request(s) recorded. "
          f"{C['dim']}Bodies discarded.{C['0']}\n")


def scan_sent(conn, store, me, limit=40):
    """UC-45. The Owner's recent sent mail → promises."""
    since = _since(store, "promise", 7)
    rows = store.q("""SELECT provider_id, message_id, recipients, subject, date_iso, account
                        FROM messages WHERE sender=? AND date_iso > ?
                       ORDER BY date_iso DESC LIMIT ?""", (me or "").lower(), since, limit)
    print(f"\n{C['b']}Reading your sent mail for promises{C['0']}  {C['dim']}since {since[:16]}{C['0']}")
    print("─" * 72)
    found = 0
    for pid, mid, to, subject, date, account in rows:
        if store.has_request(mid):
            continue
        try:
            raw = connect.fetch_verified(conn, pid, mid)
        except Exception:
            continue
        text = stage02_strip.strip(raw)["text"]
        for it in stage18_requests.extract(text, subject, "sent"):
            if it["who"] != "sender":
                continue                                        # EX-2: not the Owner's promise
            addr = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", to or "")
            store.add_request(mid, pid, account, "promise", it["what"],
                              addr[0].lower() if addr else "", it["due"],
                              it["evidence"], it["confidence"])
            found += 1
            print(f"  to {(addr[0] if addr else '?')[:26]:26} {it['what'][:40]:40} "
                  f"{C['dim']}{it['due'][:10] or 'no date'}{C['0']}")
    print(f"\n  {found} promise(s) recorded.\n")


def close_delivered(store, me):
    """BR-177: a later message from the Owner in the same thread with an attachment or 'attached'."""
    n = 0
    for r in store.open_requests("promise"):
        rid, mid = r[0], r[1]
        later = store.q("""SELECT subject FROM messages WHERE sender=? AND in_reply_to=?
                            ORDER BY date_iso DESC LIMIT 1""", (me or "").lower(), mid)
        if later and DELIVERED.search(later[0][0] or ""):
            store.set_request_status(rid, "done"); n += 1
    return n


def show(store, me):
    asks = store.open_requests("ask")
    proms = store.open_requests("promise")
    print(f"\n{C['b']}Open{C['0']}  {C['dim']}{len(asks)} asked of you · {len(proms)} you promised{C['0']}")
    print("─" * 72)
    if asks:
        print(f"\n  {C['b']}Asked of you{C['0']}")
        for r in asks:
            rid, mid, d, what, who, due, ev, conf, sender, sname, subject, to, date = r
            if who not in ("me",):
                continue
            print(f"  {rid:>3}. {what[:50]:50} {C['c']}{due[:10] or 'no date':10}{C['0']} "
                  f"{C['dim']}{(sname or sender or '')[:22]}{C['0']}")
            print(f"       {C['dim']}“{(ev or '')[:80]}”{C['0']}")
    if proms:
        print(f"\n  {C['b']}You promised{C['0']}")
        for r in proms:
            rid, mid, d, what, who, due, ev, conf, *_ = r
            print(f"  {rid:>3}. {what[:50]:50} {C['c']}{due[:10] or 'no date':10}{C['0']} "
                  f"{C['dim']}to {who[:22]}{C['0']}")
    if not asks and not proms:
        print("  nothing open.  python asks.py --scan  reads new mail.")
    print(f"\n  {C['dim']}--done N · --dismiss N · --scan · --promises{C['0']}\n")


def main():
    store = Store()
    args = sys.argv[1:]
    if "--done" in args:
        store.set_request_status(int(args[args.index("--done") + 1]), "done")
        print("\n  marked done.\n"); return
    if "--dismiss" in args:
        rid = int(args[args.index("--dismiss") + 1])
        r = next((x for x in store.open_requests() if x[0] == rid), None)
        store.set_request_status(rid, "dismissed")
        if r and r[8]:
            store.add_correction("sender", r[8], was="request", should_be="not a request")
        print("\n  dismissed, and recorded as a correction.\n"); return
    if "--scan" in args or "--promises" in args:
        conn = connect.open_mailbox(quiet=True)
        me = conn.account_email()
        days = int(args[args.index("--days") + 1]) if "--days" in args else None
        if "--scan" in args:
            scan_incoming(conn, store, me, days=days)
        if "--promises" in args:
            scan_sent(conn, store, me)
            n = close_delivered(store, me)
            if n:
                print(f"  {n} promise(s) closed — you delivered.\n")
        return
    show(store, "")


if __name__ == "__main__":
    main()
