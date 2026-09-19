"""
Custodian, as a conversation. Type sentences, not commands.

    python chat.py

    you > email ferozxdev@gmail.com and ask if he got the report
    you > what's in my inbox
    you > sort my mail
    you > anything from linkedin?
    you > quit

⚠️ WHY THIS IS A SEPARATE PROGRAM FROM THE PIPELINE.

What you type here is an INSTRUCTION. What arrives in an email is DATA. They
are read by different code, and the code that reads instructions is never
handed the contents of a message. An email therefore has no way to reach the
part of the system that decides what to do.

Everything irreversible still stops at stage 13 and waits for an exact yes.
The chat cannot talk its way past that, and neither can anything else — the
gate is a Python condition, not a rule written in a prompt.
"""

import os
import sys
from datetime import datetime

import connect
from store import Store
from pipeline import stage13_approval, stage10_redact, user_input

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

HAS_KEY = bool(os.environ.get("GEMINI_API_KEY"))


def say(text=""):
    print(f"  {C['c']}·{C['0']} {text}" if text else "")


def dim(text):
    print(f"    {C['dim']}{text}{C['0']}")


# ───────────────────────── the actions ─────────────────────────

def do_brief(conn, store, state):
    """What is actually sitting in the inbox."""
    rows = store.q("""SELECT sender_name, sender, COUNT(*) c, SUM(unread) u
                        FROM messages WHERE in_inbox = 1
                       GROUP BY sender ORDER BY c DESC LIMIT 6""")
    total = store.one("SELECT COUNT(*) FROM messages WHERE in_inbox = 1")
    unread = store.one("SELECT COUNT(*) FROM messages WHERE in_inbox = 1 AND unread = 1")
    say(f"{total:,} in the inbox, {unread:,} unread. Who sends you the most:")
    print()
    for name, addr, c, u in rows:
        dim(f"{c:>5} messages · {u or 0:>5} never opened   {(name or addr)[:38]}")
    print()
    say("Ask me to sort it, or to find something.")


def do_search(conn, store, state, term):
    if not term:
        term = input(f"  {C['dim']}what should I look for? {C['0']}").strip()
    if not term:
        return say("nothing to look for.")
    like = f"%{term}%"
    rows = store.q("""SELECT date, sender_name, sender, subject
                        FROM messages
                       WHERE subject LIKE ? OR sender LIKE ? OR sender_name LIKE ?
                       ORDER BY date DESC LIMIT 10""", like, like, like)
    if not rows:
        return say(f"nothing matching '{term}'.")
    say(f"{len(rows)} match(es) for '{term}':")
    print()
    for date, name, addr, subject in rows:
        dim(f"{(date or '')[:16]:<17} {(name or addr)[:22]:<22} {(subject or '')[:40]}")
    print()


def do_sort(conn, store, state):
    """Labelling is reversible, so it does not need an approval."""
    say("sorting — this only adds labels, and --undo removes them.")
    import subprocess
    subprocess.run([sys.executable, "sort_mailbox.py", "100"])


def do_watch(conn, store, state):
    say("that one runs in its own window so it can keep going:")
    dim("python watch.py --draft")


def do_compose(conn, store, state, to):
    """
    Draft a new message. Nothing is sent here — this only fills state with a
    pending draft, which is what makes 'send' appear on the menu at all.
    """
    if not to or "@" not in to:
        to = input(f"  {C['dim']}who should it go to? {C['0']}").strip()
    if "@" not in to:
        return say("that is not an email address.")

    subject = input(f"  {C['dim']}subject: {C['0']}").strip() or "(no subject)"
    point = input(f"  {C['dim']}what do you want to say? {C['0']}").strip()
    if not point:
        return say("nothing to say — cancelled.")

    body = point
    how = "your exact words"
    if HAS_KEY:
        try:
            from pipeline import model
            from pipeline.stage19_voice import StyleStore
            st = StyleStore()
            profile = st.profile() if st.count() else {}
            body = model.draft_reply(
                f"Write a short email to {to}. The point of it: {point}",
                subject, to, [], profile).strip()
            how = "written in your voice"
        except Exception as e:
            dim(f"model unavailable ({str(e)[:40]}) — using your words")

    print()
    dim(f"To:      {to}")
    dim(f"Subject: {subject}")
    print()
    for l in body.splitlines():
        print(f"    {C['c']}│{C['0']} {l}")
    print()

    state["current_draft"] = body
    state["draft_to"] = to
    state["draft_subject"] = subject
    state["approval"] = stage13_approval.Approval("send", body)

    say(f"{how}. Type {C['b']}yes{C['0']} to send it, or tell me what to change.")


def do_send(conn, store, state, typed):
    """
    ⚠️ Stage 13, unchanged. The chat has no power the gate does not grant it.

    Note what is compared: the exact words the user typed, against a fixed
    list, with a hash of the exact draft. Not a model's opinion of intent.
    """
    ap = state.get("approval")
    body = state.get("current_draft")
    if not ap or not body:
        return say("there is no draft to send.")

    ok, why = ap.grant(typed)
    if not ok:
        return say(f"{C['y']}{why}{C['0']} — the draft is still here.")

    audit = []
    r = stage13_approval.execute(
        conn, "send", provider_id="", draft=body, approval=ap, audit=audit,
        to=state["draft_to"], subject=state["draft_subject"])

    if r["done"]:
        say(f"{C['g']}sent.{C['0']} Gmail id {r.get('sent_id')}")
        dim("it is in your Sent folder. It cannot be unsent — which is why it asked.")
        for k in ("current_draft", "draft_to", "draft_subject", "approval"):
            state.pop(k, None)
    else:
        say(f"{C['y']}not sent — {r['reason']}{C['0']}")


def do_edit(conn, store, state, instruction):
    """
    ⚠️ Editing VOIDS the approval, because the approval was bound to a hash of
    the old text. This is what stops 'make it shorter and send it' from sending
    something the user never read.
    """
    if not state.get("current_draft"):
        return say("there is no draft to change.")
    if not HAS_KEY:
        return say("no key — cannot rewrite. Discard and compose again.")
    if not instruction:
        instruction = input(f"  {C['dim']}what should change? {C['0']}").strip()

    try:
        from pipeline import model
        new = model._generate(
            f"Rewrite this email. Change requested: {instruction}\n"
            f"Keep the meaning. Reply with the email only.\n\n"
            f"{state['current_draft']}").strip()
    except Exception as e:
        return say(f"could not rewrite: {str(e)[:50]}")

    print()
    for l in new.splitlines():
        print(f"    {C['c']}│{C['0']} {l}")
    print()
    state["current_draft"] = new
    state["approval"] = stage13_approval.Approval("send", new)   # old yes is void
    say(f"changed. Any earlier yes no longer applies — type {C['b']}yes{C['0']} to send this one.")


def do_discard(conn, store, state):
    for k in ("current_draft", "draft_to", "draft_subject", "approval"):
        state.pop(k, None)
    say("discarded. Nothing was sent.")


def do_help(conn, store, state):
    say("Say things like:")
    print()
    for line in ["email ferozxdev@gmail.com and ask about the report",
                 "what's in my inbox",
                 "sort my mail",
                 "anything from linkedin?",
                 "quit"]:
        dim(f"you > {line}")
    print()
    dim("Anything that sends, forwards or trashes will stop and ask first.")


# ───────────────────────── the loop ─────────────────────────

def main():
    print(f"\n{C['b']}Custodian{C['0']}")
    print("─" * 62)

    conn = connect.open_mailbox()
    store = Store()
    print(f"  {conn.account_email()}")
    print(f"  understanding : {C['g']+'rules + model' if HAS_KEY else C['y']+'rules only (no key)'}{C['0']}")
    print(f"  {C['dim']}type what you want. 'help' for examples, 'quit' to leave.{C['0']}")
    print("─" * 62 + "\n")

    state = {}

    while True:
        try:
            typed = input(f"  {C['b']}you >{C['0']} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not typed:
            continue

        # ⚠️ APPROVAL IS CHECKED FIRST, BEFORE ANY INTERPRETATION.
        #
        # If a draft is pending and the user typed an exact yes, that is an
        # approval and nothing else. It must never be routed through a model
        # that might decide "yes" meant something more interesting.
        if state.get("current_draft") and stage13_approval.is_approval(typed):
            do_send(conn, store, state, typed)
            print()
            continue

        intent = user_input.read(typed, state)
        action, param = intent["action"], intent["parameter"]
        dim(f"understood as: {action}" + (f" ({param})" if param else "") +
            f"  ·  {intent['why']}")

        if action == "quit":
            break
        elif action == "help":
            do_help(conn, store, state)
        elif action == "brief":
            do_brief(conn, store, state)
        elif action == "search":
            do_search(conn, store, state, param or user_input.search_term(typed))
        elif action == "sort":
            do_sort(conn, store, state)
        elif action == "watch":
            do_watch(conn, store, state)
        elif action == "compose":
            do_compose(conn, store, state, param)
        elif action == "edit":
            do_edit(conn, store, state, typed)
        elif action == "discard":
            do_discard(conn, store, state)
        elif action == "decline":
            say(f"{C['y']}not sending.{C['0']} The draft is still here — "
                f"say 'discard' to throw it away, or tell me what to change.")
        elif action == "send":
            # Reached only when a draft exists but the words were not an
            # exact yes — so it is a request to send, not consent to.
            say(f"{C['y']}I need an unambiguous yes.{C['0']} Type: yes")
        else:
            say("I did not understand that. Type 'help' for examples.")
        print()

    print(f"\n  bye.\n")


if __name__ == "__main__":
    main()
