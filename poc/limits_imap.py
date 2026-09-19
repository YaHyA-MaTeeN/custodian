"""
The limits of the free route — measured where it is safe, quoted where not.

    python limits_imap.py                    # everything
    python limits_imap.py --no-connections   # skip the connection-count test

⚠️ THE ONE THING THIS SCRIPT WILL NOT DO IS HIT A LIMIT ON PURPOSE.

Gmail's IMAP download cap is 2,500 MB a day. Cross it and Google switches IMAP
off for this account for up to a day — the POC stops, and so does every other
mail client using IMAP on it. So the caps are quoted from Google's published
figures, and what we MEASURE is how fast we go and exactly how big this
mailbox is. The arithmetic between those two says how close a full sync would
come to the cap, without going near it.

⚠️ SIZES COME FROM THE WHOLE MAILBOX, NOT A SAMPLE.

verify_doc.py measured 25 messages and its answer moved by a third between
runs. Asking for RFC822.SIZE of every message costs one command and a few
hundred KB, so here the median is taken over all of them and does not move.
"""

import math
import os
import re
import statistics
import sys
import time
import imaplib

MB = 1024 * 1024
DOWNLOAD_CAP = 2500 * MB     # Gmail, published: IMAP download per day
UPLOAD_CAP = 500 * MB        # Gmail, published: IMAP upload per day
CONN_CAP = 15                # Gmail, published: simultaneous IMAP connections
SEND_CAP = 500               # consumer Gmail, published: recipients per day

ROWS = []
DOWNLOADED = [0]             # bytes this script itself pulled down
SIZE_RE = re.compile(rb"RFC822\.SIZE (\d+)")


def row(verdict, text, evidence=""):
    ROWS.append(verdict)
    mark = {"MEASURED": "[MEASURED]", "POLICY": "[ POLICY ]",
            "LIMIT": "[ LIMIT  ]", "SKIP": "[  SKIP  ]"}.get(verdict, "[   ?    ]")
    print(f"  {mark}  {text}")
    if evidence:
        print(f"              {evidence}")


def head(title):
    print(f"\n  {title}")
    print("  " + "─" * 74)


def mb(b):
    return f"{b / MB:,.1f} MB"


def sizes(n, uid_set: str) -> list:
    """RFC822.SIZE for a set of UIDs — the size WITHOUT downloading the mail."""
    typ, data = n.uid("FETCH", uid_set, "(RFC822.SIZE)")
    out = []
    for item in data or []:
        line = item[0] if isinstance(item, tuple) else item
        if not line:
            continue
        DOWNLOADED[0] += len(line)
        m = SIZE_RE.search(line)
        if m:
            out.append(int(m.group(1)))
    return out


def search(n, gmail_query: str) -> list:
    typ, data = n.uid("SEARCH", "X-GM-RAW", f'"{gmail_query}"')
    return data[0].split() if typ == "OK" and data and data[0] else []


def fetched_bytes(data) -> list:
    out = [len(x[1]) for x in (data or []) if isinstance(x, tuple)]
    DOWNLOADED[0] += sum(out)
    return out


def main():
    import runlog
    log_path = runlog.start("limits_imap")
    print("\nCustodian — the limits of Gmail over IMAP")
    print("═" * 80)

    user, pw = os.environ.get("IMAP_USER"), os.environ.get("IMAP_PASSWORD")
    if not user or not pw:
        print("\n  IMAP_USER / IMAP_PASSWORD not set in this terminal.\n")
        return

    from connectors.imap import ImapConnector
    import connect
    host = connect.host_for(user)
    t_start = time.time()
    conn = ImapConnector(host, user, pw)
    n = conn.conn
    print(f"\n  {user}  ·  {conn.name}")

    # ── 1 ────────────────────────────────────────────────────────────
    head("1 · GOOGLE'S PUBLISHED LIMITS — QUOTED, NEVER TESTED BY HITTING THEM")
    row("POLICY", "Download over IMAP: 2,500 MB per day, per account",
        "crossing it switches IMAP off for this account for up to 24 hours")
    row("POLICY", "Upload over IMAP: 500 MB per day",
        "uploads are drafts and filed copies of sent mail — kilobytes for us")
    row("POLICY", "Simultaneous IMAP connections: 15 per account",
        "tested carefully in section 5")
    row("POLICY", "Sending over SMTP: 500 recipients per day",
        "consumer Gmail; Google Workspace accounts get 2,000")
    row("POLICY", "Largest single message: 25 MB")

    # ── 2 ────────────────────────────────────────────────────────────
    head("2 · HOW BIG THIS MAILBOX REALLY IS — EVERY MESSAGE, NOT A SAMPLE")
    n.select('"[Gmail]/All Mail"', readonly=True)
    t0 = time.time()
    all_sizes = sizes(n, "1:*")
    total = sum(all_sizes)
    med = statistics.median(all_sizes)
    row("MEASURED", f"{len(all_sizes):,} messages in All Mail — {mb(total)} in total",
        f"median {med:,.0f} bytes · largest {max(all_sizes) / MB:.1f} MB · "
        f"sizes of all of them read in {time.time() - t0:.1f}s")

    att = search(n, "has:attachment")
    att_sizes = sizes(n, b",".join(att).decode()) if att else []
    if att_sizes:
        row("MEASURED", f"{len(att_sizes):,} messages carry attachments",
            f"median {statistics.median(att_sizes) / 1024:,.0f} KB each · "
            f"{mb(sum(att_sizes))} between them")

    recent = search(n, "newer_than:30d")
    recent_sizes = sizes(n, b",".join(recent).decode()) if recent else []
    row("MEASURED", f"{len(recent_sizes):,} messages in the last 30 days — "
        f"{mb(sum(recent_sizes))}", "the window Custodian keeps message text for")

    # ── 3 ────────────────────────────────────────────────────────────
    head("3 · HOW FAST — ONE COMMAND PER MESSAGE vs ONE COMMAND FOR MANY")
    n.select("INBOX", readonly=True)       # read-only: nothing below can change mail
    typ, data = n.uid("SEARCH", None, "ALL")
    newest = data[0].split()[-200:]

    t0 = time.time()
    for u in newest[-30:]:
        typ, d = n.uid("FETCH", u, "(BODY.PEEK[HEADER])")
        fetched_bytes(d)
    one = (time.time() - t0) / 30
    row("MEASURED", f"Headers, one command each: {1 / one:,.1f} messages a second",
        f"{one * 1000:,.0f} ms per message — the old way: how fetch_envelopes "
        f"worked before the fix")

    t0 = time.time()
    typ, d = n.uid("FETCH", b",".join(newest).decode(), "(BODY.PEEK[HEADER])")
    batch_t = time.time() - t0
    hb = fetched_bytes(d)
    batch_rate = len(hb) / batch_t if batch_t else 0
    row("MEASURED", f"Headers, 200 in one command: {batch_rate:,.0f} messages a second",
        f"{batch_t:.1f}s for {len(hb)} · {batch_rate * one:,.0f}x faster than one at a time")

    # ⚠️ The two rows above time raw IMAP commands. This one times OUR code —
    # the function the product actually calls — so the fix is proven where it
    # lives, not by a benchmark that only shows the fix was possible.
    t0 = time.time()
    envs = list(conn.fetch_envelopes(newest))
    ours_t = time.time() - t0
    ours_rate = len(envs) / ours_t if ours_t else 0
    DOWNLOADED[0] += int(len(envs) * (statistics.median(hb) if hb else 6000))
    row("MEASURED", f"Our fetch_envelopes(), 200 messages: {ours_rate:,.0f} messages a second",
        f"{ours_t:.1f}s for {len(envs)} envelopes · "
        f"{ours_rate * one:,.0f}x the old one-at-a-time speed")

    t0 = time.time()
    typ, d = n.uid("FETCH", b",".join(newest[-15:]).decode(), "(BODY.PEEK[])")
    body_t = time.time() - t0
    fb = fetched_bytes(d)
    row("MEASURED", f"Full messages, 15 in one command: "
        f"{sum(fb) / MB / body_t:,.2f} MB a second",
        f"{mb(sum(fb))} in {body_t:.1f}s · BODY.PEEK, so none were marked read")
    hdr_med = statistics.median(hb) if hb else 6000

    # ── 4 ────────────────────────────────────────────────────────────
    head("4 · WHAT THAT MEANS AGAINST THE 2,500 MB DAILY CAP")
    hdr_total = hdr_med * len(all_sizes)
    row("MEASURED", f"Every header in the mailbox, once: {mb(hdr_total)} "
        f"= {hdr_total * 100 / DOWNLOAD_CAP:.1f}% of one day's cap",
        f"at {hdr_med:,.0f} bytes a header the cap allows {int(DOWNLOAD_CAP // hdr_med):,} a day")

    days = total / DOWNLOAD_CAP
    row("MEASURED", f"Every full message, once: {mb(total)} "
        f"= {total * 100 / DOWNLOAD_CAP:.0f}% of one day's cap",
        ("fits inside a single day" if days <= 1
         else f"would need {math.ceil(days)} days") +
        f" · the cap allows {int(DOWNLOAD_CAP // med):,} median-sized messages a day")

    design = hdr_total + sum(recent_sizes)
    row("MEASURED", f"What Custodian's design downloads (all headers + 30 days of text): "
        f"{mb(design)}", f"{design * 100 / DOWNLOAD_CAP:.1f}% of one day's cap — "
        f"and after the first day, only what is new")

    doc_days = 100_000 * med / DOWNLOAD_CAP
    # ⚠️ No pass/fail band here. The first version called 4.0 days "holds"
    # against a stated 3 — a third longer, waved through by a generous range.
    # Say the number and the difference, and let the reader judge.
    row("MEASURED", f"The document said 100,000 messages with bodies takes ~3 days",
        f"at this mailbox's median of {med:,.0f} bytes: {doc_days:.1f} days — "
        + (f"{(doc_days / 3 - 1) * 100:.0f}% longer than the document's 3"
           if doc_days > 3 else
           f"{(1 - doc_days / 3) * 100:.0f}% shorter than the document's 3"))
    row("MEASURED", f"The document said full messages: 33,000 a day",
        f"at this mailbox's median: {int(DOWNLOAD_CAP // med):,} a day — "
        + (f"{(1 - (DOWNLOAD_CAP // med) / 33_000) * 100:.0f}% below the document's figure"
           if DOWNLOAD_CAP // med < 33_000 else "at or above the document's figure"))

    if ours_rate:
        row("MEASURED", f"Time to sync every header: "
            f"{len(all_sizes) / ours_rate / 60:.1f} min with our code now, "
            f"{len(all_sizes) * one / 60:.0f} min the old way",
            "Gmail's cap was never the bottleneck — the way we asked was")

    # ── 5 ────────────────────────────────────────────────────────────
    head("5 · HOW MANY CONNECTIONS GMAIL ALLOWS AT ONCE")
    if "--no-connections" in sys.argv:
        row("SKIP", "connection count", "skipped by --no-connections")
    else:
        # ⚠️ Stop at 16 — one past the published cap is enough to see it.
        # Every connection opened here is closed in the finally block. If
        # web.py --watch or another mail app is running, it holds some of
        # the 15 too, and the refusal will come earlier; that is correct.
        extra, refused = [], None
        try:
            for i in range(2, CONN_CAP + 2):      # we already hold #1
                try:
                    c = imaplib.IMAP4_SSL(host, 993, timeout=20)
                    c.login(user, pw)
                    extra.append(c)
                except Exception as e:
                    refused = (i, str(e))
                    break
        finally:
            closed = 0
            for c in extra:
                try:
                    c.logout()
                    closed += 1
                except Exception:
                    pass
        held = 1 + len(extra)
        if refused:
            row("LIMIT", f"Gmail refused connection #{refused[0]} — "
                f"{held} were held at once", refused[1][:70])
        else:
            row("MEASURED", f"{held} connections held at once, none refused",
                f"the published cap is {CONN_CAP}; it was not enforced here — "
                f"do not design around that")
        row("MEASURED", "Every extra connection closed again",
            f"{len(extra)} opened, {closed} closed")
        row("MEASURED", "What it means for Custodian",
            "the cap is PER ACCOUNT — each user's mailbox gets its own 15. "
            "One server watching many users is not limited by it; we use 1-2 each")

    # ── tally ────────────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print(f"  {ROWS.count('MEASURED')} measured  ·  {ROWS.count('POLICY')} published limits  ·  "
          f"{ROWS.count('LIMIT')} limit reached  ·  {ROWS.count('SKIP')} skipped")
    print(f"\n  this script itself downloaded {mb(DOWNLOADED[0])} "
          f"= {DOWNLOADED[0] * 100 / DOWNLOAD_CAP:.2f}% of today's cap")
    print(f"  took {time.time() - t_start:.0f}s  ·  read-only — no mail was changed")
    print(f"  saved: test_runs\\{log_path.name}\n")
    try:
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
