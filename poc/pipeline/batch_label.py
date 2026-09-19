"""
Batch labelling — the teacher marks ten papers at a time.

⚠️ WHY THIS EXISTS

The obvious way to label 600 emails is 600 requests. On a free tier that is
about 15 requests a minute, so 600 requests is forty minutes of waiting and a
good chance of hitting the daily cap.

Sending TEN emails in one request costs one request instead of ten. Six hundred
emails becomes sixty requests — two minutes, comfortably inside any free tier.

This is not a trick for the demo. It is the same reason the mailbox scan fetches
in bulk rather than one message at a time: the difference between one minute and
six hours.
"""

import json
import re

from .model import INTENT, TOPIC, _generate

PER_REQUEST = 10        # ten emails per call
MAX_CHARS = 900         # per email, so ten fit comfortably in one prompt


def _prompt(batch: list[dict]) -> str:
    items = []
    for i, e in enumerate(batch, 1):
        text = (e.get("text") or "")[:MAX_CHARS].replace("\n", " ").strip()
        items.append(f'--- EMAIL {i} ---\nSubject: {e.get("subject","")}\n{text}')

    return f"""Label each of these {len(batch)} emails with two labels.

What does the sender want from the recipient? Choose exactly one:
{chr(10).join('- ' + i for i in INTENT)}

What is it about? Choose exactly one:
{chr(10).join('- ' + t for t in TOPIC)}

{chr(10).join(items)}

Reply with JSON only, one object per email, in the same order:
{{"labels": [{{"n": 1, "intent": "...", "topic": "..."}}, ...]}}
Give exactly {len(batch)} objects."""


def label_batch(batch: list[dict]) -> list[dict]:
    """
    Returns one {"intent", "topic"} per input email, in order.

    If the model returns the wrong number of labels, the batch is discarded
    rather than mis-aligned — a label attached to the wrong email is worse
    than no label, because it poisons the training data silently.
    """
    raw = _generate(_prompt(batch))
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return []
    try:
        labels = json.loads(m.group(0)).get("labels", [])
    except json.JSONDecodeError:
        return []

    if len(labels) != len(batch):
        return []

    out = []
    for lab in labels:
        intent = str(lab.get("intent", "")).strip()
        topic = str(lab.get("topic", "")).strip()
        out.append({
            "intent": intent if intent in INTENT else "just telling me",
            "topic": topic if topic in TOPIC else "other",
        })
    return out
