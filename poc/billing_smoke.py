"""
The whole subscription life, through the API, against the real database.

    python billing_smoke.py        (needs DATABASE_URL)

A throwaway account goes: no card → trial → cleanup locked → day 7 →
confirm → active → upgrade now → downgrade scheduled → renewal applies the
downgrade on the same billing day → a failed renewal pauses → actions
refused → restore → cancel → runs to the period end → ended, mailboxes
disconnected. Time is moved by handing billing.tick() a later "now".
No money moves: the NullProvider approves every card except the token "fail".
"""

import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone

if not os.environ.get("DATABASE_URL"):
    print("DATABASE_URL is not set"); sys.exit(1)
os.environ.pop("STRIPE_SECRET_KEY", None)

from fastapi.testclient import TestClient
import api
api.NO_MAILBOX = True
c = TestClient(api.app)
import billing
from pg_store import PgStore
db = PgStore().conn

email = f"bill-{int(time.time())}@example.invalid"
aid = db.execute("INSERT INTO accounts (email, confirmed_at) VALUES (%s, now()) RETURNING id", (email,)).fetchone()[0]
mb = db.execute("INSERT INTO mailboxes (account_id, address, provider, route) VALUES (%s,%s,'gmail','app_password') RETURNING id",
                (aid, f"box-{aid}@example.invalid")).fetchone()[0]
tok = secrets.token_urlsafe(32)
db.execute("INSERT INTO sessions (token, account_id, expires_at) VALUES (%s,%s,%s)", (tok, aid, datetime.now(timezone.utc) + timedelta(hours=2)))
db.commit()
h = {"Authorization": f"Bearer {tok}"}
now = datetime.now(timezone.utc)
ok_all = True


def show(label, r, want):
    global ok_all
    good = r.status_code == want
    ok_all &= good
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    extra = body.get("state") or body.get("detail") or body.get("when") or ""
    print(f"{'ok ' if good else 'BAD'} {r.status_code}  {label:46} {str(extra)[:70]}")
    return body


def state():
    return billing.status(aid)


show("status with no subscription", c.get("/api/billing", headers=h), 200)
show("start trial without a card (400)", c.post("/api/billing/start", headers=h, json={"card": ""}), 400)
show("clear the pile with no subscription (402)", c.post("/api/pile/clear", headers=h, json={"all": True, "confirm": "x"}), 402)
show("start trial with a card", c.post("/api/billing/start", headers=h, json={"card": "tok_visa", "plan": "personal"}), 200)
show("clear during trial: locked (402)", c.post("/api/pile/clear", headers=h, json={"all": True, "confirm": "x"}), 402)
show("unsubscribe during trial: locked (402)", c.post("/api/unsubscribe", headers=h, json={"sender": "a@b.c", "confirm": "x"}), 402)
print("   ", state()["message"])

billing.tick(now + timedelta(days=8))
print(f"    day 8 → {state()['state']}  (no charge was made: {not any(e['kind']=='activated' for e in billing.events(aid))})")
show("confirm on day 7 (first charge)", c.post("/api/billing/confirm", headers=h), 200)
p1 = state()["periodEnd"]
show("clear when active: past the gate (409 = token)", c.post("/api/pile/clear", headers=h, json={"all": True, "confirm": "x"}), 409)

show("upgrade to work: now", c.post("/api/billing/plan", headers=h, json={"plan": "work"}), 200)
print(f"    plan {state()['plan']} · billing date unchanged: {state()['periodEnd'] == p1}")
show("downgrade to personal: scheduled", c.post("/api/billing/plan", headers=h, json={"plan": "personal"}), 200)
print(f"    plan still {state()['plan']} · next {state()['nextPlan']} · billing date unchanged: {state()['periodEnd'] == p1}")

pe = datetime.fromisoformat(p1)
billing.tick(pe + timedelta(hours=1))
s2 = state()
print(f"    after renewal → plan {s2['plan']} · next {s2['nextPlan']} · same day of month: {datetime.fromisoformat(s2['periodEnd']).day == pe.day}")

# a card that declines at the next renewal
db.execute("UPDATE subscriptions SET customer=%s WHERE account_id=%s", (f"null_{aid}_fail", aid)); db.commit()
pe2 = datetime.fromisoformat(s2["periodEnd"])
billing.tick(pe2 + timedelta(hours=1))
print(f"    failed renewal → {state()['state']} · mailbox still connected: "
      f"{db.execute('SELECT state FROM mailboxes WHERE id=%s', (mb,)).fetchone()[0] == 'connected'}")
print("   ", state()["message"])
show("send while paused (402)", c.post("/api/messages/x/send", headers=h, json={"body": "hi", "confirm": "x"}), 402)
show("restore with the same card (402)", c.post("/api/billing/restore", headers=h, json={}), 402)
show("restore with a new card", c.post("/api/billing/restore", headers=h, json={"card": "tok_new"}), 200)

show("cancel without the word (409)", c.post("/api/billing/cancel", headers=h, json={}), 409)
show("cancel", c.post("/api/billing/cancel", headers=h, json={"confirm": "cancel"}), 200)
s3 = state()
print(f"    {s3['state']} · still usable: {s3['canClean']} · until {s3['cancelAt'][:10]}")
show("change my mind", c.post("/api/billing/keep", headers=h), 200)
show("cancel again", c.post("/api/billing/cancel", headers=h, json={"confirm": "cancel"}), 200)
billing.tick(datetime.fromisoformat(state()["cancelAt"]) + timedelta(hours=1))
print(f"    after the period → {state()['state']} · mailbox: {db.execute('SELECT state FROM mailboxes WHERE id=%s', (mb,)).fetchone()[0]}")
show("clear after it ended (402)", c.post("/api/pile/clear", headers=h, json={"all": True, "confirm": "x"}), 402)

# the 15-day rule on its own
billing.start_trial(aid, "tok_fail"); billing.tick(now + timedelta(days=8))
db.execute("UPDATE subscriptions SET state='active', period_end=%s WHERE account_id=%s", (now, aid))
db.execute("UPDATE mailboxes SET state='connected' WHERE id=%s", (mb,)); db.commit()
billing.tick(now + timedelta(hours=1))
g = state()
billing.tick(now + timedelta(days=14)); mid = state()["state"]
billing.tick(now + timedelta(days=16, hours=2))
print(f"    declined → {g['state']} · day 14 → {mid} · day 16 → {state()['state']} · mailbox: "
      f"{db.execute('SELECT state FROM mailboxes WHERE id=%s', (mb,)).fetchone()[0]}")

show("where my data is stored", c.get("/api/privacy/region", headers=h), 200)
show("move without the word (409)", c.post("/api/privacy/region", headers=h, json={"to": "eu-central"}), 409)
show("request a move to Europe", c.post("/api/privacy/region", headers=h, json={"to": "eu-central", "confirm": "move"}), 200)
show("a second move while one is open (409)", c.post("/api/privacy/region", headers=h, json={"to": "ap-southeast", "confirm": "move"}), 409)

print("    events:", " → ".join(e["kind"] for e in reversed(billing.events(aid, 40))))
db.execute("DELETE FROM accounts WHERE id=%s", (aid,)); db.commit()
print("cleaned up" + ("" if ok_all else "   *** some steps did not return the expected code ***"))
