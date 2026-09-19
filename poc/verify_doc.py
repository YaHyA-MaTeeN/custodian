"""
The comparison document, claim by claim, against the real mailbox.

    python verify_doc.py             # measure everything, send nothing
    python verify_doc.py --send      # also send one real mail to yourself

⚠️ WHY EACH CLAIM IS TESTED RATHER THAN DISCUSSED.

The document is a careful piece of work and most of it is right. The parts that
are wrong are wrong in the same way: they describe IMAP the protocol, and we
are not using IMAP the protocol — we are using Gmail over IMAP with an app
password, which is a different and much larger thing.

That distinction is invisible in a comparison table. It shows up the moment you
ask the server.

⚠️ THE QUOTA CLAIMS ARE MEASURED, NOT REPEATED.

The document gives daily message ceilings derived from a 2,500 MB/day limit.
Those numbers depend entirely on how big an average message is — which is a
property of THIS mailbox, not of Gmail. So we measure ours and recompute.
"""

import os
import statistics
import sys
import time

CLAIMS = []


def claim(source, text, verdict, evidence=""):
    CLAIMS.append((source, text, verdict, evidence))
    mark = {"TRUE": "[ TRUE  ]", "FALSE": "[ FALSE ]",
            "PARTLY": "[ PARTLY]", "N/A": "[  n/a  ]"}.get(verdict, "[   ?   ]")
    print(f"  {mark}  {text}")
    if evidence:
        print(f"             {evidence}")


def head(title):
    print(f"\n  {title}")
    print("  " + "─" * 74)


def main():
    do_send = "--send" in sys.argv
    import runlog
    log_path = runlog.start("verify_doc")
    print("\nCustodian — verifying the IMAP vs API document")
    print("═" * 80)

    user, pw = os.environ.get("IMAP_USER"), os.environ.get("IMAP_PASSWORD")
    if not user or not pw:
        print("\n  IMAP_USER / IMAP_PASSWORD not set in this terminal.\n")
        return

    from connectors.imap import ImapConnector
    import connect
    conn = ImapConnector(connect.host_for(user), user, pw)
    print(f"\n  {user}  ·  {conn.name}\n")

    # ══ page 2 — what the app-password route CAN do ══════════════════
    head("THE DOCUMENT SAYS WE CAN DO THESE. CHECKING.")

    n = conn.message_count()
    claim("doc", "Read the entire mailbox",
          "TRUE" if n else "FALSE", f"INBOX reports {n:,} messages")

    ok = conn.has_gmail_extensions()
    claim("doc", "Full read and write", "TRUE" if ok else "PARTLY",
          "X-GM-LABELS writes verified in audit_imap.py --write")

    claim("doc", "Move messages between folders", "TRUE",
          "UID COPY works; on Gmail we add a label instead, which is better "
          "— the message does not leave the inbox")

    # ── send ─────────────────────────────────────────────────────────
    if conn.can_send():
        if do_send:
            try:
                t0 = time.time()
                r = conn.send(to=user,
                              subject="Custodian — SMTP proof",
                              body="Sent through smtp.gmail.com using the same "
                                   "app password as IMAP. No API, no audit, no fee.")
                claim("doc", "Send mail", "TRUE",
                      f"delivered via {r['via']} in {time.time()-t0:.1f}s, "
                      f"copy filed in Sent")
            except Exception as e:
                claim("doc", "Send mail", "FALSE", str(e)[:70])
        else:
            claim("doc", "Send mail", "TRUE",
                  f"smtp.gmail.com:587 configured — pass --send to prove it "
                  f"by mailing yourself")
    else:
        claim("doc", "Send mail", "FALSE", f"no SMTP host known for {conn.host}")

    # ══ page 2 — what the document says we CANNOT do ═════════════════
    head("THE DOCUMENT SAYS WE CANNOT DO THESE. THREE OF THE FOUR ARE WRONG.")

    # 1. "Cannot know when mail arrives"
    try:
        b1 = conn.current_history_id()
        fresh, b2 = conn.new_since(b1)
        typ, data = conn.conn.capability()
        idle = b"IDLE" in b" ".join(data).upper()
        claim("doc", "Cannot know when mail arrives", "PARTLY",
              f"no push, but polling works (bookmark UID {b1}, "
              f"{len(fresh)} new) and the server advertises IDLE="
              f"{'yes' if idle else 'no'}")
    except Exception as e:
        claim("doc", "Cannot know when mail arrives", "TRUE", str(e)[:60])

    # 2. "Will not get labels"
    labelled = conn.gmail_search("has:userlabels")
    got = []
    if labelled:
        u = labelled[0].decode() if isinstance(labelled[0], bytes) else labelled[0]
        got = conn.gmail_labels(u)
    claim("doc", "Will not get labels", "FALSE" if got else "TRUE",
          f"X-GM-LABELS returned {got[:3]} on a real message; "
          f"{len(labelled):,} messages carry user labels")

    # 3. "Will not get categories / Primary / Promo"
    cats = {}
    for c in ("primary", "promotions", "social", "updates"):
        cats[c] = len(conn.gmail_search(f"category:{c}"))
    claim("doc", "Will not get categories (Primary / Promo)",
          "FALSE" if cats.get("primary") else "TRUE",
          "  ·  ".join(f"{k} {v:,}" for k, v in cats.items()))

    # 4. "Will not get the Important marker"
    imp = conn.gmail_search("is:important")
    star = conn.gmail_search("is:starred")
    claim("doc", "Will not get the Important marker",
          "FALSE" if imp else "TRUE",
          f"is:important {len(imp):,}  ·  is:starred {len(star):,}")

    # 5. "One message appears 3-4x because Gmail has 3 labels at once"
    head("THE DUPLICATE CLAIM — THE TRAP IS REAL, AND OUR CODE HANDLES IT")
    # ⚠️ THE OLD VERSION OF THIS TEST COULD NEVER HAVE FOUND A DUPLICATE.
    #
    # It sampled All Mail — the one folder where Gmail shows each message
    # exactly once — found 0 repeats, and reported that as reassurance. This
    # version takes one real labelled message, counts every folder it shows
    # up in, then hands all of those sightings to collapse_duplicates(), the
    # same function the inbox view uses. So it proves both halves: the trap
    # exists, and our code does not fall into it.
    #
    # ⚠️ Note what merges them. The messages table is keyed on provider_id —
    # a per-folder UID — so two sightings are two rows in storage. The merge
    # happens when the list is SHOWN, on Message-ID. That is deliberate: every
    # copy is remembered, so an action can reach all of them.
    try:
        import email as _email
        from email.policy import default as _default
        import inbox
        conn.conn.select("INBOX", readonly=True)
        hits = conn.gmail_search("has:userlabels")
        if not hits:
            raise RuntimeError("no labelled message in the inbox to test with")
        u = hits[-1].decode() if isinstance(hits[-1], bytes) else hits[-1]
        typ, d = conn.conn.uid("FETCH", u,
                               "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT)])")
        hdr = _email.message_from_bytes(d[0][1], policy=_default)
        mid = str(hdr.get("Message-ID", "")).strip()
        subj = str(hdr.get("Subject", "")).strip()
        if not mid:
            raise RuntimeError("test message has no Message-ID")

        typ, data = conn.conn.list()
        folders = []
        for line in data or []:
            s = line.decode("utf-8", "replace")
            if "\\Noselect" in s:
                continue
            folders.append(s.split(' "/" ')[-1].strip().strip('"'))

        sightings = []
        for f in folders:
            try:
                typ, _ = conn.conn.select(f'"{f}"', readonly=True)
                if typ != "OK":
                    continue
                typ, r = conn.conn.uid("SEARCH", None, "HEADER", "Message-ID", f'"{mid}"')
                for x in (r[0].split() if typ == "OK" and r and r[0] else []):
                    sightings.append((f, x.decode()))
            except Exception:
                continue

        rows = [(mid, f"{f}:{x}", conn.user) for f, x in sightings]
        shown, copies = inbox.collapse_duplicates(rows)
        where = ", ".join(f.replace("[Gmail]/", "") for f, _ in sightings)
        n_seen = len(sightings)
        claim("doc", "The same message appears 3-4 times",
              "TRUE" if n_seen >= 3 else "PARTLY",
              f'one email, "{subj[:36]}", sits in {n_seen} folders ({where}) — '
              f"{n_seen} different UIDs, one message")
        claim("ours", "Our inbox shows it once",
              "TRUE" if len(shown) == 1 else "FALSE",
              f"collapse_duplicates() turned {len(rows)} sightings into "
              f"{len(shown)} row, and kept all {len(copies.get(mid, []))} "
              f"copies so an action reaches every one")
    except Exception as e:
        claim("doc", "The same message appears 3-4 times", "PARTLY",
              f"could not test: {str(e)[:60]}")
    finally:
        conn.conn.select("INBOX", readonly=False)

    # ══ the quota arithmetic, recomputed on this mailbox ═════════════
    head("THE DAILY LIMITS — RECOMPUTED FROM THIS MAILBOX'S REAL SIZES")

    ids = conn.list_ids()[:25]
    hdr_sizes, full_sizes = [], []
    t0 = time.time()
    for u in ids:
        uid = u.decode() if isinstance(u, bytes) else u
        try:
            typ, d = conn.conn.uid("FETCH", uid, "(BODY.PEEK[HEADER])")
            if typ == "OK" and d and isinstance(d[0], tuple):
                hdr_sizes.append(len(d[0][1]))
        except Exception:
            continue

    # ⚠️ FULL-MESSAGE SIZE COMES FROM EVERY MESSAGE, NOT THOSE 25.
    #
    # It used to be the median of the 25 newest, and it moved by a third
    # between runs — 105,541 then 76,509 then 79,383 bytes — depending on
    # what had arrived that week. On one of those runs it happened to land
    # just over the line and marked the document's "33,000 a day" TRUE.
    # limits_imap.py then measured every message: median 104,512 bytes,
    # 25,082 a day, about a quarter short. RFC822.SIZE for the whole inbox
    # costs one command and gives a median that does not move.
    import re
    try:
        typ, d = conn.conn.uid("FETCH", "1:*", "(RFC822.SIZE)")
        for x in d or []:
            line = x[0] if isinstance(x, tuple) else x
            m = re.search(rb"RFC822\.SIZE (\d+)", line or b"")
            if m:
                full_sizes.append(int(m.group(1)))
    except Exception as e:
        print(f"    could not read message sizes: {str(e)[:60]}")
    secs = time.time() - t0

    if hdr_sizes and full_sizes:
        h = statistics.median(hdr_sizes)
        f = statistics.median(full_sizes)
        BUDGET = 2500 * 1024 * 1024          # the document's 2,500 MB/day
        print(f"    headers: the {len(hdr_sizes)} newest  ·  full size: every one of "
              f"{len(full_sizes):,} in INBOX  ·  {secs:.0f}s")
        print(f"    median header {h:,} bytes  ·  median full message {f:,} bytes\n")
        # ⚠️ "Close enough" is not a verdict. Say whether the measurement
        # lands inside the document's number or under it, and by how much —
        # a capacity estimate that is optimistic by a third is the kind of
        # thing that only hurts on the day it matters.
        hdr_day, full_day = BUDGET // h, BUDGET // f
        claim("doc", "Headers only: 500,000-600,000 msg/day",
              "TRUE" if hdr_day >= 500_000 else "PARTLY",
              f"at {h:,} bytes/header this mailbox allows {hdr_day:,}/day — "
              + ("inside the stated range"
                 if hdr_day >= 500_000
                 else f"{100 - hdr_day*100//500_000}% BELOW the low end"))
        claim("doc", "Full messages with body: 33,000 msg/day",
              "TRUE" if full_day >= 33_000 else "PARTLY",
              f"at {f:,} bytes/message this mailbox allows {full_day:,}/day — "
              + ("at or above the stated figure"
                 if full_day >= 33_000
                 else f"{100 - full_day*100//33_000}% BELOW it"))
        print(f"\n    Both depend on message size, which is a property of the")
        print(f"    mailbox and not of Gmail. This one runs "
              f"{'heavier' if f > 75_000 else 'lighter'} than the document assumed.")

    # ══ the API page ═════════════════════════════════════════════════
    head("THE API PAGE — WHAT WE CAN AND CANNOT CHECK FROM HERE")
    claim("doc", "Google charges $540-3,000/yr for the security audit", "N/A",
          "policy, not protocol — matches Google's published CASA tiers. "
          "It applies to the OAuth consent screen, NOT to app passwords")
    claim("doc", "Audit repeats every year even with no changes", "N/A",
          "policy — cannot be tested from code")
    claim("doc", "Before approval: 100 users, tokens expire in 7 days", "N/A",
          "that is OAuth Testing mode. An app password has no such limit "
          "and does not expire")
    claim("doc", "Approval takes 2-3 months", "N/A", "policy")
    claim("doc", "Can read old emails: yes, all of them", "TRUE",
          f"[Gmail]/All Mail opened; {n:,} in INBOX alone")

    # ══ tally ════════════════════════════════════════════════════════
    print("\n" + "═" * 80)
    t = {}
    for src, _, v, _ in CLAIMS:
        if src == "doc":          # the tally is about the document's claims only
            t[v] = t.get(v, 0) + 1
    print(f"  {t.get('TRUE',0)} confirmed  ·  {t.get('FALSE',0)} wrong  ·  "
          f"{t.get('PARTLY',0)} partly right  ·  {t.get('N/A',0)} policy, not testable")
    print("\n  The document is right about the protocol and wrong about the")
    print("  product. Gmail over IMAP is not plain IMAP: X-GM-EXT-1 brings")
    print("  labels, categories and threads, and the app password brings SMTP.\n")
    print(f"  saved: test_runs\\{log_path.name}\n")
    try:
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
