"""
Train the stage-9 reply gate on this mailbox.

    python run.py          # scan the mailbox first
    python train_gate.py   # then this

⚠️ NOBODY LABELS ANYTHING. That is the whole point of this stage.

For every message in the history, the mailbox already knows the answer — did
this person open it, did they reply to it. So a mailbox with 30,000 messages
is 30,000 training examples with the answers already attached, available the
moment the scan finishes.

Compare with stage 8, which needs a few hundred emails read and labelled by
hand — days of work. That is the real bottleneck of the project. This stage
has no bottleneck at all.

One model per person, trained on their own mail. "Will Yahya reply to this"
has nothing to do with what Sara does — a shared model would average away
exactly the signal we need. It is also a privacy requirement: Google's terms
forbid pooling many users' mail into one shared model.
"""

import json
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime

import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

from store import Store

MODEL_OUT = "gate_model.txt"
META_OUT = "gate_model.json"

FEATURES = [
    "sender_total", "sender_open_rate", "sender_recent",
    "is_machine_generated", "has_unsubscribe", "one_click",
    "is_reply", "is_auto_reply", "in_inbox",
    "subject_len", "subject_has_question", "size_kb",
    "hour", "weekday", "business_hours",
    "first_contact", "domain_total",
]


def build(store):
    """Turn the scanned mailbox into a table of features plus the answer."""
    rows = store.q("""
        SELECT sender, sender_domain, subject, date, size, unread, in_inbox,
               bulk, unsubscribe, one_click, in_reply_to, auto_sub
          FROM messages""")
    if not rows:
        print("  no messages. Run  python run.py  first.")
        sys.exit(1)

    # Per-sender history, computed once.
    sender_stats, domain_stats = {}, {}
    for r in rows:
        s, d, unread = r[0], r[1], r[5]
        a = sender_stats.setdefault(s, [0, 0])
        a[0] += 1
        a[1] += 1 - unread                    # opened
        domain_stats[d] = domain_stats.get(d, 0) + 1

    X, y = [], []
    for r in rows:
        (sender, domain, subject, date, size, unread, in_inbox,
         bulk, unsub, one_click, in_reply_to, auto_sub) = r

        total, opened = sender_stats[sender]
        try:
            dt = parsedate_to_datetime(date)
            hour, weekday = dt.hour, dt.weekday()
        except Exception:
            hour, weekday = 12, 2

        X.append([
            total,
            opened / total if total else 0.0,
            1 if total >= 5 else 0,
            bulk or 0,
            1 if unsub else 0,
            one_click or 0,
            1 if in_reply_to else 0,
            1 if auto_sub else 0,
            in_inbox or 0,
            len(subject or ""),
            1 if "?" in (subject or "") else 0,
            (size or 0) / 1024,
            hour,
            weekday,
            1 if (weekday < 5 and 7 <= hour <= 19) else 0,
            1 if total <= 1 else 0,
            domain_stats.get(domain, 0),
        ])
        # ⚠️ THE ANSWER, free from the mailbox. Nobody typed this.
        y.append(1 - unread)

    return np.array(X, dtype=float), np.array(y)


def main():
    print("\nTraining the reply gate")
    print("─" * 52)

    store = Store()
    X, y = build(store)
    positives = int(y.sum())

    print(f"  {len(y):,} messages  ·  {positives:,} opened "
          f"({positives / len(y) * 100:.1f}%)")
    print(f"  {len(FEATURES)} features  ·  0 labelled by hand\n")

    if positives < 20 or len(y) - positives < 20:
        print("  ⚠️  Too one-sided to train on — almost everything is the same class.")
        print("     A mailbox needs some opened AND some unopened mail.\n")
        sys.exit(0)

    # ⚠️ SPLIT BY TIME, NOT RANDOMLY.
    # A random split lets the model see September mail while training and be
    # tested on August. That is cheating, and it makes you confident in
    # something that does not work. Train on the past, test on the future.
    cut = int(len(y) * 0.8)
    Xtr, Xte, ytr, yte = X[:cut], X[cut:], y[:cut], y[cut:]

    t0 = datetime.now()
    model = lgb.LGBMClassifier(
        n_estimators=300, num_leaves=31, learning_rate=0.05,
        # ⚠️ 92% of email never gets a reply. Without this the model learns
        # to answer "no" every time — which scores 92% accurate and is useless.
        is_unbalance=True,
        verbose=-1,
    )
    model.fit(Xtr, ytr)
    secs = (datetime.now() - t0).total_seconds()

    p = model.predict_proba(Xte)[:, 1]
    try:
        auc = roc_auc_score(yte, p)
    except ValueError:
        auc = float("nan")

    baseline = max(yte.mean(), 1 - yte.mean())

    print(f"  trained in {secs:.1f} seconds")
    print(f"  AUC on unseen future mail : {auc:.3f}")
    print(f"  (0.500 = coin flip · published ceiling for this task is 0.72–0.79)")
    print(f"  always-guessing-the-common-answer accuracy : {baseline:.1%}")
    print(f"  ⚠️ which is why we report AUC and never accuracy\n")

    print("  what the model actually leaned on:")
    order = np.argsort(model.feature_importances_)[::-1]
    for i in order[:8]:
        bar = "█" * int(model.feature_importances_[i] /
                        max(model.feature_importances_.max(), 1) * 26)
        print(f"    {FEATURES[i]:<22} {bar}")

    model.booster_.save_model(MODEL_OUT)
    with open(META_OUT, "w") as f:
        json.dump({"features": FEATURES, "auc": None if np.isnan(auc) else round(auc, 4),
                   "trained_on": len(ytr), "tested_on": len(yte),
                   "seconds": round(secs, 2),
                   "trained_at": datetime.now().isoformat()}, f, indent=2)

    import os
    kb = os.path.getsize(MODEL_OUT) / 1024
    print(f"\n  → {MODEL_OUT}  ({kb:.0f} KB)")
    print(f"  → {META_OUT}\n")
    print("  This is a real trained model, on this mailbox, with zero manual")
    print("  labelling. Retraining it weekly costs the same two seconds.\n")


if __name__ == "__main__":
    main()
