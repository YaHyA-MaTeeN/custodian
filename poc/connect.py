"""
One place that decides which door to open.

    python run.py            # Gmail API  (OAuth, as before)
    python run.py --imap     # IMAP       (app password, no approval, no fee)

⚠️ THIS FILE EXISTS SO NO OTHER FILE HAS TO CHOOSE.

Every script asks `connect.open_mailbox()` and gets something that answers the
same eleven questions. Not one of them contains the word "gmail" or "imap"
outside of this module — which is what makes "only the connection changes"
true rather than merely claimed.

⚠️ AND WHY BOTH DOORS STAY.

  IMAP   free today, works on Gmail, Yahoo, Zoho, iCloud and every company
         mail server. No registration, no approval, no yearly audit.
         But we must ASK for new mail, over and over.

  API    Google tells US the moment mail lands, which is the whole game for
         anything reacting to what just arrived. Costs a paid security audit
         every year and months of approval.

So: IMAP to ship, API later for the one thing it is genuinely better at. The
pipeline above does not know or care which is in use.
"""

import os
import sys

GMAIL_IMAP_HOST = "imap.gmail.com"

# Where each provider's IMAP server lives. Adding one is a line, because the
# connector code is identical for all of them.
HOSTS = {
    "gmail.com":      "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "yahoo.com":      "imap.mail.yahoo.com",
    "icloud.com":     "imap.mail.me.com",
    "me.com":         "imap.mail.me.com",
    "outlook.com":    "outlook.office365.com",
    "hotmail.com":    "outlook.office365.com",
    "zoho.com":       "imap.zoho.com",
    "fastmail.com":   "imap.fastmail.com",
}


# Which company runs the mail for a domain, read from its MX records
# (UC-50 BR-30). A company address run by Google is a Gmail mailbox whatever
# the domain says, and must go through the Gmail route.
MX_SIGNATURES = (
    ("google.com", "imap.gmail.com"),
    ("googlemail.com", "imap.gmail.com"),
    ("outlook.com", "outlook.office365.com"),
    ("office365.com", "outlook.office365.com"),
    ("yahoodns.net", "imap.mail.yahoo.com"),
    ("zoho.com", "imap.zoho.com"),
    ("zoho.eu", "imap.zoho.eu"),
    ("icloud.com", "imap.mail.me.com"),
)


def mx_hosts(domain: str) -> list:
    """
    The MX records for a domain, via the system resolver.

    ⚠️ The standard library has no MX lookup and dnspython is not installed,
    so this shells out to nslookup, which every Windows and Linux box has.
    Read-only, cached by the OS, and it fails soft: an empty list means
    "could not tell", never an error the Owner has to see (UC-50 EX-1).
    """
    import re
    import subprocess
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True,
                             text=True, timeout=6).stdout
    except Exception:
        return []
    return [m.lower().rstrip(".") for m in
            re.findall(r"mail exchanger\s*=\s*(?:\d+\s+)?([\w.-]+)", out, re.I)]


def host_for(address: str) -> str:
    """
    Which IMAP server serves this address — UC-50 and UC-09, in order.

      1. A known ending goes straight to its server (BR-235).
      2. Otherwise the domain's MX records say who really runs the mail
         (BR-30): a company address on Google Workspace is imap.gmail.com.
      3. Otherwise imap.<domain>; mail.<domain> is tried by the connector
         if that does not answer (UC-09 step 3.4).

    The Owner is never asked for a server name until all of that has
    failed (BR-28).
    """
    domain = (address or "").split("@")[-1].lower()
    if domain in HOSTS:
        return HOSTS[domain]
    for mx in mx_hosts(domain):
        for sig, host in MX_SIGNATURES:
            if mx.endswith(sig):
                return host
    return f"imap.{domain}"


def want_imap() -> bool:
    """
    --imap on the command line, or IMAP_PASSWORD set with no OAuth token.

    ⚠️ The flag wins over the environment. An explicit instruction should
    never be overridden by something that happens to be set.
    """
    if "--imap" in sys.argv:
        return True
    if "--api" in sys.argv:
        return False
    # UC-12 — an upgrade recorded by upgrade.py wins over the guess below.
    try:
        import json
        door = json.loads(open("settings.json", encoding="utf-8").read()).get("door")
        if door == "api" and os.path.exists("token.json"):
            return False
        if door == "imap" and os.environ.get("IMAP_PASSWORD"):
            return True
    except Exception:
        pass
    return bool(os.environ.get("IMAP_PASSWORD")) and not os.path.exists("token.json")


def open_mailbox(quiet: bool = False):
    """
    The mailbox, whichever door it came through.

    Returns something with account_email, list_ids, fetch_envelopes,
    fetch_raw, apply_label, archive, mark_read, trash — and capability flags
    that tell the caller what this particular server can actually do.
    """
    if want_imap():
        user = os.environ.get("IMAP_USER")
        pw = os.environ.get("IMAP_PASSWORD")
        if not (user and pw):
            print("\n  --imap needs an app password:\n"
                  "    https://myaccount.google.com/apppasswords\n"
                  '    setx IMAP_USER "you@gmail.com"\n'
                  '    setx IMAP_PASSWORD "the16letters"\n'
                  "  then reopen the terminal.\n")
            sys.exit(1)
        from connectors.imap import ImapConnector
        conn = ImapConnector(host_for(user), user, pw)
        if not quiet:
            extras = []
            if getattr(conn, "supports_categories", False):
                extras.append("categories")
            if getattr(conn, "supports_labels", False):
                extras.append("labels")
            if getattr(conn, "supports_threads", False):
                extras.append("threads")
            note = f" · {', '.join(extras)}" if extras else ""
            print(f"  door: IMAP ({conn.name}){note} — no approval, no fee")
        return conn

    from connectors.gmail import GmailConnector
    conn = GmailConnector()
    if not quiet:
        print(f"  door: Gmail API — push available, paid audit at scale")
    return conn


def describe(conn) -> str:
    """One line naming what this connection can do. Used in headers."""
    caps = [c.replace("supports_", "") for c in
            ("supports_push", "supports_labels", "supports_categories",
             "supports_threads", "supports_send")
            if getattr(conn, c, False)]
    return f"{conn.name} · " + (", ".join(caps) if caps else "read only")


# ── opening a stored message safely, on either door ──────────────────
#
# One copy of this rule, used by every file that reopens a message it saved
# earlier — web.py, mailbox.py, brief.py, scan.py, waiting.py. Five copies
# would be five chances to disagree, and this rule is the one that stops the
# wrong email being shown, cached, summarised or labelled.

def looks_imap_uid(pid: str) -> bool:
    """
    An IMAP UID is all digits AND short. A Gmail API id is 16 hex characters
    and now and then contains no letters at all (1921741087216162) — length is
    what tells them apart.
    """
    return bool(pid) and pid.isdigit() and len(pid) <= 10


def live_id(conn, pid: str, mid: str):
    """
    The id to use for this message on the door we are connected through.

    ⚠️ provider_id BELONGS TO THE DOOR THAT SAVED IT.

    Of the 200 newest rows, 196 were saved through the Gmail API; opened
    through IMAP, their hex ids failed with "Could not parse command". And four
    rows saved through IMAP before the UID fix held SEQUENCE numbers that now
    name different emails. Message-ID is the one key that means the same email
    on both doors and on every day, so on IMAP — or for an id plainly from the
    other door — the message is looked up by that.
    """
    if not mid or not hasattr(conn, "find_by_message_id"):
        return pid
    if getattr(conn, "name", "").startswith("imap") or looks_imap_uid(pid):
        return conn.find_by_message_id(mid)
    return pid


def message_id_in(raw: bytes) -> str:
    """The Message-ID written inside a raw email, read from its headers only."""
    try:
        import email
        head = raw.split(b"\r\n\r\n", 1)[0][:20000]
        return str(email.message_from_bytes(head).get("Message-ID", "")).strip()
    except Exception:
        return ""


def fetch_verified(conn, pid: str, mid: str) -> bytes:
    """
    The raw email — and only if it is the email we asked for.

    ⚠️ AN ID CAN NAME A DIFFERENT MESSAGE, AND THE MAILBOX WILL NOT SAY SO.

    Checked on real data: four stored ids handed back the wrong email with no
    error at all. So the Message-ID inside what came back must match the one
    stored. Showing, caching or summarising the wrong person's email under
    this subject line is worse than failing, so a mismatch raises.
    """
    live = live_id(conn, pid, mid)
    if not live:
        raise LookupError("not in this mailbox any more — moved or deleted")
    raw = conn.fetch_raw(live)
    got = message_id_in(raw)
    if mid and got and got != mid.strip():
        raise LookupError("the mailbox returned a different email for this id — refused")
    return raw
