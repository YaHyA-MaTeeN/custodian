"""
Catch up. Run the pipeline over inbox mail that has never been through it.

    python scan.py            # up to 40 unscanned messages
    python scan.py 200        # up to 200
    python scan.py --imap     # through the free door

⚠️ WHY THIS IS SEPARATE FROM watch.py.

watch.py starts from a bookmark — "everything that arrives from now on". That
is correct for a live watcher and useless for a mailbox that already has 7,000
messages in it. Nothing was ever going to scan the backlog, so the view showed
"not run through the pipeline yet" on almost every row and there was no command
that would fix it.

⚠️ AND IT DOES NOT CONTAIN A PIPELINE.

It calls agent.run_one — the same function the terminal runs. If this file had
its own copy of the sixteen stages, the backlog and the live watcher could
reach different verdicts about the same email, and there would be no way to
say which was right. So it decides nothing. It only chooses WHO to hand over.
"""

import contextlib
import io
import sys
from datetime import datetime

import connect
from store import Store


def unscanned(store, limit: int) -> list:
    """
    Inbox messages with no stage-9 decision against them, newest first.

    ⚠️ Asks the decisions table, not a flag on the message. A flag would need
    keeping in step with the thing it describes; the decisions table IS the
    thing it describes.
    """
    rows = store.q("""
        SELECT m.provider_id, m.message_id, m.subject, m.sender_name, m.sender
          FROM messages m
         WHERE m.in_inbox = 1
           AND m.provider_id != ''
           AND NOT EXISTS (SELECT 1 FROM decisions d
                            WHERE d.message_id = m.message_id AND d.stage = '9')
         ORDER BY m.date_iso DESC, m.date DESC
         LIMIT ?""", limit * 3)
    out, seen = [], set()
    for r in rows:
        if r[1] and r[1] in seen:
            continue
        if r[1]:
            seen.add(r[1])
        out.append(r)
    return out[:limit]


def scan(conn, store, limit: int = 40, log=print) -> dict:
    """
    Hand each unscanned message to the real pipeline. Returns a tally.

    ⚠️ run_one prints a full sixteen-stage trace. That is right when a person
    asked to watch one message and wrong when catching up on two hundred, so
    the trace is captured and a single line is logged instead. The trace is
    not suppressed — it is simply not the output anyone wants here.
    """
    import agent

    todo = unscanned(store, limit)
    if not todo:
        return {"scanned": 0, "note": "nothing left to scan"}

    names = agent.known_names(store)
    tally = {"scanned": 0, "needs reply": 0, "no reply": 0, "failed": 0}

    for pid, mid, subject, sname, sender in todo:
        # The stored id belongs to the door that saved it; connect.live_id
        # looks the message up by Message-ID when it has to.
        live = connect.live_id(conn, pid, mid)
        if not live:
            log(f"  {(subject or '')[:44]:44}  not in this mailbox any more")
            tally["failed"] += 1
            continue
        try:
            env = next(iter(conn.fetch_envelopes([live])), None)
        except Exception as e:
            log(f"  could not fetch: {str(e)[:50]}")
            tally["failed"] += 1
            continue
        if env is None:
            tally["failed"] += 1
            continue

        store.save([env])
        buf = io.StringIO()
        try:
            # want_draft is False and stays False. A backlog scan must never
            # be able to reach the send path — there is nobody at the keyboard
            # to type the yes, and the approval gate is not optional.
            with contextlib.redirect_stdout(buf):
                agent.run_one(conn, store, env, names, False, [])
        except Exception as e:
            log(f"  {(subject or '')[:44]:44}  failed: {str(e)[:40]}")
            tally["failed"] += 1
            continue

        d = [x for x in store.decision_for(env.message_id) if x[0] == "9"]
        verdict = d[-1][1] if d else "exited before stage 9"
        tally["scanned"] += 1
        if verdict.startswith("needs"):
            tally["needs reply"] += 1
        elif verdict.startswith("no reply"):
            tally["no reply"] += 1
        log(f"  {(subject or '(no subject)')[:46]:46}  {verdict}")

    return tally


def main():
    limit = 40
    for a in sys.argv[1:]:
        if a.isdigit():
            limit = int(a)

    print("\nCustodian — catching up on the backlog")
    print("─" * 68)
    store = Store()
    conn = connect.open_mailbox()
    print(f"  {conn.account_email()}  ·  through {getattr(conn, 'name', '?')}")

    left = len(unscanned(store, 100000))
    print(f"  {left:,} inbox message(s) have never been scanned")
    print(f"  doing up to {limit} now\n")

    t0 = datetime.now()
    tally = scan(conn, store, limit)
    secs = (datetime.now() - t0).total_seconds()

    print("─" * 68)
    if not tally.get("scanned"):
        print(f"  {tally.get('note', 'nothing done')}\n")
        return
    print(f"  {tally['scanned']} scanned in {secs:.0f}s  ·  "
          f"{tally['needs reply']} need a reply  ·  "
          f"{tally['no reply']} do not  ·  {tally['failed']} failed")
    still = len(unscanned(store, 100000))
    print(f"  {still:,} still unscanned — run it again to continue")
    print("  refresh the browser to see them\n")


if __name__ == "__main__":
    main()
