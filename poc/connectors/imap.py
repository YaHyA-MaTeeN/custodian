"""
IMAP adapter — the universal one.

⚠️ WHY THIS EXISTS WHEN GMAIL AND OUTLOOK HAVE PROPER APIs.

Because everything else is IMAP. Yahoo, iCloud, Fastmail, a company's own
Exchange, a web host's mailbox from 1998. There is no API to call and no
partnership to sign; IMAP is the floor every provider stands on.

⚠️ AND WHY IT IS THE HARDEST ONE.

IMAP is a protocol for READING A FOLDER, not for asking questions about mail.
It has no labels, no push in the sense Gmail means it, no server-side notion of
a conversation, and no cheap "what changed since X". Everything the pipeline
takes for granted has to be either emulated or honestly declared missing —
which is exactly what the capability flags are for.

  supports_labels = False   → the pipeline files by COPYING to a folder instead
  supports_push   = False   → the caller polls; IDLE exists but holds a socket
                              open per mailbox, which does not scale to many
                              users on one worker
  supports_threads = False  → we stitch threads ourselves from In-Reply-To

⚠️ THOSE ARE THE DEFAULTS, AND ON GMAIL THREE OF THEM FLIP TO TRUE.

Gmail's IMAP advertises X-GM-EXT-1, which brings real labels, real thread ids
and the whole Gmail search language. Measured on a live mailbox: 35 of the 43
capabilities this connector was audited for work, including applying and
removing a label without the message leaving the inbox.

Sending is the one thing IMAP itself cannot do — but the app password that
opens imap.gmail.com also opens smtp.gmail.com, so send() and create_draft()
live here too. "IMAP cannot send" is true about the protocol and wrong about
the product.

⚠️ EVERY COMMAND IN HERE IS A **UID** COMMAND, AND THAT IS NOT A STYLE CHOICE.

imaplib's fetch(), search(), store() and copy() all speak SEQUENCE NUMBERS —
a message's position in the folder at this instant, which shifts whenever
anything above it arrives or leaves. We store provider_id and reuse it days
later. A sequence number reused later is a different message, and nothing
raises an error when that happens. conn.uid("FETCH", ...) is the version that
means what the caller thinks it means.

⚠️ NOTHING ABOVE THIS FILE CHANGES BECAUSE OF ANY OF THAT.

The pipeline asks `if c.supports_labels`, never `if c.name == "gmail"`. That is
the whole reason a second provider is one new file rather than a rewrite.
"""

import email
import imaplib
import os
import re
from email.policy import default as default_policy
from typing import Iterator

from .base import Envelope

# Where each provider keeps its mail. IMAP does not standardise these names,
# which is a fair summary of the protocol in general.
KNOWN = {
    # ⚠️ Gmail was missing here and silently fell through to "Sent"/"Trash",
    # which do not exist on Gmail. Trashing a message would have copied it to
    # a folder that had to be created first and was not the real bin.
    "imap.gmail.com":       {"sent": "[Gmail]/Sent Mail",
                             "trash": "[Gmail]/Trash"},
    "imap.mail.yahoo.com":  {"sent": "Sent",           "trash": "Trash"},
    "imap.mail.me.com":     {"sent": "Sent Messages",  "trash": "Deleted Messages"},
    "imap.fastmail.com":    {"sent": "Sent",           "trash": "Trash"},
    "outlook.office365.com":{"sent": "Sent Items",     "trash": "Deleted Items"},
}
DEFAULT_FOLDERS = {"sent": "Sent", "trash": "Trash"}


def _parse_sender(raw: str) -> tuple[str, str, str]:
    if not raw:
        return "", "", ""
    m = re.search(r"<([^>]+)>", raw)
    addr = (m.group(1) if m else raw).strip().lower()
    name = raw.split("<")[0].strip().strip('"') if m else ""
    return addr, name, (addr.split("@")[-1] if "@" in addr else "")


class ImapConnector:
    name = "imap"

    # ⚠️ THE HONEST ANSWERS. Claiming a capability we do not have would break
    # the pipeline in a way that looks like a bug in the pipeline.
    supports_push = False           # IDLE exists; it costs a held socket each
    supports_labels = False         # folders only — filing means MOVING
    supports_server_search = True   # IMAP SEARCH is real, if limited
    supports_spam_folder = True     # usually called Junk or Spam
    supports_threads = False        # stitched by us from In-Reply-To
    # ⚠️ Set at CONNECT time, not hard-coded — Gmail over IMAP can do things
    # Yahoo over IMAP cannot. Two servers, one protocol, different powers.
    supports_categories = False     # becomes True on Gmail (X-GM-RAW)
    supports_gmail_search = False
    # ⚠️ TRUE FOR IMAP, AND WE DO NOT ONLY HAVE IMAP.
    #
    # The app password opens smtp.gmail.com as well. Set at connect time from
    # whether we know this provider's outgoing server, so a mailbox we cannot
    # send through says so honestly instead of failing at stage 14.
    supports_send = False
    max_fetch_per_second = 10.0     # conservative; IMAP servers are not APIs

    def __init__(self, host: str, user: str, password: str = "", port: int = 993,
                 token: str = ""):
        self.host, self.user = host, user
        self._folders = KNOWN.get(host, DEFAULT_FOLDERS)
        self.errors = []
        self.conn = imaplib.IMAP4_SSL(host, port)
        if token:
            # ⚠️ UC-05 — Outlook takes no passwords any more. Microsoft
            # withdrew them for personal accounts in September 2024, so the
            # only way in is a sign-in token over the SAME IMAP engine:
            # AUTHENTICATE XOAUTH2 with "user=…\x01auth=Bearer …\x01\x01".
            # Nothing above this line changes. The token is obtained by
            # outlook.py; it is never a password and we never see one.
            auth = f"user={user}\x01auth=Bearer {token}\x01\x01"
            self.conn.authenticate("XOAUTH2", lambda _: auth.encode())
        else:
            self.conn.login(user, password)
        self.conn.select("INBOX", readonly=False)
        # Ask the server what it can do rather than guessing from the hostname.
        if self.has_gmail_extensions():
            self.supports_categories = True
            self.supports_gmail_search = True
            self.supports_labels = True     # X-GM-LABELS is real labels
            self.supports_threads = True    # X-GM-THRID is a real thread id
            self.name = "imap-gmail"
        if self.can_send():
            self.supports_send = True

    # --- Gmail's own IMAP extensions --------------------------------------
    #
    # ⚠️ THE ANSWER TO "CAN IMAP GIVE US ONLY THE PRIMARY TAB?"
    #
    # Yes, on Gmail — and this is the part most people miss. Gmail's IMAP
    # server advertises a capability called X-GM-EXT-1, which adds three
    # things plain IMAP has never had:
    #
    #   X-GM-RAW     run a full GMAIL SEARCH over IMAP. Every operator from
    #                the Gmail search box works, INCLUDING category:primary.
    #   X-GM-LABELS  read and set Gmail labels over IMAP.
    #   X-GM-THRID   Gmail's own conversation id.
    #
    # So the three things the comparison document marked as "unverified over
    # IMAP" — category tabs, labels, threads — are all reachable. They are
    # Gmail-only, which is exactly why they sit behind a capability check
    # rather than being assumed.

    def has_gmail_extensions(self) -> bool:
        """Does this server speak Gmail's IMAP dialect?"""
        try:
            typ, data = self.conn.capability()
            caps = b" ".join(data).upper()
            return b"X-GM-EXT-1" in caps
        except Exception:
            return False

    def gmail_search(self, query: str) -> list:
        """
        Run a Gmail search over IMAP. The query is the same string you would
        type into Gmail's search box.

            category:primary          only the Primary tab
            category:promotions       only Promotions
            is:unread newer_than:30d  unread from the last month
            has:attachment            anything with a file

        ⚠️ This is why "IMAP cannot do categories" is wrong FOR GMAIL. It is
        true for Yahoo, Zoho and every other IMAP server — so the pipeline
        must ask `supports_categories` rather than assume either way.
        """
        if not self.has_gmail_extensions():
            self.errors.append("server does not speak X-GM-EXT-1")
            return []
        # The query is quoted and sent as a literal, because Gmail search
        # strings contain colons and spaces that a bare atom cannot carry.
        q = query.encode()
        typ, data = self.conn.uid("SEARCH", "X-GM-RAW", b'"' + q + b'"')
        if typ != "OK":
            self.errors.append(f"X-GM-RAW search failed: {query}")
            return []
        return data[0].split()

    # Labels come back either quoted or bare, and only the server decides
    # which: a label with a space in it is quoted, one without is not.
    #     X-GM-LABELS ("Custodian/Machine mail" Custodian/Invoices \\Important)
    _LABEL = re.compile(r'"([^"]*)"|([^\s()"]+)')

    def gmail_labels(self, uid) -> list[str]:
        """
        The Gmail labels on one message, over IMAP.

        ⚠️ THIS RETURNED [] FOR EVERY UNQUOTED LABEL, AND THAT LOOKED LIKE
        "the label was never applied".

        The old pattern matched quoted strings, or bare runs of \\w. A label
        without a space is sent bare — and "Custodian/AuditProbe" contains a
        slash, which \\w does not match. So labels with spaces were read
        correctly and labels without them vanished, which is the worst
        possible split: it works on the examples you happen to try first.

        The audit reported "apply a label — did not appear" three times while
        the server was replying, in the same breath, that the label was there.
        The write was never broken. Reading it back was.
        """
        if not self.has_gmail_extensions():
            return []
        try:
            typ, data = self.conn.uid("FETCH", uid, "(X-GM-LABELS)")
            if typ != "OK" or not data or not data[0]:
                return []
            raw = data[0].decode("utf-8", "replace")
            inside = raw.split("X-GM-LABELS", 1)
            if len(inside) < 2:
                return []
            # Take only what is between the first ( and its closing ).
            body = inside[1]
            start = body.find("(")
            if start == -1:
                return []
            depth, end = 0, len(body)
            for i, ch in enumerate(body[start:], start):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            out = []
            for quoted, bare in self._LABEL.findall(body[start + 1:end]):
                name = quoted or bare
                if name:
                    out.append(name)
            return out
        except Exception:
            return []

    # --- identity ---------------------------------------------------------

    def account_email(self) -> str:
        return self.user

    def message_count(self) -> int:
        typ, data = self.conn.select("INBOX", readonly=True)
        return int(data[0]) if typ == "OK" else 0

    # --- reading ----------------------------------------------------------

    def list_ids(self, on_progress=None) -> list[str]:
        # ⚠️ UID SEARCH, NOT SEARCH — AND THE DIFFERENCE IS NOT COSMETIC.
        #
        # Plain SEARCH returns SEQUENCE NUMBERS: a message's position in the
        # folder at this instant. Delete one older message and every number
        # after it shifts down by one. We store provider_id in the database
        # and use it again tomorrow — by which time a sequence number points
        # at a different email, and nothing anywhere would report an error.
        #
        # A UID is fixed for the life of the message. gmail_search() already
        # returned UIDs, so half this connector was handing out one kind of
        # id and half the other, and both were called provider_id.
        typ, data = self.conn.uid("SEARCH", None, "ALL")
        if typ != "OK":
            self.errors.append("IMAP SEARCH failed")
            return []
        return data[0].split()[::-1]          # newest first, like Gmail

    def _fetch_one(self, uid) -> Envelope | None:
        """
        ⚠️ BODY.PEEK, not BODY.

        Plain BODY[] marks the message as READ on the server. We are reading
        envelopes to decide what matters — silently marking a customer's unread
        mail as read while doing it would be unforgivable, and it is a single
        keyword away.
        """
        try:
            typ, data = self.conn.uid("FETCH", uid, "(FLAGS BODY.PEEK[HEADER])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                return None
            # FLAGS can arrive after the header literal, in the next piece.
            trailing = data[1] if len(data) > 1 and isinstance(data[1], bytes) else b""
            return self._envelope_from(uid, data[0][0] + b" " + trailing, data[0][1])
        except Exception as e:
            self.errors.append(f"{uid}: {type(e).__name__}: {str(e)[:80]}")
            return None

    def _envelope_from(self, uid, meta: bytes, header: bytes) -> Envelope | None:
        """One FETCH response into one Envelope. Shared by single and batched fetch."""
        try:
            flags = imaplib.ParseFlags(meta) if b"FLAGS" in meta else ()
            msg = email.message_from_bytes(header, policy=default_policy)
        except Exception as e:
            self.errors.append(f"{uid}: {type(e).__name__}: {str(e)[:80]}")
            return None

        h = {k.lower(): v for k, v in msg.items()}
        addr, name, domain = _parse_sender(h.get("from", ""))
        unsub = h.get("list-unsubscribe", "")

        return Envelope(
            provider_id=uid.decode() if isinstance(uid, bytes) else str(uid),
            message_id=h.get("message-id", ""),
            thread_id="",                       # IMAP has no threads. We stitch.
            account=self.user,
            sender=addr, sender_name=name, sender_domain=domain,
            recipients=(h.get("to", "") + " " + h.get("cc", "")).strip()[:500],
            subject=str(h.get("subject", ""))[:300],
            date=h.get("date", ""),
            unread=b"\\Seen" not in flags,
            in_inbox=True,
            unsubscribe=unsub,
            one_click=bool(h.get("list-unsubscribe-post")),
            list_id=h.get("list-id", ""),
            bulk=bool(unsub) or h.get("precedence", "").lower() in ("bulk", "list"),
            auto_submitted=h.get("auto-submitted", ""),
            in_reply_to=h.get("in-reply-to", ""),
            references=h.get("references", ""),
            # Only the topmost stamp is trusted; stage 4 checks who wrote it.
            auth_results=str(h.get("authentication-results", ""))[:600],
        )

    # How many messages one FETCH asks for. 100 keeps each command line short
    # and each response a few hundred KB — well inside what servers accept.
    BATCH = 100

    def fetch_envelopes(self, ids: list) -> Iterator[Envelope]:
        """
        ⚠️ IN BATCHES — ONE ROUND TRIP FOR MANY MESSAGES.

        This used to ask for one message per command. limits_imap.py measured
        what that cost: 676 ms per message, almost all of it the round trip to
        Google and back, against 74 messages a second when 200 were asked for
        in one command. Syncing every header of a 7,882-message mailbox took
        89 minutes one at a time and under 2 minutes batched. Gmail's daily
        cap was never the bottleneck; the way we asked was.

        ⚠️ STILL SEQUENTIAL ON ONE CONNECTION.

        An IMAP connection is a single conversation with state — a selected
        folder, a command in flight. Two threads sharing one is not faster, it
        is corrupt. Batching makes each command carry more; it does not run
        commands side by side.
        """
        ids = [u.decode() if isinstance(u, bytes) else str(u) for u in ids]
        for i in range(0, len(ids), self.BATCH):
            chunk = ids[i:i + self.BATCH]
            try:
                typ, data = self.conn.uid("FETCH", ",".join(chunk),
                                          "(UID FLAGS BODY.PEEK[HEADER])")
                if typ != "OK":
                    raise RuntimeError(f"FETCH answered {typ}")
            except Exception as e:
                # A batch that fails falls back to one at a time, so one bad
                # message cannot cost us the other ninety-nine.
                self.errors.append(f"batch fetch failed, one by one instead: {str(e)[:60]}")
                for uid in chunk:
                    env = self._fetch_one(uid)
                    if env:
                        yield env
                continue

            got = {}
            items = data or []
            for j, item in enumerate(items):
                if not isinstance(item, tuple):
                    continue
                meta, header = item[0], item[1]
                # FLAGS can arrive after the header literal, in the next piece.
                nxt = items[j + 1] if j + 1 < len(items) else b""
                if isinstance(nxt, bytes):
                    meta = meta + b" " + nxt
                m = re.search(rb"UID (\d+)", meta)
                if m:
                    got[m.group(1).decode()] = (meta, header)

            # Yield in the caller's order, not the server's. A UID that is
            # missing from the answer was deleted between list and fetch —
            # skipped, not guessed at.
            for uid in chunk:
                if uid in got:
                    env = self._envelope_from(uid, *got[uid])
                    if env:
                        yield env

    # ── live polling ──────────────────────────────────────────────────

    def current_history_id(self) -> str:
        """
        A bookmark meaning "everything up to here, I have seen".

        ⚠️ Gmail hands out a real history id. IMAP has no such thing, so we
        use the highest UID in the folder — which IMAP guarantees only ever
        increases within a folder, and never repeats. Same promise, different
        mechanism. The caller is told neither, and asks for neither: it gets
        an opaque bookmark back and hands it in again next time.
        """
        try:
            typ, data = self.conn.uid("SEARCH", None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return "0"
            return data[0].split()[-1].decode()
        except Exception as e:
            self.errors.append(f"bookmark failed: {e}")
            return "0"

    def new_since(self, history_id: str) -> tuple:
        """
        What has arrived since that bookmark. Returns (ids, new bookmark).

        ⚠️ The folder must be re-selected on every poll. A long-lived IMAP
        connection does not learn about new mail on its own — SELECT is what
        makes the server re-report the folder, and without it this loop will
        sit there returning nothing forever while mail piles up.
        """
        try:
            self.conn.select("INBOX", readonly=False)
            last = int(history_id or 0)
            typ, data = self.conn.uid("SEARCH", None, f"UID {last + 1}:*")
            if typ != "OK" or not data or not data[0]:
                return [], history_id
            uids = [u.decode() for u in data[0].split()]
            # ⚠️ "UID n:*" always returns at least one message even when
            # nothing is new — the server clamps the range to the highest
            # existing UID. Anything at or below the bookmark is not new.
            fresh = [u for u in uids if int(u) > last]
            if not fresh:
                return [], history_id
            return fresh, str(max(int(u) for u in fresh))
        except Exception as e:
            self.errors.append(f"poll failed: {e}")
            return [], history_id

    def find_by_message_id(self, message_id: str) -> str | None:
        """
        This folder's UID for a message, found by its Message-ID.

        ⚠️ WHY NOT JUST USE THE STORED provider_id.

        Because it belongs to the door that saved it. A row saved through the
        Gmail API carries a hex id that IMAP cannot even parse — tested:
        "Could not parse command". And a row saved through IMAP before the UID
        fix can carry a SEQUENCE number, which now names whatever message sits
        at that position today. Message-ID is the one identifier that means
        the same email on both doors and on every day, so opening goes by it.
        """
        mid = (message_id or "").strip()
        if not mid:
            return None
        if not mid.startswith("<"):
            mid = f"<{mid}>"
        try:
            typ, data = self.conn.uid("SEARCH", None, "HEADER", "Message-ID", f'"{mid}"')
        except Exception as e:
            self.errors.append(f"find by Message-ID failed: {str(e)[:60]}")
            return None
        uids = data[0].split() if typ == "OK" and data and data[0] else []
        return uids[-1].decode() if uids else None

    def fetch_raw(self, provider_id: str) -> bytes:
        typ, data = self.conn.uid("FETCH", provider_id, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return b""
        return data[0][1]

    def fetch_attachment(self, provider_id: str, filename: str) -> bytes | None:
        raw = self.fetch_raw(provider_id)
        if not raw:
            return None
        msg = email.message_from_bytes(raw, policy=default_policy)
        for part in msg.iter_attachments():
            if part.get_filename() == filename:
                return part.get_payload(decode=True)
        return None

    # --- acting -----------------------------------------------------------

    def apply_label(self, provider_id: str, folder: str) -> None:
        """
        ⚠️ BR-100 — the same button means different things underneath.

        Gmail adds a label and the message stays put. Plain IMAP has no labels,
        so the nearest honest equivalent is a COPY into a folder. The Owner
        pressed one button; translating it is our job, not theirs.

        ⚠️ THIS USED TO MOVE THE MESSAGE, AND THE AUDIT CAUGHT IT DOING SO.

        The old version did COPY, then +FLAGS \\Deleted, then EXPUNGE. On Gmail
        that does not file a message — it takes it OUT OF THE INBOX. Labelling
        is supposed to be the safest thing the system does; sort_mailbox.py
        promises in writing that it "only applies labels, never moves,
        archives or deletes". It was archiving every message it touched.

        It also failed silently, because the label then appeared to be missing:
        we looked the message up by the UID it no longer had.

        ⚠️ AND EVERY COMMAND HERE IS A **UID** COMMAND.

        conn.copy() and conn.store() take SEQUENCE numbers — a message's
        position in the folder right now, which shifts the moment anything
        arrives or leaves. provider_id is a UID. Passing a UID to a sequence
        command does not error; it acts on a completely different message.
        """
        if self.has_gmail_extensions():
            # The real thing: add the label, leave the message where it is.
            # This is exactly what Gmail's API does for the same call.
            self.conn.uid("STORE", provider_id, "+X-GM-LABELS", f'"{folder}"')
            return
        safe = self.ensure_label(folder)
        # COPY only. The message stays in the inbox as well — filing must not
        # be able to make mail disappear from where the Owner expects it.
        self.conn.uid("COPY", provider_id, f'"{safe}"')

    # --- sending, which is NOT IMAP -----------------------------------------
    #
    # ⚠️ "IMAP CANNOT SEND" IS TRUE AND MISLEADING IN THE SAME BREATH.
    #
    # IMAP is a protocol for reading a folder. It has no verb that means send,
    # and it never will. But the thing we actually chose was not IMAP — it was
    # the APP PASSWORD, and one app password opens two doors:
    #
    #     imap.gmail.com:993   reading
    #     smtp.gmail.com:587   sending
    #
    # Same password, same account, no extra approval, no audit, no fee. So the
    # honest answer to "can it send" is yes — over SMTP, which is what every
    # mail client on earth has always done. The comparison document has this
    # right: it lists "send mail" under what the app-password route can do.
    #
    # ⚠️ THE APPROVAL GATE DOES NOT MOVE BECAUSE THE PROTOCOL DID.
    #
    # This is called from stage 14 and from nowhere else, after stage 13 has
    # matched a typed yes against a hash of this exact body. A second way to
    # send would be a second way to send without asking.

    SMTP_HOSTS = {
        "imap.gmail.com":        ("smtp.gmail.com", 587),
        "imap.mail.yahoo.com":   ("smtp.mail.yahoo.com", 587),
        "imap.mail.me.com":      ("smtp.mail.me.com", 587),
        "imap.fastmail.com":     ("smtp.fastmail.com", 587),
        "outlook.office365.com": ("smtp.office365.com", 587),
    }

    def can_send(self) -> bool:
        """Whether we know this provider's outgoing server."""
        return self.host in self.SMTP_HOSTS

    def send(self, to: str, subject: str, body: str,
             in_reply_to: str = "", references: str = "",
             thread_id: str = "") -> dict:
        """
        Send one message over SMTP. Same signature as the Gmail connector's,
        so stage 14 does not know or care which door it is going out of.

        ⚠️ The sent copy is APPENDed to the Sent folder afterwards. SMTP hands
        the message to the internet and keeps no record; Gmail's API files a
        copy for you and SMTP does not. Without the APPEND the Owner sends a
        reply and then cannot find it in their own Sent Mail, which reads as
        the message never having gone.
        """
        import smtplib
        import time
        from email.message import EmailMessage
        from email.utils import make_msgid, formatdate

        if not to:
            raise ValueError("no recipient — refusing to send")
        if not self.can_send():
            raise RuntimeError(f"no SMTP server known for {self.host}")

        password = os.environ.get("IMAP_PASSWORD", "")
        if not password:
            raise RuntimeError("IMAP_PASSWORD is not set — cannot send")

        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = self.user
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.user.split("@")[-1])
        # Threading. Without these a reply arrives as a new conversation, which
        # is the single most visible way an assistant looks broken.
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        msg.set_content(body)

        host, port = self.SMTP_HOSTS[self.host]
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(self.user, password)
            s.send_message(msg)

        # File a copy where the Owner expects to find it.
        try:
            sent = self._folders.get("sent", "Sent")
            self.conn.append(f'"{sent}"', "\\Seen",
                             imaplib.Time2Internaldate(time.time()),
                             msg.as_bytes())
        except Exception as e:
            self.errors.append(f"sent, but could not file a copy: {e}")

        return {"id": msg["Message-ID"], "threadId": thread_id or "",
                "via": f"{host}:{port}"}

    def create_draft(self, to: str, subject: str, body: str,
                     in_reply_to: str = "", references: str = "",
                     thread_id: str = "") -> dict:
        """
        ⚠️ SAFER THAN SENDING, AND THAT IS THE POINT (UC-25, BR-95).

        A draft appears in the Owner's own Drafts folder. They open it, edit
        it, and press send themselves — or never do. Over IMAP this is an
        APPEND to Drafts, which needs no SMTP and cannot reach anyone.
        """
        import time
        from email.message import EmailMessage
        from email.utils import formatdate, make_msgid

        msg = EmailMessage()
        # A Message-ID of our own, so the draft can be found again — by the
        # Owner's mail app when they send it, and by the audit to remove it.
        msg["Message-ID"] = make_msgid(domain=self.user.split("@")[-1])
        msg["To"] = to
        msg["From"] = self.user
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        msg.set_content(body)

        folder = "[Gmail]/Drafts" if self.has_gmail_extensions() else "Drafts"
        typ, data = self.conn.append(f'"{folder}"', "\\Draft",
                                     imaplib.Time2Internaldate(time.time()),
                                     msg.as_bytes())
        return {"id": str(data), "message_id": msg["Message-ID"],
                "folder": folder, "ok": typ == "OK"}

    def forward(self, provider_id: str, to: str, note: str = "") -> dict:
        """
        Forward a message. Irreversible, so stage 13 gates it like a send.

        Same shape as the Gmail connector's: the original is QUOTED, not
        re-attached. Re-attaching re-sends every attachment too, which is how
        a forward quietly becomes a data leak nobody intended.
        """
        raw = self.fetch_raw(provider_id)
        if not raw:
            raise RuntimeError(f"message {provider_id} not found — nothing forwarded")
        original = email.message_from_bytes(raw, policy=default_policy)
        part = original.get_body(preferencelist=("plain",))
        text = part.get_content() if part else ""
        body = (f"{note}\n\n---------- Forwarded message ----------\n"
                f"From: {original.get('From', '')}\n"
                f"Date: {original.get('Date', '')}\n"
                f"Subject: {original.get('Subject', '')}\n\n"
                f"{text[:3000]}")
        return self.send(to=to, subject=f"Fwd: {original.get('Subject', '')}",
                         body=body)

    def rescue_from_spam(self, provider_id: str) -> None:
        """
        Out of spam, back into the inbox. Fully reversible.

        ⚠️ UIDs BELONG TO A FOLDER. list_spam() hands out UIDs from the spam
        folder, and UID 12 in Spam is not UID 12 in INBOX. So this selects the
        spam folder before acting, and puts INBOX back afterwards.

        ⚠️ AND IT MOVES. IT NEVER DELETES FROM SPAM.

        On Gmail, deleting a message from Spam or Trash over IMAP is PERMANENT.
        A rescue built as copy-then-delete is one failed copy away from
        destroying the very message it was trying to save. MOVE is a single
        atomic step, so if it fails, nothing happened. A server without MOVE
        gets a refusal, not a riskier fallback.
        """
        spam = self._spam_folder()
        if not spam:
            raise RuntimeError("no spam folder on this server")
        if not self._has_move():
            raise RuntimeError("server has no MOVE — refusing copy-then-delete out of spam")
        self.conn.select(f'"{spam}"', readonly=False)
        try:
            typ, data = self.conn.uid("MOVE", provider_id, "INBOX")
            if typ != "OK":
                raise RuntimeError(f"rescue failed: {data}")
        finally:
            self.conn.select("INBOX", readonly=False)

    _SPAM_CANDIDATES = ("[Gmail]/Spam", "[Google Mail]/Spam",
                        "Junk", "Spam", "Bulk Mail", "INBOX.Spam")

    def _spam_folder(self) -> str | None:
        """The name this server uses for spam — found by trying, not assumed."""
        if getattr(self, "_spam", None):
            return self._spam
        found = None
        try:
            for name in self._SPAM_CANDIDATES:
                try:
                    typ, _ = self.conn.select(f'"{name}"', readonly=True)
                except Exception:
                    continue
                if typ == "OK":
                    found = name
                    break
        finally:
            self.conn.select("INBOX", readonly=False)
        self._spam = found
        return found

    def _has_move(self) -> bool:
        try:
            typ, data = self.conn.capability()
            return b"MOVE" in b" ".join(data).upper()
        except Exception:
            return False

    def _move(self, provider_id: str, dest: str) -> None:
        """
        One message, from the selected folder to `dest`.

        ⚠️ MOVE, NOT COPY + \\Deleted + EXPUNGE.

        Plain EXPUNGE removes EVERY message in the folder flagged \\Deleted —
        not just the one we meant. On a mailbox another mail client has been
        using, that can include messages we never touched. MOVE acts on one
        UID and nothing else. The fallback for servers without MOVE uses UID
        EXPUNGE, which is scoped to the single UID in the same way.
        """
        if self._has_move():
            typ, data = self.conn.uid("MOVE", provider_id, f'"{dest}"')
            if typ != "OK":
                raise RuntimeError(f"move to {dest} failed: {data}")
            return
        self.conn.uid("COPY", provider_id, f'"{dest}"')
        self.conn.uid("STORE", provider_id, "+FLAGS", "(\\Deleted)")
        self.conn.uid("EXPUNGE", provider_id)

    def label_removals_since(self, bookmark: str, our_labels: set,
                             footprint: list | None = None) -> tuple:
        """
        UC-29 · corrections the Owner made inside Gmail itself.

        ⚠️ IMAP HAS NO HISTORY FEED, SO WE DIFF INSTEAD OF LISTENING.

        Gmail's API can be asked "what changed since X" and will name every
        label the Owner removed. IMAP can only ever answer "what is true now".
        That difference is real and it is the one capability gap that actually
        costs us something — dragging a message out of Custodian/Needs a reply
        is a correction, and it happens in their mail app, not ours.

        But we do not need a change feed to notice it. We know exactly which
        messages WE labelled, because we wrote that down when we did it. So we
        re-read the labels on those messages and look for ours going missing.

        ⚠️ THIS IS CHEAP ONLY BECAUSE THE LIST IS SHORT.

        One FETCH per message we have ever labelled — tens per day, not
        thousands. Diffing the whole mailbox this way would be absurd; diffing
        our own footprint is a few seconds. If that list ever grows into the
        thousands this needs rethinking, and the caller should cap it.

        `bookmark` is accepted and ignored — the signature matches the Gmail
        connector so that correct.py never learns which door it is behind.
        Returns (list of (provider_id, label), unchanged bookmark).
        """
        if not self.has_gmail_extensions():
            return [], bookmark

        removals = []
        for provider_id, label in (footprint if footprint is not None
                                   else self._labelled_by_us()):
            if label not in our_labels:
                continue
            # ⚠️ "Our label is gone" and "the message is gone" look identical
            # from here — both come back with no labels. A message the Owner
            # archived or deleted has left INBOX, so its UID answers nothing,
            # and that is NOT a correction. Only a message we can still see,
            # without our label on it, counts. Missing a correction is
            # recoverable; inventing one teaches the system something false.
            try:
                typ, data = self.conn.uid("FETCH", provider_id, "(X-GM-LABELS)")
            except Exception:
                continue
            if typ != "OK" or not data or not data[0]:
                continue
            still = self.gmail_labels(provider_id)
            if not any(label.lower() == x.lower() for x in still):
                removals.append((provider_id, label))
        return removals, bookmark

    def _labelled_by_us(self) -> list:
        """
        Every (provider_id, label) this system has ever applied on this door.

        Read from the same audit file sort_mailbox.py writes, because the
        record of what we did should have exactly one home.
        """
        import json
        from pathlib import Path
        out = []
        # ⚠️ THIS READ TWO FILES THAT HAVE NEVER EXISTED.
        #
        # watch.py and sort_mailbox.py both write applied_labels.json. This
        # looked for sort_audit.json and watch_audit.json, found neither, and
        # returned an empty list — so the check reported "0 messages we
        # labelled" and could never have noticed a single correction. Found
        # because the audit printed that 0 and it did not add up.
        p = Path("applied_labels.json")
        if not p.exists():
            return out
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return out
        for row in rows:
            pid = str(row.get("id") or "")
            lab = row.get("label_id") or row.get("label")
            if not pid or not lab:
                continue
            # The file holds labels from BOTH doors. A Gmail API id is a
            # 16-character hex string; an IMAP UID is a short number. Asking
            # IMAP about an API id would at best find nothing and at worst
            # find a different message that happens to have that number.
            door = row.get("door", "")
            if door and not door.startswith("imap"):
                continue
            if not door and not (pid.isdigit() and len(pid) <= 10):
                continue
            out.append((pid, lab))
        return out

    # --- reversals (UC-30) --------------------------------------------------
    #
    # ⚠️ ON IMAP A UID BELONGS TO ONE FOLDER, AND A REVERSED MESSAGE HAS MOVED.
    #
    # The UID we recorded when we archived a message was its UID in INBOX. It
    # is now in All Mail, under a different UID. So every reversal here finds
    # the message again by Message-ID in the folder it is now in, acts there,
    # and puts INBOX back as the selected folder. That is why these take a
    # message_id the Gmail connector does not need.

    def _find_in(self, folder: str, message_id: str, tries: int = 4) -> str | None:
        """Select `folder` and return our UID for `message_id` there, or None."""
        import time
        mid = (message_id or "").strip()
        if not mid:
            return None
        if not mid.startswith("<"):
            mid = f"<{mid}>"
        for i in range(tries):
            typ, _ = self.conn.select(f'"{folder}"', readonly=False)
            if typ != "OK":
                return None
            typ, data = self.conn.uid("SEARCH", None, "HEADER", "Message-ID", f'"{mid}"')
            if typ == "OK" and data and data[0]:
                return data[0].split()[-1].decode()
            if i < tries - 1:
                time.sleep(0.5)      # a just-moved message can lag a moment
        return None

    def _all_mail(self) -> str:
        return "[Gmail]/All Mail" if self.has_gmail_extensions() else "Archive"

    def unarchive(self, provider_id: str, message_id: str = "") -> None:
        """Back into the inbox. On Gmail a COPY into INBOX adds the \\Inbox label."""
        try:
            u = self._find_in(self._all_mail(), message_id)
            if not u:
                raise RuntimeError("message not found in All Mail")
            if self.has_gmail_extensions():
                typ, data = self.conn.uid("COPY", u, "INBOX")
            else:
                typ, data = self.conn.uid("MOVE", u, "INBOX")
            if typ != "OK":
                raise RuntimeError(f"unarchive failed: {data}")
        finally:
            self.conn.select("INBOX", readonly=False)

    def untrash(self, provider_id: str, message_id: str = "") -> None:
        """Out of the bin, back into the inbox. A single MOVE — never expunge."""
        trash = self._folders.get("trash", "Trash")
        try:
            u = self._find_in(trash, message_id)
            if not u:
                raise RuntimeError("message not found in Trash")
            self._move(u, "INBOX")
        finally:
            self.conn.select("INBOX", readonly=False)

    def unrescue(self, provider_id: str, message_id: str = "") -> None:
        """Back into spam — the reverse of rescue_from_spam."""
        spam = self._spam_folder()
        if not spam:
            raise RuntimeError("no spam folder on this server")
        try:
            u = self._find_in("INBOX", message_id) or provider_id
            self._move(u, spam)
        finally:
            self.conn.select("INBOX", readonly=False)

    def delete_draft(self, draft_id: str, message_id: str = "") -> None:
        """
        Remove a draft we wrote. `draft_id` is the Message-ID create_draft
        returned. Deleting from Drafts is permanent — and correct, because the
        draft was ours and reached nobody.
        """
        folder = "[Gmail]/Drafts" if self.has_gmail_extensions() else "Drafts"
        try:
            u = self._find_in(folder, message_id or draft_id)
            if not u:
                raise RuntimeError("draft not found")
            self.conn.uid("STORE", u, "+FLAGS", "(\\Deleted)")
            self.conn.uid("EXPUNGE", u)
        finally:
            self.conn.select("INBOX", readonly=False)

    def remove_label(self, provider_id: str, folder: str, message_id: str = "") -> None:
        """Undo apply_label. Needed by UC-30, and by any honest audit."""
        if self.has_gmail_extensions():
            self.conn.uid("STORE", provider_id, "-X-GM-LABELS", f'"{folder}"')

    def ensure_label(self, name: str) -> str:
        """
        The same call as Gmail's, answering the same question with a folder.

        IMAP has no label ids, so the folder NAME is the handle.

        ⚠️ THE SEPARATOR COMES FROM THE SERVER, NOT FROM A GUESS.

        This used to turn every "/" into ".", on the theory that most IMAP
        servers separate levels with a dot. Gmail uses "/". So on Gmail,
        "Custodian/Flights" was created as a second, unrelated label called
        "Custodian.Flights" — four of those were found sitting empty in a real
        mailbox, beside the real ones.

        ⚠️ AND THE NAME IS QUOTED.

        imaplib does not quote arguments. "Custodian.Needs a reply" went out as
        CREATE Custodian.Needs a reply — three words — the server refused it,
        and the except below swallowed the refusal. Every label with a space in
        its name silently failed to exist.
        """
        safe = name.replace("/", self._delimiter())
        try:
            self.conn.create(f'"{safe}"')   # silently fine if it already exists
        except Exception:
            pass
        return safe

    def _delimiter(self) -> str:
        """The server's own hierarchy separator: "/" on Gmail, often "." elsewhere."""
        if getattr(self, "_delim", None):
            return self._delim
        self._delim = "."
        try:
            typ, data = self.conn.list('""', '""')
            m = re.search(rb'\) "(.)"', data[0] or b"")
            if m:
                self._delim = m.group(1).decode()
        except Exception:
            pass
        return self._delim

    def archive(self, provider_id: str) -> None:
        """
        ⚠️ Archive is the ONE place removing from the inbox is the point.

        On Gmail that is literally what it means: take away the \\Inbox label.
        Everywhere else, move it to an Archive folder. Either way the message
        still exists and can be put back — which is why this is separate from
        apply_label rather than a flavour of it.
        """
        if self.has_gmail_extensions():
            # ⚠️ ON GMAIL, ARCHIVE IS A MOVE TO ALL MAIL — NOT A LABEL REMOVAL.
            #
            # The obvious version, STORE -X-GM-LABELS (\Inbox), answers OK and
            # does nothing. Gmail hides the label of the folder you are
            # standing in: fetched from INBOX, a message's labels read "()",
            # while the same message fetched from All Mail still carries
            # \Inbox. So removing \Inbox from inside INBOX removes a label
            # Gmail never showed us — and silently doesn't. The audit failed
            # on it with both quoted and unquoted spellings; a diagnostic that
            # printed both views side by side is what finally showed why
            # (test_runs/diagnostic_archive_*.txt).
            #
            # MOVE INBOX -> [Gmail]/All Mail worked first time: gone from the
            # inbox, still in All Mail, no \Inbox label left on it.
            self._move(provider_id, "[Gmail]/All Mail")
            return
        self._move(provider_id, self.ensure_label("Archive"))

    def mark_read(self, provider_id: str) -> None:
        # UID STORE, not STORE. See the note in apply_label.
        self.conn.uid("STORE", provider_id, "+FLAGS", "(\\Seen)")

    def mark_unread(self, provider_id: str, message_id: str = "") -> None:
        self.conn.uid("STORE", provider_id, "-FLAGS", "(\\Seen)")

    def trash(self, provider_id: str) -> None:
        """Move to the provider's trash. ⚠️ Never EXPUNGE from trash."""
        self._move(provider_id, self._folders["trash"])

    def spam_envelopes(self, limit: int = 50) -> list:
        """
        UC-20. Envelopes from the spam folder, never bodies.

        ⚠️ UIDs belong to a folder. These provider_ids are valid only with the
        spam folder selected, which is why rescue_from_spam() selects it again
        before acting. INBOX is put back before returning.
        """
        spam = self._spam_folder()
        if not spam:
            return []
        try:
            self.conn.select(f'"{spam}"', readonly=True)
            typ, data = self.conn.uid("SEARCH", None, "ALL")
            uids = data[0].split()[-limit:] if typ == "OK" and data and data[0] else []
            return list(self.fetch_envelopes(uids))
        finally:
            self.conn.select("INBOX", readonly=False)

    def access_level(self) -> str:
        """
        UC-10 BR-229: 'full' or 'read only', from the server's own reply.

        SELECT answers with [READ-WRITE] or [READ-ONLY] in its OK line, and
        imaplib files that code under response(). A mailbox that lets us read
        but not change gets reading features only, and the Owner is told why
        rather than watching a label fail.
        """
        try:
            self.conn.select("INBOX", readonly=False)
            ro = self.conn.response("READ-ONLY")[1]
            rw = self.conn.response("READ-WRITE")[1]
            if ro and ro != [None]:
                return "read only"
            if rw and rw != [None]:
                return "full"
        except Exception:
            pass
        return "full"

    def list_spam(self, limit: int = 50) -> list:
        # ⚠️ GMAIL'S SPAM FOLDER IS NOT CALLED "Spam".
        #
        # It is "[Gmail]/Spam", and the audit caught this: the server had a
        # Spam folder, we could open it by hand, and list_spam() returned
        # nothing every single time. It failed silently — an empty list from
        # a spam check reads exactly like "no spam", which is the answer you
        # least want to be wrong about. Gmail's own name goes first.
        for name in self._SPAM_CANDIDATES:
            try:
                # Quoted — the name contains a slash and a bracket.
                typ, _ = self.conn.select(f'"{name}"', readonly=True)
                if typ == "OK":
                    typ, data = self.conn.uid("SEARCH", None, "ALL")
                    self.conn.select("INBOX")
                    return data[0].split()[-limit:] if typ == "OK" else []
            except Exception:
                continue
        self.conn.select("INBOX")
        return []

    def close(self):
        try:
            self.conn.logout()
        except Exception:
            pass
