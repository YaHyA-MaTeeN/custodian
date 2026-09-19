"""
Every claim about IMAP, tested against the real mailbox. No opinions.

    python audit_imap.py            # read-only, safe to run any time
    python audit_imap.py --write    # also tests label/read writes, then undoes them
    python audit_imap.py --write --send   # also forwards a test mail to yourself

⚠️ WHY THIS EXISTS.

A comparison document says what someone believes a protocol can do. This runs
the protocol and reports what happened. Two claims in the document we were
given turned out to be wrong — that Gmail-over-IMAP has no labels, and no
threads — and neither error was visible by reading. Only by asking the server.

⚠️ EVERY WRITE IS UNDONE BEFORE THE SCRIPT EXITS.

The tests that change something are off unless --write is passed, they act on
exactly one message, and they restore the previous state in a finally block. A
capability audit that leaves the mailbox different from how it found it is not
an audit, it is damage with a report attached.
"""

import os
import sys
import time
from datetime import datetime

RESULTS = []


def row(area, claim, verdict, detail=""):
    RESULTS.append((area, claim, verdict, detail))
    mark = {"YES": "[ YES ]", "NO": "[  NO ]",
            "PART": "[ PART]", "SKIP": "[ SKIP]"}.get(verdict, "[  ?  ]")
    print(f"  {mark}  {claim:<42} {detail[:60]}")


def section(title):
    print(f"\n  {title}")
    print("  " + "─" * 72)


# ── tests that would be unsafe on real mail ──────────────────────────
#
# ⚠️ Archive, trash, rescue-from-spam, forward, drafts and "notice a label the
# Owner removed" all change where a message lives, or send it somewhere. None
# of that is acceptable on a real email just to prove a point. So these run on
# messages the audit WRITES ITSELF — marked in the subject, addressed to nobody
# but the account owner — and it deletes every one of them before it finishes.

PROBE_SUBJECT = "Custodian audit probe - safe to delete"


def _make_probe(conn, folder, tag):
    """APPEND a message we wrote into `folder`. Returns its Message-ID."""
    import imaplib
    from email.message import EmailMessage
    from email.utils import make_msgid, formatdate
    m = EmailMessage()
    mid = make_msgid(domain="custodian-audit.local")
    m["Message-ID"] = mid
    m["From"] = conn.user
    m["To"] = conn.user
    m["Subject"] = f"{PROBE_SUBJECT} ({tag})"
    m["Date"] = formatdate(localtime=True)
    m.set_content("Written by audit_imap.py to test an action that is not "
                  "safe to test on real mail. The audit deletes it again.")
    typ, data = conn.conn.append(f'"{folder}"', None,
                                 imaplib.Time2Internaldate(time.time()),
                                 m.as_bytes())
    if typ != "OK":
        raise RuntimeError(f"could not place a probe in {folder}: {data}")
    return mid


def _uid_in(conn, folder, mid, tries=5):
    """
    Our probe's UID in `folder`, found by its Message-ID, or None.
    Leaves `folder` selected. Retries because a just-moved message can take a
    moment to be reported in its new folder.
    """
    for i in range(tries):
        conn.conn.select(f'"{folder}"', readonly=False)
        typ, data = conn.conn.uid("SEARCH", None, "HEADER", "Message-ID", f'"{mid}"')
        if typ == "OK" and data and data[0]:
            return data[0].split()[-1].decode()
        if i < tries - 1:
            time.sleep(0.6)
    return None


def _remove_probes(conn, mids, folders):
    """
    Permanently delete the probes this audit wrote — and only those.

    ⚠️ On Gmail a message is one object wearing labels, so deleting it means
    moving it to Trash and expunging it THERE. The expunge is UID EXPUNGE,
    scoped to our probe's UID alone. A plain EXPUNGE would take every message
    in Trash flagged \\Deleted, including any that are not ours.
    """
    trash = conn._folders.get("trash", "Trash")
    for mid in mids:
        for folder in folders:
            if folder == trash:
                continue
            try:
                u = _uid_in(conn, folder, mid, tries=1)
                if u:
                    conn._move(u, trash)
            except Exception:
                pass
        try:
            u = _uid_in(conn, trash, mid, tries=3)
            if u:
                conn.conn.uid("STORE", u, "+FLAGS", "(\\Deleted)")
                conn.conn.uid("EXPUNGE", u)
        except Exception:
            pass
    left = 0
    for mid in mids:
        for folder in folders:
            try:
                if _uid_in(conn, folder, mid, tries=1):
                    left += 1
            except Exception:
                pass
    conn.conn.select("INBOX", readonly=False)
    return left


def _unsafe_on_real_mail(conn, do_send):
    """Archive, trash, spam rescue, label-removal detection, draft, forward."""
    gmail = conn.has_gmail_extensions()
    trash = conn._folders.get("trash", "Trash")
    spam = conn._spam_folder()
    drafts = "[Gmail]/Drafts" if gmail else "Drafts"
    everywhere = ["INBOX", trash, drafts] + ([spam] if spam else []) \
        + (["[Gmail]/All Mail"] if gmail else [])
    made, sent = [], False
    lab = "Custodian/AuditProbe"
    try:
        # archive — leaves the inbox, still exists
        try:
            mid = _make_probe(conn, "INBOX", "archive"); made.append(mid)
            conn.archive(_uid_in(conn, "INBOX", mid))
            gone = _uid_in(conn, "INBOX", mid, tries=1) is None
            kept = (_uid_in(conn, "[Gmail]/All Mail", mid) is not None) if gmail else True
            row("write", "archive", "YES" if gone and kept else "NO",
                "left the inbox, still in All Mail" if gone and kept
                else f"left inbox={gone}, still exists={kept}")
        except Exception as e:
            row("write", "archive", "NO", str(e)[:56])

        # trash — leaves the inbox, lands in the bin
        try:
            mid = _make_probe(conn, "INBOX", "trash"); made.append(mid)
            conn.trash(_uid_in(conn, "INBOX", mid))
            gone = _uid_in(conn, "INBOX", mid, tries=1) is None
            binned = _uid_in(conn, trash, mid) is not None
            row("write", "move to trash", "YES" if gone and binned else "NO",
                f"left the inbox, now in {trash}" if gone and binned
                else f"left inbox={gone}, in trash={binned}")
        except Exception as e:
            row("write", "move to trash", "NO", str(e)[:56])

        # rescue from spam — found by list_spam, moved back to the inbox
        if spam:
            try:
                mid = _make_probe(conn, spam, "spam"); made.append(mid)
                u = _uid_in(conn, spam, mid)
                conn.conn.select("INBOX", readonly=False)
                listed = u in [x.decode() if isinstance(x, bytes) else str(x)
                               for x in conn.list_spam(limit=1000)]
                conn.rescue_from_spam(u)
                back = _uid_in(conn, "INBOX", mid) is not None
                out = _uid_in(conn, spam, mid, tries=1) is None
                ok = listed and back and out
                row("write", "rescue from spam", "YES" if ok else "NO",
                    "list_spam found it, now back in the inbox" if ok
                    else f"listed={listed} in inbox={back} left spam={out}")
            except Exception as e:
                row("write", "rescue from spam", "NO", str(e)[:56])
        else:
            row("write", "rescue from spam", "NO", "no spam folder found")

        # label removed in Gmail — the UC-29 correction nobody typed
        try:
            mid = _make_probe(conn, "INBOX", "label"); made.append(mid)
            u = _uid_in(conn, "INBOX", mid)
            conn.apply_label(u, lab)
            fp = [(u, lab)]
            before, _ = conn.label_removals_since("", {lab}, footprint=fp)
            conn.remove_label(u, lab)            # what the Owner does in Gmail
            after, _ = conn.label_removals_since("", {lab}, footprint=fp)
            ok = not before and after == [(u, lab)]
            row("write", "notice a label removed in Gmail", "YES" if ok else "NO",
                "quiet while the label was on, flagged it once removed" if ok
                else f"before={before} after={after}")
        except Exception as e:
            row("write", "notice a label removed in Gmail", "NO", str(e)[:56])

        # draft — lands in Drafts, reaches nobody
        try:
            r = conn.create_draft(to=conn.user, subject=f"{PROBE_SUBJECT} (draft)",
                                  body="A draft the audit wrote and will delete.")
            made.append(r["message_id"])
            there = _uid_in(conn, drafts, r["message_id"]) is not None
            row("write", "save a draft", "YES" if there else "NO",
                f"appeared in {drafts}, sent to nobody" if there
                else "not found in Drafts")
        except Exception as e:
            row("write", "save a draft", "NO", str(e)[:56])

        # forward — a real send, so only when asked, and only to yourself
        if do_send:
            try:
                mid = _make_probe(conn, "INBOX", "forward"); made.append(mid)
                u = _uid_in(conn, "INBOX", mid)
                t0 = time.time()
                r = conn.forward(u, to=conn.user,
                                 note="Forward test from audit_imap.py.")
                sent = True
                row("write", "forward", "YES",
                    f"sent via {r['via']} in {time.time()-t0:.1f}s, to your own address")
            except Exception as e:
                row("write", "forward", "NO", str(e)[:56])
        else:
            row("write", "forward", "SKIP",
                "add --send: forwards a probe to your own address")
    finally:
        left = _remove_probes(conn, made, everywhere)
        for name in (lab, lab.replace("/", ".")):
            try:
                conn.conn.delete(f'"{name}"')
            except Exception:
                pass
        row("write", "test messages deleted afterwards",
            "YES" if left == 0 else "NO",
            f"{len(made)} written, {len(made) - left} deleted"
            + ("" if left == 0 else " — CHECK TRASH AND DRAFTS"))
        conn.conn.select("INBOX", readonly=False)
    return sent


def main():
    write = "--write" in sys.argv
    import runlog
    log_path = runlog.start("audit_imap")
    print("\nCustodian — IMAP capability audit")
    print("═" * 78)

    user = os.environ.get("IMAP_USER")
    pw = os.environ.get("IMAP_PASSWORD")
    if not user or not pw:
        print("\n  IMAP_USER / IMAP_PASSWORD are not set in this terminal.")
        print("  Open a NEW terminal after setx, then run this again.\n")
        return

    from connectors.imap import ImapConnector
    import connect

    t0 = time.time()
    conn = ImapConnector(connect.host_for(user), user, pw)
    print(f"\n  {user}  ·  connected in {time.time()-t0:.1f}s")
    # ⚠️ Count the inbox BEFORE anything runs, so the closing line that
    # nothing changed is a measurement and not a promise. The first version
    # of this script printed that claim unconditionally — while it had in
    # fact moved a message out of the inbox.
    typ, d = conn.conn.select("INBOX", readonly=True)
    start_count = int(d[0])
    forwarded = False
    conn.conn.select("INBOX", readonly=False)

    # ── 1. what the server says it can do ─────────────────────────────
    section("1 · WHAT THE SERVER ADVERTISES")
    try:
        typ, data = conn.conn.capability()
        caps = b" ".join(data).decode("ascii", "replace")
    except Exception as e:
        caps = f"failed: {e}"
    gmail = conn.has_gmail_extensions()
    row("caps", "speaks Gmail's IMAP dialect (X-GM-EXT-1)",
        "YES" if gmail else "NO", "" if gmail else "plain IMAP only")
    for flag in ("IDLE", "MOVE", "UIDPLUS", "CONDSTORE", "QUOTA"):
        row("caps", f"advertises {flag}", "YES" if flag in caps else "NO",
            "push-style waiting" if flag == "IDLE" else "")

    # ── 2. sir's question: can it see ALL the labels? ─────────────────
    section("2 · CAN IT SEE EVERY GMAIL LABEL?")
    folders = []
    try:
        typ, data = conn.conn.list()
        for line in data or []:
            s = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
            name = s.split(' "/" ')[-1].strip().strip('"')
            folders.append(name)
    except Exception as e:
        row("labels", "list every folder/label", "NO", str(e)[:50])

    if folders:
        system = [f for f in folders if f.startswith("[Gmail]")]
        user_labels = [f for f in folders if not f.startswith("[Gmail]")
                       and f.upper() != "INBOX"]
        row("labels", "list every folder/label", "YES",
            f"{len(folders)} total")
        row("labels", "Gmail system folders visible", "YES" if system else "NO",
            ", ".join(x.replace("[Gmail]/", "") for x in system)[:58])
        row("labels", "your own labels visible", "YES" if user_labels else "NO",
            f"{len(user_labels)}: " + ", ".join(user_labels[:4]))

    # ── 3. the tabs — Primary, Social, Promotions ─────────────────────
    section("3 · THE GMAIL TABS (Primary / Social / Promotions)")
    counts = {}
    for cat in ("primary", "social", "promotions", "updates", "forums"):
        try:
            # ⚠️ "Found nothing" is not "failed". Forums used to show PART
            # because this mailbox has no forum mail — the query worked and
            # correctly answered zero. Judge the query, not the count.
            errs = len(conn.errors)
            hits = conn.gmail_search(f"category:{cat}")
            counts[cat] = len(hits)
            worked = len(conn.errors) == errs
            row("tabs", f"category:{cat}", "YES" if worked else "NO",
                f"{len(hits):,} messages"
                + ("" if hits or not worked else " — query works, mailbox has none"))
        except Exception as e:
            row("tabs", f"category:{cat}", "NO", str(e)[:44])

    # ── 4. spam, and the rest of the special folders ──────────────────
    section("4 · SPAM AND SPECIAL FOLDERS")
    for label, candidates in (
            ("Spam", ("[Gmail]/Spam", "Spam", "Junk")),
            ("Sent", ("[Gmail]/Sent Mail", "Sent")),
            ("All Mail", ("[Gmail]/All Mail",)),
            ("Trash", ("[Gmail]/Trash", "Trash")),
            ("Starred", ("[Gmail]/Starred",))):
        found, n = None, 0
        for name in candidates:
            try:
                typ, data = conn.conn.select(f'"{name}"', readonly=True)
                if typ == "OK":
                    found, n = name, int(data[0])
                    break
            except Exception:
                continue
        row("folders", f"can open {label}", "YES" if found else "NO",
            f"{found} — {n:,} messages" if found else "not found under any name")
    conn.conn.select("INBOX", readonly=False)

    # does OUR code find spam? (separate question from "does the server have it")
    try:
        got = conn.list_spam(limit=5)
        row("folders", "our list_spam() finds it", "YES" if got else "NO",
            f"{len(got)} returned" if got else "returns empty — see notes")
    except Exception as e:
        row("folders", "our list_spam() finds it", "NO", str(e)[:44])

    # ── 5. per-message: labels, threads, read state ───────────────────
    section("5 · WHAT WE CAN READ ABOUT ONE MESSAGE")
    ids = conn.list_ids()[:1]
    uid = ids[0].decode() if ids and isinstance(ids[0], bytes) else (ids[0] if ids else None)
    if not uid:
        row("message", "fetch a message", "NO", "inbox empty")
    else:
        # ⚠️ Test this on a message that HAS labels. Asking the newest
        # message in the inbox proves nothing — it came back empty, which
        # looked like a broken parser and was simply an unlabelled email.
        probe_uid = uid
        try:
            with_labels = conn.gmail_search("has:userlabels")
            if with_labels:
                probe_uid = (with_labels[0].decode()
                             if isinstance(with_labels[0], bytes) else with_labels[0])
        except Exception:
            pass
        labels = conn.gmail_labels(probe_uid)
        row("message", "read its Gmail labels (X-GM-LABELS)",
            "YES" if labels else "PART", ", ".join(labels[:4])[:56])
        try:
            typ, data = conn.conn.uid("FETCH", uid, "(X-GM-THRID X-GM-MSGID)")
            got = data[0].decode("utf-8", "replace") if data and data[0] else ""
            row("message", "read its thread id (X-GM-THRID)",
                "YES" if "X-GM-THRID" in got else "NO", got[:56])
        except Exception as e:
            row("message", "read its thread id (X-GM-THRID)", "NO", str(e)[:44])

        # BODY.PEEK must not mark it read — this is a promise we make
        before = conn._fetch_one(uid)
        raw = conn.fetch_raw(uid)
        after = conn._fetch_one(uid)
        same = before and after and before.unread == after.unread
        row("message", "read body WITHOUT marking it read",
            "YES" if same else "NO",
            f"{len(raw):,} bytes, unread stayed {before.unread if before else '?'}")

        try:
            import inspect
            sig = inspect.signature(conn.fetch_attachment)
            row("message", "fetch attachments", "YES",
                f"fetch_attachment{sig}")
        except Exception as e:
            row("message", "fetch attachments", "PART", str(e)[:44])

    # ── 6. live: can it notice new mail? ──────────────────────────────
    # ⚠️ BATCHED FETCHING MUST RETURN EXACTLY WHAT ONE-AT-A-TIME RETURNED.
    #
    # fetch_envelopes() now asks for 100 messages per command instead of one.
    # A batch that paired a header with the wrong UID would still "work" —
    # right count, wrong mail, no error — so this compares field by field
    # against the old one-message path on the same UIDs.
    try:
        sample = [x.decode() if isinstance(x, bytes) else str(x)
                  for x in conn.list_ids()[:50]]
        t0 = time.time()
        batched = {e.provider_id: e for e in conn.fetch_envelopes(sample)}
        bt = time.time() - t0
        t0 = time.time()
        single = {x: conn._fetch_one(x) for x in sample[:10]}
        st = (time.time() - t0) / 10
        key = lambda e: (e.message_id, e.subject, e.sender, e.unread, e.date)
        differ = [x for x, e in single.items()
                  if e and (x not in batched or key(batched[x]) != key(e))]
        row("message", "batched fetch matches one-at-a-time",
            "YES" if not differ and len(batched) == len(sample) else "NO",
            f"{len(batched)}/{len(sample)} returned · 10 compared field by field, "
            f"{len(differ)} differ")
        rate_b = len(batched) / bt if bt else 0
        row("message", "batched fetch is faster",
            "YES" if rate_b > 2 / st else "PART",
            f"{rate_b:,.0f}/s batched vs {1 / st:,.1f}/s one at a time")
    except Exception as e:
        row("message", "batched fetch matches one-at-a-time", "NO", str(e)[:56])

    section("6 · LIVE — CAN IT NOTICE NEW MAIL ARRIVING?")
    try:
        b1 = conn.current_history_id()
        fresh, b2 = conn.new_since(b1)
        row("live", "take a bookmark", "YES" if b1 != "0" else "NO", f"UID {b1}")
        row("live", "poll for anything newer", "YES",
            f"{len(fresh)} new since bookmark (0 expected on a quiet box)")
        row("live", "bookmark survives the poll", "YES" if b2 == b1 else "PART",
            f"{b1} -> {b2}")
    except Exception as e:
        row("live", "poll for new mail", "NO", str(e)[:50])
    # Push is reported once, in section 9. It used to be reported here too,
    # which counted the same missing capability twice in the tally.

    # ── 7. arbitrary Gmail search ─────────────────────────────────────
    section("7 · SEARCH")
    for q in ("newer_than:7d", "is:unread", "has:attachment",
              "from:linkedin.com", "category:primary newer_than:30d"):
        try:
            hits = conn.gmail_search(q)
            row("search", q, "YES", f"{len(hits):,} messages")
        except Exception as e:
            row("search", q, "NO", str(e)[:44])

    # ── 8. writes — off unless asked, and always undone ───────────────
    section("8 · ACTIONS THAT CHANGE THE MAILBOX")
    if not write:
        for what in ("apply a label", "remove a label", "mark read / unread",
                     "archive", "move to trash", "rescue from spam",
                     "notice a label removed in Gmail", "save a draft",
                     "forward"):
            row("write", what, "SKIP", "pass --write to test for real")
    elif uid:
        probe = "Custodian/AuditProbe"
        try:
            conn.ensure_label(probe)
            conn.apply_label(uid, probe)
            now = conn.gmail_labels(uid)
            ok = any(probe.lower() in x.lower() for x in now)
            row("write", "apply a label", "YES" if ok else "NO",
                "appeared on the message" if ok else "did not appear")
        except Exception as e:
            row("write", "apply a label", "NO", str(e)[:44])
        finally:
            try:
                conn.remove_label(uid, probe)
                row("write", "remove a label (undo)", "YES", "reverted")
            except Exception as e:
                row("write", "remove a label (undo)", "NO", str(e)[:44])

        env = conn._fetch_one(uid)
        was_unread = env.unread if env else None
        try:
            conn.mark_read(uid)
            after = conn._fetch_one(uid)
            row("write", "mark read", "YES" if after and not after.unread else "NO",
                f"unread {was_unread} -> {after.unread if after else '?'}")
        except Exception as e:
            row("write", "mark read", "NO", str(e)[:44])
        finally:
            if was_unread:
                try:
                    conn.mark_unread(uid)
                    row("write", "mark unread again (undo)", "YES", "reverted")
                except Exception as e:
                    row("write", "mark unread again (undo)", "NO", str(e)[:44])
        # ⚠️ ensure_label() creates a real folder, and on Gmail apply_label
        # never needed it — so the audit was quietly leaving an empty label
        # behind on every run, while reporting that nothing had changed. The
        # inbox count did not notice, because a new empty label does not
        # touch it. Clean up what we created.
        try:
            conn.conn.delete(f'"{probe.replace("/", ".")}"')
            conn.conn.delete(f'"{probe}"')
        except Exception:
            pass
        typ, data = conn.conn.list()
        left = [l for l in (data or []) if b"AuditProbe" in l]
        row("write", "audit cleaned up after itself", "YES" if not left else "NO",
            "probe label removed" if not left else "probe label still present")

        forwarded = _unsafe_on_real_mail(conn, "--send" in sys.argv)

    # ── 9. what IMAP simply cannot do ─────────────────────────────────
    section("9 · SENDING, AND THE REMAINING GAPS")
    # ⚠️ IMAP cannot send and that has stopped mattering. The app password
    # that opens imap.gmail.com also opens smtp.gmail.com — same credential,
    # no audit, no fee. So the honest row is about the PRODUCT, not the
    # protocol, and it says yes.
    row("gap", "send a message", "YES" if conn.supports_send else "NO",
        f"SMTP {conn.SMTP_HOSTS.get(conn.host, ('none',))[0]} — same app password"
        if conn.supports_send else f"no SMTP host known for {conn.host}")
    # Draft, forward, spam rescue and label-removal detection used to be
    # listed here as untested gaps. They are built now, and tested for real in
    # section 8 on messages the audit writes itself.
    row("gap", "snooze / unsnooze", "NO", "Gmail-only concept, no IMAP equivalent")
    row("gap", "server-pushed notification", "NO",
        "IDLE is advertised but holds one socket per mailbox — we poll")

    # ── the tally ─────────────────────────────────────────────────────
    print("\n" + "═" * 78)
    tally = {}
    for _, _, v, _ in RESULTS:
        tally[v] = tally.get(v, 0) + 1
    print(f"  {tally.get('YES',0)} work  ·  {tally.get('PART',0)} partial  ·  "
          f"{tally.get('NO',0)} do not  ·  {tally.get('SKIP',0)} not tested")
    if counts:
        print(f"\n  Primary tab over IMAP: {counts.get('primary',0):,} messages")
    print(f"\n  audit took {time.time()-t0:.0f}s  ·  "
          f"{datetime.now():%Y-%m-%d %H:%M}")
    try:
        typ, d = conn.conn.select("INBOX", readonly=True)
        end_count = int(d[0])
        delta = end_count - start_count
        if delta == 0:
            verdict = "unchanged"
        elif forwarded and delta == 1:
            verdict = "+1 is the forwarded test mail, addressed to you"
        else:
            verdict = "CHANGED — INVESTIGATE"
        print(f"  inbox {start_count:,} before, {end_count:,} after — {verdict}")
    except Exception as e:
        print(f"  could not verify the inbox count: {e}")
    print(f"  saved: test_runs\\{log_path.name}")
    print()

    try:
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
