"""
UC-44 — This person matters. One action, every protection.

    python important.py                    # who is marked
    python important.py ahmed@acc.com      # mark (shows what it means, asks yes)
    python important.py --remove ahmed@acc.com

⚠️ ONE ACTION SETS ALL OF IT (BR-170): never in the pile, never unsubscribed,
never swept with a brand, always at the top. Saved as a set of rules created
together and removed together (UC-38 machinery), covering every address the
person uses (UC-41) — including addresses linked later.

⚠️ SHOWN BACK AND CONFIRMED BEFORE SAVING (BR-172), like any rule. And it
never raises an alert (BR-173): important people rise in the list and the
digest; they do not interrupt.
"""

import os
import sys
import uuid

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")


def show(store):
    print(f"\n{C['b']}People marked important{C['0']}")
    print("─" * 60)
    groups = {}
    for rid, sentence, kind, value, action, arg, plain, gid, at in store.rules():
        if action == "top" and gid:
            groups.setdefault(gid, []).append(value)
    if not groups:
        print("  nobody yet.  python important.py <address>\n"); return
    for gid, addrs in groups.items():
        print(f"  {', '.join(sorted(set(addrs)))}")
    print()


def mark(store, address):
    address = address.lower()
    addrs = sorted({a for a, _, _ in store.addresses_of(address)} | {address})
    name = store.one("SELECT sender_name FROM messages WHERE sender=? AND sender_name!='' LIMIT 1",
                     address) or address
    print(f"\n{C['b']}{name}{C['0']}  {C['dim']}({len(addrs)} address{'es' if len(addrs)>1 else ''}){C['0']}")
    print("─" * 60)
    print(f"  will never be cleared, unsubscribed or swept, and will always be at the top.")
    print(f"  {C['dim']}Important people rise in your list and digest. They never interrupt you.{C['0']}")
    try:
        typed = input("  Save? type yes: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    if typed != "yes":
        print("  nothing saved.\n"); return
    gid = f"important-{uuid.uuid4().hex[:8]}"
    plain = f"{name}: never cleared, unsubscribed or swept; always at the top"
    for a in addrs:
        store.add_rule(f"this person matters: {address}", "person", a, "protect", "", plain, gid)
        store.add_rule(f"this person matters: {address}", "person", a, "top", "", plain, gid)
    store.record_action("", "", "correction", f"marked important: {', '.join(addrs)}")
    print(f"\n  {C['g']}saved.{C['0']} From the next message on, every part of the system respects it.\n")


def remove(store, address):
    address = address.lower()
    gids = {r[7] for r in store.rules_for(address) if r[7] and r[7].startswith("important-")}
    n = sum(store.remove_rule_group(g) for g in gids)
    print(f"\n  removed {n} rule(s) — the whole set, together.\n" if n else "\n  not marked.\n")


def main():
    store = Store()
    args = sys.argv[1:]
    if "--remove" in args:
        return remove(store, args[args.index("--remove") + 1])
    target = next((a for a in args if "@" in a), None)
    if target:
        return mark(store, target)
    show(store)


if __name__ == "__main__":
    main()
