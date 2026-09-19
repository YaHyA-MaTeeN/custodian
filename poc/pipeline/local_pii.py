"""
Stage 10, running on our own model.

⚠️ PATTERNS FIRST, THEN THE MODEL. The order is not arbitrary.

Structured identifiers - cards, IBANs, emails, phone numbers - have checkable
structure, so a regular expression gets them essentially right every time. A
model does not: ours called a credit card an SSN and an IBAN a vehicle
registration. It found them, but it typed them badly.

Names have no structure, so a regex cannot find them at all. That is exactly
what the model is for.

So: patterns claim the text they are certain about, and the model takes what
is left. Running the model first would let it mislabel a card number and stop
the pattern that would have got it right.

⚠️ AND THE HONEST LIMIT, WHICH THE MODEL DOES NOT CHANGE

Our model scores 0.922 on identifier tokens - on the dataset it was trained
on. On a benchmark of REAL documents, a model self-reporting 98.82 scored
0.27, and nothing tested beat a non-expert human at 0.77.

So the claim is: we strip identifiers, we minimise what crosses, and we
contract for zero retention. NOT "names are removed."
"""

import re
from pathlib import Path

MODEL_DIR = Path(__file__).parent.parent / "pii_model"

_tok = None
_net = None
_torch = None

# What the model calls a thing is noisy - 113 categories from 17,000 examples
# means many types had very few. What matters for redaction is that it found
# the span at all, so we collapse its 113 labels down to the handful we use.
FAMILY = {
    "FIRSTNAME": "PERSON", "LASTNAME": "PERSON", "MIDDLENAME": "PERSON",
    "FULLNAME": "PERSON", "PREFIX": "PERSON", "USERNAME": "PERSON",
    "ACCOUNTNAME": "PERSON", "GENDER": "PERSON", "JOBTITLE": "PERSON",
    "EMAIL": "EMAIL",
    "PHONENUMBER": "PHONE", "PHONEIMEI": "PHONE",
    "STREET": "ADDRESS", "BUILDINGNUMBER": "ADDRESS", "CITY": "ADDRESS",
    "STATE": "ADDRESS", "ZIPCODE": "ADDRESS", "COUNTY": "ADDRESS",
    "SECONDARYADDRESS": "ADDRESS", "NEARBYGPSCOORDINATE": "ADDRESS",
    "DATE": "DATE", "DOB": "DATE", "TIME": "DATE",
    "COMPANYNAME": "ORG",
}


def available() -> bool:
    return (MODEL_DIR / "config.json").exists()


def _load():
    global _tok, _net, _torch
    if _net is not None:
        return _tok, _net
    import warnings, logging
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification
    _torch = torch
    _tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    _net = AutoModelForTokenClassification.from_pretrained(str(MODEL_DIR)).eval()
    return _tok, _net


def find_spans(text: str, min_len: int = 2) -> list[tuple[int, int, str]]:
    """
    Character spans the model thinks are identifiers, merged into runs.
    Returns (start, end, family).
    """
    if not text.strip():
        return []
    tok, net = _load()

    enc = tok(text, return_tensors="pt", truncation=True,
              max_length=512, return_offsets_mapping=True)
    offsets = enc.pop("offset_mapping")[0]
    with _torch.no_grad():
        preds = net(**enc).logits.argmax(-1)[0]

    spans, cur, start, end = [], None, None, None
    for pid, (a, b) in zip(preds.tolist(), offsets.tolist()):
        raw = net.config.id2label[pid]
        base = raw[2:] if raw[:2] in ("B-", "I-") else raw
        fam = FAMILY.get(base, "ID" if base != "O" else "O")

        if fam == "O" or b <= a:
            if cur:
                spans.append((start, end, cur))
                cur = None
            continue
        if cur == fam and a - end <= 2:      # same run, allow a space
            end = b
        else:
            if cur:
                spans.append((start, end, cur))
            cur, start, end = fam, a, b
    if cur:
        spans.append((start, end, cur))

    return [(a, b, f) for a, b, f in spans if len(text[a:b].strip()) >= min_len]
