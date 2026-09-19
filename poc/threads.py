"""
UC-40 — Where a conversation stands, without rereading fifteen messages.

    python threads.py 4          # the thread that message 4 (mailbox numbering) belongs to

⚠️ STATE, NOT STORY (BR-153). Who is in it, what was asked and whether it
was answered, who is waiting on whom, and the latest message. Never a
paragraph retelling the thread — a confident wrong summary is worse than
none.

⚠️ EVERY OPEN QUESTION LINKS TO THE MESSAGE IT CAME FROM (BR-154), so the
Owner can check it rather than trust it.

⚠️ WHEN UNSURE, SAY NOTHING (BR-155): participants and counts only. And
every body read to build the state is discarded afterwards (BR-156).
"""

import os
import sys

import connect
from store import Store
from pipeline import stage02_strip, stage18_requests
from remind import inbox_rows

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

MAX_MESSAGES = 20          # very long threads use the most recent part, and say so


def thread_of(store, mid: str) -> list:
    """Every stored message in the same conversation, oldest first."""
    row = store.q("SELECT thread_id, refs, in_reply_to FROM messages WHERE message_id=?", mid)
    ids = {mid}
    if row and row[0][0]:
        ids |= {r[0] for r in store.q("SELECT message_id FROM messages WHERE thread_id=?", row[0][0])}
    # Stitch by In-Reply-To / References both ways (IMAP has no thread id).
    frontier, seen = list(ids), set()
    while frontier:
        m = frontier.pop()
        if m in seen:
            continue
        seen.add(m)
        for (child,) in store.q("SELECT message_id FROM messages WHERE in_reply_to=? OR refs LIKE ?",
                                m, f"%{m}%"):
            if child and child not in seen:
                ids.add(child); frontier.append(child)
        for (parent,) in store.q("SELECT in_reply_to FROM messages WHERE message_id=?", m):
            if parent and parent not in seen:
                ids.add(parent); frontier.append(parent)
    q = ",".join("?" * len(ids))
    return store.q(f"""SELECT message_id, provider_id, sender, sender_name, subject, date_iso, recipients
                        FROM messages WHERE message_id IN ({q}) ORDER BY date_iso""", *ids)


def main():
    store = Store()
    n = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
    if n is None:
        print("\n  python threads.py <message number>\n"); return
    rows = inbox_rows(store)
    if not 1 <= n <= len(rows):
        print(f"\n  no message {n}.\n"); return
    mid = rows[n - 1][0]
    msgs = thread_of(store, mid)
    if len(msgs) < 3:
        print(f"\n  This conversation has {len(msgs)} message(s). The state view starts at three.\n")
        return
    conn = connect.open_mailbox(quiet=True)
    me = (conn.account_email() or "").lower()
    truncated = len(msgs) > MAX_MESSAGES
    msgs = msgs[-MAX_MESSAGES:]

    people = sorted({(sname or sender) for _, _, sender, sname, *_ in msgs})
    print(f"\n{C['b']}{(msgs[-1][4] or '(no subject)')[:60]}{C['0']}")
    print("─" * 72)
    print(f"  {len(people)} people: {', '.join(p[:24] for p in people)}")
    if truncated:
        print(f"  {C['dim']}long thread — the most recent {MAX_MESSAGES} messages are used{C['0']}")

    # Read each message once; extract; discard.
    asks = []
    for i, (m, pid, sender, sname, subject, date, to) in enumerate(msgs):
        try:
            raw = connect.fetch_verified(conn, pid, m)
            text = stage02_strip.strip(raw)["text"]
        except Exception:
            continue
        direction = "sent" if sender.lower() == me else "incoming"
        for it in stage18_requests.extract(text, subject, direction):
            asker = "you" if direction == "sent" else (sname or sender)
            # asked of whom, in thread terms
            if it["who"] == "sender":
                owed_by = asker
            elif it["who"] == "me":
                owed_by = "you" if direction == "incoming" else "them"
            else:
                owed_by = "someone else"
            # answered if the owed party wrote later in the thread
            later = [x for x in msgs[i + 1:]
                     if (x[2].lower() == me) == (owed_by == "you")]
            asks.append({"what": it["what"], "by": asker, "owed_by": owed_by,
                         "answered": bool(later), "date": (date or "")[:10],
                         "due": it["due"][:10], "evidence": it["evidence"]})

    if not asks:
        print(f"\n  {C['y']}We couldn't work out where this stands, so we're only showing who is in it.{C['0']}\n")
        return
    open_ = [a for a in asks if not a["answered"]]
    print(f"  {len(asks)} question(s) asked · {len(open_)} still open")
    waiting_on_you = [a for a in open_ if a["owed_by"] == "you"]
    if waiting_on_you:
        print(f"  {C['c']}{', '.join(sorted({a['by'] for a in waiting_on_you}))} waiting on you.{C['0']}")
    print()
    for a in asks:
        state = f"{C['g']}answered{C['0']}" if a["answered"] else f"{C['y']}open{C['0']}"
        print(f"  {state:>18}  “{a['what'][:52]}”")
        print(f"                    {C['dim']}asked by {a['by'][:22]} on {a['date']}, owed by {a['owed_by']}"
              f"{' · due ' + a['due'] if a['due'] else ''}{C['0']}")
    last = msgs[-1]
    print(f"\n  {C['dim']}latest: {(last[3] or last[2])[:24]} on {(last[5] or '')[:10]}{C['0']}")
    print(f"  {C['dim']}Bodies were read once and discarded.{C['0']}\n")


if __name__ == "__main__":
    main()
