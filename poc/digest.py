"""
UC-31 — One message, on your schedule, covering everything. Or nothing.

    python digest.py --frequency weekly     # daily · weekly · monthly · never
    python digest.py --run                  # send it now if it is due AND there is something to say
    python digest.py --run --force          # send it now regardless of the schedule
    python digest.py --schedule             # prints the one command that runs it daily on Windows

⚠️ ONE DIGEST, BATCHED (BR-111). Never one message per event. Nothing would
kill this product faster than becoming the customer's most frequent sender.

⚠️ SILENCE IS A VALID OUTPUT (BR-112). Nothing to report means no message
is sent, and that is recorded as the correct outcome.

⚠️ SENT FROM THE OWNER'S OWN MAILBOX TO THEMSELVES. The document wants it
sent from our own address; a proof of concept has no outbound service, so
brief.py --email goes out through the connected mailbox, to the Owner only,
never to any address found in mail. That is the one place this differs from
UC-31 and it is stated here rather than hidden.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from store import Store

SETTINGS = Path("settings.json")
PERIOD = {"daily": 1, "weekly": 7, "monthly": 30}


def load() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(s: dict) -> None:
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


def something_to_say(store) -> bool:
    """BR-112. Anything at all worth a message?"""
    if store.one("SELECT COUNT(*) FROM decisions WHERE decision='needs a reply' AND at > ?",
                 (datetime.now() - timedelta(days=7)).isoformat()):
        return True
    if store.open_requests():
        return True
    if store.due_reminders(datetime.now() + timedelta(days=3)):
        return True
    if store.unsubscribes("ignoring"):
        return True
    return False


def main():
    args = sys.argv[1:]
    s = load()
    if "--frequency" in args:
        f = args[args.index("--frequency") + 1].lower()
        if f not in PERIOD and f != "never":
            print("\n  daily, weekly, monthly or never.\n"); return
        s["digest"] = f; save(s)
        print(f"\n  digest: {f}." + ("  Never is a fully supported choice." if f == "never" else "") + "\n")
        return
    if "--schedule" in args:
        py = sys.executable
        here = Path(__file__).resolve().parent
        print("\n  Run this once in a terminal to have Windows try the digest every morning at 8:")
        print(f'\n  schtasks /create /tn "Custodian digest" /sc daily /st 08:00 '
              f'/tr "cmd /c cd /d {here} && {py} digest.py --run"\n')
        print("  It sends only when the digest is due and there is something to say.\n")
        return
    if "--run" in args:
        freq = s.get("digest", "weekly")
        if freq == "never":
            print("\n  digest is off (never). Nothing sent.\n"); return
        last = s.get("digest_last", "")
        due = not last or datetime.fromisoformat(last) + timedelta(days=PERIOD[freq]) <= datetime.now()
        if not due and "--force" not in args:
            print(f"\n  not due yet — last sent {last[:10]}, frequency {freq}. Nothing sent.\n"); return
        store = Store()
        if not something_to_say(store) and "--force" not in args:
            s["digest_last"] = datetime.now().isoformat(); save(s)
            print("\n  nothing to report. No message sent — that is the correct outcome.\n"); return
        days = PERIOD[freq]
        r = subprocess.run([sys.executable, "-X", "utf8", "brief.py", "--email", "--days", str(days)])
        if r.returncode == 0:
            s["digest_last"] = datetime.now().isoformat(); save(s)
        return
    print(f"\n  digest frequency: {s.get('digest', 'weekly')}   last sent: {s.get('digest_last', 'never')[:10]}")
    print("  python digest.py --frequency weekly | --run | --schedule\n")


if __name__ == "__main__":
    main()
