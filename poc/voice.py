"""
UC-42 — See how the system thinks you write, and correct it.

    python voice.py                                  # the recipe, in plain words
    python voice.py --set sign_off "Best,"           # your setting beats what we learned
    python voice.py --set greeting "Hi" --for client.com   # a different voice for one group
    python voice.py --reset                          # back to what we learned
    python voice.py --sample                         # a sample reply in the current voice

⚠️ IN PLAIN WORDS, NEVER SCORES (BR-162). "You open with Hi, sign off Best,
usually write three or four sentences, use contractions." Nothing here is a
number the Owner has to interpret.

⚠️ AN EXPLICIT SETTING ALWAYS WINS (BR-163). Learning carries on from the
Sent folder and never overrides what the Owner set. If their recent mail
does it differently, the setting stays and we say so once.

⚠️ NO PAST EMAIL IS SHOWN (BR-165). We keep the recipe, not the mail it came
from. The sample is written on placeholder text, never a real name.
"""

import os
import sys

from pipeline.stage19_voice import StyleStore, describe

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

FIELDS = ("greeting", "sign_off", "length", "formality", "contractions")
OPTIONS = {
    "greeting":     ("Hi", "Hello", "Dear", "Hey", "none"),
    "sign_off":     ("Best,", "Thanks,", "Regards,", "Cheers,", "Kind regards,", "none"),
    "length":       ("short", "medium", "long"),
    "formality":    ("formal", "neutral", "casual"),
    "contractions": ("yes", "no"),
}


def show(st, domain=""):
    p = st.profile(domain)
    who = f" for {domain}" if domain else ""
    print(f"\n{C['b']}Your voice{who}{C['0']}")
    print("─" * 66)
    if not p:
        print(f"  {C['y']}We do not have enough of your sent mail to match your style, so drafts "
              f"use a neutral professional voice.{C['0']}")
        print(f"  {C['dim']}python learn_voice.py reads your Sent folder. Or set it by hand below.{C['0']}\n")
        return
    print(f"  {describe(p)}")
    raw = {k: v for k, v in st.db.execute("SELECT key, value FROM style_profile")}
    setk = [k[4:] for k in raw if k.startswith("set:")]
    if setk:
        print(f"  {C['dim']}you set: {', '.join(setk)} — these stay even if your recent mail differs{C['0']}")
    g = st.groups()
    if g:
        print(f"  {C['dim']}separate voices for: {', '.join(g)}{C['0']}")
    print(f"\n  {C['dim']}change one:  python voice.py --set sign_off \"Best,\"     "
          f"options: {', '.join(FIELDS)}{C['0']}\n")


def sample(st, domain=""):
    """A sample in the current voice, on placeholder text only."""
    p = st.profile(domain)
    try:
        from pipeline import model
        text = model.draft_reply(
            "Hi [PERSON_1], could you send me the revised proposal by Friday? Thanks.",
            "Revised proposal", "[PERSON_1]", [], p)
    except Exception as e:
        text = f"(sample unavailable: {str(e)[:50]})"
    print(f"\n{C['b']}Sample, in this voice{C['0']}\n{C['dim']}{'─'*66}{C['0']}\n{text}\n")


def main():
    st = StyleStore()
    args = sys.argv[1:]
    domain = args[args.index("--for") + 1] if "--for" in args else ""
    if "--set" in args:
        i = args.index("--set")
        field, value = args[i + 1], args[i + 2]
        if field not in FIELDS:
            print(f"\n  fields: {', '.join(FIELDS)}\n"); return
        st.set_field(field, value, domain)
        print(f"\n  {C['g']}saved.{C['0']} From the next draft, {field} = “{value}”"
              f"{' for ' + domain if domain else ''}. This stays even if your recent emails differ.\n")
        return
    if "--reset" in args:
        n = st.reset(domain)
        print(f"\n  reset {n} setting(s) to what we learned.\n"); return
    if "--sample" in args:
        return sample(st, domain)
    show(st, domain)


if __name__ == "__main__":
    main()
