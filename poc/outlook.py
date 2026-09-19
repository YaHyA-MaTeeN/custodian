"""
UC-05 — Connect Outlook by Microsoft sign-in. No password, ever.

    setx OUTLOOK_CLIENT_ID "your-app-registration-id"     (once; then reopen the terminal)
    python outlook.py --connect you@outlook.com            # sign in on Microsoft's page
    python outlook.py --test                               # open the mailbox over IMAP

⚠️ SIGN-IN, THEN IMAP WITH THE TOKEN (BR-210). Personal Outlook.com stopped
accepting passwords on 16 September 2024. We use Microsoft's device-code
sign-in — the Owner opens a Microsoft page, types a short code, and signs in
there with their password or the Authenticator app. We never see it. The
token then opens the mailbox over the same IMAP engine as every other door.

⚠️ TWO PERMISSIONS ONLY (BR-17): read the mailbox over IMAP, and stay
connected. Never permission to send. Replies go to Outlook's Drafts.

⚠️ NOT TESTABLE HERE. This needs a Microsoft app registration (free, quick)
and, for company accounts, publisher verification. Both are business steps
before launch; the code below is the standard device-code flow against the
public endpoints and is written to be run the day the registration exists.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"
# IMAP access + stay connected. No Mail.Send, no Graph mail.
SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
TOKEN = Path("outlook_token.json")
HOST = "outlook.office365.com"


def _post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def connect(user):
    cid = os.environ.get("OUTLOOK_CLIENT_ID")
    if not cid:
        print("\n  OUTLOOK_CLIENT_ID is not set. Register an app at portal.azure.com "
              "(free), then  setx OUTLOOK_CLIENT_ID \"<id>\"  and reopen the terminal.\n")
        return
    print(f"\n  Outlook uses Microsoft's own sign-in. You won't type a password here.")
    print(f"  We'll be able to read your mail and save drafts — we can never send anything.\n")
    dc = _post(f"{AUTH}/devicecode", {"client_id": cid, "scope": SCOPE})
    print(f"  {C['b']}{dc['message']}{C['0']}\n")
    deadline = time.time() + int(dc.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(int(dc.get("interval", 5)))
        try:
            tok = _post(f"{AUTH}/token", {"client_id": cid, "device_code": dc["device_code"],
                                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode() or "{}")
            if body.get("error") in ("authorization_pending", "slow_down"):
                continue
            print(f"\n  {C['r']}Microsoft said: {body.get('error_description', body.get('error'))[:120]}{C['0']}\n")
            return
        tok["user"] = user
        tok["obtained_at"] = time.time()
        TOKEN.write_text(json.dumps(tok), encoding="utf-8")
        print(f"\n  {C['g']}connected.{C['0']} You can remove our access any time in your Microsoft "
              f"account → Privacy → Apps and services.\n")
        return
    print(f"\n  {C['y']}You didn't accept in time, so nothing was connected.{C['0']}\n")


def access_token() -> tuple:
    """(user, token), refreshing if it is about to expire (BR-18)."""
    tok = json.loads(TOKEN.read_text(encoding="utf-8"))
    if time.time() > tok["obtained_at"] + int(tok.get("expires_in", 3600)) - 120:
        cid = os.environ.get("OUTLOOK_CLIENT_ID")
        new = _post(f"{AUTH}/token", {"client_id": cid, "grant_type": "refresh_token",
                                      "refresh_token": tok["refresh_token"], "scope": SCOPE})
        new["user"], new["obtained_at"] = tok["user"], time.time()
        TOKEN.write_text(json.dumps(new), encoding="utf-8")
        tok = new
    return tok["user"], tok["access_token"]


def test():
    if not TOKEN.exists():
        print("\n  not connected.  python outlook.py --connect you@outlook.com\n"); return
    from connectors.imap import ImapConnector
    user, token = access_token()
    c = ImapConnector(HOST, user, token=token)
    print(f"\n  {C['g']}Outlook open over IMAP{C['0']}  {user}  ·  {c.message_count():,} messages  ·  "
          f"access: {c.access_level()}\n")
    c.close()


def main():
    args = sys.argv[1:]
    if "--connect" in args:
        user = next((a for a in args if "@" in a), None)
        if not user:
            print("\n  --connect needs the Outlook address.\n"); return
        return connect(user)
    if "--test" in args:
        return test()
    print(__doc__)


if __name__ == "__main__":
    main()
