"""
Outbound mail from Custodian itself: confirmation and reset links.

    MAIL_FROM      the address Custodian sends from   (default: IMAP_USER)
    MAIL_PASSWORD  its app password                   (default: IMAP_PASSWORD)
    APP_URL        where the links point              (default: http://localhost:3000)

Plain SMTP with STARTTLS, the same door the connectors use to send replies.
For the MVP the sender is our own mailbox on a free tier; a transactional
service can replace this file without touching auth.py.

⚠️ When no sender is configured, nothing is sent and auth.py keeps returning
the token in the response, which is the development behaviour. When a sender
IS configured, the token is emailed and NOT returned.
"""

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

SMTP_HOSTS = {
    "gmail.com": ("smtp.gmail.com", 587),
    "googlemail.com": ("smtp.gmail.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587),
    "icloud.com": ("smtp.mail.me.com", 587),
    "me.com": ("smtp.mail.me.com", 587),
    "outlook.com": ("smtp.office365.com", 587),
    "hotmail.com": ("smtp.office365.com", 587),
    "zoho.com": ("smtp.zoho.com", 587),
}


def configured() -> bool:
    return bool(_from() and _password())


def _from() -> str:
    return os.environ.get("MAIL_FROM") or os.environ.get("IMAP_USER", "")


def _password() -> str:
    return os.environ.get("MAIL_PASSWORD") or os.environ.get("IMAP_PASSWORD", "")


def _smtp_host(address: str) -> tuple:
    domain = address.rsplit("@", 1)[-1].lower()
    return SMTP_HOSTS.get(domain, (f"smtp.{domain}", 587))


def send(to: str, subject: str, body: str) -> str:
    """Send one plain-text message. Returns the Message-ID. Raises on failure."""
    sender = _from()
    host, port = _smtp_host(sender)
    msg = EmailMessage()
    msg["From"] = f"Custodian <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(sender, _password())
        s.send_message(msg)
    return msg["Message-ID"]


def app_url() -> str:
    return os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")


def send_confirmation(to: str, token: str) -> str:
    return send(to, "Confirm your Custodian account",
                f"Welcome to Custodian.\n\n"
                f"Confirm your address by opening this link:\n\n"
                f"    {app_url()}/confirm?token={token}\n\n"
                f"The link works once and expires in 24 hours. If you did not sign up, ignore this message.\n")


def send_reset(to: str, token: str) -> str:
    return send(to, "Reset your Custodian password",
                f"Someone asked to reset the password for this address.\n\n"
                f"If that was you, open this link:\n\n"
                f"    {app_url()}/reset?token={token}\n\n"
                f"The link works once and expires in 1 hour. If it was not you, nothing changes; you can ignore this.\n")
