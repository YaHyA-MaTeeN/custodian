"""
UC-20 — The one important message in the spam folder.

    python spam_rescue.py            # score the spam folder, show what looks real
    python spam_rescue.py --rescue 2 # move item 2 back to the inbox

⚠️ WE DO NOT COMPETE WITH THE PROVIDER'S SPAM FILTER.

Google's is better than ours will ever be. We handle its mistakes, nothing
more — and only with signals spam cannot fake (BR-74):

    you have written to this sender before          strongest
    it is a reply in a thread you started           strong
    the provider's own authentication check passed  supporting
    you have opened this sender's mail before       supporting

⚠️ ENVELOPES ONLY. NOTHING IS OPENED, NO IMAGE IS EVER LOADED (BR-76).

A single loaded image tells a scammer the address is live. Scoring reads the
headers we already keep for every message and nothing else.

⚠️ AND NOTHING MOVES ON ITS OWN (BR-75). --rescue is the Owner acting. It is
reversible (undo puts it back in spam), so it needs no typed yes, but it is
still recorded like every action.
"""

import os
import sys

import connect
from store import Store
from pipeline import stage04_headers

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

THRESHOLD = 3


def score(store, me, env) -> tuple:
    """Points and reasons. Only from things spam cannot fake."""
    pts, why = 0, []
    # BR-77 — forwarded mailing-list traffic is the commonest false positive.
    if env.list_id or env.bulk:
        return 0, ["mailing-list traffic — set aside"]
    hist = store.history(env.sender, me)
    if hist["replied"] > 0:
        pts += 3; why.append(f"you have written to this sender {hist['replied']} time(s)")
    if env.in_reply_to and store.q("SELECT 1 FROM messages WHERE message_id=? AND sender=? LIMIT 1",
                                   env.in_reply_to, (me or "").lower()):
        pts += 3; why.append("a reply to a message you sent")
    auth = stage04_headers.read_auth(env.auth_results)
    if auth["passed"]:
        pts += 2; why.append("passed the provider's authentication check")
    if hist["opened"] > 0:
        pts += 1; why.append(f"you have opened {hist['opened']} from this sender before")
    return pts, why


def main():
    store = Store()
    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()

    print(f"\n{C['b']}Spam folder — anything that looks real?{C['0']}")
    print("─" * 74)
    envs = conn.spam_envelopes(limit=100)
    if not envs:
        print("  the spam folder is empty, or was not found.\n"); return

    scored = []
    for env in envs:
        pts, why = score(store, me, env)
        scored.append((pts, why, env))
    scored.sort(key=lambda x: -x[0])
    likely = [s for s in scored if s[0] >= THRESHOLD]

    print(f"  {len(envs)} in spam · {len(likely)} look like they may be real\n")
    if not likely:
        print(f"  {C['g']}Nothing important found. Silence is the correct output most weeks.{C['0']}\n")
        return
    for i, (pts, why, env) in enumerate(likely, 1):
        print(f"  {i}. {C['b']}{(env.subject or '(no subject)')[:56]}{C['0']}")
        print(f"     {C['dim']}from {env.sender}  ·  {(env.date or '')[:16]}{C['0']}")
        for w in why:
            print(f"     {C['c']}· {w}{C['0']}")
    print(f"\n  {C['y']}Nothing here is presented as safe. Look before you act.{C['0']}")
    print(f"  {C['dim']}python spam_rescue.py --rescue N   moves one back to the inbox.{C['0']}")

    if "--rescue" in sys.argv:
        i = sys.argv.index("--rescue")
        n = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else 0
        if not 1 <= n <= len(likely):
            print(f"  no item {n}.\n"); return
        env = likely[n - 1][2]
        try:
            conn.rescue_from_spam(env.provider_id)
            store.record_action(env.message_id, env.provider_id, "rescue_from_spam",
                                (env.subject or "")[:70], before="SPAM")
            store.add_correction("sender", env.sender, was="spam", should_be="not_spam",
                                 source="app")
            print(f"\n  {C['g']}back in the inbox:{C['0']} {(env.subject or '')[:50]}")
            print(f"  {C['dim']}Recorded. python history.py --undo puts it back in spam.{C['0']}\n")
        except Exception as e:
            print(f"\n  {C['r']}could not rescue: {str(e)[:70]}{C['0']}\n")
    else:
        print()


if __name__ == "__main__":
    main()
