import os, json, sys
os.environ["CUSTODIAN_STORE"] = "sqlite"
from fastapi.testclient import TestClient
import api
c = TestClient(api.app)
def show(label, r):
    body = r.text[:160].replace("\n", " ")
    print(f"{r.status_code:>3}  {label:42} {body}")
show("GET /api/me", c.get("/api/me"))
show("GET /api/today", c.get("/api/today"))
show("GET /api/brands", c.get("/api/brands"))
show("GET /api/unsubscribe", c.get("/api/unsubscribe"))
show("GET /api/storage", c.get("/api/storage"))
show("GET /api/catchup", c.get("/api/catchup"))
show("GET /api/search?q=invoice", c.get("/api/search?q=invoice"))
show("GET /api/recipients", c.get("/api/recipients"))
show("GET /api/voice", c.get("/api/voice"))
show("GET /api/digest/settings", c.get("/api/digest/settings"))
show("GET /api/calendar/suggestions", c.get("/api/calendar/suggestions"))
show("GET /api/mailboxes", c.get("/api/mailboxes"))
show("POST identify", c.post("/api/mailboxes/identify", json={"address": "someone@gmail.com"}))
# the gate: preview gives a token; clear without it is refused; wrong token refused
r = c.post("/api/pile/preview", json={"all": True}); show("POST /api/pile/preview", r)
tok = r.json().get("confirm", "")
show("POST /api/pile/clear (no token)", c.post("/api/pile/clear", json={"all": True}))
show("POST /api/pile/clear (bad token)", c.post("/api/pile/clear", json={"all": True, "confirm": "x"}))
show("POST /api/unsubscribe (no token)", c.post("/api/unsubscribe", json={"sender": "a@b.c"}))
show("POST /api/forward-batch (no token)", c.post("/api/forward-batch", json={"messageIds": [], "to": "me@x.com"}))
show("POST /api/forward-batch (from mail addr)", c.post("/api/forward-batch/preview", json={"messageIds": [], "to": "not an address"}))
show("POST send (no token)", c.post("/api/messages/abc/send", json={"body": "hi"}))
show("POST typed-rules (no token)", c.post("/api/typed-rules", json={"sentence": "label x as y"}))
show("DELETE mailbox (no confirm)", c.request("DELETE", "/api/mailboxes/x@y.z", json={}))
# a real message for quick + person + thread
import store as st
s = api.store()
row = s.q("SELECT provider_id, message_id, sender FROM messages WHERE in_inbox=1 ORDER BY date_iso DESC LIMIT 1")[0]
show("GET quick", c.get(f"/api/messages/{row[0]}/quick"))
show("GET people/<addr>", c.get(f"/api/people/{row[2]}"))
show("GET threads/<mid>", c.get(f"/api/threads/{row[1]}"))
show("POST reminders (past date)", c.post("/api/reminders", json={"messageId": row[1], "on": "2020-01-01"}))
show("POST reminders (bad msg)", c.post("/api/reminders", json={"messageId": "nope", "on": "tomorrow"}))
