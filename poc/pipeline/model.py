"""
The model layer — stages 8 and 11.

⚠️ WHAT THIS IS IN THE PROOF OF CONCEPT VS WHAT IT IS IN PRODUCTION

  Stage 8, reading the email
      POC         Gemini (free tier), zero-shot
      Production  mdeberta-v3-base, 278M, fine-tuned by us, on our own CPU
      Why the difference: fine-tuning needs 100-1,000 labelled emails, and
      we cannot label them before we have looked at a real mailbox. So the
      POC borrows a big model to prove the shape of the flow; production
      replaces it with a small one that runs free and never leaves our
      building.

  Stage 11, writing the reply
      POC         Gemini (free tier)
      Production  Claude Sonnet 5, or Gemini — decided by blind comparison
                  on real drafts, not by any public benchmark.

Get a free key at https://aistudio.google.com/apikey and set GEMINI_API_KEY.
"""

import json
import logging
import os
import re
import warnings

# The Gemini SDK prints an advisory about automatic function calling on every
# request. We do not use that feature, so it is noise.
warnings.filterwarnings("ignore")
for _n in ("google_genai", "google_genai.models", "google.genai"):
    logging.getLogger(_n).setLevel(logging.ERROR)

MODEL_FAST = "gemini-flash-latest"   # always current; the key decides what that means

# The two label sets. Fixed lists — the model chooses from them, it does not
# invent categories. In production these become the classifier's output layer.
INTENT = ["asking me for something", "proposing something", "promising something",
          "delivering something", "just telling me", "nothing needed"]

TOPIC = ["work", "money or bills", "travel", "appointment or meeting",
         "shopping or order", "personal", "account or security",
         "newsletter or marketing", "other"]


_CLIENT = None


def _client():
    """
    One client for the whole process. Building a new one per call means the
    previous one gets garbage-collected and closes its connection mid-flight.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set.\n"
            "  Get a free key: https://aistudio.google.com/apikey\n"
            "  Windows:  setx GEMINI_API_KEY \"your-key\"   (then reopen the terminal)")
    from google import genai
    _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def _json_from(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


# Tried in order. The free tier gets busy, so we fall back rather than fail.
MODELS = ["gemini-flash-latest", "gemini-2.5-flash",
          "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]


def _generate(prompt: str, tries_per_model: int = 2) -> str:
    """
    Every call to a hosted model goes through here.

    Two things any production caller needs and a demo usually skips:
    retry with backoff on 429 and 503, and a fallback model when one is
    overloaded. Free tiers are busy; failing the whole pipeline because a
    server was momentarily loaded is not acceptable.
    """
    import random
    import time

    last = None
    for name in MODELS:
        for attempt in range(tries_per_model):
            try:
                r = _client().models.generate_content(model=name, contents=prompt)
                return r.text or ""
            except Exception as e:
                last = e
                msg = str(e)
                if "503" in msg or "429" in msg or "UNAVAILABLE" in msg:
                    time.sleep((2 ** attempt) + random.random())
                    continue
                break          # a real error — try the next model, not again
    raise RuntimeError(f"all models failed. last: {str(last)[:160]}")


# Stage 6's one dial. Below this, our small model is treated as unsure and
# the message is sent to a bigger one. Above it, we keep our own answer.
ESCALATE_BELOW = 0.65


def _ask_gemini(text: str, subject: str = "") -> dict:
    """The hosted read. Used when we have no model, or when ours was unsure."""
    if not text.strip():
        return {"intent": "nothing needed", "topic": "other",
                "confidence": 0.0, "note": "empty after stripping"}

    prompt = f"""Read this email and answer with two labels.

What does the sender want from me? Choose exactly one:
{chr(10).join('- ' + i for i in INTENT)}

What is it about? Choose exactly one:
{chr(10).join('- ' + t for t in TOPIC)}

Reply with JSON only: {{"intent": "...", "topic": "...", "confidence": 0.0-1.0}}

Subject: {subject}
---
{text[:3000]}"""

    out = _json_from(_generate(prompt))
    intent = out.get("intent", "").strip()
    topic = out.get("topic", "").strip()

    # Gemini answers in the four-way vocabulary; stage 9 reads the binary one.
    # Translate here rather than teaching stage 9 two languages.
    REQUESTING = {"asking me for something", "proposing something"}
    return {
        "intent": ("needs a response from you" if intent in REQUESTING
                   else "no response needed"),
        "intent_detail": intent if intent in INTENT else "just telling me",
        "topic": topic if topic in TOPIC else "other",
        "confidence": float(out.get("confidence", 0.5)),
        "by": "Gemini",
    }


# ─────────────────── stage 8 — read the email ───────────────────

def classify(text: str, subject: str = "", sender: str = "") -> dict:
    """
    Two labels and a confidence. That is ALL this stage produces — it does not
    summarise, decide anything, or write. Stage 9 uses these labels; it never
    re-reads the text.

    ⚠️ OUR OWN MODEL FIRST.

    If classifier/ exists, this runs on the model we trained — on this machine,
    free, ~110 ms, and the text never leaves the building. That is the whole
    architectural claim, so it is the default and not the fallback.

    Gemini is only used when we have no model of our own yet.
    """
    from . import local_classifier
    if local_classifier.available():
        ours = local_classifier.classify(text, subject, sender)

        # ── STAGE 6, the router ──────────────────────────────────────
        #
        # ⚠️ It escalates on CONFIDENCE. Never on category.
        #
        # A rule like "always escalate anything about invoices" bakes our
        # guesses into the routing and guarantees the small model never gets
        # a chance to prove itself on invoices — so it never improves there
        # and the bill never falls. "Escalate when the small model is unsure"
        # is honest about what we actually know, and it gets cheaper on its
        # own as the small model gets better.
        #
        # 0.65 measured against this mailbox: our model's real confidences run
        # 0.52 to 0.90, and the ones it got wrong sat at the bottom of that
        # range. Tune per deployment; it is a dial, not a truth.
        if ours.get("confidence", 0.0) >= ESCALATE_BELOW:
            return ours

        if not os.environ.get("GEMINI_API_KEY"):
            ours["note"] = (f"unsure ({ours['confidence']:.2f}) but no key — "
                            f"kept our answer")
            return ours

        try:
            bigger = _ask_gemini(text, subject)
            bigger["by"] = "Gemini (escalated)"
            bigger["escalated_from"] = ours["confidence"]
            return bigger
        except Exception:
            ours["note"] = "escalation failed — kept our answer"
            return ours

    # No model of our own yet — the hosted one does the whole job.
    return _ask_gemini(text, subject)


def pick_deadline(candidates: list[dict], subject: str = "") -> dict | None:
    """
    Rules found the dates. The model picks which one is the real deadline —
    that needs understanding the sentence. The arithmetic already happened
    in code, in stage 7.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    listing = "\n".join(
        f'{i}. "{c["phrase"]}" — {c["resolved"][:10]} — context: {c["context"]}'
        for i, c in enumerate(candidates))

    prompt = f"""Which of these dates is the actual deadline the sender needs
action by? Some are just mentioned in passing.

Subject: {subject}
{listing}

Reply with JSON only: {{"index": <number>, "kind": "appointment|bill|renewal|application|meeting|default"}}
If none is a real deadline, use index -1."""

    try:
        out = _json_from(_generate(prompt))
        i = int(out.get("index", -1))
        if 0 <= i < len(candidates):
            picked = dict(candidates[i])
            picked["kind"] = out.get("kind", "default")
            return picked
    except Exception:
        pass
    return None


# ─────────────────── stage 11 — write the reply ───────────────────

def draft_reply(redacted_text: str, subject: str, sender_placeholder: str,
                style_examples: list[str], style_profile: dict,
                instruction: str = "") -> str:
    """
    ⚠️ Everything reaching this function has already passed stage 10 — names
    and identifiers replaced with placeholders. This is the ONLY point where
    anything leaves our building.

    The model writes the WHOLE message rather than fragments: measured better
    on both speed and how recipients rate the result.
    """
    examples = "\n\n---\n\n".join(style_examples[:5]) or "(none yet)"
    profile = ", ".join(f"{k}: {v}" for k, v in style_profile.items()) or "unknown"

    prompt = f"""Write a reply to this email, in the same voice as the examples.

How this person writes: {profile}

Some of their own past replies:
{examples}

---
The email to reply to (names are replaced with placeholders — keep the
placeholders exactly as they are, do not invent real names):

From: {sender_placeholder}
Subject: {subject}

{redacted_text[:3000]}
---
{('Extra instruction from the user: ' + instruction) if instruction else ''}

Write only the reply body. No subject line, no explanation, no quotes."""

    return _generate(prompt).strip()


# ─────────────────── the command reader (stage 13) ───────────────────

ACTIONS = ["send", "edit", "discard", "snooze", "remind", "archive",
           "label", "mark_read", "nothing"]


def read_command(user_text: str, state: dict) -> dict:
    """
    ⚠️ The user's typed text is an INSTRUCTION. Text inside an email is DATA.
    They never share a code path — this function is only ever called from the
    user's own channel.

    The model is not asked to "understand language". It is handed a
    multiple-choice question built by OUR code from the current state, so it
    can never choose an action we did not offer. With no draft pending,
    "send" is not on the list.
    """
    allowed = list(ACTIONS)
    if not state.get("current_draft"):
        allowed = [a for a in allowed if a not in ("send", "edit")]

    context = "\n".join(f"{k}: {v}" for k, v in state.items() if v)

    prompt = f"""The user typed a short instruction about their mailbox.

What is on screen right now:
{context or "(nothing)"}

The user typed: "{user_text}"

Think about what they mean, then choose exactly one action from this list:
{', '.join(allowed)}

Reply with JSON only:
{{"action": "...", "parameter": "...", "reasoning": "..."}}
Use "nothing" if it is unclear."""

    try:
        out = _json_from(_generate(prompt))
        action = out.get("action", "nothing")
        return {"action": action if action in allowed else "nothing",
                "parameter": out.get("parameter", ""),
                "reasoning": out.get("reasoning", "")}
    except Exception as e:
        return {"action": "nothing", "parameter": "", "reasoning": f"error: {e}"}
