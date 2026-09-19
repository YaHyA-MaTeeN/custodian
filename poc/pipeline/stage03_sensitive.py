"""
Stage 3 — The sensitive gate.

Decides whether an email should be opened at all. Sees ONLY the sender and the
subject line. Never the body.

This runs third, before anything reads a message, on purpose. Anywhere later
and something would already have opened the email before we decided it should
not be opened. The ordering is the entire safety property, so the function
signature enforces it: there is no parameter for a body.

No model here, deliberately. We want certainty, not a probability — and a
model would have to read the thing we have decided not to read.
"""

import json
import re
from pathlib import Path

# ⚠️ A HAND-WRITTEN LIST OF BANKS CANNOT SCALE, AND WE DO NOT RELY ON ONE.
#
# There are tens of thousands of banks. Nobody can type them all, and a list
# that is 90% complete is a list that fails for one user in ten. So the list
# below is the SMALLEST of four sources, and the least important:
#
#   1. WHOLE-SUFFIX RULES   .gov, .gov.uk, .gc.ca, .mil, .bank — a single rule
#                           covering every government body and every ICANN
#                           .bank registrant on earth. No list to maintain.
#
#   2. THE USER'S OWN MARKS user_sensitive.json. They know their bank; we do
#                           not. One tap in the app, no deploy, no guessing.
#
#   3. SUBJECT PATTERNS     work on senders we have never heard of. A six-digit
#                           code in a subject line looks identical whether it
#                           came from HSBC or a bank in a country we have never
#                           shipped to.
#
#   4. THE SEED LIST        below. A starting point, loaded from JSON in
#                           production so it updates without a release.
#
# ⚠️ AND THE POINT THAT ACTUALLY MATTERS: THIS STAGE IS NOT THE PROTECTION.
#
# It is the first of three layers. If it misses, the body is read by OUR OWN
# model, on our own machine — nothing has left the building. Stage 10 then
# strips identifiers before anything crosses, and stage 13 refuses to act
# without a typed yes. A miss has to defeat all three to cause harm.
#
# Designing as if the list were complete would be the actual mistake.

# Every domain ending in one of these is sensitive, whatever its name is.
SENSITIVE_SUFFIXES = (
    ".gov", ".gov.uk", ".gc.ca", ".gouv.qc.ca", ".mil",
    ".bank",            # ICANN-restricted: only verified banks may hold one
    ".insurance",       # same registry, same verification
    ".nhs.uk",          # UK health service
)

_USER_FILE = Path(__file__).parent.parent / "user_sensitive.json"


def user_marked() -> set:
    """
    Senders this specific person marked private. Read fresh every call — a
    user marking their bank must take effect on the next email, not after a
    restart.
    """
    try:
        return {d.lower() for d in json.loads(_USER_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return set()


def mark_sensitive(domain: str) -> None:
    """One tap in the app. No deploy, no code change, no guessing on our part."""
    marks = user_marked() | {domain.lower().strip()}
    _USER_FILE.write_text(json.dumps(sorted(marks), indent=2), encoding="utf-8")


# The seed list. Deliberately small — the suffix rules and the user's own
# marks do the heavy lifting.
SENSITIVE_DOMAINS = {
    # banks
    "hbl.com", "meezanbank.com", "ubldigital.com", "mcb.com.pk",
    "bankalfalah.com", "askaribank.com.pk", "jsbl.com", "faysalbank.com",
    "hsbc.com", "barclays.co.uk", "lloydsbank.com", "natwest.com",
    "chase.com", "bankofamerica.com", "wellsfargo.com", "rbc.com", "td.com",
    # government / revenue
    "fbr.gov.pk", "nadra.gov.pk", "secp.gov.pk",
    "hmrc.gov.uk", "gov.uk", "irs.gov", "cra-arc.gc.ca",
    # payments
    "paypal.com", "stripe.com", "wise.com",
}

# ⚠️ Matched as WHOLE WORDS, not substrings.
#
# "alerts" as a substring flagged jobalerts-noreply@linkedin.com as bank
# security mail. The local part is split on - . _ and each piece compared
# exactly, so "jobalerts" no longer matches "alerts".
#
# "alerts" is also gone from this list entirely: on its own it is far too
# common. A genuine security alert is caught by the sender domain or the
# subject pattern instead.
SENSITIVE_LOCALPARTS = {
    "otp", "verify", "verification", "2fa", "mfa",
    "onetimecode", "authcode", "passcode", "securitycode",
}

# ⚠️ ACCOUNT-SECURITY MAIL WAS BEING READ, AND IT SHOULD NOT HAVE BEEN.
#
# Found by running the IMAP connector: "Security alert" and "Your Google
# Account was recovered successfully" both passed straight through and were
# opened. Neither the domain list nor the subject patterns caught them.
#
# That mail is exactly the kind we promised not to read. It routinely contains
# device names, locations, IP addresses and recovery codes — and it comes from
# a domain nobody thinks to put on a bank list, because it is not a bank.
#
# So: the pattern list now covers what account-security mail SAYS, not who
# sends it. A phrase works on providers we have never heard of; a domain list
# only works on the ones we remembered.
SENSITIVE_SUBJECT = re.compile(
    r"\b("
    r"one[- ]?time (code|password|pin)"
    r"|verification code|security code|auth(entication)? code"
    r"|otp\b|\b2fa\b|two[- ]factor|recovery code"
    r"|your (statement|balance|account statement)"
    r"|test results?|lab results?|medical|prescription|diagnosis"
    r"|password reset|reset your password"
    # ⚠️ Found in the body cache, which is where it should never have been.
    # "Your Instagram password has been changed" and "New Steam Account Email
    # Verification" both passed. The old patterns matched the REQUEST to change
    # a password but not the CONFIRMATION that one changed — and the
    # confirmation is the one that proves an account was taken over.
    r"|password (has been |was |been )?changed|changed your password"
    r"|email verification|verify your (email|account|address)"
    r"|(new|confirm) (account|email) verification"
    r"|sign[- ]?in (attempt|from)"
    r"|is your (verification|security) code"
    # account security — the group that was getting through
    r"|security alert|security notification"
    r"|(new|unrecognized|unusual|suspicious) (device|sign[- ]?in|login|activity)"
    r"|(signed|logged) in(to)? your"
    r"|account was (recovered|accessed|compromised)"
    r"|account recovery|recover your account"
    r"|verify (your|it.s) you|confirm your identity"
    r"|critical security"
    r")\b", re.I)

# Local parts that mean "this is the account-security channel", whoever it is.
# accounts@, security@, no-reply@accounts.* — the same shape at every provider.
SECURITY_SUBDOMAIN = re.compile(r"\b(accounts|security|auth|login|id)\.", re.I)

SIX_DIGIT_CODE = re.compile(r"\b\d{6}\b")


def check(sender: str, subject: str, sender_domain: str = "") -> dict:
    """
    Headers only. There is no body parameter and there must never be one.
    """
    reasons = []
    domain = (sender_domain or sender.split("@")[-1]).lower()
    local = sender.split("@")[0].lower() if "@" in sender else ""

    # 1. Suffix rules — no list to maintain, covers whole categories at once.
    hit_suffix = next((s for s in SENSITIVE_SUFFIXES if domain.endswith(s)), None)
    if hit_suffix:
        reasons.append(f"government or regulated-registry domain ({hit_suffix})")

    # 2. The user's own marks — they know their bank, we do not.
    marks = user_marked()
    if domain in marks or any(domain.endswith("." + m) for m in marks):
        reasons.append(f"you marked this sender private ({domain})")

    # 4. The seed list.
    if domain in SENSITIVE_DOMAINS:
        reasons.append(f"sender domain on the sensitive list ({domain})")
    parts = set(re.split(r"[-._+]", local))
    hit = parts & SENSITIVE_LOCALPARTS
    if hit:
        reasons.append(f"sender address is security mail ({', '.join(hit)})")
    if SENSITIVE_SUBJECT.search(subject or ""):
        reasons.append("subject matches a sensitive pattern")
    # 5. The account-security channel, whoever the provider is.
    #    accounts.google.com, security.apple.com, id.atlassian.com - same shape.
    if SECURITY_SUBDOMAIN.match(domain):
        reasons.append(f"account-security channel ({domain})")
    if SIX_DIGIT_CODE.search(subject or ""):
        reasons.append("a six-digit code appears in the subject")

    return {
        "sensitive": bool(reasons),
        "reasons": reasons,
        # What the user gets told instead of a summary. The body is never read.
        "notice": f"A message from {sender} arrived. Not opened." if reasons else None,
    }
