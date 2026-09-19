"""
UC-18 — Where the space went, and what clearing would actually free.

    python storage.py                  # the largest messages, grouped by sender
    python storage.py --clear x@y.com  # trash that sender's large, unprotected mail (asks)

⚠️ SIZE ALONE NEVER JUSTIFIES DELETION (BR-67).

A large message is as likely to be a signed contract as a marketing video. So
the pile's protections apply in full: anything from someone the Owner has
replied to, anything marked important, and anything that looks like a record
(invoice, receipt, contract, statement, booking, signed) is marked protected
and kept out of bulk selection.

⚠️ SIZES COME FREE. Every message's size is already in the index — nothing
is downloaded to build this view. And the space is only reported once the
provider has moved the messages; the trash holds it until emptied, which we
say before the Owner notices and doubts the result (BR-69).
"""

import os
import re
import sys

import connect
from store import Store
from pipeline import stage13_approval

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

MB = 1024 * 1024
RECORD = re.compile(r"\b(invoice|receipt|contract|agreement|statement|booking|"
                    r"confirmation|ticket|signed|certificate|policy|payslip|"
                    r"tax|itinerary|boarding)\b", re.I)


def protected(store, me, sender, domain, subject) -> str:
    """Why this must not be bulk-cleared, or '' if it may be."""
    if store.history(sender, me)["replied"] > 0:
        return "you have replied to this sender"
    if store.is_protected(sender, domain):
        return "marked important"
    if RECORD.search(subject or ""):
        return "looks like a record"
    return ""


def show(store, me, limit=25):
    print(f"\n{C['b']}Where the space has gone{C['0']}")
    print("─" * 74)
    total = store.one("SELECT COALESCE(SUM(size),0) FROM messages")
    print(f"  {total/MB:,.0f} MB across {store.one('SELECT COUNT(*) FROM messages'):,} messages\n")

    print(f"  {C['b']}Largest messages{C['0']}")
    rows = store.q("""SELECT provider_id, sender, sender_name, sender_domain, subject,
                             date_iso, size FROM messages
                       ORDER BY size DESC LIMIT ?""", limit)
    for pid, sender, name, domain, subject, date, size in rows:
        why = protected(store, me, sender, domain, subject)
        mark = f"{C['y']}kept — {why}{C['0']}" if why else ""
        print(f"    {size/MB:>6.1f} MB  {(subject or '(no subject)')[:40]:40} "
              f"{C['dim']}{(name or sender)[:22]:22} {(date or '')[:10]}{C['0']}  {mark}")

    print(f"\n  {C['b']}By sender{C['0']}  {C['dim']}(what clearing the unprotected part would free){C['0']}")
    groups = store.q("""SELECT sender, MAX(sender_name), MAX(sender_domain), COUNT(*), SUM(size)
                          FROM messages GROUP BY sender ORDER BY SUM(size) DESC LIMIT 15""")
    for sender, name, domain, n, size in groups:
        free = store.one("""SELECT COALESCE(SUM(size),0) FROM messages WHERE sender=?""", sender)
        rep = store.history(sender, me)["replied"] > 0 or store.is_protected(sender, domain)
        if rep:
            note = f"{C['y']}protected — not offered{C['0']}"
        else:
            note = f"would free {C['g']}{free/MB:,.0f} MB{C['0']} (records inside are kept)"
        print(f"    {size/MB:>6.0f} MB  {n:>5}  {(name or sender)[:34]:34}  {note}")
    print(f"\n  {C['dim']}python storage.py --clear <address>   trashes that sender's large, "
          f"unprotected mail — after your yes.{C['0']}\n")


def clear(conn, store, me, sender, min_mb=1.0):
    sender = sender.lower()
    rows = store.q("""SELECT provider_id, message_id, sender_domain, subject, size
                        FROM messages WHERE sender=? AND size >= ? ORDER BY size DESC""",
                   sender, int(min_mb * MB))
    if not rows:
        print(f"\n  nothing from {sender} over {min_mb} MB.\n"); return
    keep = [(r, protected(store, me, sender, r[2], r[3])) for r in rows]
    go = [r for r, why in keep if not why]
    held = [(r, why) for r, why in keep if why]
    if not go:
        print(f"\n  {C['y']}everything from {sender} is protected:{C['0']}")
        for r, why in held[:5]:
            print(f"    {(r[3] or '')[:50]:50} {C['dim']}{why}{C['0']}")
        print(); return

    size = sum(r[4] for r in go)
    print(f"\n{C['b']}Clear {len(go)} message(s) from {sender}{C['0']}  frees about {size/MB:,.0f} MB")
    print("─" * 74)
    for r in go[:10]:
        print(f"    {r[4]/MB:>6.1f} MB  {(r[3] or '(no subject)')[:56]}")
    if held:
        print(f"  {C['dim']}keeping {len(held)} — records or correspondence{C['0']}")
    print(f"\n  They go to your provider's trash, where you can still recover them.")
    print(f"  The space comes back when the trash is emptied (Gmail: after 30 days).")

    ap = stage13_approval.Approval("trash", draft=f"trash {len(go)} from {sender}")
    try:
        typed = input(f"  Move {len(go)} to trash? type yes: ").strip()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    ok, why = ap.grant(typed)
    if not ok:
        print(f"  {why}. Nothing moved.\n"); return

    done = 0
    for pid, mid, domain, subject, sz in go:
        live = connect.live_id(conn, pid, mid) or pid
        r = stage13_approval.execute(conn, "trash", live, draft=ap.draft, approval=ap)
        if r["done"]:
            store.record_action(mid, pid, "trash", (subject or "")[:70], before="INBOX")
            done += 1
        else:
            print(f"    {C['r']}could not: {(subject or '')[:40]} — {r['reason'][:40]}{C['0']}")
    print(f"\n  {C['g']}{done} moved to trash.{C['0']} About {size/MB:,.0f} MB comes back when "
          f"the trash is emptied.  python history.py --undo  puts any of them back.\n")


def main():
    store = Store()
    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()
    if "--clear" in sys.argv:
        i = sys.argv.index("--clear")
        if i + 1 < len(sys.argv):
            return clear(conn, store, me, sys.argv[i + 1])
        print("  --clear needs an address"); return
    show(store, me)


if __name__ == "__main__":
    main()
