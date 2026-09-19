"""
Stage 9 — Score, track, and the reply gate.

Answers "will this person actually act on this?" — WITHOUT re-reading the email.

⚠️ The point that gets misread. Words matter enormously: stage 8 reads them and
turns them into meaning. This stage uses that MEANING as one signal among
several. What it does not use is the raw text, because measured on real
enterprise mail each feature group scored, on its own:

    your history with the sender      0.692
    history with that exact pair      0.638
    what the email was understood     0.595   ← the labels from stage 8
    who they are                      0.594
    who else is on it                 0.591
    timing                            0.540
    the raw words                     0.511   ← chance is 0.500
    everything combined               0.721

So: stage 8 reads. Stage 9 decides, using what stage 8 understood plus history.
Nothing reads the same email twice.

PRODUCTION uses LightGBM, one small model per person, trained on their own mail
with answers the mailbox already knows (did they reply, did they open it). Under
1 MB, ~2 seconds to train, retrained weekly.

THE POC uses the weights below, because a new mailbox has no history yet to
train on. Same features, hand-set instead of learned.
"""

from datetime import datetime
from pathlib import Path

# Hand-set for the POC. In production these are learned per person, which is
# why the same email scores differently for two different users.
WEIGHTS = {
    "replied_to_sender_before": 0.30,
    "opened_sender_before": 0.15,
    "is_a_request": 0.20,
    "only_recipient": 0.12,
    "not_machine_generated": 0.15,
    "in_a_thread": 0.10,
    "business_hours": 0.03,
    "verified_sender": 0.05,
}

# ⚠️ BOTH VOCABULARIES, AND THE BINARY ONE IS NOT OPTIONAL.
#
# This set was written for the original four-way classifier. When stage 8 was
# collapsed to a binary question its label became "needs a response from you",
# which was not in this set — so `is_a_request` could never be true, so
# `needs_reply` could never be true, so nothing was ever labelled "Needs a
# reply". The gate looked like it was working: it printed a sensible
# probability every time and then always answered no.
#
# The lesson is about the failure being invisible. Two components each did
# exactly what they were written to do, and the join between them was a string
# comparison nobody re-checked after the vocabulary changed.
REQUESTING = {
    "needs a response from you",                        # binary — our model
    "asking me for something", "proposing something",   # four-way — Gemini
}


MODEL_FILE = Path(__file__).parent.parent / "gate_model.txt"

# The 17 features the model was trained on, in the order train_gate.py built
# them. ⚠️ THE ORDER IS THE CONTRACT. LightGBM takes a bare array — it does not
# check names — so a column swapped here is silently scored against the wrong
# tree and nothing anywhere reports an error.
TRAINED_FEATURES = [
    "sender_total", "sender_open_rate", "sender_recent",
    "is_machine_generated", "has_unsubscribe", "one_click",
    "is_reply", "is_auto_reply", "in_inbox",
    "subject_len", "subject_has_question", "size_kb",
    "hour", "weekday", "business_hours",
    "first_contact", "domain_total",
]

_booster = None


def trained_available() -> bool:
    return MODEL_FILE.exists()


def _load():
    """One booster for the process. Loading it per email would dominate the 1 ms."""
    global _booster
    if _booster is None:
        import lightgbm as lgb
        _booster = lgb.Booster(model_file=str(MODEL_FILE))
    return _booster


def _trained_score(facts: dict, history: dict, envelope) -> float | None:
    """
    The model we actually trained on this mailbox.

    ⚠️ This exists because for a while it did not, and nobody noticed.
    gate_model.txt was trained, scored, saved — and then stage 9 quietly used
    hand-set weights instead. The model was real, the AUC was real, and not
    one prediction ever came from it. Training a model is not the same as
    wiring it in, and only the second one shows up in the output.
    """
    if not trained_available():
        return None
    try:
        import numpy as np
        from email.utils import parsedate_to_datetime

        total = history.get("sent", 0)
        opened = history.get("opened", 0)
        try:
            dt = parsedate_to_datetime(envelope.date)
            hour, weekday = dt.hour, dt.weekday()
        except Exception:
            hour, weekday = 12, 2

        subject = envelope.subject or ""
        row = [
            total,
            opened / total if total else 0.0,
            1 if total >= 5 else 0,
            1 if facts.get("machine_generated") else 0,
            1 if getattr(envelope, "unsubscribe", "") else 0,
            1 if getattr(envelope, "one_click", False) else 0,
            1 if getattr(envelope, "in_reply_to", "") else 0,
            1 if getattr(envelope, "auto_submitted", "") else 0,
            1 if getattr(envelope, "in_inbox", True) else 0,
            len(subject),
            1 if "?" in subject else 0,
            (getattr(envelope, "size", 0) or 0) / 1024,
            hour,
            weekday,
            1 if (weekday < 5 and 7 <= hour <= 19) else 0,
            1 if total <= 1 else 0,
            total,                       # domain_total ≈ sender total here
        ]
        return float(_load().predict(np.array([row], dtype=float))[0])
    except Exception:
        return None                      # the hand-set weights still work


def score(labels: dict, facts: dict, history: dict, envelope) -> dict:
    """
    labels    — from stage 8: intent, topic, confidence
    facts     — from stage 4: machine_generated, auth, is_reply
    history   — this sender: {sent, opened, replied}
    """
    f = {
        "replied_to_sender_before": history.get("replied", 0) > 0,
        "opened_sender_before": history.get("opened", 0) > 0,
        "is_a_request": labels.get("intent") in REQUESTING,
        "only_recipient": facts.get("addressed_only_to_me", True),
        "not_machine_generated": not facts.get("machine_generated", False),
        "in_a_thread": facts.get("is_reply", False),
        "business_hours": _business_hours(envelope.date),
        "verified_sender": facts.get("auth", {}).get("passed", False),
    }

    total = sum(WEIGHTS[k] for k, v in f.items() if v)
    possible = sum(WEIGHTS.values())
    p = round(total / possible, 3)
    source = "hand-set weights"

    # ⚠️ THE TRAINED MODEL, WHEN WE HAVE ONE — BLENDED, NOT SUBSTITUTED.
    #
    # It learned from what this person opens, which is a strong signal and a
    # slightly different question from "will they reply". Its AUC is 0.684,
    # below the published 0.72-0.79 ceiling. So it is averaged with the
    # hand-set weights rather than trusted alone: two mediocre estimates that
    # disagree for different reasons beat either one, and a bad training run
    # can then never swing a decision on its own.
    trained = _trained_score(facts, history, envelope)
    if trained is not None:
        p = round((p + trained) / 2, 3)
        source = f"trained model {trained:.2f} + hand-set weights"

    # A first-time sender is not a blank — it is a category the model has seen
    # many times. A stranger writing only to you, using your name, asking a
    # question, with no bulk marker, scores high with zero history.
    first_contact = history.get("sent", 0) <= 1

    reasons = [k.replace("_", " ") for k, v in f.items() if v]

    return {
        "act_probability": p,
        "needs_reply": p >= 0.45 and f["is_a_request"],
        "first_contact": first_contact,
        "scored_by": source,
        "signals": f,
        # Every decision carries its reason. The commonest complaint about
        # every rival is not knowing why their mail vanished.
        "why": ", ".join(reasons) or "no positive signals",
    }


def _business_hours(date_header: str) -> bool:
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(date_header)
        return d.weekday() < 5 and 7 <= d.hour <= 19
    except Exception:
        return False


# ─────────────────── the obligation ledger ───────────────────

def obligations(store, my_address: str) -> dict:
    """
    Who owes whom a reply. ⚠️ NO AI WHATSOEVER — this is built purely from the
    Message-ID and In-Reply-To headers.

    You sent a message. Nothing came back pointing at it. The clock runs.
    When they reply, the chain closes and the obligation clears itself.

    Needs sent mail to be useful. On a mailbox with no replies it correctly
    reports nothing.
    """
    waiting = store.q("""
        SELECT m.sender, m.sender_name, m.subject, m.date, m.thread_id
          FROM messages m
         WHERE m.sender != ?
           AND m.in_reply_to = ''
           AND NOT EXISTS (
               SELECT 1 FROM messages r
                WHERE r.thread_id = m.thread_id AND r.sender = ?)
         ORDER BY m.date DESC LIMIT 30""", my_address, my_address)

    return {
        "they_owe_me": [],          # needs sent mail
        "i_owe_them": [dict(zip(("sender", "name", "subject", "date", "thread"), r))
                       for r in waiting],
        "note": "Built from Message-ID and In-Reply-To headers. No model involved.",
    }
