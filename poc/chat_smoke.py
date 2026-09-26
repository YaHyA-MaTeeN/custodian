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

SENTENCES = [
    "anything from linkedin this week?",
    "has dua fatima replied to me?",
    "who is waiting on me?",
    "what did I promise people?",
    "what needs my attention today",
    "clear the linkedin job alerts",
    "unsubscribe me from linkedin job alerts",
    "mark dua fatima as important",
    "put everything from linkedin under Jobs",
    "remind me about the latest linkedin message on friday",
    "what did javeria hunain ask me to do?",
    "what did the google workspace email say?",
    "what is taking up space in my mailbox?",
    "which companies send me the most junk?",
    "clear linkedin's advertising",
    "what did I miss in the last 30 days?",
    "tell me about javeria hunain",
    "forward javeria hunain's emails to me@example.com",
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
