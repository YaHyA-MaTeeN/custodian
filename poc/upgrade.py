"""
UC-12 — Move a mailbox from app password to Google sign-in, in place.

    python upgrade.py            # check both doors reach the same mailbox, then switch
    python upgrade.py --back     # switch back to the app password

⚠️ IN PLACE (BR-41). The mailbox keeps its record and its identifier; it is
never disconnected and re-added. Every label, rule, correction, decision and
reminder stays attached, because they are keyed on Message-ID — the one id
that means the same email on both doors — not on either door's handle.

⚠️ THE OLD CONNECTION STAYS LIVE UNTIL THE NEW ONE IS PROVEN (BR-42). The
API door is opened and its account compared with the IMAP door's. If they
differ — the wrong Google account was chosen — nothing switches (EX-1).

⚠️ THE APP PASSWORD IS DESTROYED ONLY AFTER (BR-43, BR-45) — and only the
Owner can do that, in their Google account. This says where.

⚠️ NOBODY IS FORCED (BR-44). Ignore this and the app password keeps working.
"""

import json
import os
import sys
from pathlib import Path

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

SETTINGS = Path("settings.json")


def _settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    s = _settings()
    if "--back" in sys.argv:
        s["door"] = "imap"; SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
        print("\n  back on the app password. Nothing else changed.\n"); return

    user = os.environ.get("IMAP_USER", "")
    print(f"\n{C['b']}Upgrade {user or 'this mailbox'} to Google sign-in{C['0']}")
    print("─" * 66)
    print("  Nothing is lost, and it takes one sign-in. Google's next screen says we could")
    print("  send email, because that is how Google describes this permission.")
    print("  Sending still stops at the same typed-yes gate as before.\n")
    if not Path("credentials.json").exists():
        print(f"  {C['y']}credentials.json is missing — Google approval is not in place yet.{C['0']}\n")
        return
    try:
        from connectors.gmail import GmailConnector
        api = GmailConnector()                              # opens Google's page if needed
        api_user = (api.account_email() or "").lower()
    except Exception as e:
        print(f"\n  {C['r']}Google sign-in did not complete: {str(e)[:70]}{C['0']}")
        print(f"  {C['dim']}The app-password connection was never touched and still works.{C['0']}\n")
        return
    if user and api_user != user.lower():
        print(f"\n  {C['r']}That Google account is {api_user}, not {user}.{C['0']}")
        print(f"  Nothing has changed — please sign in again with {user}.\n")
        try:
            Path("token.json").unlink()
        except Exception:
            pass
        return
    s["door"] = "api"
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(f"\n  {C['g']}{api_user} now uses Google sign-in.{C['0']} Nothing else changed — "
          f"we still never delete, and sending still asks you first.")
    print(f"  {C['dim']}Stored message ids are re-mapped by Message-ID as each is opened, so no "
          f"message appears twice or goes missing.{C['0']}")
    print(f"\n  {C['b']}Tidy up:{C['0']} you can now delete the old app password in your Google account.")
    print("  Only you can do that:  myaccount.google.com/apppasswords")
    print(f"  {C['dim']}To stop us at any time: myaccount.google.com/connections → Custodian → "
          f"Delete all connections.{C['0']}\n")


if __name__ == "__main__":
    main()
