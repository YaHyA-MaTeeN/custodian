import sys
sys.argv = ["api.py", "--no-mailbox"]
import api
from fastapi.testclient import TestClient
c = TestClient(api.app)
print("store backend:", type(api.store()).__name__)
for p in ("/api/health", "/api/overview", "/api/messages?view=reply", "/api/today",
          "/api/pile", "/api/activity", "/api/typed-rules", "/api/privacy"):
    r = c.get(p)
    print(p, r.status_code, str(r.json())[:72])

print("--- mailbox registration ---")
import connect
conn = connect.open_mailbox(quiet=True)
s = api.store()
for row in s.mailboxes():
    print("mailbox:", row[0], row[1], row[2], "access:", row[3], "state:", row[4])
