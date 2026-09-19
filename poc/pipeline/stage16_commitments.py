"""
Stage 16 — Commitments. Turning a date in an email into a reminder that fires.

⚠️ THIS RUNS FOR EVERY MESSAGE WE OPEN, NOT ONLY THE ONES NEEDING A REPLY.

That distinction is the whole reason this file exists. "Your meeting is
tomorrow at 3" needs NO reply — stage 9 correctly says so — and it is exactly
the message a person most needs surfaced. Reminders were previously computed
inside the drafting path, which meant they only ever happened for mail that
needed answering. The mail that needed remembering got nothing.

Reply and remember are different jobs. This one hangs off stage 7, not stage 9.

⚠️ A REMINDER IS REVERSIBLE, SO IT NEEDS NO APPROVAL.

Nothing is sent, moved or deleted. The worst case is a notification the user
did not want, which they dismiss. Compare that to a send, which cannot be
recalled. The gate is spent where it is needed and not where it is not.

⚠️ AND THE ARITHMETIC IS CODE. ALWAYS.

Encoders score 25.9 and 29.1 on date arithmetic against a random baseline of
35.4 — worse than guessing. A model may READ that a sentence refers to a time.
Python works out which time, and how long before it to warn.
"""

from datetime import datetime, timedelta

# How much warning each kind of commitment deserves. A dentist appointment
# needs a day. A visa renewal needs six weeks. The offset is by TYPE, not a
# fixed number, because "remind me 2 days before" is useless for both.
LEAD = {
    "meeting":     timedelta(hours=2),
    "appointment": timedelta(days=1),
    "bill":        timedelta(days=3),
    "application": timedelta(weeks=2),
    "renewal":     timedelta(weeks=6),
    "deadline":    timedelta(days=2),
}

# Words that say what KIND of commitment this is. Matched in the subject and
# the surrounding sentence, never in the whole email — a word appearing in a
# footer should not retype the commitment.
#
# ⚠️ ORDER IS PRIORITY, MOST SPECIFIC FIRST — and it is load-bearing.
#
# "Passport renewal" came out as a BILL, because bill's list held "renew" and
# bill was checked first. That is a 3-day warning on something that needs six
# weeks. A dict of keywords is only as good as the order it is read in, and
# the general categories must always be checked last.
KIND_WORDS = {
    "renewal":     ("passport", "visa", "licence", "license", "insurance",
                    "renewal", "expires", "expiry", "expiring"),
    "appointment": ("appointment", "booking", "reservation", "consultation",
                    "doctor", "dentist", "clinic"),
    "meeting":     ("meeting", "call", "standup", "sync", "interview", "demo",
                    "zoom", "teams", "google meet", "catch up"),
    "application": ("application", "apply", "submission", "closing date"),
    # Most general, so checked last.
    "bill":        ("invoice", "bill", "payment", "statement", "subscription", "due"),
}


def classify_kind(subject: str, context: str) -> str:
    """
    What sort of commitment this is. Rules, not a model — the categories are
    ours, the words are fixed, and a wrong guess only changes how early we
    warn. Not worth a model, and certainly not worth a paid one.
    """
    blob = f"{subject} {context}".lower()
    for kind, words in KIND_WORDS.items():
        if any(w in blob for w in words):
            return kind
    return "deadline"


def reminder_time(due: datetime, kind: str = "deadline") -> datetime:
    """
    When to warn. Pure arithmetic.

    ⚠️ If the lead time has already passed — an email about a meeting in one
    hour — we do NOT skip the reminder. We fire it shortly, because late is
    still useful and silent is not.
    """
    when = due - LEAD.get(kind, LEAD["deadline"])
    now = datetime.now()
    return when if when > now else now + timedelta(minutes=5)


def from_email(env, date_candidates: list, forms: dict | None = None,
               facts: dict | None = None) -> dict | None:
    """
    One commitment, or None. Given what stage 7 found and what stage 5 read.

    ⚠️ A CALENDAR ATTACHMENT BEATS ANYTHING FOUND IN THE TEXT.

    An .ics file is the sender stating the time in a machine-readable field.
    A phrase in a sentence is us inferring it. When both exist, the declared
    one wins — reading beats guessing, every time it is available.
    """
    # ⚠️ A COMMITMENT IS SOMETHING THE OWNER IS ON THE HOOK FOR.
    #
    # A marketing email saying "80% off today" contains a date, and it is not a
    # commitment. Found in real output: a flash sale produced a reminder due at
    # 13:11 and firing at 13:16 — five minutes AFTER the thing it warned about.
    #
    # So bulk and machine-generated mail cannot create reminders from their
    # TEXT. They can still create one from an ATTACHED calendar invite, because
    # an .ics file is the sender declaring a real appointment rather than us
    # reading urgency into an advert.
    machine = bool(facts and facts.get("machine_generated")) or getattr(env, "bulk", False)

    # 1. The sender attached the answer.
    for meeting in (forms or {}).get("meetings", []):
        start = meeting.get("start")
        if not start:
            continue
        try:
            due = datetime.fromisoformat(str(start)[:19])
        except Exception:
            continue
        return {
            "due": due,
            "kind": "meeting",
            "remind_at": reminder_time(due, "meeting"),
            "why": f"calendar invite: {meeting.get('summary', 'meeting')}",
            "source": "attached invite — declared, not inferred",
        }

    # 2. Nothing attached. Use the best date phrase we found in the text —
    #    but only if a person sent it.
    if machine:
        return None
    if not date_candidates:
        return None

    # Prefer a phrase with a deadline cue near it, then the soonest future one.
    future = [c for c in date_candidates if c.get("days_away", -1) >= 0]
    if not future:
        return None
    cued = [c for c in future if c.get("looks_like_deadline")]
    best = min(cued or future, key=lambda c: c["days_away"])

    try:
        due = datetime.fromisoformat(best["resolved"])
    except Exception:
        return None

    kind = classify_kind(env.subject or "", best.get("context", ""))
    return {
        "due": due,
        "kind": kind,
        "remind_at": reminder_time(due, kind),
        "why": f"{best['phrase']!r} in the message",
        "source": "found in the text",
    }


def record(store, env, commitment: dict) -> None:
    """Write it. Reversible, so no approval was needed to get here."""
    store.add_reminder(
        message_id=env.message_id, provider_id=env.provider_id,
        kind=commitment["kind"], due=commitment["remind_at"],
        subject=(env.subject or "")[:80], why=commitment["why"])


# ── UC-23 · which label a structured commitment gets ──────────────────

LABEL_FOR = {
    "meeting":     "meeting",
    "appointment": "meeting",
    "bill":        "invoice",
    "renewal":     "invoice",
    "application": None,        # no obvious folder; the reminder is enough
}


def label_key(commitment: dict, forms: dict | None = None) -> str | None:
    """
    ⚠️ Only where the sender DECLARED it (UC-23, BR-84).

    A flight label on a message we merely guessed was about a flight is worse
    than no label — the Owner stops trusting the folder, and a folder nobody
    trusts is a folder nobody opens. So a category label is applied only when
    it came out of an attachment or a matched layout, never from the text.
    """
    forms = forms or {}
    if forms.get("passes"):
        kinds = " ".join(str(p.get("type", "")) for p in forms["passes"]).lower()
        if "board" in kinds or "flight" in kinds or "air" in kinds:
            return "flight"
        return "order"
    if forms.get("invoices"):
        return "invoice"
    if forms.get("meetings"):
        return "meeting"
    if commitment and commitment.get("source", "").startswith("attached"):
        return LABEL_FOR.get(commitment["kind"])
    return None


# ── UC-24 · BR-88, learning how much warning this person wants ────────

def learn_from_reaction(store, kind: str, reacted_early: bool) -> None:
    """
    Repeatedly dismissing a warning as too early moves it later; acting on it
    immediately moves it earlier (BR-88).

    ⚠️ Stored as a correction, not as a model weight. It takes effect on the
    next reminder rather than after a retraining cycle — same reasoning as
    UC-29: a lookup changes behaviour now, a weight changes it eventually.
    """
    store.add_correction("reminder_lead", kind,
                         was="default", source="app",
                         should_be="earlier" if reacted_early else "later")


def lead_for(store, kind: str):
    """The lead time for this kind, adjusted by what this person has done."""
    base = LEAD.get(kind, LEAD["deadline"])
    try:
        fix = store.db.execute(
            "SELECT should_be FROM corrections WHERE scope='reminder_lead' "
            "AND target=? ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
    except Exception:
        return base
    if not fix:
        return base
    # Half or double, bounded so one stray reaction cannot make a six-week
    # warning fire six months out.
    return base * 2 if fix[0] == "earlier" else base / 2
