# ═══════════════════════════════════════════════════════════════════════
#  Custodian — train the stage-10 name finder on Kaggle's free GPU
#
#  SETUP
#    1. New Notebook  ->  Accelerator: GPU T4 x2  (NOT P100)
#    2. Paste this whole file into one cell
#    3. Run All   (~3 minutes)
#    4. Output -> download pii_model.zip -> unzip into c:\mob_ai\poc\pii_model\
#
#  ⚠️ NOTHING OF YOURS IS UPLOADED. This trains on a free public dataset —
#  200,000 pieces of text with every name and identifier already marked up.
#  No mailbox involved, so nothing of ours leaves.
# ═══════════════════════════════════════════════════════════════════════

import os, shutil, time
os.environ["CUDA_VISIBLE_DEVICES"] = "0"      # one card, before torch loads

import numpy as np
import torch

# ⚠️ XLM-RoBERTa, not DeBERTa-v3.
#
# DeBERTa-v3 diverged twice on this project - once on the classifier and once
# here. Both times it trained for an epoch and then the loss went to NaN,
# which saves silently: the file looks fine, loads without complaint, and
# predicts the same label for every single token.
#
# If a trained model gives one answer for everything, check the weights for
# NaN before assuming it needs more data.
BASE_MODEL = "xlm-roberta-base"               # MIT · multilingual · stable
DATASET    = "ai4privacy/pii-masking-200k"
OUT_DIR    = "/kaggle/working/pii_model"
# ⚠️ SIZED FOR A PROOF OF CONCEPT, NOT FOR PRODUCTION.
#
# 20,000 examples at 256 tokens for 3 epochs is about ten times the compute
# of what is below, and took nearly half an hour on a shared GPU. The point
# here is to show a trained model works, so this trades accuracy for a run
# that finishes in a few minutes. Raise all three for a real one.
SAMPLES    = 6000
MAX_LEN    = 128

# ⚠️ SIZE BUYS ALMOST NOTHING ON THIS TASK
#
# Measured on the same test set:
#     33M   F1 0.931
#     44M   F1 0.954
#    184M   F1 0.955
#    434M   F1 0.961   ten times the parameters for +0.007
#
# Structured identifiers - cards, IBANs, phone numbers - are near perfect at
# any size because they have checkable structure. Names are the hard part, and
# size does not fix that.

print(f"device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

from datasets import load_dataset
from transformers import (AutoTokenizer, AutoModelForTokenClassification,
                          TrainingArguments, Trainer,
                          DataCollatorForTokenClassification)

print(f"\ndownloading {DATASET} ...")
raw = load_dataset(DATASET, split=f"train[:{SAMPLES}]")

# Column names vary between versions of this dataset, so find them rather
# than hard-coding. Right now they are mbert_text_tokens / mbert_bio_labels.
label_col = next((c for c in raw.column_names
                  if "label" in c and "span" not in c), None)
token_col = next((c for c in raw.column_names if "token" in c), None)
if not label_col or not token_col:
    raise SystemExit(f"unexpected dataset shape: {raw.column_names}")
print(f"tokens in '{token_col}' · labels in '{label_col}'")

tags = sorted({t for row in raw[label_col] for t in row})
idx = {t: i for i, t in enumerate(tags)}
print(f"{len(raw)} examples · {len(tags)} identifier types")

tok = AutoTokenizer.from_pretrained(BASE_MODEL)
net = AutoModelForTokenClassification.from_pretrained(
    BASE_MODEL, num_labels=len(tags),
    id2label={v: k for k, v in idx.items()}, label2id=idx)
print(f"{sum(p.numel() for p in net.parameters())/1e6:.0f}M parameters")


def prep(batch):
    enc = tok(batch[token_col], is_split_into_words=True,
              truncation=True, max_length=MAX_LEN)
    out = []
    for i, labs in enumerate(batch[label_col]):
        word_ids = enc.word_ids(batch_index=i)
        aligned, prev = [], None
        for w in word_ids:
            if w is None:
                aligned.append(-100)
            elif w != prev:
                aligned.append(idx[labs[w]])
            else:
                aligned.append(-100)      # label only the first sub-token
            prev = w
        out.append(aligned)
    enc["labels"] = out
    return enc


ds = raw.map(prep, batched=True, remove_columns=raw.column_names)
split = ds.train_test_split(test_size=0.15, seed=13)
print(f"train {len(split['train'])} · test {len(split['test'])}")


def metrics(p):
    pred = np.argmax(p.predictions, axis=2)
    keep = p.label_ids != -100
    # Overall token accuracy is flattered by the huge number of "not an
    # identifier" tokens, so report accuracy on the identifier tokens too.
    is_entity = keep & (p.label_ids != idx.get("O", -1))
    return {
        "token_accuracy": float((pred[keep] == p.label_ids[keep]).mean()),
        "entity_accuracy": float((pred[is_entity] == p.label_ids[is_entity]).mean())
        if is_entity.any() else 0.0,
    }


import inspect
accepted = set(inspect.signature(TrainingArguments.__init__).parameters)
wanted = {
    "output_dir": "/kaggle/working/_tmp",
    "num_train_epochs": 2,
    "per_device_train_batch_size": 64,
    "per_device_eval_batch_size": 64,
    "learning_rate": 2e-5,     # lower - divergence is the risk, not slow learning
    "warmup_steps": 40,
    "max_grad_norm": 1.0,
    "weight_decay": 0.01,
    "eval_strategy": "epoch",
    "save_strategy": "no",
    "logging_steps": 50,
    "fp16": False,          # same DataParallel/fp16 clash as the classifier
    "report_to": [],
    "seed": 13,
}
args = TrainingArguments(**{k: v for k, v in wanted.items() if k in accepted})

print("\ntraining ...\n")
t0 = time.time()
trainer = Trainer(model=net, args=args,
                  train_dataset=split["train"], eval_dataset=split["test"],
                  data_collator=DataCollatorForTokenClassification(tok),
                  compute_metrics=metrics)
trainer.train()
mins = (time.time() - t0) / 60

final = trainer.evaluate()
print("\n" + "=" * 56)
print(f"  trained in {mins:.1f} minutes")
print(f"  token accuracy   {final['eval_token_accuracy']:.3f}")
print(f"  on identifiers   {final['eval_entity_accuracy']:.3f}   <- the one that matters")
print("=" * 56)

# ⚠️ THAT NUMBER IS ON THIS DATASET, NOT ON REAL EMAIL.
#
# On a benchmark of real documents, a model self-reporting 98.82 scored 0.27.
# Another self-reporting 93.12 scored 0.34. Nothing tested beat a non-expert
# human at 0.77.
#
# So what we can honestly claim is: we strip identifiers, we minimise what
# crosses, and we contract for zero retention. NOT "names are removed."
# Measure it on our own mail before saying anything stronger.

# ⚠️ CHECK THE MODEL IS ALIVE BEFORE SAVING IT.
#
# A diverged model saves without complaint and loads without complaint. The
# only symptom is that it gives the same answer for everything. One line here
# would have caught the DeBERTa failure immediately instead of after a
# download, an unzip and a puzzled ten minutes.
bad = [n for n, p in net.named_parameters() if not torch.isfinite(p).all()]
if bad:
    raise SystemExit(
        f"\nTraining diverged - {len(bad)} tensors contain NaN or inf.\n"
        f"  first: {bad[0]}\n"
        "  Lower the learning rate or check the data. NOT saving a dead model.")

# A second check: does it actually predict more than one label?
sample = trainer.predict(split["test"].select(range(min(64, len(split["test"])))))
distinct = len(set(np.argmax(sample.predictions, axis=2).ravel().tolist()))
print(f"\n  sanity: predicts {distinct} distinct labels across 64 samples")
if distinct < 2:
    raise SystemExit("  it predicts ONE label for everything - not saving.")

net.save_pretrained(OUT_DIR)
tok.save_pretrained(OUT_DIR)
shutil.make_archive("/kaggle/working/pii_model", "zip", OUT_DIR)
print(f"\npii_model.zip  ({os.path.getsize('/kaggle/working/pii_model.zip')/1e6:.0f} MB)")
print("Output -> download -> unzip into c:\\mob_ai\\poc\\pii_model\\")
