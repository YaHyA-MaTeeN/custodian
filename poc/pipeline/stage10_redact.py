"""
Stage 10 — The privacy gateway.

⚠️ THE ONLY PLACE ANYTHING LEAVES OUR BUILDING.

If a piece of text did not pass through this function, it never reached an
outside company. That single-door design is what makes the privacy claim
provable rather than hopeful — with one exit we can show what left; with
several we can only hope.

Names and identifiers are replaced with placeholders, the model writes the
reply using the placeholders, and stage 12 swaps the real values back on our
side before the user ever sees it.

⚠️ WHAT THIS IS IN THE POC VS PRODUCTION

  POC         regex for structured identifiers + known names from the mailbox
  Production  Presidio wrapping a fine-tuned DeBERTa-v3-small (44M)

⚠️ AND THE HONEST LIMIT, WHICH DOES NOT CHANGE BETWEEN THE TWO

  On real documents, a model self-reporting 98.82 F1 scored 0.27. Piiranha
  self-reports 93.12 and scored 0.34. Nothing tested beats a non-expert human
  (0.77). Structured identifiers — cards, IBANs, phone numbers — are near
  perfect because they have checkable structure. NAMES AND FREE TEXT ARE NOT.

  So the claim we can defend is: "we strip identifiers, we minimise what
  crosses, and we contract for zero retention" — NOT "names are removed".
"""

import re

PATTERNS = [
    ("EMAIL",   re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("CARD",    re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("IBAN",    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("CNIC",    re.compile(r"\b\d{5}-\d{7}-\d\b")),                # Pakistan
    ("NI",      re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")), # UK
    ("SSN",     re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),              # US
    ("SIN",     re.compile(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b")),        # Canada
    ("PHONE",   re.compile(r"(?<!\w)(?:\+\d{1,3}[ -]?)?\(?\d{2,4}\)?[ -]?\d{3,4}[ -]?\d{3,4}(?!\w)")),
    ("URL",     re.compile(r"https?://\S+")),
]


def redact(text: str, known_names: list[str] | None = None) -> tuple[str, dict]:
    """
    Returns the redacted text and the mapping needed to restore it.

    ⚠️ The mapping is held in memory for the life of the request and is NEVER
    written to disk. A stored mapping is a stored copy of the identifiers we
    just went to the trouble of removing.
    """
    mapping, counters = {}, {}
    out = text

    # ⚠️ ORDER MATTERS, and getting it wrong is a real leak.
    #
    # An email address contains a name. If names run first,
    # "ali@company.com" becomes "[PERSON_1]@company.com" — the domain is
    # still exposed and the EMAIL pattern can no longer match it.
    #
    # Precise patterns claim their text first. Loose ones take what is left.
    for label, pattern in PATTERNS:
        for match in set(pattern.findall(out)):
            value = match if isinstance(match, str) else match[0]
            if not value or len(str(value).strip()) < 4:
                continue
            counters[label] = counters.get(label, 0) + 1
            token = f"[{label}_{counters[label]}]"
            mapping[token] = value
            out = out.replace(value, token)

    # Names last, over whatever the patterns did not claim.
    for name in sorted(known_names or [], key=len, reverse=True):
        if len(name) < 3:
            continue
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.I)
        if pattern.search(out):
            counters["PERSON"] = counters.get("PERSON", 0) + 1
            token = f"[PERSON_{counters['PERSON']}]"
            mapping[token] = name
            out = pattern.sub(token, out)

    # ── OUR OWN MODEL, over what is still left ─────────────────────────
    #
    # Patterns handle the structured identifiers; the mailbox's known names
    # handle senders we have seen. This catches what neither could: names and
    # addresses that appear only inside the message text.
    #
    # It runs LAST on purpose. It found every identifier in testing but typed
    # several wrongly - a credit card called an SSN, an IBAN called a vehicle
    # registration. Letting it go first would let a bad label displace a
    # pattern that would have been right.
    try:
        from . import local_pii
        if local_pii.available():
            for a, b, family in sorted(local_pii.find_spans(out), reverse=True):
                fragment = out[a:b].strip()
                if not fragment or fragment.startswith("["):
                    continue          # already replaced
                counters[family] = counters.get(family, 0) + 1
                token = f"[{family}_{counters[family]}]"
                mapping[token] = fragment
                out = out[:a] + token + out[b:]
    except Exception:
        pass                          # patterns alone still redact

    return out, mapping


def restore(text: str, mapping: dict) -> tuple[str, list[str]]:
    """
    Stage 12. Swap the real values back, locally, before anyone sees the draft.

    ⚠️ If any placeholder survives, DISCARD THE DRAFT. An unresolved
    [PERSON_3] in a message the user might send is worse than no draft.
    """
    out = text
    for token, value in mapping.items():
        out = out.replace(token, value)
    leftover = re.findall(r"\[[A-Z]+_\d+\]", out)
    return out, leftover


def minimise(text: str, limit: int = 3000) -> str:
    """Send the least that will do the job. Fewer tokens, less exposure."""
    return text[:limit]
