"""
Stage 5 — Forms and layouts.

Two different mechanisms sharing a stage. Keep them apart in your head.

HALF ONE — the answer arrived attached. A meeting invite carries a file with
the exact time, place and attendees. Some invoice PDFs carry the whole invoice
as data inside them. A Wallet pass carries flight, gate and seat. We open the
file and read the fields. Nothing is interpreted, nothing can be wrong.

HALF TWO — a shape we worked out ourselves. Your electricity bill looks
identical every month; only the numbers change. After 5-10 of them we record
where the amount sits, and never need a model for that sender again.

Neither half uses AI.
"""

import io
import json
import re
import zipfile

from icalendar import Calendar


# ─────────────── half one: the sender attached the answer ───────────────

def read_calendar(ics_bytes: bytes) -> list[dict]:
    """
    A meeting invite. The email might say "can we meet Thursday?" — the
    attached file says exactly when, to the minute.
    """
    out = []
    try:
        cal = Calendar.from_ical(ics_bytes)
    except Exception:
        return out

    method = str(cal.get("METHOD", "")).upper()
    for ev in cal.walk("VEVENT"):
        start = ev.get("DTSTART")
        end = ev.get("DTEND")
        out.append({
            "kind": "meeting",
            "method": method,          # REQUEST = an invitation, CANCEL kills it
            "summary": str(ev.get("SUMMARY", "")),
            "location": str(ev.get("LOCATION", "")),
            "start": start.dt.isoformat() if start else None,
            "end": end.dt.isoformat() if end else None,
            "organiser": str(ev.get("ORGANIZER", "")).replace("mailto:", ""),
            "attendees": [str(a).replace("mailto:", "")
                          for a in (ev.get("ATTENDEE") or [])
                          if isinstance(ev.get("ATTENDEE"), list)] or [],
            "recurring": bool(ev.get("RRULE")),
            "uid": str(ev.get("UID", "")),
            "sequence": int(ev.get("SEQUENCE", 0)),
        })
    return out


def read_wallet_pass(pkpass_bytes: bytes) -> dict | None:
    """
    A .pkpass is the file behind "Add to Apple Wallet" — a ZIP with a JSON
    inside. Boarding passes, event tickets, coupons.

    In travel email these turn up MORE often than calendar files do.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(pkpass_bytes)) as z:
            data = json.loads(z.read("pass.json").decode("utf-8"))
    except Exception:
        return None

    kind = next((k for k in ("boardingPass", "eventTicket", "coupon",
                             "storeCard", "generic") if k in data), None)
    fields = []
    if kind:
        for group in ("headerFields", "primaryFields",
                      "secondaryFields", "auxiliaryFields"):
            for f in data[kind].get(group, []):
                fields.append({"label": f.get("label", ""), "value": f.get("value", "")})

    return {
        "kind": "wallet_pass",
        "type": kind,
        "description": data.get("description", ""),
        "organisation": data.get("organizationName", ""),
        "relevant_date": data.get("relevantDate"),
        "fields": fields,
    }


INVOICE_XML_NAMES = (
    "factur-x.xml", "zugferd-invoice.xml",
    "xrechnung.xml", "ZUGFeRD-invoice.xml",   # note the capitalisation
)


def find_invoice_xml(pdf_bytes: bytes) -> dict | None:
    """
    A PDF can carry files inside it. Business invoices increasingly carry the
    whole invoice as machine-readable XML — Germany made businesses legally
    able to receive these from January 2025, and confirmed an email address
    is sufficient.

    POC-grade detection: look for the filenames in the raw PDF. Production
    uses the factur-x library, which reads the embedded-file table properly.
    """
    for name in INVOICE_XML_NAMES:
        if name.encode() in pdf_bytes:
            return {"kind": "invoice_xml", "filename": name,
                    "note": "structured invoice data present — parse with factur-x"}
    return None


# ─────────────── half two: layouts we work out ourselves ───────────────

TAG = re.compile(r"<\s*([a-zA-Z0-9]+)")


def structure_fingerprint(html: str) -> str:
    """
    Fingerprint the SHAPE of an email with all the words removed.

    Two K-Electric bills have identical structure and different numbers, so
    identical fingerprints. A redesign produces a different fingerprint, the
    stored layout is not applied at all, and the email falls through to the
    normal path. That is why a big redesign is safe automatically.

    Production uses MinHash (datasketch) so near-matches group too.
    """
    import hashlib
    tags = TAG.findall(html or "")
    return hashlib.sha1(">".join(tags).encode()).hexdigest()[:16]


def validate_extraction(fields: dict, required: list[str],
                        history: dict | None = None) -> tuple[bool, str]:
    """
    ⚠️ All fields or none.

    A missing required field discards the ENTIRE extraction, not just that
    field — whatever moved may have moved more than one thing.

    Then plausibility: not "is something there" but "does it look right".
    "K-Electric is never PKR 12345" catches the account number appearing
    where the amount used to be.
    """
    missing = [f for f in required if not fields.get(f)]
    if missing:
        return False, f"missing {', '.join(missing)} — discarding the whole extraction"

    amount = fields.get("amount")
    if amount is not None and history and history.get("amount_range"):
        lo, hi = history["amount_range"]
        if not (lo * 0.2 <= amount <= hi * 5):
            return False, f"amount {amount} is far outside this sender's usual range"

    return True, "ok"


def extract(attachments: list[dict], html: str = "") -> dict:
    """
    Everything this stage found. `attachments` carries a 'bytes' key when the
    caller has fetched the content.
    """
    found = {"meetings": [], "passes": [], "invoices": [],
             "fingerprint": structure_fingerprint(html) if html else None,
             "used_model": False}

    for a in attachments:
        name = (a.get("name") or "").lower()
        ctype = (a.get("type") or "").lower()
        blob = a.get("bytes")
        if not blob:
            continue
        if "calendar" in ctype or name.endswith(".ics"):
            found["meetings"].extend(read_calendar(blob))
        elif name.endswith(".pkpass") or "pkpass" in ctype:
            p = read_wallet_pass(blob)
            if p:
                found["passes"].append(p)
        elif name.endswith(".pdf") or "pdf" in ctype:
            inv = find_invoice_xml(blob)
            if inv:
                found["invoices"].append(inv)

    found["hit"] = bool(found["meetings"] or found["passes"] or found["invoices"])
    return found
