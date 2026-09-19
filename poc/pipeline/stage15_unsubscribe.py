"""
Stage 15 — Unsubscribe, properly.

⚠️ THIS IS IRREVERSIBLE, AND THAT IS NOT OBVIOUS.

Unsubscribing looks harmless next to sending mail. It is not. You cannot
un-unsubscribe: the sender's list no longer has you, and getting back on it
usually means finding a signup form that may no longer exist. If we guess
wrong, the user silently stops receiving something they wanted — and they will
not find out for weeks, which is the worst shape a mistake can have.

So it sits in stage 13's IRREVERSIBLE set alongside send, and needs a typed
yes exactly the same way.

⚠️ TWO MECHANISMS, AND ONLY ONE OF THEM IS SAFE FOR US TO USE.

  ONE-CLICK (RFC 8058)     the sender advertises List-Unsubscribe-Post.
                           One HTTPS POST. Machine-readable, standardised,
                           no page to interpret. WE DO THIS.

  A LINK IN THE BODY       a URL that opens a page with a button somewhere on
                           it. Removing you might need a click, a confirm, a
                           login, or a survey. WE DO NOT DO THIS — clicking
                           through a stranger's page automatically means
                           executing whatever that page asks for, and a
                           tracking link fires simply by being opened.

If a sender offers only a body link, we hand it to the user rather than press
it for them. Refusing to act is a real answer.
"""

import re
import urllib.parse
import urllib.request

# The header may hold several methods: <https://...>, <mailto:...>
BRACKETED = re.compile(r"<([^>]+)>")


def options(unsubscribe_header: str, one_click: bool) -> dict:
    """
    What this sender actually offers. Read, never guessed.

    `one_click` comes from List-Unsubscribe-Post, which is the sender stating
    in a standard field that a bare POST is enough. Without that field we must
    not POST, because the URL may be an ordinary page.
    """
    urls = BRACKETED.findall(unsubscribe_header or "")
    https = [u for u in urls if u.lower().startswith("https://")]
    mailto = [u for u in urls if u.lower().startswith("mailto:")]
    return {
        "can_one_click": bool(one_click and https),
        "https": https[0] if https else "",
        "mailto": mailto[0] if mailto else "",
        "has_any": bool(urls),
    }


def one_click(url: str, timeout: int = 10) -> dict:
    """
    The RFC 8058 POST. The body is fixed by the standard, not chosen by us.

    ⚠️ https only. An http:// unsubscribe URL would send the fact that this
    address is live, in clear text, to anyone watching the network — which is
    precisely the signal a spammer wants most.
    """
    if not url.lower().startswith("https://"):
        return {"done": False, "reason": "refused: unsubscribe URL is not https"}

    data = urllib.parse.urlencode({"List-Unsubscribe": "One-Click"}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "Custodian/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = 200 <= r.status < 300
            return {"done": ok, "status": r.status,
                    "reason": "unsubscribed" if ok else f"sender returned {r.status}"}
    except Exception as e:
        return {"done": False, "reason": f"could not reach the sender: {str(e)[:70]}"}


def describe(opts: dict) -> str:
    """What to tell the user before asking for their yes."""
    if opts["can_one_click"]:
        return "one-click unsubscribe, the standard kind — one request, no page opened"
    if opts["https"]:
        return ("this sender only offers a web page, not the one-click standard. "
                "I will not open it for you — here is the link")
    if opts["mailto"]:
        return "this sender only unsubscribes by email — that would send a message"
    return "this sender offers no unsubscribe method at all"
