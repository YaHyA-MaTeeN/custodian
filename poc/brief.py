"""
The daily brief — what actually needs you today.

    python brief.py              # today's brief, printed
    python brief.py --summarise  # add one-line summaries for the top few
    python brief.py --email      # send it to yourself instead (UC-31)
    python brief.py --days 3     # the last three days, not just the newest

⚠️ WHAT THIS DELIBERATELY DOES NOT DO: SUMMARISE THE WHOLE MAILBOX.

The obvious feature request is "summarise all my email". It is the wrong
feature, for two reasons that do not go away with a bigger budget:

  COST      This account has 7,859 messages. Summarising every one means
            7,859 paid calls to produce a wall of text nobody reads. At a
            million users that is 7.8 billion calls to answer a question
            nobody asked.

  USE       Old mail does not need answering. A summary of a newsletter you
            ignored 357 times is not information, it is noise with a cost.

So the brief summarises ONLY what survived the pipeline — the handful that
needs a reply — and the number is capped so the bill cannot surprise anyone.
Everything else is counted, not read.

That is the same principle as the rest of the system: spend the expensive
thing on the few items where nothing cheaper would do.
"""

import os
import sys
from datetime import datetime, timedelta

import connect
from store import Store
from pipeline import (stage02_strip, stage03_sensitive, stage04_headers,
                      stage09_gate, local_classifier)

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# ⚠️ A HARD CAP ON THE PAID PART. Not a suggestion — an upper bound on the
# bill for one brief. Whatever the mailbox does, this run cannot cost more.
MAX_SUMMARIES = 8


def line(ch="─", n=68):
    print(C["dim"] + ch * n + C["0"])


def one_line(text: str, subject: str) -> str:
    """One sentence. Only ever called for messages that already passed stage 9."""
    try:
        from pipeline import model, stage10_redact
        # ⚠️ Still through stage 10. A summary is text leaving the building
        # like any other, and it gets the same single door.
        redacted, mapping = stage10_redact.redact(stage10_redact.minimise(text, 1500))
        out = model._generate(
            "In ONE short sentence, say what this person wants. No preamble.\n\n"
            f"Subject: {subject}\n{redacted}")
        restored, leftover = stage10_redact.restore(out.strip(), mapping)
        return "(withheld — unresolved placeholder)" if leftover else restored
    except Exception as e:
        return f"(could not summarise: {str(e)[:40]})"


def send_digest(conn, lines, needs_you, machine, ignored, private, due):
    """
    UC-31 · one email, carrying everything that would otherwise need a screen.

    ⚠️ BR-112 — NOTHING TO REPORT MEANS NO MESSAGE AT ALL.
    Silence is a valid and correct output. A digest that arrives every week
    saying "nothing happened" trains people to ignore the one that matters.

    ⚠️ BR-111 — ONE message, batched. Never one per event. "Nothing would kill
    this product faster than becoming the customer's most frequent sender."
    """
    if not needs_you and not due:
        print(f"\n  {C['g']}Nothing needed your attention. No digest sent.{C['0']}")
        print(f"  {C['dim']}Silence is the correct output for a quiet week "
              f"(BR-112).{C['0']}\n")
        return

    # Most important first: anything needing a decision before anything
    # merely informing (UC-31, step 4.1). Complete in itself, so a reader
    # who never clicks through still gets the whole story (step 4.2).
    body = ["Your Custodian digest", "=" * 40, ""]
    if needs_you:
        body.append(f"{len(needs_you)} need a reply from you")
        body.append("")
        for env, sc, _ in sorted(needs_you, key=lambda x: -x[1]["act_probability"]):
            body.append(f"  * {env.subject or '(no subject)'}")
            body.append(f"    from {env.sender_name or env.sender}")
            body.append(f"    why: {sc['why']}")
            body.append("")
    if due:
        body.append(f"{len(due)} reminder(s) due")
        for _, _, kind, when, subject, why in due:
            body.append(f"  * {subject}  ({kind}, {when[:16]})")
        body.append("")
    from store import Store as _S
    extras = [strip_ansi(x) for x in extra_sections(_S())]
    if extras:
        body += extras + [""]
    body += ["-" * 40,
             "Handled without asking you:",
             f"  {machine} machine mail - the sender's headers said so",
             f"  {ignored} from senders you have never once opened",
             f"  {len(private)} sensitive - not opened, not read",
             "",
             "Nothing was sent, moved or deleted without your approval.",
             "python history.py shows everything, and reverses any of it."]

    me = conn.account_email()
    conn.send(to=me, subject="Your Custodian digest", body="\n".join(body))
    print(f"\n  {C['g']}digest sent to {me}{C['0']}")
    print(f"  {C['dim']}One message, not one per event (BR-111).{C['0']}\n")


def strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def extra_sections(store) -> list:
    """
    UC-31 step 2 — what the digest carries besides "needs a reply":
    promises coming due (UC-45), requests still open (UC-33), unread-and-
    important (UC-36, reported once), unsubscribe outcomes (UC-17), and
    what the Owner's rules did. Each line is complete on its own — a reader
    who never clicks through still gets the whole story.
    """
    from datetime import datetime, timedelta
    out = []
    proms = [r for r in store.open_requests("promise")]
    soon = [r for r in proms if r[5] and r[5][:10] <= (datetime.now() + timedelta(days=3)).date().isoformat()]
    if soon:
        out.append(f"{C['b']}{len(soon)} promise{'s' if len(soon)>1 else ''} you made come due within 3 days{C['0']}")
        for r in soon[:4]:
            out.append(f"   · you told {r[4][:22]}: {r[3][:44]}  {C['dim']}{r[5][:10]}{C['0']}")
    asks = [r for r in store.open_requests("ask") if r[4] == "me"]
    if asks:
        out.append(f"{C['b']}{len(asks)} request{'s' if len(asks)>1 else ''} of you still open{C['0']}")
        for r in asks[:4]:
            out.append(f"   · {(r[9] or r[8] or '')[:20]}: {r[3][:44]}  {C['dim']}{r[5][:10] or 'no date'}{C['0']}")
    try:
        from today import unread_important
        stale = unread_important(store)
    except Exception:
        stale = []
    if stale:
        out.append(f"{C['b']}{len(stale)} important message{'s' if len(stale)>1 else ''} still unread{C['0']}")
        for mid, sender, sname, subject, date in stale[:4]:
            days = (datetime.now() - datetime.fromisoformat(date[:19])).days if date else 0
            out.append(f"   · {(subject or '')[:40]}  {C['dim']}{(sname or sender)[:18]}, {days} days{C['0']}")
            store.mark_reported(mid, "unread_important")          # once, never again (BR-135)
    ign = store.unsubscribes("ignoring")
    stopped = store.unsubscribes("stopped")
    if ign or stopped:
        out.append(f"{C['b']}Unsubscribes:{C['0']} {len(stopped)} stopped, {len(ign)} ignoring the request"
                   + (" — " + ", ".join(r[0] for r in ign[:3]) if ign else ""))
    rules = store.rules()
    if rules:
        out.append(f"{C['dim']}{len(rules)} rule{'s' if len(rules)>1 else ''} in force. "
                   f"python rules.py shows them.{C['0']}")
    return out


def main():
    want_summaries = "--summarise" in sys.argv or "--summarize" in sys.argv
    want_email = "--email" in sys.argv
    # How far back to look. Not a storage question — we re-read from Gmail,
    # which costs 5 quota units a message and nothing in money.
    days = 1
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        if i + 1 < len(sys.argv) and sys.argv[i+1].isdigit():
            days = int(sys.argv[i+1])

    print(f"\n{C['b']}Your brief{C['0']}  {C['dim']}{datetime.now():%A %d %B, %H:%M}{C['0']}")
    line("═")

    conn = connect.open_mailbox()
    store = Store()
    me = conn.account_email()
    print(f"  {me}")

    inbox = store.one("SELECT COUNT(*) FROM messages WHERE in_inbox = 1")
    unread = store.one("SELECT COUNT(*) FROM messages WHERE in_inbox=1 AND unread=1")

    # ── the last day's arrivals ────────────────────────────────────────
    rows = store.q("""SELECT provider_id, message_id, sender, sender_name,
                             sender_domain, subject, date, bulk, unsubscribe,
                             one_click, auto_sub, in_reply_to, unread, size
                        FROM messages WHERE in_inbox = 1
                       ORDER BY date_iso DESC LIMIT ?""", 60 * days)
    if not rows:
        print("\n  nothing stored. Run  python run.py  first.\n")
        sys.exit(1)

    from connectors.base import Envelope
    needs_you, machine, ignored, private = [], 0, 0, []

    for r in rows:
        (pid, mid, sender, sname, domain, subject, date, bulk, unsub,
         one_click, auto_sub, in_reply_to, is_unread, size) = r
        env = Envelope(provider_id=pid, message_id=mid, sender=sender,
                       sender_name=sname or "", sender_domain=domain or "",
                       subject=subject or "", date=date or "", size=size or 0,
                       unread=bool(is_unread), bulk=bool(bulk),
                       unsubscribe=unsub or "", one_click=bool(one_click),
                       auto_submitted=auto_sub or "", in_reply_to=in_reply_to or "")

        if stage03_sensitive.check(sender, subject or "", domain or "")["sensitive"]:
            private.append(env)
            continue

        facts = stage04_headers.read(env)
        hist = store.history(sender, me)

        if stage04_headers.engagement_exit(hist["sent"], hist["opened"])["exit"]:
            ignored += 1
            continue
        if facts["machine_generated"]:
            machine += 1
            continue

        labels = None
        if local_classifier.available():
            try:
                # Checked on arrival, so a summary is never of the wrong email.
                raw = connect.fetch_verified(conn, pid, env.message_id)
                text = stage02_strip.strip(raw)["text"]
                labels = local_classifier.classify(text, subject or "", sender)
            except Exception:
                text = ""
        else:
            text = ""

        sc = stage09_gate.score(labels or {"intent": "no response needed",
                                           "topic": "other", "confidence": 0.0},
                                facts, hist, env)
        if sc["needs_reply"]:
            needs_you.append((env, sc, text))

    # ── what needs you ─────────────────────────────────────────────────
    print()
    if needs_you:
        print(f"  {C['b']}{len(needs_you)} need{'s' if len(needs_you)==1 else ''} "
              f"a reply from you{C['0']}\n")
        for i, (env, sc, text) in enumerate(sorted(
                needs_you, key=lambda x: -x[1]["act_probability"]), 1):
            already = store.already_replied(env.message_id)
            mark = f"{C['g']}answered{C['0']}" if already else f"{C['y']}open{C['0']}"
            print(f"  {i}. {C['b']}{(env.subject or '(no subject)')[:54]}{C['0']}")
            print(f"     {C['dim']}from {env.sender_name or env.sender} · "
                  f"{sc['act_probability']:.2f} · {mark}{C['0']}")
            if want_summaries and i <= MAX_SUMMARIES and text and not already:
                print(f"     {C['c']}→ {one_line(text, env.subject)[:88]}{C['0']}")
        if want_summaries and len(needs_you) > MAX_SUMMARIES:
            print(f"\n  {C['dim']}summarised the top {MAX_SUMMARIES} only — "
                  f"the cap is there so one brief cannot run up a bill.{C['0']}")
    else:
        print(f"  {C['g']}Nothing needs a reply.{C['0']}")

    # ── overdue and upcoming ───────────────────────────────────────────
    due = store.due_reminders()
    if due:
        print(f"\n  {C['b']}{len(due)} reminder{'s' if len(due)>1 else ''} due{C['0']}\n")
        for _, _, kind, when, subject, why in due:
            print(f"  · {subject[:52]}  {C['dim']}{kind} · {when[:16]}{C['0']}")

    # ── the sections the digest carries (UC-31 step 2) ─────────────────
    for line_ in extra_sections(store):
        print(f"  {line_}")

    # ── everything else, counted not read ──────────────────────────────
    print(f"\n  {C['dim']}{'─'*58}{C['0']}")
    print(f"  {C['dim']}Handled without asking you:{C['0']}")
    print(f"     {machine:>4}  machine mail — the sender's headers said so")
    print(f"     {ignored:>4}  from senders you have never once opened")
    if private:
        print(f"     {len(private):>4}  {C['r']}sensitive — not opened, not read{C['0']}")
        for env in private[:3]:
            print(f"           {C['dim']}{env.sender}{C['0']}")

    print(f"\n  {C['dim']}Mailbox: {inbox:,} in the inbox, {unread:,} unread.{C['0']}")
    if want_email:
        send_digest(conn, None, needs_you, machine, ignored, private, due)
    elif not want_summaries and needs_you:
        print(f"  {C['dim']}python brief.py --summarise   adds one line each "
              f"for the top {MAX_SUMMARIES}.{C['0']}")
        print(f"  {C['dim']}python brief.py --email       send it to yourself "
              f"instead.{C['0']}")
    print()


if __name__ == "__main__":
    main()
