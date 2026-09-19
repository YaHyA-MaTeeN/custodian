"""
UC-29 — Tell it it was wrong, once.

    python correct.py                    # what did it decide, and about whom
    python correct.py ali@company.com    # correct one sender
    python correct.py --scan             # pick up corrections made in Gmail
    python correct.py --timing           # "you warned me too late" 

⚠️ WHY THIS IS THE MOST VALUABLE UNBUILT FEATURE, NOW BUILT.

BR-107: corrections are the only training data we can clearly use. Everything
else is inference. When somebody drags a message out of a label, they have
told us plainly that we were wrong — no labelling budget, no annotator, no
guessing what they meant.

⚠️ IT TAKES EFFECT IMMEDIATELY, NOT AFTER RETRAINING (BR-106).

A correction is a row we look up before trusting any model, not a weight we
adjust later. That is what makes "one correction is enough" true rather than
aspirational. Retraining still happens weekly and folds the corrections in —
but the behaviour changes on the very next email, not next Sunday.

⚠️ AND CORRECTIONS MADE IN GMAIL COUNT (AC-29.3).

If the Owner drags a message out of one of our labels in their own mail app,
that is a correction. Only accepting disagreement through our own screen would
mean missing the place people actually disagree.
"""

import os
import sys

from connectors.gmail import GmailConnector
from store import Store
from sort_mailbox import LABELS

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# ⚠️ WHAT CAN BE CORRECTED, AND HOW WIDELY.
#
# Two questions, always: WHAT was wrong, and WHO does the fix apply to.
#
# The scope matters as much as the answer. "This one message" and "everything\n# from linkedin.com forever" are both legitimate corrections and they are very
# different instructions — collapsing them into one would either under-apply
# the fix or over-apply it, and the Owner cannot tell us which they meant if
# we never ask.
CHOICES = {
    "1": ("always needs a reply",        "reply"),
    "2": ("never needs a reply",         "waiting"),
    "3": ("never open this at all",      "private"),
    "4": ("it is NOT sensitive - safe to open", "not_sensitive"),
    "5": ("wrong label - it is a meeting",     "meeting"),
    "6": ("wrong label - it is an invoice",    "invoice"),
    "7": ("wrong label - it is an order",      "order"),
    "8": ("stop labelling this at all",  "none"),
    "9": ("leave it alone",              None),
}

# Who the correction covers. UC-29 says corrections are made where the mistake
# is, not in a settings screen — so this is asked in the same breath, once.
SCOPES = {
    "1": ("just this sender",       "sender"),
    "2": ("everyone at that domain","domain"),
    "3": ("only this one message",  "message"),
}

# Reminder timing is a correction too (UC-24, BR-88), and it has its own shape:
# not "what is this" but "when should you have told me".
TIMING = {
    "1": ("warn me earlier",  "earlier"),
    "2": ("warn me later",    "later"),
    "3": ("do not remind me for this kind", "never"),
}


def show_recent(store):
    """What has it decided lately, and why. The reason is already on the item."""
    rows = store.q("""SELECT d.message_id, d.decision, d.reason, d.score, m.sender,
                             m.sender_name, m.subject
                        FROM decisions d LEFT JOIN messages m
                          ON m.message_id = d.message_id
                       ORDER BY d.at DESC LIMIT 15""")
    if not rows:
        print(f"\n  {C['dim']}No decisions recorded yet. Run "
              f"python agent.py 10 first.{C['0']}\n")
        return []

    print(f"\n{C['b']}Recent decisions — and why{C['0']}")
    print("─" * 72)
    for i, (mid, dec, why, score, sender, name, subject) in enumerate(rows, 1):
        print(f"  {C['dim']}{i:>2}{C['0']} {C['b']}{(subject or '(no subject)')[:48]}{C['0']}")
        print(f"     {C['dim']}from {name or sender}{C['0']}")
        s = f" ({score:.2f})" if score is not None else ""
        print(f"     {C['c']}{dec}{s}{C['0']}")
        print(f"     {C['dim']}because: {why}{C['0']}")
    print("─" * 72)
    print(f"  {C['dim']}Every decision carries the reason recorded at the time "
          f"it was made.{C['0']}")
    print(f"  {C['dim']}python correct.py <sender>   to disagree with one.{C['0']}\n")
    return rows


def correct_sender(store, sender: str):
    """One sender, one correction, applied from now on."""
    sender = sender.strip().lower()
    rows = store.q("""SELECT subject, sender_name FROM messages
                       WHERE sender=? ORDER BY date_iso DESC LIMIT 3""", sender)
    if not rows:
        print(f"\n  no mail from {sender} in the database.\n")
        return

    hist = store.q("""SELECT d.decision, d.reason FROM decisions d
                        JOIN messages m ON m.message_id = d.message_id
                       WHERE m.sender=? ORDER BY d.at DESC LIMIT 1""", sender)

    print(f"\n{C['b']}{sender}{C['0']}")
    print("─" * 72)
    if hist:
        print(f"  we decided : {C['c']}{hist[0][0]}{C['0']}")
        print(f"  because    : {C['dim']}{hist[0][1]}{C['0']}")
    else:
        print(f"  {C['dim']}no decision recorded for this sender yet{C['0']}")
    print(f"  recent     : {rows[0][0][:52]}")

    existing = store.correction_for(sender, sender.split("@")[-1])
    if existing:
        print(f"  {C['y']}already corrected: {existing['should_be']}{C['0']}")

    print(f"\n  What should it do instead?\n")
    for k, (label, _) in CHOICES.items():
        print(f"    {C['b']}{k}{C['0']}  {label}")
    try:
        pick = input("\n  > ").strip()
    except (EOFError, KeyboardInterrupt):
        pick = "4"

    if pick not in CHOICES:
        print("  not one of the options — nothing changed.\n")
        return
    label, key = CHOICES[pick]
    if key is None:
        print("  nothing changed.\n")
        return

    # ⚠️ ASKED IN THE SAME BREATH, NOT IN A SETTINGS SCREEN (UC-29 scope guard).
    #
    # "This sender" and "everyone at this domain" are different instructions.
    # Guessing which one they meant is how a correction either fails to stick
    # or quietly spreads further than anybody intended.
    print(f"\n  {C['b']}Who does that apply to?{C['0']}\n")
    for k, (slabel, _) in SCOPES.items():
        print(f"    {C['b']}{k}{C['0']}  {slabel}")
    try:
        spick = input("\n  > ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        spick = "1"
    scope_label, scope = SCOPES.get(spick, SCOPES["1"])

    # ⚠️ THE TARGET HAS TO MATCH THE SCOPE.
    #
    # This stored the sender's address for every scope, so "only this one\n    # message" quietly behaved as "this sender, forever" — the widest possible
    # reading of the narrowest possible instruction. A correction that applies
    # more broadly than asked is worse than one that fails, because nobody
    # notices it happening.
    if scope == "domain":
        target = sender.split("@")[-1]
    elif scope == "message":
        latest = store.q("""SELECT message_id, subject FROM messages
                             WHERE sender=? ORDER BY date_iso DESC LIMIT 1""", sender)
        if not latest or not latest[0][0]:
            print("  no single message to pin this to — nothing changed.\n")
            return
        target = latest[0][0]
        print(f"  {C['dim']}pinned to: {latest[0][1][:50]}{C['0']}")
    else:
        target = sender

    was = hist[0][0] if hist else "(no prior decision)"
    store.add_correction(scope, target, was, key, source="app")
    # ⚠️ UC-29 step 6 — a correction IS an action, and BR-110 says the audit
    # log covers everything in one place. A correction that only lives in its
    # own table is invisible on the history screen, which is exactly where
    # somebody looks when asking "why did this change?"
    store.record_action("", "", "correction",
                        f"{target}: {was} -> {key} ({scope_label})",
                        before=was)

    # ⚠️ State back what we understood, in ONE line. A misread correction has
    # to be visible now, not discovered three weeks later in the wrong folder.
    print(f"\n  {C['g']}Understood:{C['0']} for {C['b']}{scope_label}{C['0']} "
          f"({C['b']}{target}{C['0']}) — {C['b']}{label}{C['0']}.")
    print(f"  {C['dim']}In effect from the next email. Nothing is retrained; "
          f"this is a lookup.{C['0']}")

    # 5 · offer to revise past decisions — offer, never apply on its own.
    n = store.q("SELECT COUNT(*) FROM messages WHERE sender=?", sender)[0][0]
    print(f"\n  {n} past message(s) from this sender were decided the old way.")
    try:
        again = input("  Re-sort them too? type yes: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        again = "no"
    if again == "yes":
        print(f"  {C['dim']}run: python sort_mailbox.py 200{C['0']}")
    else:
        print(f"  {C['dim']}left as they are. Past decisions are never revised "
              f"without being offered first.{C['0']}")
    print()


def correct_timing(store, kind: str = ""):
    """
    UC-24 / BR-88 — "you warned me too late" is a correction like any other.

    It has a different shape from the rest: not "what is this message" but
    "when should you have told me". Same principle though — a lookup that
    changes the next reminder, not a weight that changes eventually.
    """
    kinds = ["meeting", "appointment", "bill", "application", "renewal", "deadline"]
    if kind not in kinds:
        print(f"\n{C['b']}Which kind of reminder was mistimed?{C['0']}\n")
        for i, k in enumerate(kinds, 1):
            from pipeline.stage16_commitments import LEAD
            lead = LEAD.get(k, LEAD["deadline"])
            print(f"    {C['b']}{i}{C['0']}  {k:<14} {C['dim']}currently warns "
                  f"{lead} before{C['0']}")
        try:
            pick = input("\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not pick.isdigit() or not 1 <= int(pick) <= len(kinds):
            print("  nothing changed.\n")
            return
        kind = kinds[int(pick) - 1]

    print(f"\n{C['b']}What should change about {kind} reminders?{C['0']}\n")
    for k, (label, _) in TIMING.items():
        print(f"    {C['b']}{k}{C['0']}  {label}")
    try:
        pick = input("\n  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if pick not in TIMING:
        print("  nothing changed.\n")
        return
    label, direction = TIMING[pick]

    store.add_correction("reminder_lead", kind, "default", direction, source="app")
    store.record_action("", "", "correction",
                        f"{kind} reminders: {direction}", before="default")

    from pipeline.stage16_commitments import lead_for
    print(f"\n  {C['g']}Understood:{C['0']} {kind} reminders will "
          f"{C['b']}{label}{C['0']}.")
    print(f"  {C['dim']}new lead time: {lead_for(store, kind)} before the "
          f"deadline. In effect from the next one.{C['0']}\n")


def scan_mailbox(store):
    """
    AC-29.3 — corrections the Owner made in Gmail, by dragging a message out
    of one of our labels. We ask Gmail what changed rather than re-reading.
    """
    conn = GmailConnector()
    all_labels = {l["name"]: l["id"] for l in
                  conn.svc.users().labels().list(userId="me").execute().get("labels", [])}
    ours = {all_labels[n]: n for n in LABELS.values() if n in all_labels}
    if not ours:
        print(f"\n  none of our labels exist yet — nothing to watch.\n")
        return

    bookmark = conn.current_history_id()
    print(f"\n{C['b']}Watching for corrections in Gmail{C['0']}")
    print("─" * 72)
    print(f"  {len(ours)} of our labels are being watched.")
    print(f"  {C['dim']}Drag a message out of a Custodian label in Gmail, then "
          f"run this again.{C['0']}")

    removals, new_bookmark = conn.label_removals_since(bookmark, set(ours))
    if not removals:
        print(f"\n  {C['dim']}no corrections since bookmark {bookmark}.{C['0']}")
        print(f"  {C['dim']}Nothing to learn — which is the correct outcome when "
              f"nothing was wrong.{C['0']}\n")
        return

    print(f"\n  {C['g']}{len(removals)} correction(s) found{C['0']}\n")
    for pid, label_id in removals:
        try:
            m = conn.svc.users().messages().get(
                userId="me", id=pid, format="metadata",
                metadataHeaders=["From", "Subject"]).execute()
            h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
            frm = h.get("From", "")
            addr = frm.split("<")[-1].strip("> ").lower()
            store.add_correction("sender", addr, ours[label_id], "not this label",
                                 source="mailbox")
            store.record_action("", pid, "correction",
                                f"{addr}: removed {ours[label_id]} in Gmail",
                                before=ours[label_id])
            print(f"  · you removed {C['c']}{ours[label_id]}{C['0']} from mail "
                  f"by {C['b']}{addr}{C['0']}")
            print(f"    {C['dim']}{h.get('Subject','')[:56]}{C['0']}")
        except Exception as e:
            print(f"  could not read one: {str(e)[:50]}")
    print(f"\n  {C['dim']}Recorded. These outweigh anything the models inferred.{C['0']}\n")


def main():
    store = Store()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--scan" in sys.argv:
        return scan_mailbox(store)
    if "--timing" in sys.argv:
        return correct_timing(store)
    if args and "@" in args[0]:
        return correct_sender(store, args[0])

    rows = show_recent(store)
    corrections = store.all_corrections()
    if corrections:
        print(f"{C['b']}Corrections in force{C['0']}")
        print("─" * 72)
        for cid, scope, target, was, should, source, at in corrections[:10]:
            where = "in Gmail" if source == "mailbox" else "in the app"
            print(f"  {target:<34} → {C['c']}{should}{C['0']}  "
                  f"{C['dim']}{where}, {at[:10]}{C['0']}")
        print()


if __name__ == "__main__":
    main()
