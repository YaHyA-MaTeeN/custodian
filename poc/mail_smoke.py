"""
Confirmation email, for real.

    python mail_smoke.py         (needs DATABASE_URL, IMAP_USER, IMAP_PASSWORD)

Registers a throwaway account whose address is YOUR OWN mailbox, so the
confirmation email lands where we can check it. Waits for it to arrive over
IMAP, reads the link out of it, confirms with that token through the API,
logs in, then deletes the account. Proves: register → email sent → link
works → account confirmed.
"""

import os
import re
import sys
import time

for v in ("DATABASE_URL", "IMAP_USER", "IMAP_PASSWORD"):
    if not os.environ.get(v):
        print(f"{v} is not set"); sys.exit(1)

from fastapi.testclient import TestClient
import api
api.NO_MAILBOX = True
c = TestClient(api.app)

import connect
from connectors.imap import ImapConnector
me = os.environ["IMAP_USER"]
# a distinct account address that still delivers to your inbox (Gmail ignores +tags)
local, domain = me.split("@")
addr = f"{local}+smoke{int(time.time())}@{domain}"
pw = "confirm-me-12345"


def show(label, r):
    print(f"{r.status_code:>3}  {label:34} {r.text[:110]}")
    return r


r = show("register (sends email)", c.post("/api/auth/register", json={"email": addr, "password": pw}))
assert "confirmToken" not in r.text, "token must not be returned when the mailer is configured"
show("login before confirm (401)", c.post("/api/auth/login", json={"email": addr, "password": pw}))

print("     waiting for the email to arrive ...", flush=True)
box = ImapConnector(connect.host_for(me), me, os.environ["IMAP_PASSWORD"])
token, waited = "", 0
while not token and waited < 120:
    time.sleep(10); waited += 10
    box.conn.select("INBOX")
    typ, data = box.conn.uid("SEARCH", None, 'SUBJECT "Confirm your Custodian account"')
    uids = data[0].split() if typ == "OK" and data and data[0] else []
    if uids:
        typ, msg = box.conn.uid("FETCH", uids[-1], "(BODY.PEEK[])")
        import email as _email
        from email import policy as _policy
        parsed = _email.message_from_bytes(msg[0][1], policy=_policy.default) if typ == "OK" else None
        part = parsed.get_body(("plain",)) if parsed else None
        text = part.get_content() if part else ""          # decoded, unfolded
        m = re.search(r"token=([A-Za-z0-9_\-]+)", text)
        token = m.group(1) if m else ""
print(f"     arrived after ~{waited}s, token found: {'yes' if token else 'no'}")
if not token:
    print("no confirmation email arrived within 2 minutes"); sys.exit(1)

show("confirm with emailed token", c.post("/api/auth/confirm", json={"token": token}))
show("login after confirm (200)", c.post("/api/auth/login", json={"email": addr, "password": pw}))

# clean up: the account, and the two emails out of the inbox (trash, recoverable)
from pg_store import PgStore
db = PgStore().conn
db.execute("DELETE FROM public.accounts WHERE email=%s", (addr,)); db.commit()
for u in uids:
    try:
        box.conn.uid("MOVE", u, "[Gmail]/Trash")
    except Exception:
        pass
box.close()
print("cleaned up", addr)
