"""
The mailbox — every account, one place. The thing sir asked to build first.

    python mailbox.py                # the list
    python mailbox.py --warm         # pull the last 30 days of important mail
    python mailbox.py --open 4       # open message 4 — fetched live if needed
    python mailbox.py --primary      # only Gmail's Primary tab
    python mailbox.py --imap         # through the IMAP door instead

⚠️ THE SHAPE OF THIS, AND WHY IT IS NOT "STORE EVERYTHING".

    everything, ever      HEADERS ONLY — sender, subject, date, account
    last 30 days          headers + the body, but only for mail worth reading
    anything older        the body is fetched LIVE when the Owner opens it

A ten-year mailbox is 100,000 messages and roughly 10 GB of text. Holding all
of it to make a list scroll is paying storage rent on mail the Owner will never
reopen. Holding thirty days of the mail that mattered is a few megabytes.

⚠️ AND THE PART THAT MAKES THAT HONEST.

"We delete after 30 days" written in a policy is an intention. `trim_bodies()`
runs on every open of this view, so the window cannot widen through neglect.
The retention rule is code, and it executes whether or not anyone remembers it.

⚠️ WHY "IMPORTANT" IS NOT OUR OPINION.

The 30-day fetch does not keep everything from 30 days — it keeps what the
pipeline judged worth reading. On Gmail we can go further and ask for the
Primary tab itself, which is Google's own sorting, not ours. Measured on this
account: 1,747 primary out of 9,395 categorised.
"""

import os
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import connect
from store import Store
from pipeline import stage02_strip, stage03_sensitive, stage04_headers

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

WINDOW_DAYS = 30
ACCOUNT_COLOURS = [C["c"], C["g"], C["y"], C["r"]]


def arg_after(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default


def when(value: str):
    """Accepts our ISO column first, an RFC header second."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:19])
    except Exception:
        pass
    try:
        d = parsedate_to_datetime(value)
        return d if d.tzinfo is None else d.replace(tzinfo=None)
    except Exception:
        return None


def rows_for(store, primary_only=False, limit=200):
    """Headers. Always headers — this is the cheap part and it covers everything."""
    # ⚠️ auto_sub and unsubscribe are SELECTed because stage 4 reads them.
    # Building an Envelope without them meant every message looked human-sent
    # and non-bulk — so seven bounce notifications were judged "worth keeping"
    # and their bodies cached. A partial envelope does not fail loudly; it
    # produces a confident wrong answer.
    q = """SELECT message_id, provider_id, sender, sender_name, subject,
                  COALESCE(NULLIF(date_iso,''), date), unread,
                  COALESCE(account,'(unknown)'), categories, bulk,
                  auto_sub, unsubscribe, one_click, in_reply_to
             FROM messages WHERE in_inbox = 1
              ORDER BY date_iso DESC, date DESC LIMIT ?"""
    rows = store.q(q, limit * 3)
    if primary_only:
        # Gmail stamps its own tab on the envelope. Where it is missing we do
        # not guess — a row we cannot classify stays in the list rather than
        # being hidden by an assumption.
        rows = [r for r in rows if "Personal" in (r[8] or "") or not (r[8] or "")]
    seen, out = set(), []
    for r in rows:                      # BR-99 — one message, shown once
        if r[0] and r[0] in seen:
            continue
        if r[0]:
            seen.add(r[0])
        out.append(r)
    return out[:limit]


def worth_keeping(store, env, facts) -> bool:
    """
    ⚠️ Which of the last 30 days' mail is worth holding the body for.

    Not a category we invented — the same three questions the pipeline already
    asks. If it would not survive stage 3 or stage 4, its body is not worth
    the disk it would sit on.
    """
    if stage03_sensitive.check(env.sender, env.subject, env.sender_domain)["sensitive"]:
        return False                    # never held, by design
    if facts["machine_generated"]:
        return False
    # ⚠️ Auto-replies and bounces are machine mail that stage 4 deliberately
    # does NOT call machine-generated — an out-of-office from a colleague is
    # still worth reading, so the pipeline keeps them.
    #
    # But holding the TEXT of seven "Delivery Status Notification (Failure)"
    # messages is disk spent on nothing. Whether to read a thing and whether
    # to keep a copy of it are separate questions, and this is the second one.
    if facts.get("auto_reply"):
        return False
    hist = store.history(env.sender)
    if stage04_headers.engagement_exit(hist["sent"], hist["opened"])["exit"]:
        return False
    return True


def warm(conn, store):
    """Pull the bodies for the window. The only bulk fetch in the whole view."""
    print(f"\n{C['b']}Warming the last {WINDOW_DAYS} days{C['0']}")
    print("─" * 74)

    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)
    rows = rows_for(store, limit=400)
    from connectors.base import Envelope

    kept = skipped = 0
    for r in rows:
        (mid, pid, sender, sname, subject, date, unread, account, cats,
         bulk, auto_sub, unsub, one_click, in_reply_to) = r
        d = when(date)
        if not d or d < cutoff:
            continue                    # outside the window — headers only
        if store.has_body(mid):
            continue

        env = Envelope(provider_id=pid, message_id=mid, sender=sender,
                       sender_name=sname or "",
                       sender_domain=(sender or "").split("@")[-1],
                       subject=subject or "", date=date or "",
                       unread=bool(unread), bulk=bool(bulk), account=account,
                       auto_submitted=auto_sub or "", unsubscribe=unsub or "",
                       one_click=bool(one_click), in_reply_to=in_reply_to or "")
        facts = stage04_headers.read(env)
        if not worth_keeping(store, env, facts):
            skipped += 1
            continue
        try:
            # Opened by fingerprint and checked on arrival, so the text cached
            # under this message is this message's text (connect.fetch_verified).
            text = stage02_strip.strip(connect.fetch_verified(conn, pid, mid))["text"]
            if text.strip():
                store.cache_body(mid, pid, account, text)
                kept += 1
                print(f"  {C['g']}+{C['0']} {(subject or '')[:56]}")
        except Exception as e:
            print(f"  {C['y']}!{C['0']} could not fetch: {str(e)[:44]}")

    st = store.body_stats()
    print("─" * 74)
    print(f"  {kept} body(ies) pulled · {skipped} skipped as not worth reading")
    print(f"  holding {st['count']} bodies, {st['mb']:.2f} MB")
    print(f"  {C['dim']}Everything older than {WINDOW_DAYS} days stays "
          f"headers-only and is fetched when opened.{C['0']}\n")


def open_one(conn, store, n: int, primary_only=False):
    """
    Open one message. From cache if it is in the window, live if it is not.

    ⚠️ THE POINT OF THIS FUNCTION IS THE SECOND CASE.

    A three-year-old email opens in about two seconds because the provider
    still has it and always did. That is why holding ten years of text would
    buy us nothing but a storage bill.
    """
    rows = rows_for(store, primary_only, limit=200)
    if not 1 <= n <= len(rows):
        print(f"\n  no message {n}. There are {len(rows)}.\n")
        return
    (mid, pid, sender, sname, subject, date, unread, account, cats,
     bulk, auto_sub, unsub, one_click, in_reply_to) = rows[n - 1]

    print(f"\n{C['b']}{subject or '(no subject)'}{C['0']}")
    print(f"{C['dim']}from {sname or sender}  ·  {account}  ·  {(date or '')[:31]}{C['0']}")
    print("─" * 74)

    sens = stage03_sensitive.check(sender, subject or "", (sender or "").split("@")[-1])
    if sens["sensitive"]:
        print(f"  {C['r']}Not opened.{C['0']} {sens['reasons'][0]}")
        print(f"  {C['dim']}This message is never read by us, from cache or live.{C['0']}\n")
        return

    t0 = datetime.now()
    text = store.body(mid)
    if text:
        source = f"{C['g']}from the 30-day cache{C['0']}"
    else:
        try:
            text = stage02_strip.strip(connect.fetch_verified(conn, pid, mid))["text"]
            ms = (datetime.now() - t0).total_seconds()
            source = f"{C['c']}fetched live in {ms:.1f}s{C['0']} — never stored"
        except Exception as e:
            print(f"  could not fetch: {str(e)[:60]}\n")
            return

    for line in text.strip()[:1800].splitlines()[:30]:
        if line.strip():
            print(f"  {line.strip()[:88]}")
    if len(text) > 1800:
        print(f"  {C['dim']}… {len(text)-1800:,} more characters{C['0']}")
    print("─" * 74)
    print(f"  {source}\n")


def show(store, conn, primary_only=False):
    removed = store.trim_bodies(WINDOW_DAYS)      # retention, enforced in code
    rows = rows_for(store, primary_only)
    accounts = sorted({r[7] for r in rows})
    colour = {a: ACCOUNT_COLOURS[i % len(ACCOUNT_COLOURS)]
              for i, a in enumerate(accounts)}

    total = store.one("SELECT COUNT(*) FROM messages")
    st = store.body_stats()

    title = "Mailbox — Primary only" if primary_only else "Mailbox — everything"
    print(f"\n{C['b']}{title}{C['0']}")
    print("─" * 74)
    for a in accounts:
        n = store.one("SELECT COUNT(*) FROM messages WHERE account=?", a)
        print(f"  {colour[a]}●{C['0']} {a:<36} {n:>7,} messages")
    print(f"  {C['dim']}{total:,} headers held · {st['count']} bodies cached "
          f"({st['mb']:.2f} MB){C['0']}")
    if removed:
        print(f"  {C['dim']}{removed} body(ies) past {WINDOW_DAYS} days deleted "
              f"just now{C['0']}")
    print("─" * 74)

    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)
    for i, r in enumerate(rows[:30], 1):
        (mid, pid, sender, sname, subject, date, unread, account, cats,
         bulk, auto_sub, unsub, one_click, in_reply_to) = r
        d = when(date)
        inside = bool(d and d >= cutoff)
        if store.has_body(mid):
            mark = f"{C['g']}●{C['0']}"          # body held
        elif inside:
            mark = f"{C['y']}○{C['0']}"          # in window, not pulled
        else:
            mark = f"{C['dim']}·{C['0']}"        # headers only, fetch on open
        flag = C["b"] if unread else C["dim"]
        print(f" {i:>3} {mark} {colour.get(account, C['dim'])}▏{C['0']}"
              f"{flag}{(subject or '(no subject)')[:44]:<44}{C['0']} "
              f"{C['dim']}{(sname or sender)[:20]:<20} {(date or '')[:16]}{C['0']}")

    print("─" * 74)
    print(f"  {C['g']}●{C['0']} body held   "
          f"{C['y']}○{C['0']} in the {WINDOW_DAYS}-day window, not pulled   "
          f"{C['dim']}·{C['0']} headers only — fetched when opened")
    print(f"\n  {C['dim']}python mailbox.py --open 4     open one "
          f"(live fetch if it is old){C['0']}")
    print(f"  {C['dim']}python mailbox.py --warm       pull the window's "
          f"bodies{C['0']}")
    print(f"  {C['dim']}python mailbox.py --primary    Gmail's Primary tab "
          f"only{C['0']}\n")


def main():
    store = Store()
    conn = connect.open_mailbox()
    primary = "--primary" in sys.argv

    if "--warm" in sys.argv:
        return warm(conn, store)
    n = arg_after("--open")
    if n and n.isdigit():
        return open_one(conn, store, int(n), primary)
    show(store, conn, primary)


if __name__ == "__main__":
    main()
