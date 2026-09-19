"""
Dump emails for hand-labelling.

    python dump_for_labelling.py            # 200 emails
    python dump_for_labelling.py 300

Writes to_label.txt — a compact, numbered list of emails to be labelled by
hand rather than by another model.

⚠️ WHY HAND-LABEL AT ALL, WHEN A MODEL CAN DO IT

The classifier is shared across every user, so it is labelled ONCE, ever. That
is different from the reply gate, which is trained per person from data the
mailbox already holds. A one-time job worth doing carefully.

Model-written labels get us started on day one. Careful labels give the model
a better teacher, and every measurement in this area says the same thing: the
quality of the training data matters more than the size of the model.

⚠️ AND THE COST: whoever labels these reads the email content. Keep the dump
local, and delete it when the labelling is done.
"""

import re
import sys
from pathlib import Path

from connectors.gmail import GmailConnector
from pipeline import stage02_strip
from store import Store

OUT = "to_label.txt"
CHARS = 320          # enough to judge intent, short enough to read quickly


def clean(s: str) -> str:
    """One line, no control characters, collapsed whitespace."""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return "".join(c for c in s if c.isprintable())


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 200

    store = Store()
    rows = store.q("""SELECT provider_id, subject, sender_name, sender, bulk
                        FROM messages
                       WHERE subject != ''
                       ORDER BY RANDOM() LIMIT ?""", want * 3)
    if not rows:
        print("  no messages. Run  python run.py  first.\n")
        sys.exit(1)

    # Skip anything already labelled.
    done = set()
    if Path("labelled.jsonl").exists():
        import json
        with open("labelled.jsonl", encoding="utf-8") as f:
            done = {json.loads(l)["id"] for l in f if l.strip()}

    print(f"\nDumping {want} emails for hand-labelling")
    print("-" * 52)

    conn = GmailConnector()
    out, n = [], 0

    for pid, subject, sname, sender, bulk in rows:
        if n >= want:
            break
        if pid in done:
            continue
        try:
            text = stage02_strip.strip(conn.fetch_raw(pid))["text"]
        except Exception:
            continue
        if len(text) < 25:
            continue

        n += 1
        out.append(
            f"[{n}] id={pid} bulk={1 if bulk else 0}\n"
            f"    from: {clean(sname or sender)[:44]}\n"
            f"    subj: {clean(subject)[:90]}\n"
            f"    body: {clean(text)[:CHARS]}\n"
        )
        if n % 20 == 0:
            print(f"\r  {n}/{want}", end="", flush=True)

    Path(OUT).write_text("\n".join(out), encoding="utf-8")
    print(f"\r  {n} emails written")
    print(f"\n  -> {OUT}  ({Path(OUT).stat().st_size / 1024:.0f} KB)")
    print("\n  Paste that file into the chat to have it labelled,")
    print("  then run:  python apply_labels.py\n")


if __name__ == "__main__":
    main()
