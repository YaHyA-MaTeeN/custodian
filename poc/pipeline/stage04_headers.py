"""
Stage 4 — Header rules.

Reads what the sender declared about its own mail, plus the verification stamp
our provider applied on arrival.

⚠️ These produce FACTS, not verdicts. "Machine-generated" is a fact. "Junk" is
not — bank statements, flight bookings, invoices and password resets are all
machine-generated, and a shop's sale email is noise to one person and the whole
point of the mailbox to another.

So this stage does not decide what matters. It attaches facts, and the decision
belongs to stage 9, which works on what this particular person actually does.

The rule that follows: a rule may route mail. It may never discard it.
"""

import re

AUTH_OK = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*pass\b", re.I)
AUTH_FAIL = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*(fail|softfail|permerror)\b", re.I)


def read_auth(auth_results: str, our_authserv: tuple = ("mx.google.com",
                                                        "spf.protection.outlook.com")):
    """
    ⚠️ Only the topmost Authentication-Results header, and only if OUR OWN
    provider stamped it, can be trusted. Every header below it was written by
    whoever sent the mail.

    Parsing "the Authentication-Results header" without checking who stamped
    it is an exploitable bug, not a style question.
    """
    if not auth_results:
        return {"checked": False, "passed": False, "note": "no verification stamp"}

    first_line = auth_results.split("\n")[0]
    authserv = first_line.split(";")[0].strip().lower()

    if not any(authserv.startswith(a) for a in our_authserv):
        return {"checked": False, "passed": False,
                "note": f"stamp is from '{authserv}', not our provider — ignored"}

    if AUTH_FAIL.search(first_line):
        return {"checked": True, "passed": False,
                "note": "verification FAILED — sender may be forged"}
    if AUTH_OK.search(first_line):
        return {"checked": True, "passed": True,
                "note": "verified as genuinely from that domain"}
    return {"checked": True, "passed": False, "note": "verification inconclusive"}


def read(env, auth_results: str = "") -> dict:
    """
    `env` is an Envelope. Returns facts to attach to the message.
    """
    facts = {
        # The sender told us this. Required on bulk mail since February 2024,
        # so it is near-universal on exactly the mail we want to identify.
        "machine_generated": bool(env.bulk),
        "has_unsubscribe": bool(env.unsubscribe),
        "one_click_unsubscribe": bool(env.one_click),
        "list_id": env.list_id,

        # Out-of-office and automatic replies. Information, not noise —
        # "Ali is away until the 12th" should pause an obligation, not vanish.
        "auto_reply": env.auto_submitted.lower() in ("auto-replied", "auto-generated"),

        # Threading. This is what the obligation ledger runs on.
        "is_reply": bool(env.in_reply_to),

        "addressed_only_to_me": True,   # refined by the caller when To/Cc known
    }
    facts["auth"] = read_auth(auth_results)
    return facts


def engagement_exit(sent: int, opened: int, min_messages: int = 8) -> dict:
    """
    The ONLY thing that exits at stage 4, and it is evidence about this person,
    not a category we invented.

    A sender with many messages and not one ever opened. That is measured
    behaviour — the same signal for everybody, no taxonomy required, and it
    gives opposite answers for two different people with the same sender,
    which is correct.
    """
    if sent >= min_messages and opened == 0:
        return {"exit": True,
                "reason": f"{sent} messages from this sender, not one ever opened"}
    return {"exit": False, "reason": None}
