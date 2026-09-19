"""
Custodian proof of concept — entry point.

    pip install google-api-python-client google-auth-oauthlib
    python run.py

Put credentials.json beside this file first. Writes report.html.

Note what this file does NOT contain: any mention of Gmail. It asks the
connector what it can do, never who it is. Swapping in an Outlook or IMAP
connector is one line at the top and nothing else changes.
"""

import sys
from datetime import datetime

import connect
from store import Store
import analyze
import report

BATCH = 500


def main():
    t0 = datetime.now()
    print("\nCustodian — mailbox scan")
    print("─" * 46)

    # The only line that names a specific kind of mailbox.
    print("connecting…")
    try:
        conn = connect.open_mailbox()
    except FileNotFoundError:
        print("\n  credentials.json not found.")
        print("  Google Cloud Console → APIs & Services → Credentials")
        print("  → OAuth client ID → Desktop app → download → put it here.\n")
        sys.exit(1)

    account = conn.account_email()
    print(f"  {account} — {conn.message_count():,} messages")
    print(f"  push: {conn.supports_push} · labels: {conn.supports_labels} · "
          f"search: {conn.supports_server_search}")

    store = Store()

    print("\nlisting message ids…")
    ids = conn.list_ids(
        on_progress=lambda n: print(f"\r  {n:,}", end="", flush=True))
    print(f"\r  {len(ids):,} ids")

    already = store.have()
    todo = [i for i in ids if i not in already]

    if todo:
        print(f"\nreading {len(todo):,} envelopes (no bodies)…")
        done = 0
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            try:
                got = list(conn.fetch_envelopes(chunk))
            except Exception as e:
                print(f"\n  batch failed: {type(e).__name__}: {e}")
                got = []
            done += store.save(got)
            pct = done * 100 // len(todo)
            # Print on a NEW LINE every few batches. A \r-only progress
            # line is invisible in some terminals, which makes a working scan
            # look like a dead one.
            bar = "#" * (pct // 4) + "." * (25 - pct // 4)
            print(f"  [{bar}] {done:,} / {len(todo):,}  ({pct}%)", flush=True)

            # ⚠️ A silent zero-result run is the worst failure mode. If the
            # first batch produces nothing, stop and say why rather than
            # grinding through 7,000 more and reporting an empty mailbox.
            if start == 0 and not got:
                print("\n\n  nothing came back from the first batch. Errors:")
                for e in conn.errors[:5]:
                    print(f"    {e}")
                if not conn.errors:
                    print("    (none recorded — try lowering workers in gmail.py)")
                sys.exit(1)
        print()
        if conn.errors:
            print(f"  {len(conn.errors)} transient error(s) during the scan, "
                  f"all retried. First: {conn.errors[0][:80]}")
    else:
        print(f"\n  all {len(ids):,} already stored")

    print("\nanalysing…")
    findings = analyze.scan(store)
    path = report.write(findings, account)

    mins = (datetime.now() - t0).total_seconds() / 60
    print("─" * 46)
    print(f"  {findings['total']:,} messages · {findings['senders']:,} senders "
          f"· {findings['gb']:.1f} GB")
    print(f"  {findings['bulk_total']:,} bulk from {findings['bulk_senders']:,} senders")
    print(f"  {findings['dormant_senders']:,} senders never once opened "
          f"({findings['dormant_messages']:,} messages)")
    print(f"  {findings['threads']:,} threads")
    print(f"\n  → {path}   ({mins:.1f} min)\n")


if __name__ == "__main__":
    main()
