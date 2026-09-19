"""
Stage 18 — What was actually asked, of whom, and by when.

⚠️ THE STAGE THAT MAKES THE PRODUCT AGENTIC (UC-33).

Everything before this reads the envelope, or data a big sender embedded. This
reads what a PERSON wrote — "please send the revised proposal by Friday" — and
names the request, the owner and the date. Pointed at the Sent folder it reads
the mirror: what the Owner promised (UC-45). Run across a thread it gives
where a conversation stands (UC-40).

⚠️ CHEAP MODEL FIRST, PAID MODEL ONLY WHEN IT EARNS ITS KEEP.

Our own classifier already says whether a message needs a response. Only
messages it says yes to — ten to thirty a day, not hundreds — reach the paid
model, and only after stage 10 has replaced every name and number with a
placeholder. Bulk mail never gets here at all (BR-118).

⚠️ WHEN UNSURE, RECORD NOTHING (BR-119).

Two people reading the same email agree only 72% of the time on whether
something is a promise or a proposal. A wrong deadline is worse than no
deadline. Below the threshold, silence is the correct output.

⚠️ THE MODEL NAMES THE PHRASE. CODE WORKS OUT THE DATE.

"by Friday" comes back as text and stage 7 resolves it. A vague phrase —
"early next week" — produces a request with no date, never a guessed one.

⚠️ AND NOTHING IS EVER ACTED ON BECAUSE OF WHAT IS FOUND HERE (BR-122).

The output is a row in a table. A draft, a warning or a calendar suggestion
may follow, and each still needs the Owner. An email cannot create a task,
a deadline or an action by asking for one (BR-93).
"""

from datetime import datetime

THRESHOLD = 0.6            # below this, nothing is recorded — measured, not chosen


def _resolve(phrase: str, sent_on: str = "") -> str:
    """The phrase → an ISO date, by code. '' if it cannot be settled."""
    if not phrase:
        return ""
    from . import stage07_dates
    try:
        cands = stage07_dates.find_candidates(phrase)
    except Exception:
        cands = []
    future = [c for c in cands if c.get("resolved")]
    if not future:
        return ""
    return str(future[0]["resolved"])[:19]


def extract(text: str, subject: str, direction: str, known_names=None) -> list:
    """
    Requests in one message. Returns a list of
        {what, who, due, evidence, confidence}
    Empty when there is nothing, or when unsure — both are correct outcomes.

    `direction` is "incoming" (someone asking the Owner) or "sent" (the Owner
    promising someone). The prompt is told which, because "I'll send it
    Friday" means opposite things in the two folders.
    """
    from . import stage10_redact, model, prompts
    if not (text or "").strip():
        return []
    # ⚠️ One door out: redacted, minimised, restored locally afterwards.
    redacted, mapping = stage10_redact.redact(stage10_redact.minimise(text, 2500),
                                              known_names or [])
    prompt = prompts.get("extract_request", direction=direction,
                         subject=subject or "", text=redacted)
    try:
        out = model._json_from(model._generate(prompt))
    except Exception:
        return []                                   # never a degraded guess
    items = []
    for it in (out.get("items") or [])[:5]:
        try:
            conf = float(it.get("confidence", 0))
        except Exception:
            conf = 0.0
        if conf < THRESHOLD:
            continue
        what, _ = stage10_redact.restore(str(it.get("what", ""))[:200], mapping)
        evidence, _ = stage10_redact.restore(str(it.get("evidence", ""))[:300], mapping)
        who = str(it.get("who", "")).lower()
        if who not in ("me", "sender", "third party"):
            who = "third party"
        due = _resolve(str(it.get("when_phrase", "")))
        if what.strip():
            items.append({"what": what.strip(), "who": who, "due": due,
                          "evidence": evidence.strip(), "confidence": round(conf, 2)})
    return items
