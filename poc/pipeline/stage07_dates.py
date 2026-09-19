"""
Stage 7 — Find dates.

Three different jobs, three different tools, and the split is not a preference:

  FIND the date phrases   →  rules            ~90% accurate, free
  PICK which is the real  →  the model        needs to understand the sentence
  CALCULATE the date      →  a date library   ⚠️ NEVER a model

⚠️ On temporal arithmetic, BERT-base scores 25.9 and RoBERTa-large 29.1 against
a random baseline of 35.4 — both WORSE THAN GUESSING. GPT-4 scores 91.2. So no
model ever computes "three working days from Thursday" here; ordinary code does.

POC uses dateparser for finding. Production adds HeidelTime and duckling, which
are stronger on loose phrasing like "the Friday after next".
"""

import re
from datetime import datetime, timedelta

import dateparser
from dateparser.search import search_dates

# Phrases that suggest a date is a DEADLINE rather than just a mentioned date.
DEADLINE_CUES = re.compile(
    r"\b(by|before|due|deadline|no later than|expires?|last day|"
    r"closing|cut[- ]?off|latest)\b", re.I)

# ⚠️ dateparser's search_dates is very loose. On a real message it returned
# 'dil' and 'bla' — words from an Urdu song lyric — as date phrases, resolved
# them to a day four days out, and the pipeline duly offered to set a reminder.
#
# So a candidate must LOOK like a date before it is one. A real date phrase
# contains a number, a month, a weekday, or one of a short list of relative
# words. Anything else is a word that happened to resemble one to a parser.
#
# This runs as a filter rather than as a replacement for the parser, because
# the parser is good at the phrases it finds correctly and bad only at
# deciding what counts as a phrase at all.
# ⚠️ A BARE NUMBER IS NOT A DATE. This rule was "any digit", and on a real
# LinkedIn message the phrase "150, 41 Comments" became a deadline on the 14th
# of February. A reminder invented out of an engagement count is worse than a
# missed one: it teaches the Owner that our reminders are noise.
#
# So a digit only counts when something around it says "time" — a month, a
# weekday, a clock, a date separator, an ordinal, or a unit of duration.
LOOKS_LIKE_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"      # a month
    r"|\b(mon|tues?|wed|thur?s?|fri|sat|sun)"                    # a weekday
    r"|\b(today|tomorrow|tonight|yesterday|noon|midnight)\b"     # a named day
    r"|\d{1,2}\s*[:.]\s*\d{2}"                                   # a clock, 15:00
    r"|\d{1,2}\s*(am|pm)\b"                                      # 3pm
    r"|\d{1,4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,4}"                # 15/10/2026
    r"|\b\d{1,2}(st|nd|rd|th)\b"                                 # the 5th
    r"|\b\d+\s*(day|week|month|year|hour|minute)s?\b"            # 3 days
    r"|\b(next|last|this|coming)\s+"
    r"(week|month|year|quarter|day|morning|afternoon|evening)\b"
    r"|\b(end|start|beginning)\s+of\s+(the\s+)?(week|month|year)\b",
    re.I)

SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "SKIP_TOKENS": ["t"],
}


# ⚠️ dateparser does not find the commonest deadline phrases in English.
#
# Measured: "deadline is next week" -> None. "by end of month" -> None. And
# "can you do it next week?" matched the word "do" and resolved it to a date
# four days out. It is blind to these AND it substitutes noise for them.
#
# So the ordinary phrases are matched explicitly and resolved by arithmetic,
# which is this stage's rule anyway: code computes dates, never a model.
RELATIVE = re.compile(
    r"\b("
    r"(?:next|this|coming|following)\s+(?:week|month|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday)"
    r"|(?:end|start|beginning)\s+of\s+(?:the\s+)?(?:week|month|year)"
    r"|in\s+\d+\s+(?:days?|weeks?|months?)"
    r"|\d+\s+(?:days?|weeks?|months?)\s+from\s+now"
    r")\b", re.I)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"]


def resolve_relative(phrase: str, ref: datetime) -> datetime | None:
    """'next friday', 'end of month', 'in 3 days' — worked out, not guessed."""
    p = phrase.lower().strip()

    m = re.match(r"in (\d+) (day|week|month)s?", p) or         re.match(r"(\d+) (day|week|month)s? from now", p)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return ref + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[unit])

    if "end of" in p:
        if "week" in p:               # Friday of this week
            return ref + timedelta(days=(4 - ref.weekday()) % 7)
        if "month" in p:
            nxt = (ref.replace(day=28) + timedelta(days=4)).replace(day=1)
            return nxt - timedelta(days=1)
        if "year" in p:
            return ref.replace(month=12, day=31)
    if "start of" in p or "beginning of" in p:
        if "week" in p:               # next Monday
            return ref + timedelta(days=(7 - ref.weekday()) % 7 or 7)
        if "month" in p:
            return (ref.replace(day=28) + timedelta(days=4)).replace(day=1)

    for i, day in enumerate(WEEKDAYS):
        if day in p:
            ahead = (i - ref.weekday()) % 7
            if ahead == 0 or "next" in p or "following" in p:
                ahead += 7 if ahead == 0 else 0
            return (ref + timedelta(days=ahead)).replace(hour=9, minute=0)

    if "week" in p:                   # "next week" / "this week"
        return ref + timedelta(days=7)
    if "month" in p:
        return ref + timedelta(days=30)
    return None


def find_candidates(text: str, reference: datetime | None = None) -> list[dict]:
    """
    Every date phrase in the text, with the words around it so the model can
    later judge which one is the actual deadline.
    """
    if not text:
        return []
    ref = reference or datetime.now()
    try:
        hits = search_dates(text[:4000], settings={**SETTINGS, "RELATIVE_BASE": ref})
    except Exception:
        hits = None
    # ⚠️ Do NOT return here when dateparser finds nothing. It finds nothing for
    # "next week" and "end of month", which are the two commonest deadline
    # phrases in English — and the explicit pass below is exactly what catches
    # them. An early return made that pass unreachable on the cases it existed
    # for, which is the quietest kind of dead code: reachable in testing,
    # unreachable in the situation it was written for.
    out, seen = [], set()
    for phrase, when in (hits or []):
        if when is None or phrase.strip().lower() in seen:
            continue
        # The filter. A word that merely parses is not a date.
        if not LOOKS_LIKE_DATE.search(phrase):
            continue
        seen.add(phrase.strip().lower())

        idx = text.find(phrase)
        context = text[max(0, idx - 60): idx + len(phrase) + 60].replace("\n", " ")

        out.append({
            "phrase": phrase,
            "resolved": when.isoformat(),
            "context": context.strip(),
            # A hint, not a decision. The model picks the real deadline.
            "looks_like_deadline": bool(DEADLINE_CUES.search(context)),
            "days_away": (when.date() - ref.date()).days,
        })

    # The phrases dateparser cannot see, resolved in code.
    for m in RELATIVE.finditer(text[:4000]):
        phrase = m.group(0)
        if phrase.strip().lower() in seen:
            continue
        when = resolve_relative(phrase, ref)
        if not when:
            continue
        seen.add(phrase.strip().lower())
        context = text[max(0, m.start() - 60): m.end() + 60].replace("\n", " ")
        out.append({
            "phrase": phrase,
            "resolved": when.isoformat(),
            "context": context.strip(),
            "looks_like_deadline": bool(DEADLINE_CUES.search(context)),
            "days_away": (when.date() - ref.date()).days,
        })
    return out


# ─────────────── the arithmetic. Code, never a model ───────────────

def add_working_days(start: datetime, days: int, holidays: set = frozenset()) -> datetime:
    """'Three working days from Thursday.' A model gets this wrong. Code does not."""
    d, added = start, 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.date() not in holidays:
            added += 1
    return d


def parse_exact(phrase: str, reference: datetime | None = None) -> datetime | None:
    return dateparser.parse(
        phrase, settings={**SETTINGS, "RELATIVE_BASE": reference or datetime.now()})


def reminder_time(deadline: datetime, kind: str = "default") -> datetime:
    """
    A dentist appointment needs a day's warning. A visa renewal needs six weeks.
    The offset is by TYPE of commitment, not a fixed number.

    Production learns these from when people snooze or act early.
    """
    lead = {
        "appointment": timedelta(days=1),
        "bill": timedelta(days=3),
        "renewal": timedelta(weeks=6),
        "application": timedelta(weeks=2),
        "meeting": timedelta(hours=2),
        "default": timedelta(days=2),
    }.get(kind, timedelta(days=2))

    when = deadline - lead
    return when if when > datetime.now() else datetime.now() + timedelta(minutes=30)
