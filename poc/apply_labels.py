"""
Turn hand-written labels into training data.

    1.  python dump_for_labelling.py      -> to_label.txt
    2.  paste to_label.txt into the chat, get labels back
    3.  save them as labels.txt
    4.  python apply_labels.py            -> labelled.jsonl

labels.txt is one line per email, in the same order as the dump:

    1  asking me for something | work
    2  just telling me | newsletter or marketing
    3  delivering something | shopping or order

⚠️ The number must match the [n] in the dump. If a line is missing or out of
order the email is skipped rather than mislabelled — a label attached to the
wrong email poisons the training set silently, which is worse than having
fewer examples.
"""

import json
import re
import sys
from pathlib import Path

DUMP = "to_label.txt"
LABELS = "labels.txt"
OUT = "labelled.jsonl"

INTENT = ["asking me for something", "proposing something", "promising something",
          "delivering something", "just telling me", "nothing needed"]

TOPIC = ["work", "money or bills", "travel", "appointment or meeting",
         "shopping or order", "personal", "account or security",
         "newsletter or marketing", "other"]


def read_dump() -> dict:
    """{n: {id, subject, text}} from to_label.txt"""
    if not Path(DUMP).exists():
        print(f"\n  {DUMP} not found. Run:  python dump_for_labelling.py\n")
        sys.exit(1)

    out, cur = {}, None
    for line in Path(DUMP).read_text(encoding="utf-8").splitlines():
        head = re.match(r"^\[(\d+)\]\s+id=(\S+)", line)
        if head:
            cur = int(head.group(1))
            out[cur] = {"id": head.group(2), "subject": "", "text": ""}
        elif cur and line.strip().startswith("subj:"):
            out[cur]["subject"] = line.split("subj:", 1)[1].strip()
        elif cur and line.strip().startswith("body:"):
            out[cur]["text"] = line.split("body:", 1)[1].strip()
    return out


def read_labels() -> dict:
    """{n: (intent, topic)} from labels.txt"""
    if not Path(LABELS).exists():
        print(f"\n  {LABELS} not found.")
        print("  Save the labels from the chat as labels.txt, one per line:")
        print("    1  asking me for something | work\n")
        sys.exit(1)

    out, bad = {}, 0
    for line in Path(LABELS).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)[\s.\)]+(.+?)\s*\|\s*(.+)$", line)
        if not m:
            bad += 1
            continue
        n, intent, topic = int(m.group(1)), m.group(2).strip(), m.group(3).strip()
        if intent not in INTENT or topic not in TOPIC:
            bad += 1
            continue
        out[n] = (intent, topic)
    if bad:
        print(f"  {bad} line(s) skipped - unrecognised label or format")
    return out


def main():
    dump = read_dump()
    labels = read_labels()

    print(f"\nApplying labels")
    print("-" * 52)
    print(f"  {len(dump)} emails in the dump")
    print(f"  {len(labels)} labels provided")

    matched = sorted(set(dump) & set(labels))
    missing = sorted(set(dump) - set(labels))
    if missing:
        print(f"  {len(missing)} unlabelled, skipped: {missing[:10]}"
              f"{'...' if len(missing) > 10 else ''}")

    existing = set()
    if Path(OUT).exists():
        with open(OUT, encoding="utf-8") as f:
            existing = {json.loads(l)["id"] for l in f if l.strip()}
        print(f"  {len(existing)} already in {OUT} - not duplicated")

    written = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for n in matched:
            e = dump[n]
            if e["id"] in existing:
                continue
            intent, topic = labels[n]
            f.write(json.dumps({
                "id": e["id"], "subject": e["subject"], "sender": "",
                "text": e["text"], "intent": intent, "topic": topic,
                "labelled_by": "hand",
            }) + "\n")
            written += 1

    print(f"\n  {written} new example(s) written to {OUT}")

    counts = {}
    for line in open(OUT, encoding="utf-8"):
        if line.strip():
            k = json.loads(line)["intent"]
            counts[k] = counts.get(k, 0) + 1
    total = sum(counts.values())
    print(f"\n  {total} examples now, across {len(counts)} classes:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {v:>4}  {k}")

    if total < 100:
        print(f"\n  ⚠️  {total} is thin. The crossover where a fine-tuned small")
        print("     model beats a prompted large one is 100-1,000 examples.")
    print("\n  Now run:  python train_classifier.py train\n")


if __name__ == "__main__":
    main()
