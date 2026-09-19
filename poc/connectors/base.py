"""
The connector interface.

One agent, one adapter per kind of mailbox. Nothing above this layer knows
whether it is talking to Gmail, Outlook, or an IMAP server from 1998.

The rule that makes that true: the pipeline asks a connector WHAT IT CAN DO,
never WHO IT IS. `if c.supports_push` — never `if c.name == "gmail"`. That way
a fifth kind of mailbox is one new file and nothing else changes.
"""

from dataclasses import dataclass, field
from typing import Iterator, Protocol


@dataclass
class Envelope:
    """
    What we know about a message without opening it.

    Every field here comes from headers or metadata. None of it requires
    reading the body — which is what makes an envelope-only scan honest
    rather than a technicality.
    """
    # identity
    provider_id: str            # the mailbox's own id. Opaque handle, not a key.
    message_id: str             # the RFC header. THIS is our primary key —
                                # it is the only id that means the same thing
                                # across all four kinds of mailbox.
    thread_id: str = ""
    # ⚠️ UC-27 / BR-98 — WHICH mailbox this arrived at. Every row carries it and
    # it is never inferred from the address, because the same message can reach
    # two of the Owner's accounts and the reply must leave from the right one
    # (BR-92). Placed here, among the defaulted fields, because a dataclass
    # cannot have a defaulted field before a required one.
    account: str = ""

    # who and when
    sender: str = ""
    sender_name: str = ""
    sender_domain: str = ""
    recipients: str = ""        # the To line. Needed to know who WE wrote to —
                                # without it "have I replied to this person"
                                # is unanswerable and the gate's heaviest
                                # feature is permanently false.
    subject: str = ""
    date: str = ""

    # state
    size: int = 0
    unread: bool = False
    in_inbox: bool = False
    categories: list = field(default_factory=list)

    # what the sender declared about itself
    unsubscribe: str = ""       # List-Unsubscribe
    one_click: bool = False     # List-Unsubscribe-Post — RFC 8058
    list_id: str = ""
    bulk: bool = False
    auto_submitted: str = ""    # out-of-office and machine replies

    # threading — this is what the obligation ledger runs on
    in_reply_to: str = ""
    references: str = ""
    # ⚠️ The provider's own verification stamp (Authentication-Results).
    # Stage 4 had a careful reader for this header from the start and was
    # never handed the header. It feeds two things nothing else can: spam
    # rescue (UC-20 — "passed its security checks" is a signal spam cannot
    # fake) and brand grouping (UC-16 — the DKIM signing domain is who really
    # sent it, whatever the From line says).
    auth_results: str = ""


class Connector(Protocol):
    """
    Every mailbox adapter implements this.

    The capability flags are not decoration. The pipeline branches on them,
    because some differences genuinely cannot be hidden — a connector that
    cannot push has to be polled, and that is a different code path, not a
    different phrasing.
    """

    name: str

    # --- what this door can do -------------------------------------------
    supports_push: bool             # else the caller schedules a poll
    supports_labels: bool           # else labels are emulated with folders
    supports_server_search: bool    # else filter locally
    supports_spam_folder: bool
    max_fetch_per_second: float     # drives our own rate limiting

    # --- identity ---------------------------------------------------------
    def account_email(self) -> str: ...
    def message_count(self) -> int: ...

    # --- reading ----------------------------------------------------------
    def list_ids(self) -> Iterator[str]:
        """Every message id in the mailbox."""

    def fetch_envelopes(self, ids: list[str]) -> Iterator[Envelope]:
        """Envelopes only. Implementations MUST NOT fetch bodies here."""

    def fetch_body(self, provider_id: str) -> str:
        """One message body. Called deliberately, never in bulk."""

    # --- acting -----------------------------------------------------------
    def apply_label(self, provider_id: str, label: str) -> None: ...
    def archive(self, provider_id: str) -> None: ...
    def mark_read(self, provider_id: str) -> None: ...
    def trash(self, provider_id: str) -> None: ...
