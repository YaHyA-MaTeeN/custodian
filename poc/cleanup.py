"""
UC-46 — The first cleanup. Four stages, in the only order that works.

    python cleanup.py

⚠️ ORDER IS THE WHOLE POINT (BR-179). Unsubscribe first, so the mailbox does
not refill while it is cleared. Then the pile. Then the brand sweep for what
is left. Then reclaim space. Run the other way round and the work undoes
itself.

⚠️ NOTHING NEW (BR-180). Every stage is an existing script with its own
safety rules, and nothing is looser inside the guide than outside it. Every
stage can be skipped; stopping keeps progress (BR-181). One result at the end
(BR-182).
"""

import os
import subprocess
import sys

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

STAGES = [
    ("unsubscribe", "Stop the mail coming, so it doesn't refill",
     ["unsubscribe.py"], "python unsubscribe.py <address>   for each sender you want stopped"),
    ("pile",        "Clear the pile — everything worthless, in groups",
     ["pile.py"],        "python pile.py --clear all   (or one address at a time)"),
    ("brand",       "Brand sweep — one company's advertising, keeping its receipts",
     ["brand.py"],       "python brand.py --clear <company>"),
    ("storage",     "Reclaim space — the few huge messages",
     ["storage.py"],     "python storage.py --clear <address>"),
]


def counts(store) -> dict:
    return {
        "trashed": store.one("SELECT COUNT(*) FROM actions WHERE action='trash' AND undone=0"),
        "stopped": store.one("SELECT COUNT(*) FROM unsub_requests"),
        "mb": store.one("""SELECT COALESCE(SUM(m.size),0) FROM actions a JOIN messages m
                            USING(message_id) WHERE a.action='trash' AND a.undone=0""") / (1024 * 1024),
    }


def main():
    store = Store()
    before = counts(store)
    print(f"\n{C['b']}Your scan is done. Let's clear it in four steps.{C['0']}")
    print("─" * 72)
    for i, (key, title, _, _) in enumerate(STAGES, 1):
        print(f"  {i}. {title}")
    print(f"\n  {C['dim']}We'll stop the mail coming before we clear it, so it doesn't refill.{C['0']}\n")

    for i, (key, title, script, how) in enumerate(STAGES, 1):
        print(f"{C['b']}Step {i} — {title}{C['0']}")
        try:
            typed = input("  open this step? (yes / skip / stop): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            typed = "stop"
        if typed == "stop":
            print("  stopped. Progress is kept — run cleanup.py again to continue.\n"); break
        if typed != "yes":
            print("  skipped.\n"); continue
        subprocess.run([sys.executable, "-X", "utf8"] + script)
        print(f"  {C['dim']}then: {how}{C['0']}")
        try:
            input("  press Enter when this step is done: ")
        except (EOFError, KeyboardInterrupt):
            break
        print()

    after = counts(store)
    print("─" * 72)
    print(f"  {C['g']}{after['trashed'] - before['trashed']:,} cleared. "
          f"{after['stopped'] - before['stopped']} senders stopped. "
          f"{after['mb'] - before['mb']:,.0f} MB back.{C['0']}")
    print(f"  {C['dim']}Nothing you've replied to was touched. python history.py --undo reverses any of it.{C['0']}\n")


if __name__ == "__main__":
    main()
