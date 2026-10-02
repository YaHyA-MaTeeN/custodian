"""
The CalDAV calendar, end to end, against a real CalDAV server on this machine.

    python calendar_smoke.py

Starts Radicale (a standard CalDAV server) on a free local port with a
throwaway user, seeds four events, then drives the API and the chat:
today's list must show only the live event; adding needs the confirm token
for that exact event; an added event lands on the server with no attendees;
a declined suggestion is never offered again; the calendar object has no
way to change or delete an event. Everything is removed afterwards.

Uses the local single-user store, so it needs no database or mailbox.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

os.environ["CUSTODIAN_STORE"] = "sqlite"
USER, PW = "tester@example.com", "calendar-test-pw"

tmp = tempfile.mkdtemp(prefix="caldav-")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
open(os.path.join(tmp, "users"), "w").write(f"{USER}:{PW}\n")
server = subprocess.Popen([sys.executable, "-m", "radicale",
                           "--server-hosts", f"127.0.0.1:{port}",
                           "--storage-filesystem-folder", os.path.join(tmp, "store"),
                           "--auth-type", "htpasswd",
                           "--auth-htpasswd-filename", os.path.join(tmp, "users"),
                           "--auth-htpasswd-encryption", "plain",
                           "--logging-level", "error"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
url = f"http://127.0.0.1:{port}/"
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
    except OSError:
        time.sleep(0.2)

os.environ.update({"CALDAV_URL": url, "CALDAV_USER": USER, "CALDAV_PASSWORD": PW})
ok_all = True


def check(label, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'}  {label:52} {str(extra)[:70]}")


try:
    import caldav
    # ── seed ───────────────────────────────────────────────────────────
    client = caldav.DAVClient(url=url, username=USER, password=PW)
    cal = client.principal().make_calendar(name="Personal")
    now = datetime.now().replace(second=0, microsecond=0)
    t10 = now.replace(hour=10, minute=0); t14 = now.replace(hour=14, minute=0); t16 = now.replace(hour=16, minute=0)

    def ics(uid, summary, start, extra=""):
        return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//seed//EN\r\nBEGIN:VEVENT\r\n"
                f"UID:{uid}\r\nDTSTAMP:{start:%Y%m%dT%H%M%S}\r\nDTSTART:{start:%Y%m%dT%H%M%S}\r\n"
                f"DTEND:{start + timedelta(hours=1):%Y%m%dT%H%M%S}\r\nSUMMARY:{summary}\r\n{extra}"
                "END:VEVENT\r\nEND:VCALENDAR\r\n")
    cal.save_event(ics("seed-1", "Dentist", t10))
    cal.save_event(ics("seed-2", "Team lunch (cancelled)", t14, "STATUS:CANCELLED\r\n"))
    cal.save_event(ics("seed-3", "Vendor call (declined)", t16,
                       f"ORGANIZER:mailto:boss@example.com\r\nATTENDEE;PARTSTAT=DECLINED:mailto:{USER}\r\n"))
    cal.save_event(ics("seed-4", "Tomorrow's thing", t10 + timedelta(days=1)))
    print(f"     CalDAV server on {url}, calendar 'Personal', 4 events seeded\n")

    # ── provider routing ───────────────────────────────────────────────
    import calendar_caldav as cc
    saved = os.environ.pop("CALDAV_URL")
    check("iCloud address → CalDAV at caldav.icloud.com", cc.route_for("a@icloud.com") == "caldav" and "icloud" in cc.url_for("a@icloud.com"))
    check("Yahoo address → CalDAV", cc.route_for("a@yahoo.com") == "caldav" and "yahoo" in cc.url_for("a@yahoo.com"))
    check("Gmail address → Google route", cc.route_for("a@gmail.com") == "google")
    check("Outlook address → Microsoft route", cc.route_for("a@outlook.com") == "microsoft")
    os.environ["CALDAV_URL"] = saved

    # ── no change, no delete, by construction ──────────────────────────
    c2 = cc.open_for(USER, PW)
    check("calendar object cannot delete or change events",
          not any(hasattr(c2, m) for m in ("delete", "update", "move", "change", "remove", "edit")),
          [m for m in dir(c2) if not m.startswith("_")])

    # ── through the API ────────────────────────────────────────────────
    from fastapi.testclient import TestClient
    import api
    api.NO_MAILBOX = True
    c = TestClient(api.app)
    store = api.store()

    r = c.get("/api/calendar/today").json()
    titles = [e["title"] for e in r.get("events", [])]
    check("today: connected", r.get("connected") is True)
    check("today: shows the live event", "Dentist" in titles, titles)
    check("today: leaves out the cancelled one", not any("cancelled" in t for t in titles))
    check("today: leaves out the one you declined", not any("declined" in t for t in titles))
    check("today: leaves out tomorrow", "Tomorrow's thing" not in titles)

    sug = c.get("/api/calendar/suggestions").json()["suggestions"]
    check("suggestions from mail, each with wording + token", sug and all(s.get("confirm") for s in sug), f"{len(sug)} suggestion(s)")
    if not sug:
        raise SystemExit("no dated commitment in the local store to suggest; scan some mail first")
    first = sug[0]
    r1 = c.post("/api/calendar/add", json={"key": first["key"]})
    check("add without the token: refused (409)", r1.status_code == 409, r1.json().get("detail"))
    r2 = c.post("/api/calendar/add", json={"key": first["key"], "confirm": "wrong"})
    check("add with a wrong token: refused (409)", r2.status_code == 409)
    r3 = c.post("/api/calendar/add", json={"key": first["key"], "confirm": first["confirm"]})
    check("add with the token for this event: added (200)", r3.status_code == 200, first["title"])
    added_uid = r3.json().get("eventId", "")

    found = [e for e in cal.events() if str(e.icalendar_component.get("UID")) == added_uid]
    comp = found[0].icalendar_component if found else None
    check("the event is on the CalDAV server", bool(found), added_uid)
    check("…with the suggested title", comp is not None and str(comp.get("SUMMARY")) == first["title"])
    check("…and no attendees, so no invite went anywhere", comp is not None and not comp.get("ATTENDEE"))

    again = c.get("/api/calendar/suggestions").json()["suggestions"]
    check("an added suggestion is not offered again", all(s["key"] != first["key"] for s in again))
    if again:
        d = c.post("/api/calendar/decline", json={"key": again[0]["key"]})
        after = c.get("/api/calendar/suggestions").json()["suggestions"]
        check("a declined suggestion is not offered again", d.status_code == 200 and all(s["key"] != again[0]["key"] for s in after))
        declined_key = again[0]["key"]
    else:
        declined_key = ""

    # ── through the chat ───────────────────────────────────────────────
    ch = c.post("/api/chat", json={"text": "what's on my calendar today?"}).json()
    check("chat: 'what's on my calendar today?' lists the event", ch.get("intent") == "calendar" and "Dentist" in ch.get("reply", ""),
          ch.get("reply", "").split("\n")[1] if "\n" in ch.get("reply", "") else ch.get("reply", ""))

    # ── leave the local store as it was ────────────────────────────────
    for k in (first["key"], declined_key):
        if k:
            store.db.execute("DELETE FROM reported WHERE message_id=? AND kind='calendar_declined'", (k,))
    store.db.execute("DELETE FROM actions WHERE action='calendar_add' AND before=?", (added_uid,))
    store.db.commit()
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except Exception:
        server.kill()
    shutil.rmtree(tmp, ignore_errors=True)

print("\ncleaned up" + ("" if ok_all else "   *** some checks failed ***"))
