"""
Send a mail on the user's behalf — through the real gate, not around it.

    python send_mail.py ferozxdev@gmail.com "Subject here" "what to say"
    python send_mail.py ferozxdev@gmail.com            # asks for the rest
    python send_mail.py --verbatim ...                 # send my exact words

⚠️ THIS IS THE ONLY SCRIPT THAT PUTS MAIL INTO THE WORLD.

It is deliberately built on top of the same stage 13 and stage 14 that the
pipeline uses. It does not have its own shortcut to the send call, because a
second path to sending is a second place the gate can be missed.

WHAT HAPPENS, IN ORDER

  19  your voice        your writing profile + your closest past replies
  11  write it          the model drafts, using that voice
  13  ask you           the draft is shown, hashed, and you type yes
  14  do it             one API call, audited

Type anything that is not an unambiguous yes and nothing is sent. That is the
default, not the exception.
"""

import os
import sys

from connectors.gmail import GmailConnector
from pipeline import stage13_approval

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m",
     "y": "\033[33m", "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")


def line(ch="─", n=70):
    print(C["dim"] + ch * n + C["0"])


def voice():
    """Stage 19 — how this person actually writes."""
    try:
        from pipeline.stage19_voice import StyleStore, describe
        st = StyleStore()
        if st.count() == 0:
            return [], {}, "none stored — run learn_voice.py"
        prof = st.profile()
        return [], prof, describe(prof)
    except Exception as e:
        return [], {}, f"unavailable: {e}"


def write_draft(point: str, subject: str, to: str, profile, examples):
    """
    Stage 11. The model writes; if there is no key, we send what you typed.

    ⚠️ No redaction step here, and that is correct: this text is YOURS. You
    typed it. Stage 10 exists to protect the contents of OTHER people's mail
    before it crosses to a model — there is no incoming email in this path.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        return point, "no key — sending your text unchanged"
    try:
        from pipeline import model
        drafted = model.draft_reply(
            f"Write a short email to {to}. The point of it: {point}",
            subject, to, examples, profile)
        return drafted.strip(), "drafted by the model in your voice"
    except Exception as e:
        return point, f"model unavailable ({str(e)[:40]}) — sending your text"


def main():
    verbatim = "--verbatim" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--verbatim"]
    if not args:
        print(__doc__)
        sys.exit(1)

    to = args[0]
    subject = args[1] if len(args) > 1 else input("  Subject: ").strip()
    point = " ".join(args[2:]) if len(args) > 2 else input("  What do you want to say: ").strip()

    if "@" not in to:
        print(f"\n  {C['r']}'{to}' is not an email address.{C['0']}\n")
        sys.exit(1)

    print(f"\n{C['b']}Sending on your behalf{C['0']}")
    line("═")

    conn = GmailConnector()
    print(f"  from  {conn.account_email()}")
    print(f"  to    {to}")
    print(f"  send permission: "
          f"{C['g'] + 'granted' if conn.supports_send else C['r'] + 'MISSING'}{C['0']}")

    if not conn.supports_send:
        print(f"\n  {C['r']}This connector cannot send. Nothing to do.{C['0']}\n")
        sys.exit(1)

    # ── 19 ────────────────────────────────────────────────────────────
    examples, profile, summary = voice()
    print(f"\n  {C['dim']}19{C['0']} YOUR VOICE      {summary}")

    # ── 11 ────────────────────────────────────────────────────────────
    if verbatim:
        body, how = point, "verbatim — your exact words, no model involved"
    else:
        body, how = write_draft(point, subject, to, profile, examples)
    print(f"  {C['dim']}11{C['0']} WRITE IT        {how}")

    print()
    line("┄")
    print(f"  {C['dim']}To:      {to}{C['0']}")
    print(f"  {C['dim']}Subject: {subject}{C['0']}")
    print()
    for l in body.splitlines():
        print(f"  {C['c']}│{C['0']} {l}")
    line("┄")

    # ── 13 ── the gate ────────────────────────────────────────────────
    ap = stage13_approval.Approval("send", body)
    print(f"\n  {C['dim']}13{C['0']} ASK YOU         draft hashed as "
          f"{C['dim']}{ap.hash}{C['0']} — waiting for an explicit yes")
    print(f"\n  {C['y']}This will actually send. Type yes to send, "
          f"anything else to stop.{C['0']}")

    try:
        answer = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = "no"

    ok, why = ap.grant(answer)
    print(f"     {C['g'] if ok else C['y']}{why}{C['0']}")

    # ── 14 ────────────────────────────────────────────────────────────
    audit = []
    result = stage13_approval.execute(
        conn, "send", provider_id="", draft=body,
        approval=ap if ok else None, audit=audit,
        to=to, subject=subject)

    print(f"  {C['dim']}14{C['0']} DO IT           "
          f"{C['g'] + 'SENT' if result['done'] else C['y'] + 'not sent'}{C['0']}"
          f" — {result['reason']}")

    if result.get("sent_id"):
        print(f"\n  {C['g']}Gmail message id {result['sent_id']}{C['0']}")
        print(f"  {C['dim']}It is in your Sent folder. It cannot be unsent — "
              f"which is exactly why it asked.{C['0']}")
    print()


if __name__ == "__main__":
    main()
