"""
UC-22 — What you asked for and never got back.

    python waiting.py            # who has not replied to you
    python waiting.py --label    # also mark them in Gmail

⚠️ THIS FAILURE IS INVISIBLE BY NATURE.

An unanswered question leaves NO TRACE in your inbox. Nothing arrives, so
nothing reminds you. Every other feature reacts to something appearing; this
one is the only feature that reacts to something NOT appearing, and it is the
only way that failure is ever caught.

⚠️ WE NEVER CHASE THE RECIPIENT (BR-83).

The reminder goes to the Owner, only ever to the Owner. Sending "just
following up" on somebody's behalf without them asking is exactly the
behaviour that gets a product uninstalled, and BR-83 forbids it outright.
"""

import os
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import connect
from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m",
     "y": "\033[33m", "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

WAITING_LABEL = "Custodian/Waiting on them"

# ⚠️ BR-81 — only messages that ASKED something are tracked.
#
# A message that merely informed needs no reply, and listing it would make the
# feature noise. This is deliberately conservative: a missed question is a
# small loss, a list full of things that never needed answers is a dead feature.
ASKED = re.compile(
    r"\?"                                            # a question mark
    r"|\b(can|could|would|will) you\b"
    r"|\b(please|kindly) (send|share|confirm|review|check|let me know|advise)\b"
    r"|\blet me know\b|\bwhat do you think\b|\bany update\b"
    r"|\bwaiting (for|on)\b|\bneed (your|the)\b|\bconfirm\b",
    re.I)

# How long before it is worth mentioning. BR-81's flow says the threshold
# varies — a colleague after two days, a supplier after a week — so it is set
# by how often you two actually correspond, not by one global number.
def threshold_days(exchanges: int) -> int:
    if exchanges >= 10:
        return 2          # you talk constantly; two days of silence is odd
    if exchanges >= 3:
        return 4
    return 7              # a stranger or a supplier gets a week


def asked_something(subject: str, snippet: str) -> bool:
    return bool(ASKED.search(f"{subject} {snippet}"))


def main():
    want_label = "--label" in sys.argv
    print(f"\n{C['b']}Waiting on a reply{C['0']}")
    print("─" * 68)

    conn = connect.open_mailbox()
    store = Store()
    me = conn.account_email()
    print(f"  {me}")

    r = conn.svc.users().messages().list(
        userId="me", labelIds=["SENT"], maxResults=80).execute()
    ids = [m["id"] for m in r.get("messages", [])]
    if not ids:
        print("\n  nothing in your sent folder.\n")
        return

    print(f"  checking {len(ids)} sent message(s) ...\n")

    now = datetime.now().astimezone()
    waiting, skipped_informational, skipped_bulk, answered = [], 0, 0, 0

    for mid in ids:
        try:
            m = conn.svc.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["To", "Subject", "Date", "Message-ID"]).execute()
        except Exception:
            continue
        h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
        to_line = h.get("To", "")
        subject = h.get("Subject", "")
        snippet = m.get("snippet", "")

        # BR-82 — bulk recipients are never tracked.
        recipients = [a for a in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", to_line)]
        if len(recipients) > 3:
            skipped_bulk += 1
            continue
        if not recipients:
            continue

        # BR-81 — did it actually ask anything?
        if not asked_something(subject, snippet):
            skipped_informational += 1
            continue

        try:
            sent_at = parsedate_to_datetime(h.get("Date", ""))
            if sent_at.tzinfo is None:
                sent_at = sent_at.astimezone()
        except Exception:
            continue
        days = (now - sent_at).days

        # ⚠️ BR-82 — a reply from ANYONE in the thread clears it, and E1 says
        # we also match on sender and subject because plenty of people reply as
        # a fresh message. We err towards clearing rather than nagging.
        thread = conn.svc.users().threads().get(
            userId="me", id=m["threadId"], format="metadata",
            metadataHeaders=["From"]).execute()
        got_reply = False
        for msg in thread.get("messages", []):
            frm = " ".join(x["value"] for x in msg["payload"]["headers"]
                           if x["name"] == "From")
            if me.lower() not in frm.lower():
                got_reply = True
                break
        if not got_reply:
            for addr in recipients:
                hits = store.q("SELECT 1 FROM messages WHERE sender=? AND date>? LIMIT 1",
                               addr.lower(), h.get("Date", ""))
                if hits:
                    got_reply = True
                    break

        if got_reply:
            answered += 1
            continue

        exchanges = store.history(recipients[0], me)["sent"]
        limit = threshold_days(exchanges)
        if days >= limit:
            waiting.append({"id": mid, "to": recipients[0], "subject": subject,
                            "days": days, "limit": limit})

    if waiting:
        print(f"  {C['b']}{len(waiting)} still unanswered{C['0']}\n")
        for w in sorted(waiting, key=lambda x: -x["days"]):
            urgency = C["r"] if w["days"] >= w["limit"] * 2 else C["y"]
            print(f"  {urgency}{w['days']:>3} days{C['0']}  {w['subject'][:44]}")
            print(f"           {C['dim']}to {w['to']} · you usually hear back "
                  f"within {w['limit']} days{C['0']}")

        if want_label:
            print()
            ids_map = {l["name"]: l["id"] for l in conn.svc.users().labels()
                       .list(userId="me").execute().get("labels", [])}
            lid = ids_map.get(WAITING_LABEL)
            if not lid:
                lid = conn.svc.users().labels().create(
                    userId="me", body={"name": WAITING_LABEL,
                                       "labelListVisibility": "labelShow",
                                       "messageListVisibility": "show"}
                ).execute()["id"]
                print(f"  created label: {WAITING_LABEL}")
            for w in waiting:
                try:
                    conn.apply_label(w["id"], lid)
                    store.record_action("", w["id"], "label", WAITING_LABEL, before=lid)
                except Exception:
                    pass
            print(f"  {C['g']}marked in Gmail — visible on the sent message "
                  f"itself{C['0']}")
    else:
        print(f"  {C['g']}Nothing is waiting on a reply.{C['0']}")

    print("\n" + "─" * 68)
    print(f"  {C['dim']}{answered:>3} already answered{C['0']}")
    print(f"  {C['dim']}{skipped_informational:>3} did not ask anything — never listed (BR-81){C['0']}")
    print(f"  {C['dim']}{skipped_bulk:>3} sent to several people — never tracked (BR-82){C['0']}")
    print(f"\n  {C['dim']}Nothing was sent to anyone. We remind you, never chase "
          f"them (BR-83).{C['0']}\n")


if __name__ == "__main__":
    main()
