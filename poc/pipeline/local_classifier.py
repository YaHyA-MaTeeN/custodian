"""
Stage 8, running on our own model.

⚠️ THIS IS THE WHOLE ARCHITECTURAL CLAIM.

The design says the email is read by a model WE trained, on OUR hardware, at
no cost per email and without the text leaving the building. This file is
where that stops being a claim and starts being true.

  Gemini            1-2 seconds   ·  costs money  ·  text leaves
  our model         ~110 ms       ·  free         ·  stays on this machine

The model is loaded once and held in memory. Loading a 1.1 GB model per email
would make it slower than the API it replaces.

⚠️ HONEST STATE: trained on 199 examples from one mailbox. Strong on the two
classes that had enough data, weak on the two that had two examples each. It
proves the component works end to end. It is not yet good enough to ship.
"""

import re
from pathlib import Path

MODEL_DIR = Path(__file__).parent.parent / "classifier"

_tok = None
_net = None
_torch = None


def available() -> bool:
    return (MODEL_DIR / "config.json").exists()


def _load():
    """Load once, keep in memory."""
    global _tok, _net, _torch
    if _net is not None:
        return _tok, _net

    import warnings, logging
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)

    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    _torch = torch
    _tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    _net = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR)).eval()
    return _tok, _net


# ── topic, from rules ───────────────────────────────────────────────────
# We only trained the model on INTENT — the label that actually drives stage 9.
# Topic is a coarse bucket, so rules do it: free, instant, and no second model
# to train and keep in step.

TOPIC_RULES = [
    ("account or security", re.compile(
        r"\b(security alert|verification|verify|password|sign(ed)? in|"
        r"two[- ]factor|otp|confirm your email|activate your account|"
        r"terms of service|privacy policy)\b", re.I)),
    ("appointment or meeting", re.compile(
        r"\b(meeting|calendar|invite|invitation to (a )?(call|meeting)|"
        r"zoom|webinar|appointment|reschedul|confirmation for)\b", re.I)),
    ("travel", re.compile(
        r"\b(flight|boarding pass|itinerary|booking reference|check[- ]in|"
        r"hotel|departure|gate \d)\b", re.I)),
    ("money or bills", re.compile(
        r"\b(invoice|receipt|payment|bill|due|amount|refund|subscription|"
        r"charged|transaction|statement)\b", re.I)),
    ("shopping or order", re.compile(
        r"\b(your order|shipped|delivery|tracking|cart|% off|sale|discount|"
        r"deal|shop now|offers)\b", re.I)),
    ("newsletter or marketing", re.compile(
        r"\b(newsletter|unsubscribe|weekly digest|recommended for you|"
        r"upgrade now|free trial|what.s new|hadith|digest)\b", re.I)),
    ("work", re.compile(
        r"\b(job|hiring|application|linkedin|connect|network|intern|"
        r"report|project|deadline|colleague|paper|research)\b", re.I)),
]


def guess_topic(text: str, subject: str = "", sender: str = "") -> str:
    blob = f"{subject} {sender} {text[:600]}"
    for topic, pattern in TOPIC_RULES:
        if pattern.search(blob):
            return topic
    return "other"


# ── the model ───────────────────────────────────────────────────────────

def classify(text: str, subject: str = "", sender: str = "") -> dict:
    """
    Same shape as the Gemini version, so stage 8 does not care which ran.
    """
    if not text.strip():
        return {"intent": "nothing needed", "topic": "other",
                "confidence": 0.0, "by": "our model"}

    tok, net = _load()
    joined = f"{subject}\n{text}" if subject else text

    with _torch.no_grad():
        out = net(**tok(joined, return_tensors="pt",
                        truncation=True, max_length=256))
    probs = _torch.softmax(out.logits, dim=-1)[0]
    i = int(probs.argmax())

    return {
        "intent": net.config.id2label[i],
        "topic": guess_topic(text, subject, sender),
        "confidence": float(probs[i]),
        "by": "our model",
    }
