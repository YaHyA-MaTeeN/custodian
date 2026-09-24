"""
Per-user mailbox connections, end to end, in accounts mode.

    python mailbox_smoke.py        (needs DATABASE_URL, IMAP_USER, IMAP_PASSWORD)

Signs in as the account that owns the test mailbox, connects that mailbox
through the API (the app password is verified against Gmail and stored
encrypted in the vault), then calls a route that needs the mailbox: the
API must open it FROM THE VAULT, not from the environment. A second,
fresh account must be told to connect a mailbox first. Everything the test
created is removed at the end.
"""

import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone

for v in ("DATABASE_URL", "IMAP_USER", "IMAP_PASSWORD"):
    if not os.environ.get(v):
        print(f"{v} is not set"); sys.exit(1)

from cryptography.fernet import Fernet
os.environ["CUSTODIAN_SECRET"] = Fernet.generate_key().decode()     # this run only

from fastapi.testclient import TestClient
import api
api.NO_MAILBOX = True            # the API must NOT fall back to its own mailbox
c = TestClient(api.app)

from pg_store import PgStore
root = PgStore()
db = root.conn
me = os.environ["IMAP_USER"].lower()


def show(label, r):
    print(f"{r.status_code:>3}  {label:40} {r.text[:120]}")
    return r


def session_for(account_id):
    tok = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions (token, account_id, expires_at) VALUES (%s,%s,%s)",
               (tok, account_id, datetime.now(timezone.utc) + timedelta(hours=1)))
    db.commit()
    return {"Authorization": f"Bearer {tok}"}


owner = db.execute("SELECT a.id, a.email FROM public.mailboxes m JOIN public.accounts a ON a.id=m.account_id "
                   "WHERE m.address=%s", (me,)).fetchone()
if not owner:
    print("the test mailbox is not registered to any account"); sys.exit(1)
h_owner = session_for(owner[0])
print(f"owner account {owner[0]} <{owner[1]}> owns {me}")

# a second, empty account
other = f"smoke-{int(time.time())}@example.invalid"
other_id = db.execute("INSERT INTO accounts (email, confirmed_at) VALUES (%s, now()) RETURNING id", (other,)).fetchone()[0]
db.commit()
h_other = session_for(other_id)

show("other: spam (no mailbox → 409)", c.get("/api/spam", headers=h_other))
show("owner: connect (verifies + vault)", c.post("/api/mailboxes/connect", headers=h_owner,
                                                json={"address": me, "appPassword": os.environ["IMAP_PASSWORD"]}))
row = db.execute("SELECT COUNT(*) FROM public.credentials cr JOIN public.mailboxes m ON m.id=cr.mailbox_id "
                 "WHERE m.address=%s", (me,)).fetchone()
print(f"     credential rows in vault for {me}: {row[0]}")
show("owner: mailboxes", c.get("/api/mailboxes", headers=h_owner))
t = time.time()
show("owner: spam (opens mailbox from vault)", c.get("/api/spam", headers=h_owner))
print(f"     first open {time.time()-t:.1f}s")
t = time.time()
show("owner: spam again (pooled)", c.get("/api/spam", headers=h_owner))
print(f"     second call {time.time()-t:.1f}s")
import mailboxes
print("     pooled connections:", [k for k in mailboxes._POOL])
show("other: spam still 409", c.get("/api/spam", headers=h_other))

# clean up: credential, sessions, the other account; the mailbox row stays as it was
db.execute("DELETE FROM public.credentials WHERE mailbox_id IN (SELECT id FROM public.mailboxes WHERE address=%s)", (me,))
db.execute("DELETE FROM public.sessions WHERE account_id IN (%s, %s)", (owner[0], other_id))
db.execute("DELETE FROM public.accounts WHERE id=%s", (other_id,))
db.commit()
mailboxes.drop(owner[1])
print("cleaned up")
