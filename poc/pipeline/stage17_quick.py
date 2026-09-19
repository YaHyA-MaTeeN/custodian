"""
Stage 17 / UC-26 — The one-word reply, with no AI at all.

⚠️ A SURPRISING SHARE OF REPLIES ARE ONE WORD.

"Yes." "Thanks." "Received." "Not for me." Sending an email like that through a
language model is paying for prose where none is wanted — and it is slower for
the customer than tapping a button.

So: a fixed list, chosen by what the message asked. No model, no network, no
cost, and instant.

⚠️ THE TAP IS THE APPROVAL (BR-96).

BR-91 says nothing is ever sent without the Owner's action. Choosing the answer
IS that action. What the gate still enforces is that the exact text is shown
before it goes, never after (AC-26.2) — the Owner approves words, not an idea.
"""

import re

# The whole vocabulary. Deliberately tiny: a long list is a writing tool
# wearing a disguise, and anything needing real writing is UC-25's job.
ANSWERS = {
    "yes":       "Yes, that works for me.",
    "no":        "Sorry, that will not work for me.",
    "thanks":    "Thanks, received.",
    "received":  "Got it, thank you.",
    "will_do":   "Will do.",
    "not_me":    "I think this was meant for someone else.",
    "later":     "Let me come back to you on this.",
    "confirm":   "Confirmed.",
}

# Which answers make sense for which question. Matched on the incoming text —
# and note these are only SUGGESTIONS. Nothing is chosen automatically.
TRIGGERS = [
    (re.compile(r"\b(can you|could you|will you|would you|please)\b.*\?", re.I),
     ["yes", "no", "later"]),
    (re.compile(r"\b(are you (free|available)|does .* work|suit you|"
                r"shall we|how about)\b", re.I),
     ["yes", "no", "later"]),
    (re.compile(r"\b(confirm|confirmation|acknowledge|rsvp)\b", re.I),
     ["confirm", "yes", "no"]),
    (re.compile(r"\b(attached|enclosed|sending you|here is|please find)\b", re.I),
     ["received", "thanks"]),
    (re.compile(r"\b(thank you|thanks|cheers)\b", re.I),
     ["thanks"]),
]

DEFAULT = ["thanks", "later", "not_me"]


def suggest(text: str, subject: str = "") -> list[dict]:
    """
    Two or three answers that fit what was asked. Rules only — no model runs
    and no network call is made, which is the entire point of this stage.
    """
    blob = f"{subject}\n{text}"[:1500]
    keys = []
    for pattern, options in TRIGGERS:
        if pattern.search(blob):
            keys = options
            break
    if not keys:
        keys = DEFAULT
    # ⚠️ Capped at three. More than three is a menu, and a menu is slower than
    # typing the word yourself — which would defeat the feature.
    return [{"key": k, "text": ANSWERS[k]} for k in keys[:3]]


def text_for(key: str) -> str:
    return ANSWERS.get(key, "")
