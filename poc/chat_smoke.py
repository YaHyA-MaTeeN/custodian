"""
The chat, end to end, on the local copy.

    python chat_smoke.py            (needs GEMINI_API_KEY; CUSTODIAN_STORE=sqlite for the local file)

Sends real sentences through /api/chat and prints what came back. Gated
answers must come with a confirm token and a route, never an action taken.
"""

import os
import sys
import time

os.environ.setdefault("CUSTODIAN_STORE", "sqlite")
from fastapi.testclient import TestClient
import api
api.NO_MAILBOX = True                     # mode 2 reads only bodies already stored
c = TestClient(api.app)

import api as _api
_s = _api.store()
_me = os.environ.get("IMAP_USER", "").lower()
# ⚠️ No real names in this file. The person and the bulk sender are picked
# from whichever mailbox is being tested (or set SMOKE_PERSON / SMOKE_SENDER).
_p = _s.q("""SELECT sender_name FROM messages WHERE bulk=0 AND unsubscribe='' AND sender_name!='' AND sender!=?
             GROUP BY sender_name ORDER BY COUNT(*) DESC LIMIT 1""", _me)
_b = _s.q("""SELECT sender_name FROM messages WHERE unsubscribe!='' AND sender_name!=''
             GROUP BY sender_name ORDER BY COUNT(*) DESC LIMIT 1""")
PERSON = os.environ.get("SMOKE_PERSON") or (_p[0][0] if _p else "someone")
SENDER = os.environ.get("SMOKE_SENDER") or (_b[0][0] if _b else "newsletter")

SENTENCES = [
    f"anything from {SENDER} this week?",
    f"has {PERSON} replied to me?",
    "who is waiting on me?",
    "what did I promise people?",
    "what needs my attention today",
    f"clear the {SENDER} mail",
    f"unsubscribe me from {SENDER}",
    f"mark {PERSON} as important",
    f"put everything from {SENDER} under Reading",
    f"remind me about the latest {SENDER} message on friday",
    f"what did {PERSON} ask me to do?",
    f"what did the last email from {PERSON} say?",
    "what is taking up space in my mailbox?",
    "which companies send me the most junk?",
    f"clear {SENDER}'s advertising",
    "what did I miss in the last 30 days?",
    f"tell me about {PERSON}",
    f"forward {PERSON}'s emails to me@example.com",
    "how do my replies sound?",
    "turn the digest off",
    "what's on my calendar today?",
    "what is the weather tomorrow",
]

hist = []
for s in SENTENCES:
    t = time.time()
    r = c.post("/api/chat", json={"text": s, "history": hist[-4:]})
    dt = time.time() - t
    j = r.json() if r.status_code == 200 else {"reply": r.text}
    print(f"\nyou > {s}")
    print(f"[{r.status_code} · {j.get('intent','?'):11} · {dt:4.1f}s]" + ("  gated → " + j["action"]["route"] if j.get("action") else ""))
    for line in str(j.get("reply", "")).split("\n")[:6]:
        print("   ", line[:110])
    hist += [{"role": "user", "text": s}, {"role": "assistant", "text": str(j.get("reply", ""))[:200]}]
