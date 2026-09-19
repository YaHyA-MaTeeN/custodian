# ═══════════════════════════════════════════════════════════════════════
#  Custodian — train the stage-8 classifier on Kaggle's free GPU
#
#  SETUP (once, ~5 minutes)
#    1. kaggle.com  ->  Create  ->  New Notebook
#    2. Right panel  ->  Session options  ->  Accelerator  ->  GPU T4 x2
#       (T4, NOT P100 - the P100 is too old for Kaggle's PyTorch build)
#    3. Right panel  ->  Input  ->  Upload  ->  New Dataset
#       drag in  labelled.jsonl  ->  name it  custodian-labels  ->  Create
#    4. Paste this whole file into one cell
#    5. Run All
#    6. When it finishes: right panel -> Output -> download classifier.zip
#
#  Then on your laptop: unzip it into  c:\mob_ai\poc\classifier\
# ═══════════════════════════════════════════════════════════════════════

import glob, inspect, json, os, shutil, time

# ⚠️ MUST come before torch is imported.
#
# Kaggle's "GPU T4 x2" gives two cards, and the Trainer wraps the model in
# DataParallel to use both. For 199 examples that gains nothing and causes
# two separate failures. Restricting to one card avoids both.
#
# Use the T4 accelerator, NOT P100 — the P100 is compute capability 6.0 and
# Kaggle's PyTorch build only supports 7.0 and above. It will download, load,
# and then fail with "no kernel image is available for execution".
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import numpy as np

# XLM-RoBERTa, not mDeBERTa-v3.
#
# ⚠️ mDeBERTa-v3 is known to be unstable when fine-tuned: on this data it
# trained fine for one epoch (0.70 accuracy) then the loss went to NaN and
# every prediction collapsed to one class. XLM-R is the same size, equally
# multilingual, and far better behaved. It was also the original
# recommendation in the product plan.
BASE_MODEL = "xlm-roberta-base"               # 278M · MIT · multilingual
OUT_DIR    = "/kaggle/working/classifier"
MAX_LEN    = 256
EPOCHS     = 5

# ⚠️ BINARY = the distinction the pipeline actually uses.
#
# stage09_gate.py only ever asks one thing of this label:
#     is_a_request = intent in {"asking me for something", "proposing something"}
# The four-way split is collapsed to that the moment it arrives.
#
# So training four classes on 199 examples — two of them with 5 and 10
# examples — spends most of the data learning a distinction nothing
# downstream reads, and produces a model that is unsure about everything.
#
# Binary turns those into a 56 vs 143 split, which is genuinely learnable,
# and loses nothing the system consumes.
BINARY     = True

INTENT = ["asking me for something", "proposing something", "promising something",
          "delivering something", "just telling me", "nothing needed"]

# ── find the uploaded file, whatever the dataset ended up being called ──
hits = glob.glob("/kaggle/input/**/labelled.jsonl", recursive=True)
if not hits:
    raise SystemExit(
        "labelled.jsonl not found.\n"
        "  Right panel -> Input -> Upload -> New Dataset -> drag labelled.jsonl in.")
LABELLED = hits[0]
print(f"data: {LABELLED}")

import torch
print(f"device: {'GPU - ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU (turn the accelerator on!)'}")

from datasets import Dataset
from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                          TrainingArguments, Trainer)
from sklearn.metrics import f1_score, accuracy_score, classification_report

# ── load ───────────────────────────────────────────────────────────────
rows = [json.loads(l) for l in open(LABELLED, encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("intent") in INTENT]

if BINARY:
    REQUESTING = {"asking me for something", "proposing something"}
    for r in rows:
        r["intent"] = ("needs a response from you" if r["intent"] in REQUESTING
                       else "no response needed")
    INTENT = ["needs a response from you", "no response needed"]
    print("\nbinary mode — training the distinction stage 9 actually uses")

print(f"\n{len(rows)} examples")

counts = {i: sum(1 for r in rows if r["intent"] == i) for i in INTENT}
for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    if v:
        print(f"  {v:>4}  {k}")

present = [i for i in INTENT if counts[i] >= 3]
if len(present) < 2:
    raise SystemExit("not enough class variety to train on")
idx  = {lab: i for i, lab in enumerate(present)}
rows = [r for r in rows if r["intent"] in idx]

# ⚠️ SPLIT BY TIME, NOT RANDOMLY.
# A random split lets the model see later mail while training and be tested on
# earlier mail. That is cheating, and it makes you confident in something that
# does not work. Train on the past, test on the future.
cut = int(len(rows) * 0.8)
train_rows, test_rows = rows[:cut], rows[cut:]
print(f"\ntrain {len(train_rows)} · test {len(test_rows)} · {len(present)} classes")

# ── model ──────────────────────────────────────────────────────────────
tok = AutoTokenizer.from_pretrained(BASE_MODEL)
net = AutoModelForSequenceClassification.from_pretrained(
    BASE_MODEL, num_labels=len(present),
    id2label={v: k for k, v in idx.items()}, label2id=idx)
print(f"\n{sum(p.numel() for p in net.parameters())/1e6:.0f}M parameters")

def prep(b):
    enc = tok(b["text"], truncation=True, max_length=MAX_LEN, padding="max_length")
    enc["labels"] = [idx[i] for i in b["intent"]]
    return enc

ds_tr = Dataset.from_list(train_rows).map(prep, batched=True)
ds_te = Dataset.from_list(test_rows).map(prep, batched=True)

def metrics(p):
    pred = np.argmax(p.predictions, axis=1)
    return {"accuracy": accuracy_score(p.label_ids, pred),
            "macro_f1": f1_score(p.label_ids, pred, average="macro", zero_division=0)}

# Build only the arguments this version of transformers accepts, so a library
# upgrade does not break the script.
accepted = set(inspect.signature(TrainingArguments.__init__).parameters)
wanted = {
    "output_dir": "/kaggle/working/_tmp",
    "num_train_epochs": EPOCHS,
    "per_device_train_batch_size": 16,
    "per_device_eval_batch_size": 32,
    "learning_rate": 2e-5,        # lower - divergence is the risk, not slow learning
    "warmup_steps": 15,
    "max_grad_norm": 1.0,         # clip gradients - the other half of not diverging
    "weight_decay": 0.01,
    "eval_strategy": "epoch",
    "save_strategy": "no",
    "logging_steps": 10,
    # ⚠️ Leave half precision OFF.
    # Kaggle's "GPU T4 x2" wraps the model in DataParallel, and that combined
    # with fp16 raises "Attempting to unscale FP16 gradients". With only a
    # couple of hundred examples, fp16 saves nothing worth having.
    "fp16": False,
    "report_to": [],
    "seed": 13,
}
args = TrainingArguments(**{k: v for k, v in wanted.items() if k in accepted})

# ⚠️ CLASS WEIGHTING.
#
# 138 of 199 examples are one class. Without this the model learns the only
# strategy that minimises loss on such data: always guess the common one. It
# would score 0.69 accuracy and be useless — exactly the trap the reply gate
# has with its 92% negatives.
#
# Weighting each class by the inverse of how often it appears makes a mistake
# on a rare class cost as much as several mistakes on a common one.
freq = np.array([counts[c] for c in present], dtype=np.float32)
weights = torch.tensor(len(rows) / (len(present) * freq), dtype=torch.float32)
print("\nclass weights (rare classes count for more):")
for c, w in zip(present, weights.tolist()):
    print(f"  {w:5.2f}x  {c}")


class WeightedTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False, **kw):
        labels = inputs.pop("labels")
        out = model(**inputs)
        loss = torch.nn.functional.cross_entropy(
            out.logits.view(-1, len(present)), labels.view(-1),
            weight=weights.to(out.logits.device))
        return (loss, out) if return_outputs else loss


print("\ntraining...\n")
t0 = time.time()
trainer = WeightedTrainer(model=net, args=args, train_dataset=ds_tr,
                          eval_dataset=ds_te, compute_metrics=metrics)
trainer.train()
mins = (time.time() - t0) / 60

# ── results ────────────────────────────────────────────────────────────
final = trainer.evaluate()
print("\n" + "=" * 56)
print(f"  trained in {mins:.1f} minutes")
print(f"  accuracy  {final['eval_accuracy']:.3f}")
print(f"  macro F1  {final['eval_macro_f1']:.3f}   <- the one that matters")
print("=" * 56)

# ⚠️ Macro F1, not accuracy. With one class at 69% of the data, a model that
# always guesses that class scores 0.69 accuracy and is useless. Macro F1
# weights every class equally, so it exposes exactly that failure.
pred = np.argmax(trainer.predict(ds_te).predictions, axis=1)
true = np.array([idx[r["intent"]] for r in test_rows])
print("\nper class:\n")
print(classification_report(true, pred, labels=list(range(len(present))),
                            target_names=present, zero_division=0))

# ── save, shrunk for download ──────────────────────────────────────────
#
# ⚠️ Saved at HALF PRECISION.
#
# The weights were trained at 32 bits per number. Storing them at 16 halves
# the file — 1.1 GB becomes ~550 MB — and for running a finished model it
# costs nothing measurable in accuracy. We are not training any more, so the
# extra precision has no job left to do.
#
# The design goes one step further in production: convert to ONNX and 8 bits,
# which lands around 280 MB and runs roughly 14x faster on CPU. That is done
# on the laptop, after download, by shrink_model.py.
net = net.half()
net.save_pretrained(OUT_DIR, safe_serialization=True)
tok.save_pretrained(OUT_DIR)

shutil.make_archive("/kaggle/working/classifier", "zip", OUT_DIR)
size = os.path.getsize("/kaggle/working/classifier.zip") / 1e6
print(f"\nclassifier.zip  ({size:.0f} MB, half precision)")
print("Right panel -> Output -> download -> unzip into c:\\mob_ai\\poc\\classifier\\")
print("Then on the laptop:  python shrink_model.py   (ONNX + 8-bit, ~280 MB, much faster)")
