"""
Stage 13 — Approval, and stage 14 — the executor.

⚠️ THE MOST IMPORTANT CODE IN THE SYSTEM.

The rule that nothing sends without the user's yes lives HERE, in our own code,
below the model layer. Not in a prompt, not in an instruction to the AI.

Why it has to be this way: in published testing, ALL 1,404 real email agents
tested were hijacked, most within about two attempts. The action that held up
best was sending mail — but only because some models volunteer a confirmation,
AND THE ATTACK WORKS BY TELLING THE MODEL IT NEED NOT ASK.

A model's manners are a behaviour, and behaviours can be argued with. This code
never reads the email, so nothing inside an email can reach it.
"""

import hashlib
from datetime import datetime, timedelta

# Cannot be undone once done. These always require an explicit yes.
IRREVERSIBLE = {"send", "forward", "unsubscribe", "trash"}

# Reversible. We do these freely, and log how to undo them.
# ⚠️ "draft" is REVERSIBLE, and that is the whole argument of UC-25.
#
# A draft sitting in the Owner's own Drafts folder cannot leave without them
# pressing send in their own mail app. No timer of ours, no setting, no code
# path can dispatch it. So writing one needs no approval — the approval is
# structural rather than procedural, which is stronger.
REVERSIBLE = {"label", "archive", "mark_read", "snooze", "remind",
              "rescue_from_spam", "draft"}

AFFIRMATIVE = {"yes", "y", "yep", "yeah", "send", "send it", "ok", "okay",
               "go", "do it", "confirm", "approved", "haan", "ji", "theek hai"}

APPROVAL_TTL = timedelta(hours=24)


def draft_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def is_approval(user_text: str) -> bool:
    """
    ⚠️ EXACT match, not substring, not fuzzy.

    "don't send it" CONTAINS "send it". Substring matching would send it.

    Anything that is not an unambiguous yes returns False, so the default is
    always "nothing happens, ask again". That is safer than a button, because
    the failure direction is fixed.
    """
    return (user_text or "").strip().lower().rstrip(".!") in AFFIRMATIVE


class Approval:
    def __init__(self, action: str, draft: str = "", requested_at=None):
        self.action = action
        self.draft = draft
        self.hash = draft_hash(draft)
        self.requested_at = requested_at or datetime.now()
        self.granted = False

    def grant(self, user_text: str) -> tuple[bool, str]:
        if not is_approval(user_text):
            return False, "not an unambiguous yes — nothing sent"
        if datetime.now() - self.requested_at > APPROVAL_TTL:
            return False, "approval expired — showing the draft again"
        self.granted = True
        return True, "approved"


def check(action: str, draft: str, approval: Approval | None) -> tuple[bool, str]:
    """
    The gate. Called before every action, without exception.
    """
    if action in REVERSIBLE:
        return True, "reversible — no approval needed"

    if action not in IRREVERSIBLE:
        return False, f"unknown action '{action}' — refused"

    if approval is None or not approval.granted:
        return False, "needs an explicit yes"

    # ⚠️ The approval is bound to a HASH OF THE EXACT DRAFT.
    #
    # If the draft changed after the user said yes — because they asked for an
    # edit — the old approval no longer applies. This is what stops "make it
    # shorter and send" from sending a message the user never saw.
    if draft_hash(draft) != approval.hash:
        return False, "the draft changed after approval — showing it again"

    return True, "approved for this exact draft"


# ─────────────────── stage 14 — execute ───────────────────

def execute(connector, action: str, provider_id: str,
            draft: str = "", approval: Approval | None = None,
            audit=None, to: str = "", subject: str = "",
            in_reply_to: str = "", references: str = "",
            thread_id: str = "", extra: dict | None = None) -> dict:
    """
    One API call per decision. Idempotent, audited, undoable.

    The audit row is written BEFORE the call, with how to reverse it. If the
    process dies between the write and the call, we have a record of an action
    that may not have happened — which is the correct direction to fail.
    """
    extra = extra or {}

    # ⚠️ Checked before the gate, not after. Asking someone to approve a send
    # that cannot possibly work trains them to click yes on things that do
    # nothing — and that is exactly the habit the gate depends on not having.
    if action == "send" and not (to or "").strip():
        return {"done": False, "action": action,
                "reason": "no recipient — refusing to ask you to approve this"}

    ok, reason = check(action, draft, approval)
    if not ok:
        return {"done": False, "action": action, "reason": reason}

    undo = {
        "label": {"call": "remove_label"},
        "archive": {"call": "apply_label", "arg": "INBOX"},
        "mark_read": {"call": "apply_label", "arg": "UNREAD"},
        "trash": {"call": "untrash"},
        "rescue_from_spam": {"call": "apply_label", "arg": "SPAM"},
        "draft": {"call": "delete_draft"},
        "remind": {"call": "clear_reminder"},
        "snooze": {"call": "unsnooze"},
        # These three cannot be undone. That is exactly why they are gated.
        "send": None,
        "forward": None,
        "unsubscribe": None,
    }.get(action)

    if audit is not None:
        audit.append({"at": datetime.now().isoformat(), "action": action,
                      "message": provider_id, "reason": reason, "undo": undo})

    try:
        if action == "label":
            connector.apply_label(provider_id, draft)     # draft carries label id
        elif action == "archive":
            connector.archive(provider_id)
        elif action == "mark_read":
            connector.mark_read(provider_id)
        elif action == "trash":
            connector.trash(provider_id)
        elif action == "forward":
            # Irreversible for the same reason send is: it puts a message in
            # somebody else's inbox and there is no recall.
            sent = connector.forward(provider_id, to=to, note=draft)
            return {"done": True, "action": action, "reason": reason,
                    "undo": None, "sent_id": sent.get("id")}
        elif action == "unsubscribe":
            from . import stage15_unsubscribe as unsub
            opts = unsub.options(extra.get("unsubscribe", ""),
                                 extra.get("one_click", False))
            if not opts["can_one_click"]:
                # We refuse rather than click through a stranger's page.
                return {"done": False, "action": action,
                        "reason": unsub.describe(opts), "link": opts["https"]}
            r = unsub.one_click(opts["https"])
            return {"done": r["done"], "action": action,
                    "reason": r["reason"], "undo": None}
        elif action == "rescue_from_spam":
            connector.rescue_from_spam(provider_id)
        elif action == "draft":
            d = connector.create_draft(
                to=to, subject=subject, body=draft,
                in_reply_to=in_reply_to, references=references,
                thread_id=thread_id)
            return {"done": True, "action": action, "reason": "written to Drafts",
                    "undo": {"call": "delete_draft"}, "draft_id": d.get("id")}
        elif action in ("remind", "snooze"):
            # Reversible: nothing has been sent, moved or deleted. The row is
            # written by the caller, which owns the store; this branch exists
            # so the action passes through the same single gate as the rest.
            pass
        elif action == "send":
            # ⚠️ The only line in the project that puts mail into the world.
            # It is reachable only through check() above, which requires an
            # exact typed yes bound to a hash of this exact text.
            if not getattr(connector, "supports_send", False):
                return {"done": False, "action": action,
                        "reason": "this connector has no send permission"}
            sent = connector.send(
                to=to, subject=subject, body=draft,
                in_reply_to=in_reply_to, references=references,
                thread_id=thread_id)
            if audit:
                audit[-1]["provider_message_id"] = sent.get("id")
            return {"done": True, "action": action, "reason": reason,
                    "undo": None, "sent_id": sent.get("id")}
        return {"done": True, "action": action, "reason": reason, "undo": undo}
    except Exception as e:
        return {"done": False, "action": action, "reason": f"provider error: {e}"}
