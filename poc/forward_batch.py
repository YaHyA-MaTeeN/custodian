"""
UC-35 — Forward a whole set to one person, as drafts, in one action.

    python forward_batch.py --from invoices@supplier.com --to finance@myco.com
    python forward_batch.py --find "invoice" --to finance@myco.com --note "for September"
    python forward_batch.py --save finance@myco.com "finance"      # add to your own list
    python forward_batch.py --recipients                            # your list

⚠️ EVERY FORWARD IS A DRAFT (BR-128). Nothing leaves until the Owner sends
each one from their own mail app. There is no send here at all.

⚠️ THE RECIPIENT COMES ONLY FROM THE OWNER (BR-129). Typed on this command
line, or picked from the list they built. No address found inside any message
may ever address a draft, however clearly the message asks — otherwise a
person pressing send without reading the To: line has been robbed, and the
human check is worthless. Addresses inside the selected mail are never
suggested and never used.

⚠️ REVIEWED BEFORE ANY IS WRITTEN (BR-130), ALL OR NOTHING, WITH A LIMIT
(BR-132). A half-written batch is worse than none — the Owner cannot tell
which are missing — so a failure removes the ones already written.
"""

import os
import re
import sys

import connect
from store import Store
from pipeline import stage02_strip

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

LIMIT = 25
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")


def select(store, sender=None, term=None, limit=LIMIT + 1) -> list:
    if sender:
        return store.q("""SELECT provider_id, message_id, sender, subject, date_iso, account
                            FROM messages WHERE sender=? AND in_inbox=1
                           ORDER BY date_iso DESC LIMIT ?""", sender.lower(), limit)
    like = f"%{term}%"
    return store.q("""SELECT provider_id, message_id, sender, subject, date_iso, account
                        FROM messages WHERE in_inbox=1 AND (subject LIKE ? OR sender LIKE ?)
                       ORDER BY date_iso DESC LIMIT ?""", like, like, limit)


def main():
    store = Store()
    args = sys.argv[1:]
    if "--recipients" in args:
        for a, label in store.saved_recipients():
            print(f"  {a:40} {label}")
        return
    if "--save" in args:
        i = args.index("--save")
        store.save_recipient(args[i + 1], args[i + 2] if i + 2 < len(args) else "")
        print(f"\n  saved {args[i+1]} to your list.\n"); return

    to = args[args.index("--to") + 1].lower() if "--to" in args else ""
    if not to or not EMAIL.match(to):
        print("\n  --to needs an address you typed, or one from --recipients.\n"); return
    sender = args[args.index("--from") + 1] if "--from" in args else None
    term = args[args.index("--find") + 1] if "--find" in args else None
    note = args[args.index("--note") + 1] if "--note" in args else ""
    if not sender and not term:
        print("\n  choose the set with --from <address> or --find <words>.\n"); return

    rows = select(store, sender, term)
    if not rows:
        print("\n  nothing matched.\n"); return
    if len(rows) > LIMIT:
        print(f"\n  {C['y']}That is more than {LIMIT} messages. Narrow it down — we will not put "
              f"that many drafts in your mailbox.{C['0']}\n"); return

    conn = connect.open_mailbox(quiet=True)
    me = conn.account_email()

    # ── review, before anything is written (BR-130) ──────────────────
    print(f"\n{C['b']}{len(rows)} draft(s) to {to}{C['0']}")
    print("─" * 72)
    for pid, mid, snd, subject, date, account in rows:
        print(f"  {(date or '')[:10]}  {(subject or '(no subject)')[:46]:46} "
              f"{C['dim']}from {account or me}{C['0']}")
    if note:
        print(f"\n  note on each: {C['dim']}{note}{C['0']}")
    print(f"\n  Each is a DRAFT in your Drafts folder. Nothing is sent.")
    try:
        typed = input("  Write them? type yes: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    if typed != "yes":
        print("  nothing written.\n"); return

    written = []
    try:
        for pid, mid, snd, subject, date, account in rows:
            raw = connect.fetch_verified(conn, pid, mid)
            text = stage02_strip.strip(raw)["text"]
            body = (f"{note}\n\n" if note else "") + \
                   f"---------- Forwarded message ----------\nFrom: {snd}\n" \
                   f"Date: {date}\nSubject: {subject}\n\n{text[:4000]}"
            d = conn.create_draft(to=to, subject=f"Fwd: {subject or ''}", body=body)
            written.append((d.get("id"), d.get("message_id", ""), mid, pid, subject))
            store.record_action(mid, pid, "draft", f"forward to {to}", before=str(d.get("id")))
        print(f"\n  {C['g']}{len(written)} drafts are waiting in your Drafts folder. "
              f"Nothing has been sent.{C['0']}\n")
    except Exception as e:
        # All or nothing (EX-2): remove what was written, report the batch failed.
        for did, dmid, *_ in written:
            try:
                conn.delete_draft(did, dmid)
            except Exception:
                pass
        print(f"\n  {C['r']}We could not prepare all of these, so we have prepared none.{C['0']} "
              f"{C['dim']}({str(e)[:60]}){C['0']}\n")


if __name__ == "__main__":
    main()
