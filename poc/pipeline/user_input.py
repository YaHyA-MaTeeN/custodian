"""
The user's own channel — how typed sentences become actions.

⚠️ THE SEPARATION THIS FILE EXISTS TO ENFORCE.

    text the USER types   →  an INSTRUCTION  →  this file
    text inside an EMAIL  →  DATA            →  stages 2, 8, 10, 11

They never share a code path. Nothing in this file is ever handed the contents
of a message, which is why an email cannot reach it to issue a command. That is
the whole defence: in published testing all 1,404 email agents evaluated were
hijacked by instructions hidden in email text, and every one of them had a
single path that carried both kinds of text.

⚠️ AND THE SECOND DEFENCE: THE MODEL NEVER PICKS FROM AN OPEN SET.

It is handed a multiple-choice question that OUR code builds from the current
state. With no draft on screen, "send" is not one of the options — so no
sentence, however phrased, can produce a send. The model chooses between
options we already decided were safe.

Rules run before the model. Most instructions are three words and do not need
one, and a rule that fires is free, instant and predictable.
"""

import re

# Everything the chat can do. Reversible actions are done immediately;
# irreversible ones go to stage 13 for an explicit yes.
ALL_ACTIONS = ["compose", "send", "edit", "discard", "decline",
               "sort", "brief", "search", "watch", "help", "quit", "nothing"]

IRREVERSIBLE = {"send"}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")

# ⚠️ Word-boundary matched, not substring. "unsorted" must not fire "sort".
# A refusal, typed while something is waiting to be sent.
#
# "no" once came back from the model as an EDIT instruction, which would have
# rewritten the very draft the user was refusing. Refusals are now matched by
# a rule that runs before everything else, so no model ever interprets one.
NEGATIVE = re.compile(
    r"^(no|nope|nah|don'?t|do ?not|no thanks|not now|stop|wait|hold on|cancel)\b",
    re.I)

# "stop" is deliberately NOT a quit word any more. With a draft on screen it
# means "do not send", and quitting on it would be the wrong reading of the
# more dangerous of the two possibilities.
RULES = [
    ("quit",   r"\b(quit|exit|bye|close)\b"),
    ("help",   r"\b(help|what can you do|commands?)\b"),
    ("sort",   r"\b(sort|categorish?e|categorize|label|organise|organize|tidy)\b"),
    ("brief",  r"\b(brief|summary|summarise|summarize|what.s (in|new)|inbox|catch me up)\b"),
    ("search", r"\b(search|find|look for|show me|any(thing)? from)\b"),
    ("watch",  r"\b(watch|live|monitor|keep an eye)\b"),
    ("discard",r"\b(discard|cancel|forget it|never mind|delete the draft)\b"),
    ("edit",   r"\b(edit|change|rewrite|shorter|longer|redo|make it)\b"),
    ("compose",r"\b(compose|write|send|email|mail|message)\b"),
]


def allowed_actions(state: dict) -> list[str]:
    """
    ⚠️ Built from state by our code, never by the model.

    With nothing drafted, send/edit/discard are not on the menu at all. This is
    what makes "just send it, the user already agreed" impossible to act on.
    """
    actions = list(ALL_ACTIONS)
    if not state.get("current_draft"):
        for a in ("send", "edit", "discard", "decline"):
            actions.remove(a)
    return actions


def by_rules(text: str, allowed: list[str]) -> dict | None:
    """A cheap first pass. Returns None when it is not confident."""
    low = (text or "").strip().lower()
    if not low:
        return None

    addr = EMAIL.search(text or "")

    # A refusal, while something is waiting to be sent. Checked before
    # everything else and never passed to a model.
    if "decline" in allowed and NEGATIVE.match(low):
        return {"action": "decline", "parameter": "",
                "why": "you said no — the draft stays, nothing is sent"}

    for action, pattern in RULES:
        if action not in allowed:
            continue
        if re.search(pattern, low):
            # "email ali@x.com about the invoice" — the address is the target.
            if action == "compose" and addr:
                return {"action": "compose", "parameter": addr.group(0),
                        "why": "matched a rule and found an address"}
            if action == "compose" and not addr:
                continue          # "send" with no address is probably approval
            param = search_term(text) if action == "search" else ""
            return {"action": action, "parameter": param, "why": "matched a rule"}

    # An address on its own is unambiguous enough.
    if addr and "compose" in allowed:
        return {"action": "compose", "parameter": addr.group(0),
                "why": "an address and nothing else"}
    return None


STOPWORDS = {"anything", "something", "any", "some", "from", "about", "for",
             "show", "me", "find", "search", "look", "the", "a", "an", "is",
             "there", "in", "my", "mail", "mails", "email", "emails", "inbox",
             "please", "can", "you", "i", "have", "got", "with", "of", "on"}


def search_term(text: str) -> str:
    """
    The words worth searching for, out of a whole sentence.

    "anything from linkedin?" -> "linkedin". Without this the query is the
    entire sentence, which matches no subject line ever written.
    """
    words = re.findall(r"[\w.@-]{2,}", (text or "").lower())
    kept = [w for w in words if w not in STOPWORDS]
    return max(kept, key=len) if kept else ""


def read(text: str, state: dict) -> dict:
    """
    One typed sentence in, one chosen action out.

    Rules first. The model only sees what the rules could not place, and even
    then it is choosing from `allowed`, so its answer is checked against that
    list before we act on it.
    """
    allowed = allowed_actions(state)

    hit = by_rules(text, allowed)
    if hit:
        return hit

    import os
    if not os.environ.get("GEMINI_API_KEY"):
        return {"action": "nothing", "parameter": "",
                "why": "no rule matched and no key to ask a model"}

    try:
        from . import model
        context = "\n".join(f"{k}: {str(v)[:120]}" for k, v in state.items() if v)
        prompt = f"""The user typed a short instruction about their own mailbox.

What is on screen right now:
{context or "(nothing)"}

The user typed: "{text}"

Choose exactly one action from this list and nothing else:
{', '.join(allowed)}

compose = write a new email (parameter = the recipient's address if given)
search  = look for messages (parameter = what to look for)
sort    = apply labels across the mailbox
brief   = summarise what is in the inbox

Reply with JSON only:
{{"action": "...", "parameter": "...", "why": "..."}}
Use "nothing" if it is unclear."""
        out = model._json_from(model._generate(prompt))
        action = out.get("action", "nothing")
        # ⚠️ Checked against our list. A model that answers "delete_everything"
        # gets "nothing", not an exception and not an action.
        return {"action": action if action in allowed else "nothing",
                "parameter": str(out.get("parameter", ""))[:200],
                "why": str(out.get("why", ""))[:120] or "chosen by the model"}
    except Exception as e:
        return {"action": "nothing", "parameter": "", "why": f"could not read it: {e}"}
