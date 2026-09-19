"""
Train the stage-8 classifier — our own model, on our own mailbox.

    python run.py                        # scan the mailbox first
    python train_classifier.py label     # step 1: Gemini writes the answers
    python train_classifier.py train     # step 2: our small model learns them

⚠️ HOW WE GET TRAINING DATA WITHOUT LABELLING ANYTHING BY HAND

The obvious problem: to fine-tune a small model you need a few hundred emails
with correct labels, and reading them yourself is days of work.

The way round it is called DISTILLATION, and it is how this is actually done.
A big model labels the examples; a small model learns from those labels. The
small one ends up doing the same job for free, on our own hardware.

This is not a shortcut invented for a demo. Published work found a large model
beat crowd-workers on annotation quality, exceeded the agreement level of
trained human annotators, and cost under $0.003 per label.

⚠️ AND THE HONEST LIMIT: the small model inherits the big model's mistakes. It
starts as good as its teacher, not better. What improves it past that is real
corrections from real users — which is exactly what the correction loop feeds
back. This gets us a working model on day one instead of day five.

WHERE TO RUN STEP 2
    Laptop      works. 500 examples, CPU, roughly 20-40 minutes.
    Kaggle      free GPU, 30 hours a week. Same job in about 3 minutes.
                Upload labelled.jsonl, run this file, download the folder.
"""

import json
import os
import sys
import time
from pathlib import Path

BASE_MODEL = "microsoft/mdeberta-v3-base"   # 278M · MIT · multilingual
LABELLED = "labelled.jsonl"
OUT_DIR = "classifier"
TARGET = 400          # enough to train on; crossover is 100-1,000

INTENT = ["asking me for something", "proposing something", "promising something",
          "delivering something", "just telling me", "nothing needed"]


# ══════════════════ step 1 — the teacher writes the answers ══════════════════

def label():
    """
    Take emails from the scanned mailbox, ask the teacher what each one is,
    and save the answers.

    ⚠️ TEN EMAILS PER REQUEST, not one.

    A free tier allows roughly 15 requests a minute. One email per request
    means 600 requests and forty minutes of waiting; ten per request means
    60 requests and about two minutes. Same principle as fetching mail in
    bulk rather than one message at a time.
    """
    import time
    from store import Store
    from pipeline.batch_label import label_batch, PER_REQUEST

    if not os.environ.get("GEMINI_API_KEY"):
        print("\n  GEMINI_API_KEY is not set.")
        print("  Free key: https://aistudio.google.com/apikey")
        print('  setx GEMINI_API_KEY "your-key"   then reopen the terminal\n')
        sys.exit(1)

    store = Store()
    rows = store.q("""SELECT provider_id, subject, sender_name, sender
                        FROM messages
                       WHERE subject != '' ORDER BY RANDOM() LIMIT ?""", TARGET * 3)
    if not rows:
        print("  no messages. Run  python run.py  first.\n")
        sys.exit(1)

    done = set()
    if Path(LABELLED).exists():
        with open(LABELLED, encoding="utf-8") as f:
            done = {json.loads(l)["id"] for l in f if l.strip()}
        print(f"  {len(done)} already labelled - continuing from there")

    print(f"\nStep 1 - the teacher labels up to {TARGET} emails")
    print(f"  {PER_REQUEST} per request, so about {TARGET // PER_REQUEST} requests")
    print("-" * 52)

    from connectors.gmail import GmailConnector
    from pipeline import stage02_strip
    conn = GmailConnector()

    # Fetch and strip first, so a slow mailbox does not look like a slow model.
    print("  reading message bodies...")
    pool, seen = [], 0
    for pid, subject, sname, sender in rows:
        if len(pool) + len(done) >= TARGET:
            break
        if pid in done:
            continue
        try:
            text = stage02_strip.strip(conn.fetch_raw(pid))["text"]
        except Exception:
            continue
        if len(text) < 25:
            continue
        pool.append({"id": pid, "subject": subject or "", "sender": sender,
                     "text": text[:2000]})
        seen += 1
        if seen % 25 == 0:
            print(f"\r  {seen} fetched", end="", flush=True)
    print(f"\r  {len(pool)} emails ready to label")

    if not pool:
        print("\n  nothing new to label.\n")
        return

    n, failed = len(done), 0
    with open(LABELLED, "a", encoding="utf-8") as out:
        for i in range(0, len(pool), PER_REQUEST):
            batch = pool[i:i + PER_REQUEST]
            try:
                labels = label_batch(batch)
            except Exception as e:
                print(f"\n  batch failed, waiting: {str(e)[:70]}")
                time.sleep(20)
                failed += 1
                continue

            # A wrong-length reply means the labels could be misaligned.
            # Discard rather than risk poisoning the training data silently.
            if not labels:
                failed += 1
                continue

            for email, lab in zip(batch, labels):
                out.write(json.dumps({
                    "id": email["id"], "subject": email["subject"],
                    "sender": email["sender"], "text": email["text"],
                    "intent": lab["intent"], "topic": lab["topic"],
                }) + "\n")
            out.flush()
            n += len(labels)
            print(f"\r  labelled {n}/{TARGET}   ", end="", flush=True)
            time.sleep(4.5)      # ~13 requests a minute, safely under the cap

    print(f"\n\n  -> {LABELLED}  ({n} examples)")
    if failed:
        print(f"  {failed} batch(es) discarded - a misaligned label is worse than none")

    counts = {}
    for line in open(LABELLED, encoding="utf-8"):
        if line.strip():
            k = json.loads(line)["intent"]
            counts[k] = counts.get(k, 0) + 1
    print("\n  what the teacher found:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {v:>4}  {k}")

    print("\n  Now run:  python train_classifier.py train\n")


# ══════════════════ step 2 — our small model learns them ══════════════════

def train():
    import numpy as np
    import torch
    from datasets import Dataset
    from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                              TrainingArguments, Trainer)
    from sklearn.metrics import f1_score, accuracy_score

    if not Path(LABELLED).exists():
        print(f"\n  {LABELLED} not found. Run:  python train_classifier.py label\n")
        sys.exit(1)

    rows = [json.loads(l) for l in open(LABELLED, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["intent"] in INTENT]
    print(f"\nStep 2 — training our own model on {len(rows)} examples")
    print("─" * 52)

    counts = {i: sum(1 for r in rows if r["intent"] == i) for i in INTENT}
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {v:>4}  {k}")

    present = [i for i in INTENT if counts[i] >= 3]
    if len(present) < 2:
        print("\n  ⚠️  Not enough variety to train on — nearly everything is one class.")
        print("     Label more mail, or use a mailbox with a wider mix.\n")
        sys.exit(0)

    idx = {lab: i for i, lab in enumerate(present)}
    rows = [r for r in rows if r["intent"] in idx]

    # ⚠️ SPLIT BY TIME, not randomly — the file is in the order it was written.
    cut = int(len(rows) * 0.8)
    train_rows, test_rows = rows[:cut], rows[cut:]
    print(f"\n  train {len(train_rows)}  ·  test {len(test_rows)}  "
          f"·  {len(present)} classes")

    print(f"\n  downloading {BASE_MODEL} …")
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    net = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(present),
        id2label={v: k for k, v in idx.items()}, label2id=idx)
    params = sum(p.numel() for p in net.parameters())
    print(f"  {params/1e6:.0f}M parameters · device: "
          f"{'GPU' if torch.cuda.is_available() else 'CPU'}")

    def prep(batch):
        enc = tok(batch["text"], truncation=True, max_length=256, padding="max_length")
        enc["labels"] = [idx[i] for i in batch["intent"]]
        return enc

    ds_tr = Dataset.from_list(train_rows).map(prep, batched=True)
    ds_te = Dataset.from_list(test_rows).map(prep, batched=True)

    def metrics(p):
        pred = np.argmax(p.predictions, axis=1)
        return {"accuracy": accuracy_score(p.label_ids, pred),
                "macro_f1": f1_score(p.label_ids, pred, average="macro", zero_division=0)}

    # transformers 5.x renamed some of these. Build only what this version
    # accepts, so the script survives a library upgrade instead of crashing.
    import inspect
    accepted = set(inspect.signature(TrainingArguments.__init__).parameters)
    wanted = {
        "output_dir": "_train_tmp",
        "num_train_epochs": 5,
        "per_device_train_batch_size": 8,
        "per_device_eval_batch_size": 16,
        "learning_rate": 3e-5,       # small — we are nudging, not rebuilding
        "warmup_steps": 20,
        "weight_decay": 0.01,
        "eval_strategy": "epoch",
        "save_strategy": "no",
        "logging_steps": 10,
        "report_to": [],
        "seed": 13,
    }
    args = TrainingArguments(**{k: v for k, v in wanted.items() if k in accepted})

    print("\n  training …\n")
    t0 = time.time()
    trainer = Trainer(model=net, args=args, train_dataset=ds_tr,
                      eval_dataset=ds_te, compute_metrics=metrics)
    trainer.train()
    mins = (time.time() - t0) / 60

    final = trainer.evaluate()
    print("\n" + "─" * 52)
    print(f"  trained in {mins:.1f} minutes")
    print(f"  accuracy  {final['eval_accuracy']:.3f}")
    print(f"  macro F1  {final['eval_macro_f1']:.3f}   ← the one that matters")

    net.save_pretrained(OUT_DIR)
    tok.save_pretrained(OUT_DIR)
    size = sum(f.stat().st_size for f in Path(OUT_DIR).rglob("*")) / 1e6
    print(f"\n  → {OUT_DIR}/  ({size:.0f} MB)")
    print("\n  This model is ours. It runs on our own CPU, costs nothing per")
    print("  email, and never sends anything outside. Convert it to ONNX to")
    print("  make it roughly 14x faster.\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "label":
        label()
    elif cmd == "train":
        train()
    else:
        print(__doc__)
