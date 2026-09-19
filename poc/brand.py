"""
UC-16 — One company's clutter, without its receipts.

    python brand.py                     # companies, not addresses
    python brand.py linkedin.com        # that company's mail, split by what it is
    python brand.py --clear linkedin.com   # trash its advertising, keep its records (asks)
    python brand.py --protect linkedin.com # keep everything from it, forever

⚠️ WHO REALLY SENT IT. The strongest evidence is the DKIM signing domain in
the provider's Authentication-Results stamp — the same account signs mail
from a dozen different-looking addresses (BR-60). That header is only held
for mail indexed since it was added, so where it is missing the fallback is
the root of the sender's domain plus a matching display name, and the view
says the grouping is less certain (EX-2). Two companies on one shared bulk
provider are never merged on the sending account alone (EX-1).

⚠️ A NARROWER PILE, NOT A LICENCE TO DELETE MORE (BR-62). Every pile rule
applies: replied-to senders and marked-important people are never offered,
and anything that looks like a record is held back and named as protected.
"""

import os
import re
import sys
from collections import defaultdict

import connect
from store import Store
from storage import RECORD
from pipeline import stage13_approval

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

DKIM = re.compile(r"dkim=pass[^;]*?header\.(?:d|i)=@?([\w.-]+)", re.I)
TWO_PART_TLD = ("co.uk", "com.au", "co.nz", "com.pk", "org.uk", "ac.uk", "com.br")


def root(domain: str) -> str:
    """e.linkedin.com → linkedin.com; mail.grammarly.com → grammarly.com."""
    parts = (domain or "").lower().split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_PART_TLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def companies(store, me) -> dict:
    """{company: {addresses:set, names:set, n, certain:bool, ids:[...]}}"""
    rows = store.q("""SELECT sender, sender_name, sender_domain, COALESCE(auth_results,''),
                             provider_id, message_id, subject, bulk, unsubscribe
                        FROM messages WHERE in_inbox=1 AND (bulk=1 OR unsubscribe!='')""")
    out = defaultdict(lambda: {"addresses": set(), "names": set(), "n": 0,
                               "certain": False, "ids": []})
    for sender, name, domain, auth, pid, mid, subject, bulk, unsub in rows:
        m = DKIM.search(auth or "")
        key = root(m.group(1)) if m else root(domain)
        g = out[key]
        g["addresses"].add(sender); g["names"].add((name or "").strip())
        g["n"] += 1; g["ids"].append((sender, pid, mid, subject))
        if m:
            g["certain"] = True
    # Never offer a company the Owner corresponds with or protects.
    for key, g in list(out.items()):
        if any(store.history(a, me)["replied"] > 0 or store.is_protected(a, key)
               for a in g["addresses"]) or store.is_protected("", key):
            del out[key]
    return out


def split(g) -> tuple:
    keep = [x for x in g["ids"] if RECORD.search(x[3] or "")]
    go = [x for x in g["ids"] if not RECORD.search(x[3] or "")]
    return go, keep


def show_all(store, me):
    cs = companies(store, me)
    print(f"\n{C['b']}Companies{C['0']}  {C['dim']}{len(cs)} found{C['0']}")
    print("─" * 72)
    for key, g in sorted(cs.items(), key=lambda kv: -kv[1]["n"])[:30]:
        go, keep = split(g)
        sure = "" if g["certain"] else f" {C['y']}less certain{C['0']}"
        print(f"  {g['n']:>5}  {key:32} {C['dim']}{len(g['addresses'])} address(es){C['0']}{sure}"
              + (f"  {C['dim']}{len(keep)} records kept{C['0']}" if keep else ""))
    print(f"\n  {C['dim']}python brand.py <company>   shows the split.{C['0']}\n")


def show_one(store, me, key):
    cs = companies(store, me)
    g = cs.get(key)
    if not g:
        print(f"\n  {key} is not in the list — no bulk mail, or you correspond with them.\n"); return
    go, keep = split(g)
    print(f"\n{C['b']}{key}{C['0']}  {C['dim']}we matched {len(g['addresses'])} addresses to this company"
          f"{'' if g['certain'] else ' — less certain, grouped by domain and name'}{C['0']}")
    print("─" * 72)
    print(f"  {C['b']}Advertising and notifications{C['0']} — {len(go)} — offered for clearing")
    for s, pid, mid, subject in go[:8]:
        print(f"    {(subject or '(no subject)')[:60]}")
    print(f"\n  {C['g']}Protected{C['0']} — {len(keep)} — receipts, bookings, statements are kept")
    for s, pid, mid, subject in keep[:6]:
        print(f"    {(subject or '')[:60]}")
    print(f"\n  {C['dim']}python brand.py --clear {key}   clears the first group after your yes."
          f"\n  python brand.py --protect {key} keeps everything from them, forever.{C['0']}\n")


def clear(conn, store, me, key):
    cs = companies(store, me)
    g = cs.get(key)
    if not g:
        print(f"\n  {key} is not offered.\n"); return
    go, keep = split(g)
    print(f"\n{C['b']}Clearing {len(go)} advertising messages from {key}. Keeping {len(keep)} records.{C['0']}")
    print("  They go to your provider's trash, where you can still recover them.")
    ap = stage13_approval.Approval("trash", draft=f"trash {len(go)} from {key}")
    try:
        typed = input(f"  Move {len(go)} to trash? type yes: ").strip()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    ok, why = ap.grant(typed)
    if not ok:
        print(f"  {why}. Nothing moved.\n"); return
    done = 0
    for s, pid, mid, subject in go:
        live = connect.live_id(conn, pid, mid) or pid
        r = stage13_approval.execute(conn, "trash", live, draft=ap.draft, approval=ap)
        if r["done"]:
            store.record_action(mid, pid, "trash", (subject or "")[:70], before="INBOX"); done += 1
    print(f"\n  {C['g']}{done} moved to trash.{C['0']} {len(keep)} records untouched. "
          f"python history.py --undo reverses any.\n")


def protect(store, key):
    store.add_rule(f"keep everything from {key}", "domain", key, "protect", "",
                   f"never put mail from {key} in the pile, never unsubscribe, never sweep")
    print(f"\n  {C['g']}{key} is protected.{C['0']} Excluded from every pile and sweep.\n")


def main():
    store = Store()
    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()
    args = sys.argv[1:]
    if "--clear" in args:
        return clear(conn, store, me, args[args.index("--clear") + 1].lower())
    if "--protect" in args:
        return protect(store, args[args.index("--protect") + 1].lower())
    key = next((a for a in args if "." in a and not a.startswith("--")), None)
    if key:
        return show_one(store, me, key.lower())
    show_all(store, me)


if __name__ == "__main__":
    main()
