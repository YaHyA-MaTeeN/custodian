"""
UC-34 — Your calendar, both ways: read today, add what you approve.

    python calendar_sync.py --connect        # one-time Google sign-in, CALENDAR ONLY
    python calendar_sync.py --today          # today's events, for the morning plan
    python calendar_sync.py --suggest        # important dates from your mail we could add
    python calendar_sync.py --add 2          # add suggestion 2 (asks first)
    python calendar_sync.py --disconnect

⚠️ READING AND ADDING ARE TWO JOBS. Reading shows the day in the plan and
the details are discarded (BR-125) — we keep no calendar archive, exactly as
we keep no mail archive. Adding puts an event in only after "Add this?" —
yes (BR-221). We never move, change, cancel or delete an event (BR-124), and
we never email an invite (BR-127).

⚠️ WHAT COUNTS AS IMPORTANT (BR-219): deadlines someone asks of you (UC-33),
promises you made with a date (UC-45), confirmed bookings and bill due dates
(UC-23). Never sales, webinars or newsletters — and never anything from spam
or mail flagged suspicious (BR-220). A No is remembered so the same item is
never asked about again.

⚠️ GMAIL ON AN APP PASSWORD (BR-222). Mail stays on the app password; the
calendar needs a one-time Google sign-in for the calendar scope only. That
scope is "sensitive", not "restricted", so it needs Google's review but not
the paid annual security assessment Gmail's mail scope does — confirm before
budgeting (UC-34 open question). This is not the mail upgrade in UC-12.

Other providers (iCloud, Yahoo, Zoho, company servers) speak CalDAV with the
same app password: calendar_caldav.py. connected() / today_events() /
add_event() below choose the right one, so callers never need to know which.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# Calendar only. Not gmail.modify, not gmail.send, not calendar.readonly —
# we need to ADD approved events, so view-and-edit (UC-34 "Permissions").
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN = Path("calendar_token.json")          # separate from mail's token.json
DECLINED = Path("calendar_declined.json")    # a No is kept (BR-221)


def service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request()); refreshed = True
            except Exception:
                pass
        if not refreshed:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds)


def today(svc) -> list:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    r = svc.events().list(calendarId="primary", timeMin=start.isoformat() + "Z",
                          timeMax=end.isoformat() + "Z", singleEvents=True,
                          orderBy="startTime").execute()
    out = []
    for e in r.get("items", []):
        if e.get("status") == "cancelled":
            continue                                          # step 6.2
        me = next((a for a in e.get("attendees", []) if a.get("self")), None)
        if me and me.get("responseStatus") == "declined":
            continue
        s = e.get("start", {})
        out.append((s.get("dateTime", s.get("date", ""))[:16].replace("T", " "),
                    e.get("summary", "(no title)")))
    return out


def declined(store=None) -> set:
    """Suggestions the person said No to. Kept per account in the store; the
    file is the single-user fallback from before."""
    try:
        out = set(json.loads(DECLINED.read_text(encoding="utf-8")))
    except Exception:
        out = set()
    if store is not None:
        out |= {r[0] for r in store.q("SELECT message_id FROM reported WHERE kind='calendar_declined'")}
    return out


def decline(store, key: str) -> None:
    store.mark_reported(key, "calendar_declined")


# ── which calendar: CalDAV (most providers) or Google ───────────────────

def _caldav_login(address: str = "", password: str = ""):
    """(address, password) for CalDAV in single-user mode, or ("", "")."""
    import calendar_caldav
    address = address or os.environ.get("CALDAV_USER") or os.environ.get("IMAP_USER", "")
    password = password or os.environ.get("CALDAV_PASSWORD") or os.environ.get("IMAP_PASSWORD", "")
    if not address or not password:
        return "", ""
    if calendar_caldav.route_for(address) != "caldav" and not os.environ.get("CALDAV_URL"):
        return "", ""
    return address, password


def backend(address: str = "", password: str = ""):
    """
    ('caldav', calendar) | ('google', service) | ('microsoft', None) | (None, None).
    CalDAV first, because it needs nothing beyond the mailbox's own password.
    """
    import calendar_caldav
    a, pw = _caldav_login(address, password)
    if a:
        return "caldav", calendar_caldav.open_for(a, pw)
    target = address or os.environ.get("IMAP_USER", "")
    if TOKEN.exists():
        return "google", service()
    if calendar_caldav.route_for(target) == "microsoft":
        return "microsoft", None
    return None, None


def connected(address: str = "", password: str = "") -> bool:
    if _caldav_login(address, password)[0]:
        return True
    return TOKEN.exists()


def today_events(address: str = "", password: str = "") -> list:
    kind, cal = backend(address, password)
    if kind == "caldav":
        return cal.today()
    if kind == "google":
        return today(cal)
    return []


def add_event(store, key: str, title: str, start: datetime, address: str = "", password: str = "") -> str:
    """Add one approved event, record it, never ask about it again. Returns the event id."""
    kind, cal = backend(address, password)
    if kind == "caldav":
        ev_id = cal.add(title, start)
    elif kind == "google":
        body = {"summary": title, "description": "Added by Custodian after your approval.",
                "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": (start + timedelta(hours=1)).isoformat(), "timeZone": "UTC"}}
        ev_id = cal.events().insert(calendarId="primary", body=body).execute().get("id", "")
    else:
        raise LookupError("no calendar connected")
    store.record_action("", "", "calendar_add", title[:70], before=ev_id)
    decline(store, key)                       # added: never suggested again
    return ev_id


def suggestions(store) -> list:
    """(key, title, date_iso, source) — only from the sources BR-219 allows."""
    out, seen = [], declined(store)
    for mid, pid, kind, due, subject, why in store.pending_reminders():
        key = f"reminder:{mid}"
        if key in seen or not due:
            continue
        # BR-220: nothing from spam or suspicious mail. A reminder only exists
        # for mail that passed stage 3 and stage 4, so this is already true.
        out.append((key, f"{subject[:50]} ({kind})", str(due)[:19], "commitment from your mail"))
    for r in store.open_requests():
        rid, mid, direction, what, who, due, *_ = r
        if not due:
            continue
        key = f"request:{rid}"
        if key in seen:
            continue
        label = "you promised: " if direction == "promise" else "asked of you: "
        out.append((key, (label + what)[:60], due[:19], "deadline from your mail"))
    return sorted(out, key=lambda x: x[2])


def main():
    store = Store()
    args = sys.argv[1:]
    if "--disconnect" in args:
        if TOKEN.exists():
            TOKEN.unlink()
        print("\n  calendar disconnected. Events already added stay in your calendar.\n"); return
    if "--connect" in args:
        svc = service()
        print(f"\n  {C['g']}calendar connected.{C['0']} We will read your events and add only "
              f"important events you approve. We never move, change or delete an event.\n")
        return
    if "--suggest" in args or "--add" in args:
        sug = suggestions(store)
        if not sug:
            print("\n  nothing to suggest — no dated commitment or request is open.\n"); return
        print(f"\n{C['b']}Important dates from your mail{C['0']}")
        print("─" * 66)
        for i, (key, title, date, src) in enumerate(sug, 1):
            print(f"  {i:>2}. {date[:16].replace('T',' ')}  {title:52} {C['dim']}{src}{C['0']}")
        if "--add" in args:
            n = int(args[args.index("--add") + 1])
            if not 1 <= n <= len(sug):
                print("\n  no such suggestion.\n"); return
            key, title, date, src = sug[n - 1]
            print(f"\n  Add ‘{title} – {date[:16].replace('T',' ')}’ to your calendar?")
            try:
                typed = input("  [yes / no]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                typed = "no"
            if typed != "yes":
                d = declined(); d.add(key)
                DECLINED.write_text(json.dumps(sorted(d)), encoding="utf-8")
                print("  not added, and we will not ask about this one again.\n"); return
            add_event(store, key, title, datetime.fromisoformat(date[:19]))
            print(f"  {C['g']}added.{C['0']} We will never change or delete it — that is yours.\n")
        else:
            print(f"\n  {C['dim']}python calendar_sync.py --add N   adds one, after your yes.{C['0']}\n")
        return
    # --today, or no flag
    if not connected():
        print("\n  calendar not connected.  python calendar_sync.py --connect\n"); return
    try:
        evs = today_events()
    except Exception as e:
        print(f"\n  {C['y']}calendar isn't responding. Your mail features still work.{C['0']} "
              f"{C['dim']}({str(e)[:50]}){C['0']}\n"); return
    print(f"\n{C['b']}Today{C['0']}")
    print("─" * 66)
    if not evs:
        print("  no events today.")
    for when, title in evs:
        print(f"  {when[-5:] if ' ' in when else 'all day':>7}  {title[:56]}")
    print(f"\n  {C['dim']}Read for the plan and discarded. We keep no calendar archive.{C['0']}\n")


if __name__ == "__main__":
    main()
