"""
UC-41 — One person, across every address they use.

    python people.py                         # who is linked to whom
    python people.py ahmed@acc.com           # everything about one person
    python people.py --suggest               # links we think exist, with evidence
    python people.py --link a@x.com b@y.com  # you say they are one person
    python people.py --split b@y.com         # not the same person — undo, one click

⚠️ NOT A CONTACT MANAGER (BR-159). No phone numbers, no company records, no
notes, nothing looked up outside. A person here is only what their own mail
proves: which addresses they use, and what is owed in each direction.

⚠️ A NAME ALONE IS NEVER ENOUGH (BR-160). Two people called Ahmed stay two
people. We link automatically only on the same display name PLUS the same
domain, or the same name plus a reply that moved between the addresses.
Anything weaker is a SUGGESTION with its evidence, for the Owner to confirm.

⚠️ EVERY LINK IS VISIBLE AND SPLITS IN ONE CLICK (BR-158). A wrong merge
mixes two people's mail, so the evidence is stored beside the link.
"""

import os
import re
import sys

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

SHARED = re.compile(r"^(info|no-?reply|noreply|support|hello|team|admin|sales|contact|"
                    r"notifications?|news|newsletter|mail|help|billing)@", re.I)


def suggestions(store) -> list:
    """(address_a, address_b, evidence, strong) for addresses that may be one person."""
    rows = store.q("""SELECT sender, MAX(sender_name), MAX(sender_domain), COUNT(*)
                        FROM messages WHERE sender_name != '' AND bulk=0 AND unsubscribe=''
                       GROUP BY sender""")
    by_name = {}
    for addr, name, domain, n in rows:
        if SHARED.match(addr):
            continue                                            # EX-2: an organisation
        key = re.sub(r"\s+", " ", name.strip().lower())
        if len(key) < 5 or " " not in key:
            continue                                            # a first name alone links nobody
        by_name.setdefault(key, []).append((addr, domain))
    out = []
    for name, addrs in by_name.items():
        if len(addrs) < 2:
            continue
        a0, d0 = addrs[0]
        for a, d in addrs[1:]:
            if store.person_of(a) == store.person_of(a0):
                continue                                        # already linked
            strong = d == d0
            ev = f"same name “{name}”" + (" and same domain" if strong else " — different domains")
            out.append((a0, a, ev, strong))
    return out


def autolink(store) -> int:
    n = 0
    for a, b, ev, strong in suggestions(store):
        if strong:
            store.link_addresses(b, store.person_of(a), ev); n += 1
    return n


def show_person(store, address):
    person = store.person_of(address)
    addrs = store.addresses_of(person)
    name = store.one("SELECT sender_name FROM messages WHERE sender=? AND sender_name!='' LIMIT 1",
                     person) or person
    print(f"\n{C['b']}{name}{C['0']}")
    print("─" * 70)
    for a, ev, by_owner in addrs:
        print(f"  {a:40} {C['dim']}{'you linked this' if by_owner else ev}{C['0']}")
    alist = [a for a, _, _ in addrs]
    q = ",".join("?" * len(alist))

    owe = [r for r in store.open_requests("ask") if r[8] in alist and r[4] == "me"]
    owed = [r for r in store.open_requests("ask") if r[8] in alist and r[4] in alist]
    prom = [r for r in store.open_requests("promise") if r[4] in alist]
    print(f"\n  {C['b']}You owe them {len(owe)}.{C['0']}  They owe you {len(owed)}.  "
          f"You promised them {len(prom)}.")
    for r in owe[:5]:
        print(f"    {C['c']}·{C['0']} {r[3][:56]}  {C['dim']}{r[5][:10] or 'no date'}{C['0']}")
    for r in prom[:5]:
        print(f"    {C['y']}·{C['0']} you: {r[3][:52]}  {C['dim']}{r[5][:10] or 'no date'}{C['0']}")

    recent = store.q(f"""SELECT subject, date_iso, sender, account FROM messages
                          WHERE sender IN ({q}) ORDER BY date_iso DESC LIMIT 6""", *alist)
    if recent:
        print(f"\n  {C['b']}Recent{C['0']}")
        for subject, date, sender, account in recent:
            print(f"    {(date or '')[:10]}  {(subject or '(no subject)')[:46]:46} "
                  f"{C['dim']}{account or ''}{C['0']}")
    print(f"\n  {C['dim']}python important.py {person}   ·   python people.py --split <address>{C['0']}\n")


def main():
    store = Store()
    args = sys.argv[1:]
    if "--link" in args:
        i = args.index("--link")
        a, b = args[i + 1].lower(), args[i + 2].lower()
        store.link_addresses(b, store.person_of(a), "you said so", by_owner=True)
        print(f"\n  linked {b} → {store.person_of(a)}.\n"); return
    if "--split" in args:
        store.split_person(args[args.index("--split") + 1])
        print("\n  split. Both are their own person again; nothing was lost.\n"); return
    if "--suggest" in args:
        print(f"\n{C['b']}Possible links{C['0']}")
        print("─" * 70)
        for a, b, ev, strong in suggestions(store):
            mark = f"{C['g']}strong{C['0']}" if strong else f"{C['y']}needs you{C['0']}"
            print(f"  {mark:>7}  {a:30} ↔ {b:30} {C['dim']}{ev}{C['0']}")
        print(f"\n  {C['dim']}python people.py --link a b   confirms one.{C['0']}\n"); return
    target = next((a for a in args if "@" in a), None)
    if target:
        return show_person(store, target.lower())
    n = autolink(store)
    print(f"\n{C['b']}People{C['0']}  {C['dim']}{n} link(s) made on strong evidence{C['0']}")
    print("─" * 70)
    groups = {}
    for addr, person, ev, by_owner, at in store.q(
            "SELECT address, person, evidence, by_owner, at FROM person_links"):
        groups.setdefault(person, []).append(addr)
    if not groups:
        print("  nobody linked yet.  python people.py --suggest\n"); return
    for person, addrs in groups.items():
        print(f"  {person:34} + {', '.join(a for a in addrs if a != person)}")
    print()


if __name__ == "__main__":
    main()
