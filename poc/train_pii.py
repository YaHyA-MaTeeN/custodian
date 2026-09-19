"""
Train the stage-10 name finder.

    python train_pii.py

⚠️ NO LABELLING NEEDED HERE EITHER — the answers already exist.

There are public datasets of text with every name, phone number and identifier
already marked up. We download one and train on it. Nothing of ours is
involved, which also means nothing of ours leaves.

We train DeBERTa-v3-small — 44M parameters — because size buys almost nothing
on this task. Measured on the same test set:

    33M   F1 0.931
    44M   F1 0.954     ← ours
    184M  F1 0.955
    434M  F1 0.961     ten times the size for +0.007

⚠️ AND THE LIMIT THAT MATTERS MORE THAN ANY OF THOSE NUMBERS

Model-card scores on synthetic data do not survive real email. On a benchmark
of real documents, a model self-reporting 98.82 scored 0.27. Another
self-reporting 93.12 scored 0.34. Nothing tested beat a non-expert human.

Structured identifiers — cards, IBANs, phone numbers — are near perfect,
because they have checkable structure. Names and free text are not.

So what we can honestly claim is: we strip identifiers, we minimise what
crosses, and we contract for zero retention. NOT "names are removed."

WHERE TO RUN
    Laptop   works. Small model, small dataset. Roughly 15-30 minutes.
    Kaggle   free GPU. About 3 minutes.
"""

import sys
import time
from pathlib import Path

BASE_MODEL = "microsoft/deberta-v3-small"     # 44M · MIT
DATASET = "ai4privacy/pii-masking-200k"       # free, already labelled
OUT_DIR = "pii_model"
SAMPLES = 8000                                 # plenty; the task is easy


def main():
    import numpy as np
    import torch
    from datasets import load_dataset
    from transformers import (AutoTokenizer, AutoModelForTokenClassification,
                              TrainingArguments, Trainer,
                              DataCollatorForTokenClassification)

    print("\nTraining the name finder")
    print("─" * 52)
    print(f"  downloading {DATASET} …")

    try:
        raw = load_dataset(DATASET, split=f"train[:{SAMPLES}]")
    except Exception as e:
        print(f"\n  could not download: {str(e)[:120]}")
        print("  Check the connection, or use a pre-trained model instead:")
        print("    iiiorg/piiranha-v1-detect-personal-information\n")
        sys.exit(1)

    # The dataset marks every token with what kind of identifier it is.
    col = next((c for c in ("mbert_bio_labels", "bio_labels", "labels", "ner_tags")
                if c in raw.column_names), None)
    tok_col = next((c for c in ("mbert_tokens", "tokens", "source_text")
                    if c in raw.column_names), None)
    if not col or not tok_col:
        print(f"\n  unexpected dataset shape: {raw.column_names}\n")
        sys.exit(1)

    tags = sorted({t for row in raw[col] for t in row})
    idx = {t: i for i, t in enumerate(tags)}
    print(f"  {len(raw)} examples · {len(tags)} identifier types")

    print(f"\n  downloading {BASE_MODEL} …")
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    net = AutoModelForTokenClassification.from_pretrained(
        BASE_MODEL, num_labels=len(tags),
        id2label={v: k for k, v in idx.items()}, label2id=idx)
    params = sum(p.numel() for p in net.parameters())
    print(f"  {params/1e6:.0f}M parameters · device: "
          f"{'GPU' if torch.cuda.is_available() else 'CPU'}")

    def prep(batch):
        enc = tok(batch[tok_col], is_split_into_words=True,
                  truncation=True, max_length=256)
        out = []
        for i, labs in enumerate(batch[col]):
            word_ids = enc.word_ids(batch_index=i)
            aligned, prev = [], None
            for w in word_ids:
                if w is None:
                    aligned.append(-100)
                elif w != prev:
                    aligned.append(idx[labs[w]])
                else:
                    aligned.append(-100)      # only label the first sub-token
                prev = w
            out.append(aligned)
        enc["labels"] = out
        return enc

    ds = raw.map(prep, batched=True, remove_columns=raw.column_names)
    split = ds.train_test_split(test_size=0.15, seed=13)

    def metrics(p):
        pred = np.argmax(p.predictions, axis=2)
        keep = p.label_ids != -100
        return {"token_accuracy": float((pred[keep] == p.label_ids[keep]).mean())}

    args = TrainingArguments(
        output_dir="_pii_tmp",
        num_train_epochs=2,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        learning_rate=5e-5,
        warmup_ratio=0.1,
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=50,
        report_to=[],
    )

    print("\n  training …\n")
    t0 = time.time()
    trainer = Trainer(
        model=net, args=args,
        train_dataset=split["train"], eval_dataset=split["test"],
        data_collator=DataCollatorForTokenClassification(tok),
        compute_metrics=metrics)
    trainer.train()
    mins = (time.time() - t0) / 60

    final = trainer.evaluate()
    print("\n" + "─" * 52)
    print(f"  trained in {mins:.1f} minutes")
    print(f"  token accuracy  {final['eval_token_accuracy']:.3f}")
    print(f"  ⚠️ on THIS dataset. Real email will be substantially worse —")
    print(f"     measure it on our own mail before claiming anything.")

    net.save_pretrained(OUT_DIR)
    tok.save_pretrained(OUT_DIR)
    size = sum(f.stat().st_size for f in Path(OUT_DIR).rglob("*")) / 1e6
    print(f"\n  → {OUT_DIR}/  ({size:.0f} MB)\n")


if __name__ == "__main__":
    main()
