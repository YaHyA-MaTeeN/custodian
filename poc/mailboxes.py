"""
Each signed-in person's own mailbox connections, opened from the vault.

⚠️ ONE CONNECTION PER (ACCOUNT, ADDRESS), KEPT WHILE IN USE.

An IMAP session is a conversation with server-side state. It is opened once
per mailbox, reused across requests, checked before each use, and closed
after it has sat idle for a while. Two people never share one.

⚠️ THE PASSWORD PASSES THROUGH, IT IS NOT KEPT. It comes out of the vault,
goes into the connector's login, and the local name is deleted. It is never
logged and never returned.

Single-user mode (no DATABASE_URL) keeps the old behaviour: the one mailbox
the environment describes.
"""

import os
import threading
import time

from fastapi import HTTPException

import connect

IDLE_SECONDS = 600
_POOL: dict = {}            # (account_email, address) -> [connector, last_used]
_LOCK = threading.Lock()


def _rows(store) -> list:
    """(id, address, provider, state) for this account's mailboxes."""
    return store.conn.execute(
        "SELECT id, address, provider, state FROM public.mailboxes "
        "WHERE account_id=%s ORDER BY id", (store.account_id,)).fetchall()


def _open(store, mailbox_id: int, address: str):
    from api_mvp import vault_get
    from connectors.imap import ImapConnector
    if not os.environ.get("CUSTODIAN_SECRET"):
        raise HTTPException(503, "The credential vault is not configured on this server (CUSTODIAN_SECRET).")
    secret = vault_get(store, mailbox_id)
    if not secret:
        raise HTTPException(409, f"No stored credential for {address}. Reconnect the mailbox.")
    try:
        c = ImapConnector(connect.host_for(address), address, secret)
    except Exception as e:
        raise HTTPException(502, f"Could not open {address}: {str(e)[:80]}")
    finally:
        del secret
    return c


def _alive(c) -> bool:
    try:
        return c.conn.noop()[0] == "OK"
    except Exception:
        return False


def conn_for(account, store, address: str = ""):
    """
    The live connection for one of this account's mailboxes.

    address empty → the account's first connected mailbox.
    """
    if account is None:
        import api
        return api.conn()
    rows = [r for r in _rows(store) if r[3] == "connected"]
    if address:
        rows = [r for r in rows if r[1].lower() == address.lower()]
    if not rows:
        raise HTTPException(409, "Connect a mailbox first." if not address
                            else f"{address} is not a connected mailbox of this account.")
    mailbox_id, addr = rows[0][0], rows[0][1]
    key = (account.email, addr)
    with _LOCK:
        entry = _POOL.get(key)
        if entry and _alive(entry[0]):
            entry[1] = time.time()
            return entry[0]
        if entry:
            try:
                entry[0].close()
            except Exception:
                pass
        c = _open(store, mailbox_id, addr)
        _POOL[key] = [c, time.time()]
        _sweep()
        return c


def conn_for_message(account, store, message_id: str):
    """The connection for the mailbox a stored message belongs to."""
    if account is None:
        return conn_for(account, store)
    addr = store.one("SELECT COALESCE(account,'') FROM messages WHERE message_id=?", message_id) or ""
    return conn_for(account, store, addr)


def _sweep():
    now = time.time()
    for key, (c, last) in list(_POOL.items()):
        if now - last > IDLE_SECONDS:
            try:
                c.close()
            except Exception:
                pass
            _POOL.pop(key, None)


def drop(account_email: str, address: str = "") -> None:
    """Forget (and close) connections, e.g. after a disconnect."""
    with _LOCK:
        for key in list(_POOL):
            if key[0] == account_email and (not address or key[1].lower() == address.lower()):
                try:
                    _POOL[key][0].close()
                except Exception:
                    pass
                _POOL.pop(key, None)
