"""
UC-34 for everyone who is not on Google: the CalDAV calendar.

iCloud, Yahoo, Zoho, Fastmail and most company servers publish the person's
calendar over CalDAV, and accept the SAME app password the mailbox already
uses. So connecting the mailbox connects the calendar: no second sign-in.

    Google   → calendar_sync.py (one-time Google sign-in, calendar scope only)
    Outlook  → needs the Microsoft app registration (Graph), not CalDAV
    others   → this file

⚠️ TWO ABILITIES ONLY: READ TODAY, ADD ONE EVENT. There is deliberately no
method here that changes, moves or deletes an event (BR-124). Anything we
add stays the person's; we never touch it again. Adding happens only after
the person said yes to that exact event (BR-221). No invites are sent
(BR-127): events are created with no attendees.

⚠️ NOTHING IS KEPT. Today's events are fetched, shown, and discarded (BR-125).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

CALDAV_HOSTS = {
    "icloud.com": "https://caldav.icloud.com/",
    "me.com":     "https://caldav.icloud.com/",
    "mac.com":    "https://caldav.icloud.com/",
    "yahoo.com":  "https://caldav.calendar.yahoo.com/",
    "zoho.com":   "https://calendar.zoho.com/",
    "zohomail.com": "https://calendar.zoho.com/",
    "fastmail.com": "https://caldav.fastmail.com/",
}
NOT_CALDAV = {
    "gmail.com": "google", "googlemail.com": "google",
    "outlook.com": "microsoft", "hotmail.com": "microsoft", "live.com": "microsoft", "msn.com": "microsoft",
}


def route_for(address: str) -> str:
    """'caldav' | 'google' | 'microsoft' for an email address."""
    domain = (address or "").rsplit("@", 1)[-1].lower()
    return NOT_CALDAV.get(domain, "caldav")


def url_for(address: str) -> str:
    """The CalDAV server for an address. CALDAV_URL overrides (company servers, tests)."""
    if os.environ.get("CALDAV_URL"):
        return os.environ["CALDAV_URL"]
    domain = (address or "").rsplit("@", 1)[-1].lower()
    return CALDAV_HOSTS.get(domain, f"https://{domain}/")      # RFC 6764 discovery from the domain


class CalDAVCalendar:
    """One person's calendar. Read today; add after a yes. Nothing else."""

    def __init__(self, url: str, username: str, password: str):
        import caldav
        self._client = caldav.DAVClient(url=url, username=username, password=password, timeout=30)
        self.username = username
        principal = self._client.principal()
        cals = principal.calendars()
        if not cals:
            raise LookupError("this account has no calendar")
        # the first calendar that holds events; the person's default on every server we know
        self._cal = next((c for c in cals if "VEVENT" in (self._components(c) or ["VEVENT"])), cals[0])

    @staticmethod
    def _components(cal):
        try:
            return cal.get_supported_components()
        except Exception:
            return None

    def name(self) -> str:
        try:
            return self._cal.get_display_name() or "calendar"
        except Exception:
            return "calendar"

    def today(self, day: datetime = None) -> list:
        """[(when, title)] for one day, cancelled and declined events left out."""
        start = (day or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        out = []
        for ev in self._cal.search(start=start, end=end, event=True, expand=True):
            comp = ev.icalendar_component
            if str(comp.get("STATUS", "")).upper() == "CANCELLED":
                continue
            me_declined = False
            for att in (comp.get("ATTENDEE") or []) if isinstance(comp.get("ATTENDEE"), list) else \
                       ([comp.get("ATTENDEE")] if comp.get("ATTENDEE") else []):
                who = str(att).lower().replace("mailto:", "")
                if who == self.username.lower() and str(att.params.get("PARTSTAT", "")).upper() == "DECLINED":
                    me_declined = True
            if me_declined:
                continue
            dt = comp.get("DTSTART").dt
            when = dt.strftime("%Y-%m-%d %H:%M") if isinstance(dt, datetime) else f"{dt.isoformat()} all day"
            out.append((when, str(comp.get("SUMMARY", "(no title)"))))
        return sorted(out)

    def add(self, title: str, start: datetime, minutes: int = 60) -> str:
        """Create one event. No attendees, so no invite goes anywhere. Returns its UID."""
        from icalendar import Calendar, Event
        uid = f"custodian-{uuid.uuid4()}"
        cal = Calendar()
        cal.add("prodid", "-//Custodian//calendar//EN")
        cal.add("version", "2.0")
        ev = Event()
        ev.add("uid", uid)
        ev.add("summary", title)
        ev.add("description", "Added by Custodian after your approval.")
        ev.add("dtstamp", datetime.now(timezone.utc))
        ev.add("dtstart", start)
        ev.add("dtend", start + timedelta(minutes=minutes))
        cal.add_component(ev)
        self._cal.save_event(cal.to_ical().decode())
        return uid


def open_for(address: str, password: str) -> CalDAVCalendar:
    return CalDAVCalendar(url_for(address), address, password)
