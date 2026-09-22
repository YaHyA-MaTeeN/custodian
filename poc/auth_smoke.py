"""
The accounts routes, end to end, in accounts mode (DATABASE_URL set).

    python auth_smoke.py

Registers a throwaway account, confirms it, logs in, asks who it is, logs
out, resets the password, logs in with the new one, and then deletes the
account so nothing is left behind. Every step prints its status code.
"""

import os
import sys
import time

if not os.environ.get("DATABASE_URL"):
    print("DATABASE_URL is not set: accounts mode is off, nothing to test.")
    sys.exit(1)

from fastapi.testclient import TestClient
import api
api.NO_MAILBOX = True

c = TestClient(api.app)
email = f"smoke-{int(time.time())}@example.invalid"
pw1, pw2 = "first-password-123", "second-password-456"


def show(label, r):
    print(f"{r.status_code:>3}  {label:36} {r.text[:110]}")
    return r


r = show("register", c.post("/api/auth/register", json={"email": email, "password": pw1}))
token = r.json().get("confirmToken", "")
show("login before confirm (must fail)", c.post("/api/auth/login", json={"email": email, "password": pw1}))
show("confirm", c.post("/api/auth/confirm", json={"token": token}))
r = show("login", c.post("/api/auth/login", json={"email": email, "password": pw1}))
sess = r.json().get("token", "")
h = {"Authorization": f"Bearer {sess}"}
show("me (with session)", c.get("/api/me", headers=h))
show("me (no session, must be 401)", c.get("/api/me"))
show("wrong password (same message)", c.post("/api/auth/login", json={"email": email, "password": "nope"}))
show("unknown email (same message)", c.post("/api/auth/login", json={"email": "x" + email, "password": "nope"}))
show("logout", c.post("/api/auth/logout", headers=h))
show("me after logout (must be 401)", c.get("/api/me", headers=h))
import auth
reset = auth.request_reset(email)
show("reset with token", c.post("/api/auth/reset/confirm", json={"token": reset.get("resetToken", ""), "password": pw2}))
show("old password (must fail)", c.post("/api/auth/login", json={"email": email, "password": pw1}))
show("new password", c.post("/api/auth/login", json={"email": email, "password": pw2}))

# leave nothing behind
from pg_store import PgStore
db = PgStore().conn
db.execute("DELETE FROM public.accounts WHERE email=%s", (email,))
db.commit()
print("cleaned up", email)
