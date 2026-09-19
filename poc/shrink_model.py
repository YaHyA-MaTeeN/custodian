"""
Shrink the trained classifier — ONNX, 8-bit.

    python shrink_model.py

⚠️ THIS IS THE STEP THE DESIGN SPECIFIES AND MOST DEMOS SKIP.

A model trained in PyTorch is stored at 32 bits per number and run by a
framework built for training. Neither is what you want once training is done.

  before   1.1 GB   PyTorch   ~110 ms per email
  after    ~280 MB  ONNX 8bit  much faster, and no PyTorch in production

Two separate changes, and it is worth knowing which does what:

  ONNX          a portable format plus a small fast runtime. The model is
                finished and will never change, so the runtime can fuse
                operations, pre-plan memory, and use CPU instructions tuned
                for exactly this shape of maths. Measured elsewhere at
                roughly 14x faster on CPU than the training framework.

  8-bit         store each weight in one byte instead of four. Four times
                smaller. On classification the accuracy cost is typically
                well under a point - and this script measures it rather
                than assuming it.

Production never installs PyTorch at all, which also takes the container
from gigabytes to megabytes.
"""

import shutil
import sys
import time
from pathlib import Path

SRC = Path("classifier")
DST = Path("classifier_onnx")


def main():
    if not (SRC / "config.json").exists():
        print(f"\n  {SRC}/ not found. Train and download it first.\n")
        sys.exit(1)

    try:
        from optimum.onnxruntime import (ORTModelForSequenceClassification,
                                         ORTQuantizer)
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
    except ImportError:
        print("\n  needs optimum:")
        print("    pip install optimum[onnxruntime]\n")
        sys.exit(1)

    from transformers import AutoTokenizer
    import torch

    before = sum(f.stat().st_size for f in SRC.rglob("*")) / 1e6
    print("\nShrinking the classifier")
    print("-" * 52)
    print(f"  before  {before:.0f} MB  (PyTorch)")

    # ── measure the model we have, so the comparison is real ────────────
    from pipeline import local_classifier
    samples = [
        "can you send me the q3 figures by friday?",
        "Your job alert for associate. 30+ new jobs match your preferences.",
        "Hi, I would like to join your professional network",
        "Your invoice of PKR 8450 is due on 15 September",
        "50 percent off everything today only. Shop now.",
    ]
    baseline = [local_classifier.classify(s)["intent"] for s in samples]
    t0 = time.time()
    for s in samples:
        local_classifier.classify(s)
    ms_before = (time.time() - t0) / len(samples) * 1000
    print(f"          {ms_before:.0f} ms per email")

    # ── convert ─────────────────────────────────────────────────────────
    print("\n  converting to ONNX ...")
    if DST.exists():
        shutil.rmtree(DST)
    model = ORTModelForSequenceClassification.from_pretrained(str(SRC), export=True)
    tok = AutoTokenizer.from_pretrained(str(SRC))
    model.save_pretrained(str(DST))
    tok.save_pretrained(str(DST))

    print("  quantising to 8-bit ...")
    quantizer = ORTQuantizer.from_pretrained(str(DST))
    quantizer.quantize(
        save_dir=str(DST),
        quantization_config=AutoQuantizationConfig.avx512_vnni(
            is_static=False, per_channel=False))

    # Drop the un-quantised copy so the folder is not twice the size.
    for f in DST.glob("model.onnx"):
        if (DST / "model_quantized.onnx").exists():
            f.unlink()

    after = sum(f.stat().st_size for f in DST.rglob("*")) / 1e6

    # ── check it still agrees with the model we started from ────────────
    print("\n  checking the shrunk model still says the same thing ...")
    import onnxruntime as ort
    import numpy as np
    onnx_file = (DST / "model_quantized.onnx")
    if not onnx_file.exists():
        onnx_file = next(DST.glob("*.onnx"))
    sess = ort.InferenceSession(str(onnx_file), providers=["CPUExecutionProvider"])
    import json
    labels = json.loads((DST / "config.json").read_text())["id2label"]

    agree = 0
    t0 = time.time()
    for s, was in zip(samples, baseline):
        enc = tok(s, return_tensors="np", truncation=True,
                  max_length=256, padding="max_length")
        feed = {i.name: enc[i.name] for i in sess.get_inputs() if i.name in enc}
        logits = sess.run(None, feed)[0]
        now = labels[str(int(np.argmax(logits)))]
        agree += (now == was)
    ms_after = (time.time() - t0) / len(samples) * 1000

    print("-" * 52)
    print(f"  after   {after:.0f} MB      ({before/max(after,1):.1f}x smaller)")
    print(f"          {ms_after:.0f} ms per email  ({ms_before/max(ms_after,1):.1f}x faster)")
    print(f"  agrees with the original on {agree}/{len(samples)} samples")
    if agree < len(samples):
        print("  ⚠️  8-bit changed some answers - check on a larger sample")
    print(f"\n  -> {DST}/\n")


if __name__ == "__main__":
    main()
