"""
Gmail adapter.

The only file in the project that knows Gmail exists. Everything Gmail-specific
lives here: quota units, label ids, the metadata fetch format, OAuth.
"""

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .base import Envelope

# ⚠️ TWO SCOPES, AND DELIBERATELY NOT A THIRD.
#
#   gmail.modify  read, label, archive, trash. NOT permanent delete.
#   gmail.send    send only. It cannot read anything.
#
# We still never ask for https://mail.google.com/ — the full-access scope that
# permits messages.delete. Not asking is stronger than promising not to.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/gmail.send"]

# Headers we ask for. Everything the pipeline needs, nothing more.
HEADERS = ["From", "To", "Cc", "Subject", "Date",
           "List-Unsubscribe", "List-Unsubscribe-Post", "List-Id", "Precedence",
           "Message-ID", "In-Reply-To", "References", "Auto-Submitted",
           "Authentication-Results"]


def _parse_sender(raw: str) -> tuple[str, str, str]:
    """'Ali Raza <ali@x.com>' -> ('ali@x.com', 'Ali Raza', 'x.com')"""
    if not raw:
        return "", "", ""
    m = re.search(r"<([^>]+)>", raw)
    addr = (m.group(1) if m else raw).strip().lower()
    name = raw.split("<")[0].strip().strip('"') if m else ""
    domain = addr.split("@")[-1] if "@" in addr else ""
    return addr, name, domain


class GmailConnector:
    name = "gmail"

    # Gmail can do everything. IMAP is where these start saying False.
    supports_push = True
    supports_labels = True
    supports_server_search = True
    supports_spam_folder = True
    supports_threads = True
    supports_send = True
    max_fetch_per_second = 40.0        # ~250 quota units/sec at 5 units a fetch

    def __init__(self, credentials="credentials.json", token="token.json", workers=6):
        self.workers = workers
        creds = None
        if os.path.exists(token):
            creds = Credentials.from_authorized_user_file(token, SCOPES)
        if not creds or not creds.valid:
            refreshed = False
            if creds and creds.expired and creds.refresh_token:
                # ⚠️ A refresh can FAIL, and until 19 Sept it crashed here.
                #
                # While the app is unpublished, Google expires the grant after
                # seven days (measured: written 11 Sept, dead 18 Sept). The
                # refresh then raises "invalid_grant", and every script died
                # with a traceback instead of asking the Owner to sign in
                # again. A failed refresh is the normal case, not an error.
                try:
                    creds.refresh(Request())
                    refreshed = True
                except Exception as e:
                    print(f"  Gmail sign-in expired ({str(e)[:60]}) — asking again")
            if not refreshed:
                flow = InstalledAppFlow.from_client_secrets_file(credentials, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token, "w") as f:
                f.write(creds.to_json())
        self.creds = creds
        self.svc = build("gmail", "v1", credentials=creds)
        self._profile = self.svc.users().getProfile(userId="me").execute()
        # ⚠️ The Google client is NOT thread-safe — its underlying HTTP
        # connection gets corrupted when several threads share it, and the
        # failure is silent. Each worker thread gets its own service object.
        self._local = threading.local()
        self.errors = []          # collected rather than swallowed silently

    # --- sending ----------------------------------------------------------

    def send(self, to: str, subject: str, body: str,
             in_reply_to: str = "", references: str = "",
             thread_id: str = "") -> dict:
        """
        Send one message. Called ONLY from stage 14, and stage 14 only calls it
        after stage 13 matched an exact typed yes against a hash of this exact
        body. There is no other caller, and there must never be one.

        Returns the provider's own record of what it sent, so the audit line
        can name a real message rather than an intention.
        """
        from email.message import EmailMessage
        import base64

        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = self.account_email()
        msg["Subject"] = subject
        # Threading. Without these a reply arrives as a new conversation, which
        # is the single most visible way an assistant looks broken.
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        msg.set_content(body)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        return self.svc.users().messages().send(userId="me", body=payload).execute()

    def create_draft(self, to: str, subject: str, body: str,
                     in_reply_to: str = "", references: str = "",
                     thread_id: str = "") -> dict:
        """
        ⚠️ SAFER THAN SENDING, AND THAT IS THE POINT (UC-25, BR-95).

        A draft in the user's own Drafts folder cannot leave without them
        pressing send in their own mail app. There is no timer, no setting and
        no code path of ours that can dispatch it. The approval stops being a
        promise we make and becomes a fact about where the message lives.

        It is also where they already look: correctly threaded, it appears
        inside the conversation in Gmail, so nobody has to open our app.
        """
        from email.message import EmailMessage
        import base64

        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = self.account_email()
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        msg.set_content(body)

        payload = {"message": {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}}
        if thread_id:
            payload["message"]["threadId"] = thread_id
        return self.svc.users().drafts().create(userId="me", body=payload).execute()

    def label_removals_since(self, history_id: str, our_label_ids: set) -> tuple[list, str]:
        """
        UC-29 · corrections the Owner made inside Gmail itself.

        ⚠️ Dragging a message out of one of our labels IS a correction (AC-29.3)
        and it happens in their mail app, not ours. If we only accepted
        disagreement through our own screen we would miss the place people
        actually disagree.

        Returns (list of (provider_id, label_id), new bookmark).
        """
        from googleapiclient.errors import HttpError
        out, page, latest = [], None, history_id
        try:
            while True:
                r = self.svc.users().history().list(
                    userId="me", startHistoryId=history_id,
                    historyTypes=["labelRemoved"], pageToken=page).execute()
                latest = r.get("historyId", latest)
                for h in r.get("history", []):
                    for rem in h.get("labelsRemoved", []):
                        mid = rem.get("message", {}).get("id")
                        for lab in rem.get("labelIds", []):
                            if lab in our_label_ids:
                                out.append((mid, lab))
                page = r.get("nextPageToken")
                if not page:
                    break
        except HttpError as e:
            if e.resp.status == 404:
                return [], self.current_history_id()
            raise
        return out, latest

    def ensure_label(self, name: str) -> str:
        """
        Create-or-find one label, and hand back the handle to file with.

        ⚠️ BR-100 — one button, different meanings underneath. Here the handle
        is a Gmail label id and the message never moves. On IMAP the same call
        returns a FOLDER NAME and filing moves the message. The caller does not
        know or care which, which is the entire point of this method existing.
        """
        existing = {l["name"]: l["id"] for l in
                    self.svc.users().labels().list(userId="me")
                    .execute().get("labels", [])}
        if name in existing:
            return existing[name]
        made = self.svc.users().labels().create(
            userId="me", body={"name": name,
                               "labelListVisibility": "labelShow",
                               "messageListVisibility": "show"}).execute()
        return made["id"]

    def forward(self, provider_id: str, to: str, note: str = "") -> dict:
        """
        Forward a message. Irreversible, so stage 13 gates it like a send.

        The original is quoted underneath rather than re-attached: attaching
        the raw message re-sends every attachment too, which is how a forward
        quietly becomes a data leak nobody intended.
        """
        original = self.svc.users().messages().get(
            userId="me", id=provider_id, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        h = {x["name"]: x["value"] for x in original["payload"]["headers"]}
        body = (f"{note}\n\n---------- Forwarded message ----------\n"
                f"From: {h.get('From','')}\n"
                f"Date: {h.get('Date','')}\n"
                f"Subject: {h.get('Subject','')}\n\n"
                f"{original.get('snippet','')}")
        return self.send(to=to, subject=f"Fwd: {h.get('Subject','')}", body=body)

    # --- spam: the folder we look INTO, never move things into -------------

    def list_spam(self, limit: int = 50) -> list[str]:
        """
        Message ids sitting in the spam folder.

        ⚠️ We read this folder to RESCUE things, never to put things in it.
        Google's spam filter is far better than anything we would build, so we
        do not compete with it. What it cannot know is that this particular
        person has replied to this particular sender eleven times — and that is
        exactly the case where it is wrong.
        """
        r = self.svc.users().messages().list(
            userId="me", labelIds=["SPAM"], maxResults=limit).execute()
        return [m["id"] for m in r.get("messages", [])]

    def rescue_from_spam(self, provider_id: str) -> None:
        """Out of spam, back into the inbox. Fully reversible."""
        self.svc.users().messages().modify(
            userId="me", id=provider_id,
            body={"removeLabelIds": ["SPAM"], "addLabelIds": ["INBOX"]}).execute()

    def unsnooze(self, provider_id: str) -> None:
        """Put a snoozed message back in the inbox."""
        self.svc.users().messages().modify(
            userId="me", id=provider_id, body={"addLabelIds": ["INBOX"]}).execute()

    # --- live: what has arrived since we last looked ----------------------

    def current_history_id(self) -> str:
        """
        Gmail's bookmark for "the mailbox as of now". Everything that happens
        afterwards gets a higher id, so this is where a watcher starts.
        """
        return self.svc.users().getProfile(userId="me").execute()["historyId"]

    def new_since(self, history_id: str) -> tuple[list[str], str]:
        """
        New INBOX messages since that bookmark, plus the new bookmark.

        ⚠️ This is history.list, NOT a re-scan. We ask Gmail "what changed"
        rather than "give me everything and I will diff it myself". On a 7,000
        message mailbox that is the difference between 1 quota unit and about
        1,500, every single poll.

        ⚠️ History ids expire after roughly a week. When ours is too old Gmail
        returns 404 rather than silently giving us nothing, and we restart from
        now. Missing a few old messages is correct here; pretending we are up
        to date when we are not is the failure that matters.
        """
        from googleapiclient.errors import HttpError

        ids, page, latest = [], None, history_id
        try:
            while True:
                r = self.svc.users().history().list(
                    userId="me", startHistoryId=history_id,
                    historyTypes=["messageAdded"], pageToken=page).execute()
                latest = r.get("historyId", latest)
                for h in r.get("history", []):
                    for added in h.get("messagesAdded", []):
                        m = added.get("message", {})
                        if "INBOX" in m.get("labelIds", []):
                            ids.append(m["id"])
                page = r.get("nextPageToken")
                if not page:
                    break
        except HttpError as e:
            if e.resp.status == 404:
                self.errors.append("history id expired — restarting from now")
                return [], self.current_history_id()
            raise

        # dict.fromkeys keeps order and drops the duplicates Gmail sends when
        # a message is touched more than once between polls.
        return list(dict.fromkeys(ids)), latest

    def _thread_svc(self):
        """One service object per thread. Built once, reused after that."""
        if not hasattr(self._local, "svc"):
            self._local.svc = build("gmail", "v1", credentials=self.creds,
                                    cache_discovery=False)
        return self._local.svc

    # --- identity ---------------------------------------------------------

    def account_email(self) -> str:
        return self._profile["emailAddress"]

    def message_count(self) -> int:
        return self._profile["messagesTotal"]

    # --- reading ----------------------------------------------------------

    def list_ids(self, on_progress=None) -> list[str]:
        """500 ids per call, 5 quota units each. Cheap."""
        ids, page = [], None
        while True:
            r = self.svc.users().messages().list(
                userId="me", maxResults=500, pageToken=page,
                includeSpamTrash=False).execute()
            ids.extend(m["id"] for m in r.get("messages", []))
            if on_progress:
                on_progress(len(ids))
            page = r.get("nextPageToken")
            if not page:
                return ids

    def _fetch_one(self, mid: str) -> Envelope | None:
        # Retry with backoff — Gmail returns 429 when we go too fast, and a
        # transient network error should not cost us a message.
        import random
        import time
        for attempt in range(4):
            try:
                # format="metadata" — Gmail does not send the body at all.
                m = self._thread_svc().users().messages().get(
                    userId="me", id=mid, format="metadata",
                    metadataHeaders=HEADERS).execute()
                break
            except Exception as e:
                self.errors.append(f"{mid}: {type(e).__name__}: {str(e)[:90]}")
                if attempt == 3:
                    return None
                time.sleep((2 ** attempt) * 0.5 + random.random() * 0.3)
        else:
            return None

        h = {x["name"].lower(): x["value"]
             for x in m.get("payload", {}).get("headers", [])}
        labels = m.get("labelIds", [])
        addr, name, domain = _parse_sender(h.get("from", ""))
        unsub = h.get("list-unsubscribe", "")

        return Envelope(
            provider_id=m["id"],
            message_id=h.get("message-id", ""),
            thread_id=m.get("threadId", ""),
            account=self.account_email(),   # BR-98 — never inferred later
            sender=addr, sender_name=name, sender_domain=domain,
            recipients=(h.get("to", "") + " " + h.get("cc", "")).strip()[:500],
            subject=h.get("subject", "")[:300],
            date=h.get("date", ""),
            size=m.get("sizeEstimate", 0),
            unread="UNREAD" in labels,
            in_inbox="INBOX" in labels,
            categories=[l.replace("CATEGORY_", "").title()
                        for l in labels if l.startswith("CATEGORY_")],
            unsubscribe=unsub,
            one_click=bool(h.get("list-unsubscribe-post")),
            list_id=h.get("list-id", ""),
            bulk=bool(unsub) or h.get("precedence", "").lower() in ("bulk", "list"),
            auto_submitted=h.get("auto-submitted", ""),
            in_reply_to=h.get("in-reply-to", ""),
            references=h.get("references", ""),
            auth_results=h.get("authentication-results", "")[:600],
        )

    def spam_envelopes(self, limit: int = 50) -> list:
        """UC-20. Envelopes from the spam folder, never bodies."""
        return list(self.fetch_envelopes(self.list_spam(limit)))

    def fetch_envelopes(self, ids: list[str]) -> Iterator[Envelope]:
        """
        One service object per thread, exceptions collected not swallowed.
        A silent zero-result loop is the worst possible failure, so anything
        that goes wrong lands in self.errors and the caller can report it.
        """
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._fetch_one, i) for i in ids]
            for fut in futures:
                try:
                    env = fut.result()
                except Exception as e:
                    self.errors.append(f"{type(e).__name__}: {str(e)[:90]}")
                    continue
                if env:
                    yield env

    def fetch_body(self, provider_id: str) -> str:
        m = self.svc.users().messages().get(
            userId="me", id=provider_id, format="full").execute()
        return m.get("snippet", "")

    # --- acting -----------------------------------------------------------
    # Not used by the scan. Here so the interface is real, not aspirational.

    def apply_label(self, provider_id: str, label_id: str) -> None:
        self.svc.users().messages().modify(
            userId="me", id=provider_id,
            body={"addLabelIds": [label_id]}).execute()

    def archive(self, provider_id: str) -> None:
        # Gmail does not move anything. It removes a label.
        self.svc.users().messages().modify(
            userId="me", id=provider_id,
            body={"removeLabelIds": ["INBOX"]}).execute()

    def mark_read(self, provider_id: str) -> None:
        self.svc.users().messages().modify(
            userId="me", id=provider_id,
            body={"removeLabelIds": ["UNREAD"]}).execute()

    def trash(self, provider_id: str) -> None:
        # trash(), never delete(). Recoverable for 30 days, and it needs no
        # extra permission. We never ask for the scope that can delete.
        self.svc.users().messages().trash(userId="me", id=provider_id).execute()

    # --- reversals (UC-30) --------------------------------------------------
    #
    # ⚠️ One reversal per reversible action, on BOTH connectors, same names.
    #
    # Undo used to be written twice — in history.py and again in api.py — and
    # both times as raw Gmail API calls. Over IMAP the button answered "this
    # door cannot reverse mailbox actions yet", which broke the rule the whole
    # connector layer exists for: ask what a door can do, never who it is.
    # The reversals now live here, and history.reverse_action calls them.
    #
    # `message_id` is accepted and unused on this door; IMAP needs it because
    # a UID belongs to one folder and the message has moved.

    def remove_label(self, provider_id: str, label_id: str, message_id: str = "") -> None:
        self.svc.users().messages().modify(
            userId="me", id=provider_id,
            body={"removeLabelIds": [label_id]}).execute()

    def unarchive(self, provider_id: str, message_id: str = "") -> None:
        self.svc.users().messages().modify(
            userId="me", id=provider_id, body={"addLabelIds": ["INBOX"]}).execute()

    def mark_unread(self, provider_id: str, message_id: str = "") -> None:
        self.svc.users().messages().modify(
            userId="me", id=provider_id, body={"addLabelIds": ["UNREAD"]}).execute()

    def untrash(self, provider_id: str, message_id: str = "") -> None:
        self.svc.users().messages().untrash(userId="me", id=provider_id).execute()

    def unrescue(self, provider_id: str, message_id: str = "") -> None:
        """Back into spam — the reverse of rescue_from_spam."""
        self.svc.users().messages().modify(
            userId="me", id=provider_id,
            body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}).execute()

    def delete_draft(self, draft_id: str, message_id: str = "") -> None:
        self.svc.users().drafts().delete(userId="me", id=draft_id).execute()

    # --- raw fetch, used by stage 2 -----------------------------------------

    def find_by_message_id(self, message_id: str) -> str | None:
        """
        This mailbox's own id for a message, found by its Message-ID.

        ⚠️ provider_id belongs to ONE door. A row saved through IMAP carries a
        numeric UID; this door speaks Gmail's hex ids. Message-ID is the only
        key both understand, so a row from the other door is looked up by it.
        """
        mid = (message_id or "").strip().strip("<>")
        if not mid:
            return None
        r = self.svc.users().messages().list(
            userId="me", q=f"rfc822msgid:{mid}", maxResults=1).execute()
        found = r.get("messages", [])
        return found[0]["id"] if found else None

    def fetch_raw(self, provider_id: str) -> bytes:
        """The whole original message. Called deliberately, one at a time."""
        import base64
        m = self.svc.users().messages().get(
            userId="me", id=provider_id, format="raw").execute()
        return base64.urlsafe_b64decode(m["raw"].encode("ASCII"))

    def fetch_attachment(self, provider_id: str, filename: str) -> bytes | None:
        """One attachment's bytes, by filename."""
        import base64
        try:
            m = self.svc.users().messages().get(
                userId="me", id=provider_id, format="full").execute()
            for part in self._walk_parts(m.get("payload", {})):
                if part.get("filename") == filename:
                    aid = part.get("body", {}).get("attachmentId")
                    if not aid:
                        data = part.get("body", {}).get("data")
                        return base64.urlsafe_b64decode(data) if data else None
                    a = self.svc.users().messages().attachments().get(
                        userId="me", messageId=provider_id, id=aid).execute()
                    return base64.urlsafe_b64decode(a["data"])
        except Exception:
            return None
        return None

    @staticmethod
    def _walk_parts(payload):
        yield payload
        for p in payload.get("parts", []) or []:
            yield from GmailConnector._walk_parts(p)
