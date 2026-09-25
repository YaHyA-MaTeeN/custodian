"""
Accounts, sign-in and sessions (UC-01, UC-02) — on the public schema.

    python auth.py register you@x.com          # asks for a password; prints the confirm token
    python auth.py confirm <token>
    python auth.py login you@x.com             # prints a session token
    python auth.py reset you@x.com             # prints a reset token (would be emailed)

⚠️ WHAT IS AND IS NOT STORED. The password is stored as a salted one-way
scrypt hash, never in any readable form (UC-01 "Data NOT stored"). A
confirmation or reset token is single-use and expires. A session is a
random token with an expiry, scoped to one account.

⚠️ THE SAME MESSAGE FOR "NO SUCH ACCOUNT" AND "WRONG PASSWORD" (BR-07), and
a growing delay after repeated failures, so nobody can list which addresses
have accounts by trying them.

⚠️ SIGNING IN GRANTS NO MAILBOX ACCESS (BR-05). A session lets you reach
your account. Each mailbox is a separate, explicit grant (UC-04 … UC-11).

⚠️ A PASSWORD RESET ENDS EVERY OTHER SESSION (BR-08) and touches no mailbox
connection — the two are unrelated.
"""

import hashlib
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone

SESSION_DAYS = 30
CONFIRM_DAYS = 7
RESET_HOURS = 1
_FAILS = {}                    # email → (count, last_at); progressive delay from the 4th


def _conn():
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url, connect_timeout=20)


# ── passwords ────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return secrets.compare_digest(got.hex(), h)
    except Exception:
        return False


# ── register, confirm ────────────────────────────────────────────────────

def register(email: str, password: str) -> dict:
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return {"ok": False, "detail": "That does not look like an email address."}
    if len(password) < 8:
        return {"ok": False, "detail": "Use at least 8 characters."}
    with _conn() as c:
        r = c.execute("SELECT id, confirmed_at FROM accounts WHERE email=%s", (email,)).fetchone()
        if r and r[1]:
            # EX-1: never reveals which sign-in method the account uses.
            return {"ok": False, "detail": "That address already has an account. Sign in, or reset your password."}
        if r:
            c.execute("UPDATE accounts SET password_hash=%s WHERE id=%s", (hash_password(password), r[0]))
            account_id = r[0]
        else:
            account_id = c.execute(
                "INSERT INTO accounts (email, password_hash) VALUES (%s, %s) RETURNING id",
                (email, hash_password(password))).fetchone()[0]
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO confirmation_tokens (token, account_id, purpose, expires_at) "
                  "VALUES (%s, %s, 'confirm', %s)",
                  (token, account_id, datetime.now(timezone.utc) + timedelta(days=CONFIRM_DAYS)))
        c.commit()
    # Emailed when a sender is configured (mailer.py). Otherwise, in
    # development, returned here for the caller to deliver.
    import mailer
    if mailer.configured():
        try:
            mailer.send_confirmation(email, token)
            return {"ok": True, "needsConfirmation": True, "detail": "Check your inbox for the confirmation link."}
        except Exception as e:
            return {"ok": False, "detail": f"Could not send the confirmation email ({type(e).__name__}). Try again in a minute."}
    return {"ok": True, "needsConfirmation": True, "confirmToken": token}


def confirm(token: str) -> dict:
    with _conn() as c:
        r = c.execute("SELECT account_id, expires_at FROM confirmation_tokens "
                      "WHERE token=%s AND purpose='confirm'", (token,)).fetchone()
        if not r or r[1] < datetime.now(timezone.utc):
            return {"ok": False, "detail": "That link is not valid any more. Request a new one."}
        c.execute("UPDATE accounts SET confirmed_at=now() WHERE id=%s", (r[0],))
        c.execute("DELETE FROM confirmation_tokens WHERE token=%s", (token,))
        c.commit()
    return {"ok": True}


# ── login, sessions ──────────────────────────────────────────────────────

def _throttle(email: str):
    n, last = _FAILS.get(email, (0, 0))
    if n >= 3:
        wait = min(2 ** (n - 3), 30)
        if time.time() - last < wait:
            time.sleep(wait - (time.time() - last))


def login(email: str, password: str) -> dict:
    email = email.strip().lower()
    _throttle(email)
    with _conn() as c:
        r = c.execute("SELECT id, password_hash, confirmed_at FROM accounts WHERE email=%s",
                      (email,)).fetchone()
        ok = bool(r and r[1] and check_password(password, r[1]))
        if not ok:
            n, _ = _FAILS.get(email, (0, 0))
            _FAILS[email] = (n + 1, time.time())
            # T-1: identical whether or not the address exists.
            return {"ok": False, "detail": "That email address and password do not match."}
        if not r[2]:
            return {"ok": False, "detail": "Confirm your address first — check your inbox."}
        _FAILS.pop(email, None)
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions (token, account_id, expires_at) VALUES (%s, %s, %s)",
                  (token, r[0], datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
        c.commit()
    return {"ok": True, "token": token, "account": {"id": r[0], "email": email}}


def whoami(token: str) -> dict | None:
    """The account behind a session token, or None."""
    if not token:
        return None
    with _conn() as c:
        r = c.execute("""SELECT a.id, a.email, a.plan, a.digest, a.data_region
                           FROM sessions s JOIN accounts a ON a.id = s.account_id
                          WHERE s.token=%s AND s.expires_at > now()""", (token,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "email": r[1], "plan": r[2], "digest": r[3], "dataRegion": r[4]}


def logout(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token=%s", (token,))
        c.commit()


# ── password reset ───────────────────────────────────────────────────────

def request_reset(email: str) -> dict:
    email = email.strip().lower()
    with _conn() as c:
        r = c.execute("SELECT id FROM accounts WHERE email=%s", (email,)).fetchone()
        token = None
        if r:
            token = secrets.token_urlsafe(32)
            c.execute("INSERT INTO confirmation_tokens (token, account_id, purpose, expires_at) "
                      "VALUES (%s, %s, 'reset', %s)",
                      (token, r[0], datetime.now(timezone.utc) + timedelta(hours=RESET_HOURS)))
            c.commit()
    # T-3: the same reply whether or not the address exists.
    import mailer
    if mailer.configured():
        if token:
            try:
                mailer.send_reset(email, token)
            except Exception:
                pass                       # same reply either way; never reveal
        return {"ok": True, "detail": "If that address has an account, a reset link is on its way."}
    return {"ok": True, "detail": "If that address has an account, a reset link is on its way.",
            "resetToken": token}


def reset_password(token: str, password: str) -> dict:
    if len(password) < 8:
        return {"ok": False, "detail": "Use at least 8 characters."}
    with _conn() as c:
        r = c.execute("SELECT account_id, expires_at FROM confirmation_tokens "
                      "WHERE token=%s AND purpose='reset'", (token,)).fetchone()
        if not r or r[1] < datetime.now(timezone.utc):
            return {"ok": False, "detail": "That reset link is not valid any more."}
        c.execute("UPDATE accounts SET password_hash=%s, confirmed_at=COALESCE(confirmed_at, now()) "
                  "WHERE id=%s", (hash_password(password), r[0]))
        c.execute("DELETE FROM sessions WHERE account_id=%s", (r[0],))          # BR-08
        c.execute("DELETE FROM confirmation_tokens WHERE token=%s", (token,))
        c.commit()
    return {"ok": True}


# ── keyboard use ─────────────────────────────────────────────────────────

def main():
    import getpass
    args = sys.argv[1:]
    if not args:
        print(__doc__); return
    cmd = args[0]
    if cmd == "register":
        print(register(args[1], getpass.getpass("  password: ")))
    elif cmd == "confirm":
        print(confirm(args[1]))
    elif cmd == "login":
        print(login(args[1], getpass.getpass("  password: ")))
    elif cmd == "reset":
        print(request_reset(args[1]))
    elif cmd == "whoami":
        print(whoami(args[1]))


if __name__ == "__main__":
    main()
