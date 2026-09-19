"""
UC-15 — The pile. Everything worthless, in one place, cleared on your click.

    python pile.py                        # see it, grouped, with a reason each
    python pile.py --rescue x@y.com       # take a sender out — recorded as a correction
    python pile.py --clear x@y.com        # trash that group (asks for your yes)
    python pile.py --clear all            # trash every group (asks for your yes)
    python pile.py --archive x@y.com      # gentler: out of the inbox, not deleted

⚠️ THE MOST DANGEROUS USE CASE IN THE SYSTEM.

A person facing 8,000 messages will not read them. They will press the
button. Whatever is in the pile is what gets cleared. So the five rules that
decide what gets IN are the whole feature, and every one is enforced here:

    BR-54  only POSITIVE proof of bulk mail — an unsubscribe header, an
           automated-message marker, a bulk precedence. Absence of evidence
           is never evidence.
    BR-55  nothing from anyone the Owner has EVER replied to.
    BR-56  nothing that looks like one person writing to one person.
    BR-57  nothing that looks like a record — receipt, booking, statement,
           contract, ticket — even from a sender whose advertising is cleared.
    BR-58  when uncertain, keep.

⚠️ WE NEVER ISSUE A DELETION (BR-59). Clearing is a move to the provider's
Trash, on the Owner's typed yes, through the same gate every irreversible
action uses. It stays recoverable there for the provider's window (Gmail: 30
days), and every message moved is in the audit log for UC-30.

⚠️ THE SAFETY RULES OUTRANK ANY TYPED RULE (BR-147). A rule saying "clear
everything from X" cannot put a replied-to sender or a record into the pile.
"""

import os
import sys

import connect
from store import Store
from pipeline import stage03_sensitive, stage13_approval
from storage import RECORD

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

DORMANT_MIN = 8            # the never-opened rule needs enough mail to mean something


def build(store, me: str) -> tuple:
    """
    Groups that may be cleared, and how many messages were deliberately kept.
    Returns (groups, held_back, excluded_senders) where each group is
    {sender, name, count, opened, first, last, reason, ids:[(pid, mid, subject)]}.
    """
    rows = store.q("""SELECT sender, MAX(sender_name), MAX(sender_domain), COUNT(*),
                             COALESCE(SUM(1-unread),0), MIN(date_iso), MAX(date_iso),
                             MAX(bulk), MAX(CASE WHEN unsubscribe!='' THEN 1 ELSE 0 END),
                             MAX(CASE WHEN auto_sub!='' THEN 1 ELSE 0 END)
                        FROM messages WHERE in_inbox=1
                       GROUP BY sender HAVING COUNT(*) >= 2
                       ORDER BY COUNT(*) DESC""")
    groups, held, excluded = [], 0, {}
    for sender, name, domain, n, opened, first, last, bulk, unsub, auto in rows:
        proof = []
        if unsub:  proof.append("carry an unsubscribe header")
        if bulk:   proof.append("marked bulk by the sender")
        if auto:   proof.append("automated messages")
        if not proof:
            continue                                            # BR-54 / BR-56
        if store.history(sender, me)["replied"] > 0:
            excluded[sender] = "you have replied to them"; continue   # BR-55
        if store.is_protected(sender, domain):
            excluded[sender] = "marked important"; continue           # UC-44
        fix = store.correction_for(sender, domain)
        if fix and fix.get("should_be") in ("keep", "reply", "always needs a reply"):
            excluded[sender] = "you rescued this sender before"; continue
        if stage03_sensitive.check(sender, "", domain)["sensitive"]:
            excluded[sender] = "sensitive sender — never touched"; continue

        msgs = store.q("""SELECT provider_id, message_id, subject FROM messages
                           WHERE sender=? AND in_inbox=1 ORDER BY date_iso DESC""", sender)
        keep = [m for m in msgs if RECORD.search(m[2] or "")]           # BR-57
        go = [m for m in msgs if not RECORD.search(m[2] or "")]
        held += len(keep)
        if not go:
            continue
        never = opened == 0 and n >= DORMANT_MIN
        reason = (f"{len(go)} messages, {', '.join(proof)}, "
                  + ("none ever opened" if opened == 0 else f"{opened} opened"))
        groups.append({"sender": sender, "name": name or sender, "count": len(go),
                       "opened": opened, "first": (first or "")[:10], "last": (last or "")[:10],
                       "reason": reason, "never": never, "ids": go, "kept": len(keep)})
    # Strongest evidence first: never-opened senders lead (feature 05).
    groups.sort(key=lambda g: (not g["never"], -g["count"]))
    return groups, held, excluded


def show(store, me):
    groups, held, excluded = build(store, me)
    total = sum(g["count"] for g in groups)
    print(f"\n{C['b']}The pile{C['0']}  {C['dim']}{total:,} messages in {len(groups)} groups{C['0']}")
    print("─" * 74)
    print(f"  {C['g']}Nothing here is from anyone you have ever replied to.{C['0']}")
    print(f"  {C['g']}Nothing here looks like a receipt, a booking or a letter written to you.{C['0']}")
    print(f"  {C['dim']}We deliberately left {held} message(s) out because they look like records, "
          f"and {len(excluded)} sender(s) because of you.{C['0']}\n")
    for g in groups[:30]:
        lead = f"{C['y']}never opened{C['0']}  " if g["never"] else ""
        print(f"  {g['count']:>5}  {g['name'][:34]:34} {C['dim']}{g['first']} → {g['last']}{C['0']}")
        print(f"         {lead}{C['dim']}{g['reason']}{C['0']}"
              + (f"  {C['dim']}· {g['kept']} kept as records{C['0']}" if g["kept"] else ""))
    if len(groups) > 30:
        print(f"  {C['dim']}… and {len(groups)-30} more groups{C['0']}")
    print(f"\n  {C['dim']}python pile.py --clear <address>   trashes one group after your yes"
          f"\n  python pile.py --rescue <address>  keeps a sender out of the pile for good{C['0']}\n")


def rescue(store, sender):
    store.add_correction("sender", sender.lower(), was="pile", should_be="keep", source="app")
    store.record_action("", "", "correction", f"rescued {sender} from the pile")
    print(f"\n  {C['g']}{sender} will never be put in the pile again.{C['0']} Recorded as a correction.\n")


def act(conn, store, me, target, action="trash"):
    groups, _, _ = build(store, me)
    chosen = groups if target == "all" else [g for g in groups if g["sender"] == target.lower()]
    if not chosen:
        print(f"\n  {target} is not in the pile.\n"); return
    msgs = [(g["sender"], *m) for g in chosen for m in g["ids"]]
    verb = "trash" if action == "trash" else "archive"
    print(f"\n{C['b']}{len(msgs):,} message(s) from {len(chosen)} sender(s) will be {verb}ed{C['0']}")
    print("─" * 74)
    for g in chosen[:8]:
        print(f"  {g['count']:>5}  {g['name'][:40]}")
    if action == "trash":
        print(f"\n  They go to your provider's trash, where you can still recover them"
              f" (Gmail: 30 days).")
    else:
        print(f"\n  They leave the inbox but are not deleted. Nothing is lost.")

    ap = stage13_approval.Approval(action, draft=f"{action} {len(msgs)} from {target}")
    try:
        typed = input(f"  {verb.title()} {len(msgs)}? type yes: ").strip()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    ok, why = ap.grant(typed)
    if not ok:
        print(f"  {why}. Nothing moved.\n"); return

    done = failed = 0
    for i, (sender, pid, mid, subject) in enumerate(msgs, 1):
        live = connect.live_id(conn, pid, mid) or pid
        r = stage13_approval.execute(conn, action, live, draft=ap.draft, approval=ap)
        if r["done"]:
            store.record_action(mid, pid, action, (subject or "")[:70], before="INBOX")
            done += 1
        else:
            failed += 1
        if i % 25 == 0:
            print(f"    {i}/{len(msgs)} …")
    print(f"\n  {C['g']}{done} {verb}ed.{C['0']}"
          + (f"  {C['r']}{failed} could not be — still in the pile.{C['0']}" if failed else "")
          + f"\n  {C['dim']}python history.py --undo  puts any of them back.{C['0']}\n")


def main():
    store = Store()
    args = sys.argv[1:]
    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()
    if "--rescue" in args:
        return rescue(store, args[args.index("--rescue") + 1])
    if "--clear" in args:
        return act(conn, store, me, args[args.index("--clear") + 1], "trash")
    if "--archive" in args:
        return act(conn, store, me, args[args.index("--archive") + 1], "archive")
    show(store, me)


if __name__ == "__main__":
    main()
