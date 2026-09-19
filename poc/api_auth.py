"""
Who is calling the API, and which account's data they get.

⚠️ TWO MODES, ONE RULE.

  Single-user (no DATABASE_URL)  — the laptop POC. No sign-in; every route
                                    serves the one local mailbox, as before.
  Accounts (DATABASE_URL set)     — every route needs  Authorization: Bearer
                                    <session token>. The token names an
                                    account; the account names a schema; the
                                    store handed to the route can only see
                                    that schema. There is no route that takes
                                    an account id from the caller.

⚠️ SIGNING IN GRANTS NO MAILBOX ACCESS (UC-02 BR-05). A session reaches an
account. Connecting a mailbox is its own explicit step with its own
credential, per mailbox.

⚠️ ONE STORE PER ACCOUNT, KEPT OPEN. A PgStore costs seconds to open over
the network; it is opened once per account and reused. The API already runs
one request at a time, so a shared store is safe.
"""

import os
import threading
from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

_STORES: dict = {}
_LOCK = threading.Lock()


def accounts_mode() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


class Account(BaseModel):
    id: int
    email: str
    plan: str = "trial"
    digest: str = "weekly"
    dataRegion: str = ""


def current_account(authorization: Optional[str] = Header(default=None)) -> Optional[Account]:
    """The account behind the Bearer token; None in single-user mode."""
    if not accounts_mode():
        return None
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    import auth
    who = auth.whoami(token) if token else None
    if not who:
        raise HTTPException(401, "Sign in first.")
    return Account(**who)


def store_for(account: Optional[Account]):
    """This account's store — the SQLite file in single-user mode."""
    if account is None:
        import api
        return api.store()
    with _LOCK:
        s = _STORES.get(account.email)
        if s is None:
            from pg_store import PgStore
            s = PgStore(account_email=account.email)
            _STORES[account.email] = s
        return s


def account_email(account: Optional[Account]) -> str:
    if account is not None:
        return account.email
    try:
        import api
        c = api.conn(required=False)
        return c.account_email() if c else os.environ.get("IMAP_USER", "")
    except Exception:
        return os.environ.get("IMAP_USER", "")


# ── the routes ───────────────────────────────────────────────────────────

class Credentials(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    token: str


class NewPassword(BaseModel):
    token: str
    password: str


def register(app):
    import auth

    @app.post("/api/auth/register")
    def api_register(body: Credentials):
        if not accounts_mode():
            raise HTTPException(409, "Accounts are off in single-user mode.")
        r = auth.register(body.email, body.password)
        if not r.get("ok"):
            raise HTTPException(400, r["detail"])
        # Until there is an outbound mail service the confirm token is returned
        # to the caller; in production it is emailed and never returned.
        return r

    @app.post("/api/auth/confirm")
    def api_confirm(body: Token):
        r = auth.confirm(body.token)
        if not r.get("ok"):
            raise HTTPException(400, r["detail"])
        return r

    @app.post("/api/auth/login")
    def api_login(body: Credentials):
        if not accounts_mode():
            raise HTTPException(409, "Accounts are off in single-user mode.")
        r = auth.login(body.email, body.password)
        if not r.get("ok"):
            raise HTTPException(401, r["detail"])
        return r

    @app.post("/api/auth/logout")
    def api_logout(authorization: Optional[str] = Header(default=None)):
        if authorization and authorization.lower().startswith("bearer "):
            auth.logout(authorization[7:].strip())
        return {"ok": True}

    @app.post("/api/auth/reset")
    def api_reset(body: dict):
        r = auth.request_reset(str(body.get("email", "")))
        return {"ok": True, "detail": r["detail"]}       # never the token

    @app.post("/api/auth/reset/confirm")
    def api_reset_confirm(body: NewPassword):
        r = auth.reset_password(body.token, body.password)
        if not r.get("ok"):
            raise HTTPException(400, r["detail"])
        return r

    @app.get("/api/me")
    def api_me(account: Optional[Account] = Depends(current_account)):
        if account is None:
            return {"id": 0, "email": account_email(None), "plan": "poc", "digest": "weekly",
                    "dataRegion": "this laptop", "mode": "single-user"}
        return account.model_dump() | {"mode": "accounts"}
