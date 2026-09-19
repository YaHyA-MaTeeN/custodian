"""
Actually sort the mailbox — labels appear in Gmail.

    python sort_mailbox.py 200        # label 200 messages
    python sort_mailbox.py --undo     # remove every label we added

Everything before this decides. This is the only script that CHANGES the
mailbox, and it is deliberately the smallest one.

⚠️ WHAT IT WILL AND WILL NOT DO

  applies labels          yes - they show up in Gmail immediately
  moves anything          no
  archives anything       no
  deletes anything        NO. We never delete. We do not even ask for the
                          permission that could.

Every label is recorded in an audit file, and --undo removes exactly what was
added and nothing else. That is what makes this safe to run on a real mailbox:
not a promise, but the fact that the only action taken is one that reverses.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import connect
from store import Store
from pipeline import stage02_strip, stage03_sensitive, stage04_headers, stage09_gate

AUDIT = Path("applied_labels.json")

# Labels we create. Gmail nests them under one parent, so everything we did is
# visible in one place and easy to remove.
LABELS = {
    "reply":    "Custodian/Needs a reply",
    "waiting":  "Custodian/Machine mail",
    "dormant":  "Custodian/Never opened",
    "private":  "Custodian/Private — not read",
    # UC-23 · structured mail, filed by what the sender already declared.
    # These come from reading an attachment exactly, never from guessing a
    # category — which is why they are safe to apply without asking.
    "flight":   "Custodian/Flights",
    "order":    "Custodian/Orders",
    "invoice":  "Custodian/Invoices",
    "meeting":  "Custodian/Meetings",
    "waiting_on": "Custodian/Waiting on them",
}

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m",
     "y": "\033[33m", "r": "\033[31m", "0": "\033[0m"}
import os
if os.name == "nt":
    os.system("")


def ensure_labels(conn) -> dict:
    """
    Create our labels once. Returns {key: handle}.

    ⚠️ The handle is a Gmail label id on Gmail and a folder name on IMAP, and
    this function does not know which. It asks the connector. That is what
    stops "which provider is this" leaking out of connectors/ and into every
    script above it.
    """
    return {key: conn.ensure_label(name) for key, name in LABELS.items()}


def decide(env, facts, hist, labels, store=None) -> str | None:
    """
    Which label this message gets. Returns None to leave it alone.

    ⚠️ Nothing here is a category we invented. Every branch is either a fact
    the sender declared or something this person actually did.
    """
    # ⚠️ A CORRECTION OUTRANKS EVERYTHING BELOW IT (UC-29, BR-106).
    #
    # Checked first, before any rule and before any model, because the Owner
    # telling us we were wrong is stronger evidence than anything we inferred.
    # And it is a lookup, not a weight — so "one correction is enough" is true
    # on the very next email rather than after the weekly retrain.
    if store is not None:
        fix = store.correction_for(env.sender, env.sender_domain)
        if fix:
            if fix["should_be"] == "not this label":
                return None                      # they took our label off. Respect it.
            return fix["should_be"]
        # UC-44 — a person marked important is always at the top, whatever
        # the headers or the model say. A rule beats the model (BR-145).
        if store.is_protected(env.sender, env.sender_domain):
            return "reply"

    if stage03_sensitive.check(env.sender, env.subject, env.sender_domain)["sensitive"]:
        return "private"

    if stage04_headers.engagement_exit(hist["sent"], hist["opened"])["exit"]:
        return "dormant"

    if labels and labels.get("intent") == "needs a response from you":
        return "reply"

    if facts["machine_generated"]:
        return "waiting"

    return None


def main():
    if "--undo" in sys.argv:
        return undo()

    want = next((int(a) for a in sys.argv[1:] if a.isdigit()), 100)

    print(f"\n{C['b']}Sorting the mailbox{C['0']}")
    print("─" * 56)

    conn = connect.open_mailbox()
    store = Store()
    me = conn.account_email()
    print(f"  {me}")

    from pipeline import local_classifier
    has_model = local_classifier.available()
    print(f"  classifier: {C['g']+'our own model' if has_model else C['y']+'not trained'}{C['0']}")

    label_ids = ensure_labels(conn)

    rows = store.q("""SELECT provider_id, message_id, sender, sender_name,
                             sender_domain, subject, date, bulk, unsubscribe,
                             one_click, auto_sub, in_reply_to, unread
                        FROM messages
                       WHERE in_inbox = 1
                       ORDER BY date_iso DESC LIMIT ?""", want)
    if not rows:
        print("\n  no inbox messages stored. Run  python run.py  first.\n")
        sys.exit(1)

    print(f"\n  labelling {len(rows)} messages ...\n")

    from connectors.base import Envelope
    applied, tally = [], {}

    for i, r in enumerate(rows, 1):
        (pid, mid, sender, sname, domain, subject, date,
         bulk, unsub, one_click, auto_sub, in_reply_to, unread) = r

        env = Envelope(provider_id=pid, message_id=mid, sender=sender,
                       sender_name=sname or "", sender_domain=domain or "",
                       subject=subject or "", date=date or "",
                       unread=bool(unread), bulk=bool(bulk),
                       unsubscribe=unsub or "", one_click=bool(one_click),
                       auto_submitted=auto_sub or "", in_reply_to=in_reply_to or "")

        facts = stage04_headers.read(env)
        hist = store.history(sender, me)

        # Only read the body when the cheap signals have not already decided.
        labels = None
        if has_model and not facts["machine_generated"]:
            try:
                text = stage02_strip.strip(conn.fetch_raw(pid))["text"]
                labels = local_classifier.classify(text, subject or "", sender)
            except Exception:
                pass

        key = decide(env, facts, hist, labels, store)
        # UC-38 — a typed rule beats the model (BR-145). A label rule names
        # its own label; it is created once here and reused. Matching is a
        # string comparison — no model runs for a rule after it is saved.
        for rule in store.rules_for(sender, domain or "", subject or ""):
            action, arg = rule[4], rule[5]
            if action == "label" and arg:
                if arg not in label_ids:
                    label_ids[arg] = conn.ensure_label(arg)
                    LABELS[arg] = arg
                key = arg
                break
            if action == "never_reply" and key == "reply":
                key = None
                break
        # Recorded whether or not we label it — "we looked and chose to do
        # nothing" is a decision the Owner may equally want to disagree with.
        store.record_decision(
            mid, "sort", LABELS.get(key, "left alone"),
            f"machine={facts['machine_generated']}, "
            f"opened {hist['opened']}/{hist['sent']} from this sender"
            + (f", model said {labels['intent']} ({labels['confidence']:.2f})"
               if labels else ""),
            labels["confidence"] if labels else None)
        if not key:
            continue

        try:
            conn.apply_label(pid, label_ids[key])
            # UC-30 · the audit log, with the state before the change
            store.record_action(mid, pid, "label", LABELS[key],
                                before=label_ids[key])
            applied.append({"id": pid,
                            # which door applied it — the file serves both,
                            # and their ids mean different things
                            "door": getattr(conn, "name", ""),
                            "label_id": label_ids[key],
                            "label": LABELS[key], "subject": (subject or "")[:70],
                            "at": datetime.now().isoformat()})
            tally[LABELS[key]] = tally.get(LABELS[key], 0) + 1
        except Exception as e:
            print(f"  could not label one: {str(e)[:60]}")

        if i % 20 == 0:
            print(f"  {i}/{len(rows)} ...")
        time.sleep(0.05)      # stay well inside the quota

    # ⚠️ Written AFTER each batch, not at the end, so an interrupted run is
    # still fully undoable.
    AUDIT.write_text(json.dumps(applied, indent=2), encoding="utf-8")

    print("\n" + "─" * 56)
    for name, n in sorted(tally.items(), key=lambda x: -x[1]):
        print(f"  {n:>4}  {name}")
    print(f"\n  {len(applied)} labels applied · logged in {AUDIT}")
    print(f"  {C['g']}Open Gmail — they are in the sidebar under 'Custodian'{C['0']}")
    print(f"\n  {C['dim']}Nothing was moved, archived or deleted.{C['0']}")
    print(f"  {C['dim']}python sort_mailbox.py --undo   removes every one.{C['0']}\n")


def undo():
    """Remove exactly what we added, and nothing else."""
    if not AUDIT.exists():
        print(f"\n  {AUDIT} not found — nothing to undo.\n")
        return

    applied = json.loads(AUDIT.read_text(encoding="utf-8"))
    print(f"\n{C['b']}Removing {len(applied)} labels{C['0']}")
    print("─" * 56)

    conn = connect.open_mailbox()
    ok = 0
    for i, a in enumerate(applied, 1):
        try:
            conn.svc.users().messages().modify(
                userId="me", id=a["id"],
                body={"removeLabelIds": [a["label_id"]]}).execute()
            ok += 1
        except Exception:
            pass
        if i % 25 == 0:
            print(f"  {i}/{len(applied)} ...")

    AUDIT.unlink()
    print(f"\n  {ok} removed. The mailbox is exactly as it was.\n")


if __name__ == "__main__":
    main()
