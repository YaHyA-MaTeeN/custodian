"""
UC-27 / UC-28 — Every account in one list, and one search across all of them.

    python inbox.py                  # the merged inbox
    python inbox.py --account x@y    # only that mailbox
    python inbox.py --needs-reply    # only what needs you
    python inbox.py --find linkedin  # search every mailbox at once

⚠️ THIS IS WHAT MAKES "ALL YOUR ACCOUNTS, ONE PRICE" A PRODUCT.

Gmail cannot search your Outlook. Outlook cannot search your Yahoo. Nobody a
customer can buy searches all of them at once. That is the whole pitch, and it
is worth nothing until the list actually merges.

⚠️ WHAT WE DELIBERATELY DO NOT BUILD.

A mail client. No composing from scratch, no calendar, no contacts, no offline.
Every company that tried to own the whole mail experience here has died or been
sold. We are a layer on top of mailboxes people already have.

⚠️ AND HOW SEARCH WORKS, WHICH IS A DECISION NOT AN ACCIDENT (BR-102/103).

We search OUR INDEX — sender, subject, date, category, account — not the
providers. Asking four providers and merging their answers is slow,
inconsistent, and broken whenever any one of them is down.

Searching INSIDE message text would mean storing the words of every message,
which is close to holding the mail itself. BR-103 leaves that open, and this
file does not quietly decide it: envelope search only, and it says so.
"""

import os
import sys
from collections import defaultdict

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# One colour per account so the eye can separate them without reading.
ACCOUNT_COLOURS = [C["c"], C["g"], C["y"], C["r"]]


def arg_after(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default


def accounts(store) -> list[str]:
    rows = store.q("SELECT DISTINCT COALESCE(account,'') FROM messages "
                   "WHERE COALESCE(account,'') != ''")
    return sorted(r[0] for r in rows)


def collapse_duplicates(rows: list) -> tuple[list, dict]:
    """
    ⚠️ BR-99 — ONE MESSAGE, SHOWN ONCE.

    A message sent to two of the Owner's addresses arrives twice and is the
    same message. We match on Message-ID, which every message carries and which
    is the only identifier that means the same thing in every mailbox.

    Both copies are REMEMBERED, not discarded, because an action has to apply
    to both — filing it in one account while it sits unread in the other is
    exactly the failure the merged inbox exists to prevent.
    """
    seen, out, copies = {}, [], defaultdict(list)
    for r in rows:
        mid = r[0] or ""
        copies[mid].append((r[-1], r[1]))          # (account, provider_id)
        if mid and mid in seen:
            continue                               # a duplicate — already shown
        if mid:
            seen[mid] = True
        out.append(r)
    return out, {k: v for k, v in copies.items() if len(v) > 1}


def show(store, only_account=None, needs_reply=False, query=None, limit=40):
    accs = accounts(store)
    colour = {a: ACCOUNT_COLOURS[i % len(ACCOUNT_COLOURS)] for i, a in enumerate(accs)}

    where, args = ["in_inbox = 1"], []
    if only_account:
        where.append("account = ?")
        args.append(only_account)
    if query:
        # BR-102 — envelope fields only. Never the body, which we do not hold.
        where.append("(subject LIKE ? OR sender LIKE ? OR sender_name LIKE ?)")
        args += [f"%{query}%"] * 3
    args.append(limit * 3)                         # room to collapse duplicates

    rows = store.q(f"""SELECT message_id, provider_id, sender, sender_name,
                              subject, date, unread, COALESCE(account,'(unknown)')
                         FROM messages WHERE {' AND '.join(where)}
                        ORDER BY date_iso DESC LIMIT ?""", *args)

    if needs_reply:
        keep = {r[0] for r in store.q(
            "SELECT message_id FROM decisions WHERE decision LIKE '%needs a reply%'")}
        rows = [r for r in rows if r[0] in keep]

    rows, dupes = collapse_duplicates(rows)
    rows = rows[:limit]

    title = "Search" if query else "Inbox"
    print(f"\n{C['b']}{title}{C['0']}  {C['dim']}across "
          f"{len(accs) or 1} mailbox(es){C['0']}")
    if query:
        print(f"  {C['dim']}matching {query!r} — sender, subject and name. "
              f"Not message text (BR-103).{C['0']}")
    print("─" * 76)

    if not accs:
        print(f"  {C['y']}Only one mailbox is connected, and it predates the "
              f"account column.{C['0']}")
        print(f"  {C['dim']}Run  python run.py  again to stamp every message "
              f"with its account.{C['0']}")
    else:
        for a in accs:
            n = store.one("SELECT COUNT(*) FROM messages WHERE account=? "
                          "AND in_inbox=1", a)
            print(f"  {colour[a]}●{C['0']} {a:<34} {n:>6,} in inbox")
    print("─" * 76)

    if not rows:
        print(f"\n  nothing to show.\n")
        return

    for mid, pid, sender, name, subject, date, unread, acc in rows:
        dot = colour.get(acc, C["dim"])
        flag = C["b"] if unread else C["dim"]
        extra = ""
        if mid in dupes:
            others = {a for a, _ in dupes[mid]}
            extra = f"  {C['y']}[also in {len(others)-1} other]{C['0']}"
        print(f"  {dot}●{C['0']} {flag}{(subject or '(no subject)')[:46]:<46}{C['0']} "
              f"{C['dim']}{(name or sender)[:20]:<20}{C['0']}{extra}")
        # BR-98 — every row says which account it came from. Never inferred.
        print(f"    {C['dim']}{acc} · {(date or '')[:16]}{C['0']}")

    print("─" * 76)
    print(f"  {len(rows)} shown")
    if dupes:
        print(f"  {C['y']}{len(dupes)} message(s) reached more than one of your "
              f"addresses — shown once (BR-99).{C['0']}")
        print(f"  {C['dim']}Both copies are remembered, so filing one files "
              f"both.{C['0']}")
    print()


def capabilities():
    """
    BR-100 — one button, different meanings underneath. Worth printing,
    because it is the part everyone assumes is magic.
    """
    print(f"\n{C['b']}What each provider can actually do{C['0']}")
    print("─" * 76)
    print(f"  {'':<16} {'push':>6} {'labels':>8} {'threads':>9} {'send':>6}   filing means")
    rows = [
        ("Gmail",   True,  True,  True,  True,  "add a label — the message does not move"),
        ("Outlook", True,  True,  True,  True,  "add a category, or move to a folder"),
        ("JMAP",    True,  True,  True,  True,  "add a keyword"),
        ("IMAP",    False, False, False, False, "COPY to a folder, then delete here"),
    ]
    for nm, push, lab, thr, snd, filing in rows:
        y = lambda b: (C["g"] + "yes" + C["0"]) if b else (C["y"] + "no" + C["0"])
        print(f"  {nm:<16} {y(push):>15} {y(lab):>17} {y(thr):>17} {y(snd):>15}")
        print(f"  {C['dim']}{'':<16} {filing}{C['0']}")
    print("─" * 76)
    print(f"  {C['dim']}The pipeline asks WHAT CAN YOU DO, never WHO ARE YOU.")
    print(f"  A fifth provider is one new file and no changes anywhere "
          f"else.{C['0']}\n")


def main():
    store = Store()
    if "--capabilities" in sys.argv:
        return capabilities()
    show(store,
         only_account=arg_after("--account"),
         needs_reply="--needs-reply" in sys.argv,
         query=arg_after("--find"))


if __name__ == "__main__":
    main()
