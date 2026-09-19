"""
Stage 2 — Parse and strip.

An email arrives with the entire previous conversation quoted underneath it.
This cuts that away and keeps only the new words. It is the single biggest cost
saving in the system: published measurement on 938 real emails put the
reduction at ~85%, median 966 tokens down to 124.
"""

from email import message_from_bytes
from email.policy import default as default_policy

from email_reply_parser import EmailReplyParser
from selectolax.parser import HTMLParser


def html_to_text(html: str) -> str:
    """
    Strip tags, keep the words.

    Deliberately NOT trafilatura or readability. Those exist to keep the
    article and throw away navigation, footers and boilerplate. In an email
    the "boilerplate" is the data — the amount, the due date, the order
    number. They solve the inverse of our problem.
    """
    tree = HTMLParser(html)
    for tag in tree.css("script, style"):
        tag.decompose()
    return tree.text(separator=" ", strip=True)


def pick_body(msg) -> tuple[str, bool]:
    """
    An email commonly contains itself twice — a plain part and an HTML part.
    Prefer plain; fall back to HTML.
    """
    had_html = False
    plain = html = None

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            continue
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
            had_html = True

    if plain and len(plain.strip()) > 30:
        return plain, had_html
    if html:
        return html_to_text(html), True
    return plain or "", had_html


def strip(raw_bytes: bytes) -> dict:
    """Raw message bytes in, clean new text out."""
    msg = message_from_bytes(raw_bytes, policy=default_policy)
    body, had_html = pick_body(msg)
    original_len = len(body)
    # The raw message including markup. Two different savings get reported:
    # raw -> text is the HTML strip, text -> new is the quoted-reply cut.
    raw_len = len(raw_bytes)

    new_text = EmailReplyParser.parse_reply(body) if body else ""

    # ~2% of replies strip to almost nothing — someone answers "ok" above a
    # long quote, or the quote markers are unusual. Without this guard we
    # would silently classify empty strings and never know.
    if len(new_text.strip()) < 20 and original_len > 20:
        new_text = body

    attachments = [
        {"name": p.get_filename(), "type": p.get_content_type(),
         "size": len(p.get_payload(decode=True) or b"")}
        for p in msg.iter_attachments()
    ]

    return {
        "text": new_text.strip(),
        "raw_chars": raw_len,
        "original_chars": original_len,
        "stripped_chars": len(new_text.strip()),
        "reduction": round(1 - len(new_text.strip()) / original_len, 3) if original_len else 0.0,
        "total_reduction": round(1 - len(new_text.strip()) / raw_len, 3) if raw_len else 0.0,
        "had_html": had_html,
        "attachments": attachments,
    }
