"""
The always-on worker. One process, no browser, no keyboard.

    python worker.py               every connected mailbox, forever
    python worker.py --once        one pass, then exit (for a scheduler)
    python worker.py --every 30    seconds between passes (default 20)

What one pass does, for each mailbox it can open:

    1. new mail first     — fetch, save, run the pipeline (labels only)
    2. a little backlog   — three older messages, only when nothing new came
    3. housekeeping       — once an hour: requests scan (UC-33/45),
                            unsubscribe outcomes (BR-66), digest if due

⚠️ IT CANNOT SEND AND IT CANNOT CLEAR. There is nobody here to type the yes,
so the approval gate has nobody to ask. want_draft is False everywhere below
and no route through this file reaches trash, unsubscribe or send. It reads,
decides and labels. A process with no human attached does nothing else.

⚠️ ONE MAILBOX AT A TIME, ITS OWN CONNECTION. An IMAP session has state (a
selected folder, a command in flight). Each mailbox gets its own door and its
own store, opened once and kept.

⚠️ CREDENTIALS NEVER TOUCH THE LOG. In accounts mode the app password comes
out of the vault (api_mvp.vault_get), goes straight into the connector, and
is not held anywhere else.
"""

import os
import sys
import time
from datetime import datetime, timedelta

import connect
from store import Store

HOUSEKEEPING_EVERY = timedelta(hours=1)


class Mailbox:
    """One connected mailbox: its door, its store, its bookmark."""

    def __init__(self, address: str, conn, store):
        self.address, self.conn, self.store = address, conn, store
        self.bookmark, self.live = "", False
        try:
            self.bookmark = self.conn.current_history_id()
            self.live = True
        except Exception:
            pass                                  # backlog only
        self.last_housekeeping = datetime.min
        self.stats = {"new": 0, "backlog": 0, "errors": 0}

    # ── one pass ──────────────────────────────────────────────────────
    def step(self, log) -> str:
        import agent
        import scan as backlog
        fresh = []
        if self.live:
            fresh, self.bookmark = self.conn.new_since(self.bookmark)
        if fresh:
            names = agent.known_names(self.store)
            for env in self.conn.fetch_envelopes(fresh):
                self.store.save([env])
                try:
                    agent.run_one(self.conn, self.store, env, names, False, [])   # never drafts
                    self.stats["new"] += 1
                except Exception as e:
                    self.stats["errors"] += 1
                    log(f"pipeline failed on one message: {str(e)[:60]}")
            return f"{len(fresh)} new"
        t = backlog.scan(self.conn, self.store, limit=3, log=lambda *a: None)
        if t.get("scanned"):
            self.stats["backlog"] += t["scanned"]
            return f"{t['scanned']} older"
        return "idle"

    def housekeeping(self, log) -> None:
        if datetime.now() - self.last_housekeeping < HOUSEKEEPING_EVERY:
            return
        self.last_housekeeping = datetime.now()
        s, me = self.store, self.address
        try:
            import asks
            asks.scan_incoming(self.conn, s, me, limit=20)
            asks.scan_sent(self.conn, s, me, limit=20)
            asks.close_delivered(s, me)
        except Exception as e:
            log(f"requests scan skipped: {str(e)[:60]}")
        try:
            import unsubscribe
            now = datetime.now()
            for sender, requested_at, outcome, _ in s.unsubscribes():
                if outcome != "watching":
                    continue
                days = (now - datetime.fromisoformat(str(requested_at)[:19])).days
                after = s.one("SELECT COUNT(*) FROM messages WHERE sender=? AND date_iso > ?",
                              sender, str(requested_at)[:19])
                if after:
                    s.set_unsubscribe_outcome(sender, "ignoring")
                elif days >= unsubscribe.WATCH_DAYS:
                    s.set_unsubscribe_outcome(sender, "stopped")
        except Exception as e:
            log(f"unsubscribe check skipped: {str(e)[:60]}")
        # The digest is the one thing here that sends — to the Owner, about
        # the Owner's own mail, on the schedule the Owner set. digest.py
        # decides whether it is due and whether there is anything to say.
        try:
            import subprocess
            subprocess.run([sys.executable, "-X", "utf8", "digest.py", "--run"],
                           capture_output=True, timeout=300)
        except Exception as e:
            log(f"digest skipped: {str(e)[:60]}")


# ── which mailboxes ──────────────────────────────────────────────────────

def open_all(log) -> list:
    """
    Single-user: the one mailbox the environment describes.
    Accounts: every mailbox in public.mailboxes whose app password is in the
    vault — one connector each, with that account's own schema.
    """
    if not os.environ.get("DATABASE_URL"):
        conn = connect.open_mailbox(quiet=True)
        return [Mailbox(conn.account_email(), conn, Store())]

    from pg_store import PgStore
    from connectors.imap import ImapConnector
    import api_mvp
    root = PgStore()                       # public tables only, no account yet
    rows = root.conn.execute(
        "SELECT a.email, m.id, m.address, m.provider FROM public.mailboxes m "
        "JOIN public.accounts a ON a.id=m.account_id "
        "WHERE m.state='connected' ORDER BY m.id").fetchall()
    out = []
    for account_email, mailbox_id, address, provider in rows:
        try:
            secret = api_mvp.vault_get(root, mailbox_id)
            if not secret:
                log(f"{address}: no credential in the vault — skipped")
                continue
            conn = ImapConnector(connect.host_for(address), address, secret)
            del secret
            out.append(Mailbox(address, conn, PgStore(account_email=account_email)))
            log(f"{address}: opened ({provider})")
        except Exception as e:
            log(f"{address}: could not open — {str(e)[:60]}")
    return out


def main():
    args = sys.argv[1:]
    every = int(args[args.index("--every") + 1]) if "--every" in args else 20
    once = "--once" in args

    def log(m):
        print(f"  {datetime.now():%H:%M:%S}  {m}", flush=True)

    print("\n  Custodian worker — reads, decides, labels. Never sends, never clears.")
    boxes = open_all(log)
    if not boxes:
        print("  no mailbox could be opened. Nothing to do.\n")
        return
    cadence = "one pass" if once else f"every {every}s"
    log(f"{len(boxes)} mailbox(es) · {cadence}")
    while True:
        for box in boxes:
            try:
                what = box.step(log)
                if what != "idle":
                    log(f"{box.address}: {what}")
                box.housekeeping(log)
            except Exception as e:
                box.stats["errors"] += 1
                log(f"{box.address}: {str(e)[:70]}")
                if not os.environ.get("DATABASE_URL") and any(
                        k in str(e) for k in ("socket", "EOF", "BYE", "closed")):
                    try:
                        box.conn = connect.open_mailbox(quiet=True)
                        log(f"{box.address}: reconnected")
                    except Exception:
                        pass
        if once:
            for box in boxes:
                log(f"{box.address}: new {box.stats['new']} · older {box.stats['backlog']} "
                    f"· errors {box.stats['errors']}")
            return
        time.sleep(every)


if __name__ == "__main__":
    main()
