"""
The chat: a sentence in, a plain answer out, over the features that exist.

⚠️ THE MODEL READS THE QUESTION. OUR CODE PRODUCES THE ANSWER.

Mode 1, look-up.  Gemini maps the sentence (names hidden) to ONE item on a
                  fixed menu with its inputs. Our code runs that feature on
                  our data and writes the reply from a template.
Mode 2, read.     Only when the question is about what an email SAYS. Our
                  search finds the messages, their text goes through the same
                  redact → model → restore path drafting uses, and the model
                  answers in words. Nothing it did not receive can be in the
                  answer.
Not found.        When neither mode has anything, the reply says so. Never a
                  guess.

⚠️ THE CHAT NEVER EXECUTES ANYTHING IRREVERSIBLE. For clear, unsubscribe,
send and rules it returns the same preview wording and confirm token the
matching route expects, plus the route to call. The person's yes goes
through that route and its gate, exactly like a button would.

⚠️ WHAT THE USER TYPES IS AN INSTRUCTION; WHAT AN EMAIL SAYS IS DATA. Email
text only ever reaches the model inside mode 2's answer prompt, where it is
labelled as a document to read, and the intent step never sees it.
"""

import re
from datetime import datetime, timedelta

from pipeline import model, prompts, stage02_strip, stage03_sensitive, stage10_redact, stage13_approval

MENU = {
    "search":      "find messages: who (a person or sender), words (in the subject), days (how far back)",
    "replied":     "has a person replied to me / am I waiting on them: who",
    "waiting":     "what people are waiting on ME for (open requests of me)",
    "promised":    "what I promised other people",
    "today":       "what needs attention today",
    "remind":      "set a follow-up reminder: who or words to find the message, when",
    "important":   "mark a person as important: who",
    "rule":        "a standing rule in the person's own words: sentence",
    "clear":       "clear / trash / archive bulk mail from a sender: who",
    "unsubscribe": "stop a sender's mailings: who",
    "draft":       "draft a reply to a person's latest message: who",
    "read":        "a question about what an email actually SAYS (did I attend, what did they decide, what is the price): question, who, words, days",
    "storage":     "what is taking up space / largest emails / reclaim storage",
    "brands":      "which companies send the most bulk mail, or clear one company's advertising: company",
    "catchup":     "catch up after time away / what did I miss / summary of what arrived: days",
    "person":      "everything about one person (their addresses, what is owed both ways, recent mail): who",
    "forward":     "forward messages to someone: who (whose messages), words, to (the recipient address the user typed)",
    "voice":       "how my drafts sound / my writing voice / make my replies shorter, more formal, etc.: sentence",
    "digest":      "the weekly summary email: turn it on or off, or change how often: when (daily, weekly, monthly, never)",
    "calendar":    "what is on my calendar today, or dates from mail worth adding",
    "unknown":     "none of the above, or not about the person's mail",
}
ARGS = ("who", "words", "days", "when", "sentence", "question", "to", "company")
GENERIC = {"the", "a", "an", "junk", "spam", "bulk", "company", "companies", "brand", "brands", "most", "mail", "email",
           "emails", "newsletters", "advertising", "ads", "senders", "everything", "all", "me", "my"}

RULE_SHAPE = re.compile(r"^(please\s+)?((put|move|file|label|send|keep).+(under|into|in|as|to)|always|never|from now on|whenever)")

# Nouns that name one feature and nothing else. Seen in the sentence, they
# settle the intent without a model call: cheaper, and never misrouted.
KEYWORDS = (("digest", "digest"), ("weekly summary", "digest"), ("calendar", "calendar"),
            ("unsubscribe", "unsubscribe"), ("storage", "storage"), ("taking up space", "storage"),
            ("writing voice", "voice"), ("my voice", "voice"))


def _clean(v):
    return (v or "").strip() if isinstance(v, str) else v


# ── people ───────────────────────────────────────────────────────────────

def resolve_person(store, who: str) -> dict:
    """
    {"address", "name"} | {"domain", "name"} | {"ambiguous": [(name, address), ...]} | {}.

    Order: an address · an exact sender name · a company (several senders
    share the domain, e.g. "linkedin") · a name containing all the words.
    A clear winner is 3x as frequent as the runner-up; otherwise ask.
    """
    who = _clean(who).lower().strip('"\'')
    who = re.sub(r"^(the|from|mr|ms|mrs)\s+", "", who).strip()
    if not who:
        return {}
    if "@" in who:
        row = store.q("SELECT sender, MAX(sender_name) FROM messages WHERE sender=? GROUP BY sender", who)
        return {"address": who, "name": (row[0][1] if row else "") or who}
    exact = store.q("SELECT sender, MAX(sender_name), COUNT(*) FROM messages WHERE LOWER(sender_name)=? "
                    "GROUP BY sender ORDER BY COUNT(*) DESC LIMIT 2", who)
    if exact:
        return {"address": exact[0][0], "name": exact[0][1] or exact[0][0]}
    if " " not in who:
        dom = store.q("SELECT sender_domain, COUNT(DISTINCT sender), COUNT(*) FROM messages "
                      "WHERE sender_domain LIKE ? GROUP BY sender_domain ORDER BY COUNT(*) DESC LIMIT 1", f"%{who}%")
        if dom and dom[0][1] >= 2:
            return {"domain": dom[0][0], "name": dom[0][0]}
    words = [w for w in re.split(r"\s+", who) if w]
    sql = ("SELECT sender, MAX(sender_name), COUNT(*) FROM messages WHERE "
           + " AND ".join("(LOWER(sender_name) LIKE ? OR sender LIKE ?)" for _ in words)
           + " GROUP BY sender ORDER BY COUNT(*) DESC LIMIT 8")
    args = [x for w in words for x in (f"%{w}%", f"%{w}%")]
    rows = store.q(sql, *args)
    if not rows:
        return {}
    people = {}
    for addr, name, n in rows:
        key = store.person_of(addr) if hasattr(store, "person_of") else addr
        p = people.setdefault(key, {"address": addr, "name": name or addr, "n": 0})
        p["n"] += n
    ranked = sorted(people.values(), key=lambda p: -p["n"])
    if len(ranked) == 1 or ranked[0]["n"] >= 3 * max(1, ranked[1]["n"]):
        return {"address": ranked[0]["address"], "name": ranked[0]["name"]}
    return {"ambiguous": [(p["name"], p["address"]) for p in ranked[:4]]}


# ── the intent step ──────────────────────────────────────────────────────

def read_intent(text: str, history: list, known_names: list) -> dict:
    """Gemini picks one menu item. Names hidden on the way out, restored on the way back."""
    redacted, mapping = stage10_redact.redact(text, known_names)
    turns = []
    for h in (history or [])[-4:]:
        t, _ = stage10_redact.redact(str(h.get("text", ""))[:300], known_names)
        turns.append(f"{h.get('role', 'user')}: {t}")
    menu = "\n".join(f"- {k}: {v}" for k, v in MENU.items())
    prompt = prompts.get("chat_intent", menu=menu, history="\n".join(turns) or "(none)", text=redacted)
    try:
        out = model._json_from(model._generate(prompt))
    except Exception as e:
        return {"intent": "unknown", "args": {}, "error": str(e)[:80]}
    intent = str(out.get("intent", "unknown")).lower().strip()
    if intent not in MENU:
        intent = "unknown"
    args = {}
    for k in ARGS:
        v = out.get(k)
        if isinstance(v, str):
            v, _ = stage10_redact.restore(v, mapping)
            args[k] = v.strip()
        elif v is not None:
            args[k] = v
    return {"intent": intent, "args": args}


# ── helpers ──────────────────────────────────────────────────────────────

def _since(days) -> str:
    try:
        d = int(days)
    except (TypeError, ValueError):
        d = 0
    return (datetime.now() - timedelta(days=d)).isoformat()[:19] if d > 0 else ""


def find_messages(store, who="", words="", days=None, limit=5, address="", domain="") -> list:
    """(message_id, provider_id, sender, sender_name, subject, date_iso, sender_domain, account)"""
    sql = ("SELECT message_id, provider_id, sender, sender_name, subject, date_iso, sender_domain, COALESCE(account,'') "
           "FROM messages WHERE 1=1")
    args = []
    if address:
        sql += " AND sender=?"; args.append(address.lower())
    elif domain:
        sql += " AND sender_domain=?"; args.append(domain.lower())
    elif who:
        like = f"%{who.lower()}%"
        sql += " AND (LOWER(sender_name) LIKE ? OR sender LIKE ?)"; args += [like, like]
    if words:
        sql += " AND LOWER(subject) LIKE ?"; args.append(f"%{words.lower()}%")
    s = _since(days)
    if s:
        sql += " AND date_iso > ?"; args.append(s)
    sql += " ORDER BY date_iso DESC LIMIT ?"; args.append(limit)
    return store.q(sql, *args)


def _line(r) -> str:
    mid, pid, sender, name, subject, date, *_ = r
    return f"{(date or '')[:10]}  {(name or sender)[:24]}: {(subject or '(no subject)')[:60]}"


def _item(r) -> dict:
    mid, pid, sender, name, subject, date, *_ = r
    return {"messageId": mid, "providerId": pid, "sender": sender, "senderName": name,
            "subject": subject, "date": (date or "")[:16]}


# ── the handlers ─────────────────────────────────────────────────────────

def handle(store, me: str, text: str, history: list = None, body_of=None, known_names=None) -> dict:
    """
    One chat turn. Returns {reply, intent, items?, action?, confirm?, wording?}.

    body_of(message_id, provider_id) -> str | ""   fetches text for mode 2
    (the API passes one that opens the right mailbox; None means only the
    bodies already in the store can be read).
    """
    text = (text or "").strip()
    if not text:
        return {"reply": "Type something and I'll look.", "intent": "unknown"}
    known_names = known_names or []
    low = text.lower()
    hit = next((i for k, i in KEYWORDS if k in low), "")
    if hit in ("digest", "calendar", "storage", "voice"):
        it = {"intent": hit, "args": {"when": low, "sentence": text}}
    elif RULE_SHAPE.search(low):
        # "put X under Y", "always …", "never touch …": a standing rule, in the
        # person's own words. rules.interpret reads the whole sentence itself.
        it = {"intent": "rule", "args": {"sentence": text}}
    else:
        it = read_intent(text, history or [], known_names)
        if hit == "unsubscribe" and it["intent"] in ("clear", "unknown", "search"):
            it["intent"] = "unsubscribe"
    intent, a = it["intent"], it["args"]
    me = (me or "").lower()

    def person(allow_domain=False):
        p = resolve_person(store, a.get("who", ""))
        if p.get("domain") and not allow_domain:
            # a company, not a person: a sender-level action needs its busiest sender
            row = store.q("SELECT sender, MAX(sender_name), COUNT(*) FROM messages WHERE sender_domain=? "
                          "GROUP BY sender ORDER BY COUNT(*) DESC LIMIT 1", p["domain"])
            p = {"address": row[0][0], "name": row[0][1] or row[0][0]} if row else {}
        if p.get("ambiguous"):
            opts = "; ".join(f"{n} <{ad}>" for n, ad in p["ambiguous"])
            return None, {"reply": f"Which one do you mean: {opts}?", "intent": intent, "needs": "who"}
        if not p:
            return None, {"reply": f"I can't find anyone called \"{a.get('who', '')}\" in your mail.", "intent": intent}
        return p, None

    # ── mode 1 ──────────────────────────────────────────────────────
    if intent == "search":
        who = a.get("who", "")
        addr = dom = ""
        if who:
            p, err = person(allow_domain=True)
            if err:
                return err
            addr, dom = p.get("address", ""), p.get("domain", "")
        rows = find_messages(store, words=a.get("words", ""), days=a.get("days"), address=addr, domain=dom, limit=8)
        if not rows:
            return {"reply": "Nothing matching that in your mail.", "intent": intent, "items": []}
        head = f"{len(rows)} message(s)" + (f" from {p['name']}" if (addr or dom) else "") + \
               (f" with \"{a['words']}\" in the subject" if a.get("words") else "") + ":"
        return {"reply": head + "\n" + "\n".join(_line(r) for r in rows), "intent": intent,
                "items": [_item(r) for r in rows]}

    if intent == "replied":
        p, err = person()
        if err:
            return err
        addr = p["address"]
        last_in = store.q("SELECT date_iso, subject, message_id, provider_id FROM messages WHERE sender=? ORDER BY date_iso DESC LIMIT 1", addr)
        last_out = store.q("SELECT date_iso, subject FROM messages WHERE sender=? AND LOWER(recipients) LIKE ? ORDER BY date_iso DESC LIMIT 1",
                           me, f"%{addr}%") if me else []
        if not last_in and not last_out:
            return {"reply": f"No mail either way with {p['name']}.", "intent": intent}
        din = (last_in[0][0] or "")[:10] if last_in else ""
        dout = (last_out[0][0] or "")[:10] if last_out else ""
        if last_out and (not last_in or dout > din):
            return {"reply": f"No. You last wrote to {p['name']} on {dout} (\"{(last_out[0][1] or '')[:50]}\") and nothing has come back since.",
                    "intent": intent, "waitingOn": p["name"]}
        return {"reply": f"Yes. The last message from {p['name']} is from {din}: \"{(last_in[0][1] or '')[:60]}\"."
                         + (f" You last wrote to them on {dout}." if dout else " You have not written to them."),
                "intent": intent, "items": [_item(last_in[0] + ("", "", "", "")) if False else
                                            {"messageId": last_in[0][2], "providerId": last_in[0][3],
                                             "subject": last_in[0][1], "date": din}]}

    if intent in ("waiting", "promised"):
        direction = "ask" if intent == "waiting" else "promise"
        rows = [r for r in store.open_requests(direction) if direction == "promise" or r[4] == "me"]
        if not rows:
            return {"reply": "Nothing open." if intent == "promised" else "Nobody is waiting on you right now.", "intent": intent, "items": []}
        lines = []
        for r in rows[:8]:
            rid, mid, d, what, who, due, ev, conf, sender, sname, subject, *_ = r
            other = (sname or sender or who or "someone")
            lines.append((f"{other[:22]} asked: " if direction == "ask" else f"you told {other[:22]}: ") + f"{what[:60]}" + (f" (by {due[:10]})" if due else ""))
        head = f"{len(rows)} thing(s) people are waiting on you for:" if direction == "ask" else f"{len(rows)} promise(s) you made:"
        return {"reply": head + "\n" + "\n".join(lines), "intent": intent,
                "items": [{"id": r[0], "what": r[3], "who": r[9] or r[8] or r[4], "due": r[5], "messageId": r[1]} for r in rows[:8]]}

    if intent == "today":
        import today
        items = today.build(store)
        if not items:
            return {"reply": "Nothing needs you today.", "intent": intent, "items": []}
        lines = [f"{today.LABEL.get(k, k):9} {t}  ({n})" for k, t, n, mid in items[:10]]
        return {"reply": f"{len(items)} item(s) today:\n" + "\n".join(lines), "intent": intent,
                "items": [{"kind": k, "text": t, "note": n, "messageId": mid} for k, t, n, mid in items[:10]]}

    if intent == "remind":
        import remind
        who = a.get("who", ""); addr = dom = ""
        if who:
            p, err = person(allow_domain=True)
            if err:
                return err
            addr, dom = p.get("address", ""), p.get("domain", "")
        rows = find_messages(store, words=a.get("words", ""), address=addr, domain=dom, limit=1)
        if not rows:
            return {"reply": "I couldn't find which message you mean. Say who it is from, or a word from the subject.", "intent": intent, "needs": "who"}
        due = remind.when(a.get("when", "")) if a.get("when") else None
        if not due:
            return {"reply": f"When should I remind you about \"{(rows[0][4] or '')[:50]}\"? For example: tomorrow, Friday, 3 October.",
                    "intent": intent, "needs": "when", "items": [_item(rows[0])]}
        if due < datetime.now():
            return {"reply": "That date has already passed. Pick another.", "intent": intent, "needs": "when"}
        mid, pid, sender, name, subject, *_ = rows[0]
        store.add_reminder(message_id=mid, provider_id=pid, kind="remind", due=due, subject=(subject or "")[:80], why="asked in chat")
        store.record_action(mid, pid, "remind", due.strftime("%Y-%m-%d"))
        return {"reply": f"Done. I'll bring back \"{(subject or '')[:50]}\" from {name or sender} on {due:%A %d %B}. It stays in your inbox until then.",
                "intent": intent, "items": [_item(rows[0])]}

    if intent == "important":
        import uuid
        p, err = person()
        if err:
            return err
        addrs = sorted({x for x, _, _ in store.addresses_of(p["address"])} | {p["address"]})
        gid = f"important-{uuid.uuid4().hex[:8]}"
        plain = f"{p['name']}: never cleared, unsubscribed or swept; always at the top"
        for x in addrs:
            store.add_rule(f"this person matters: {p['name']}", "person", x, "protect", "", plain, gid)
            store.add_rule(f"this person matters: {p['name']}", "person", x, "top", "", plain, gid)
        return {"reply": f"Done. {p['name']} is marked important: never cleared or unsubscribed, always at the top. Undo from History.", "intent": intent}

    if intent == "rule":
        import rules
        sentence = a.get("sentence") or text
        r = rules.interpret(sentence)
        if "unclear" in r:
            return {"reply": f"I need one more thing: {r['unclear']}", "intent": intent, "needs": "sentence"}
        n = rules.count_matches(store, r["match_kind"], r["match_value"])
        wording = r["plain"]
        return {"reply": f"I understood: {wording} This would match {n} of your messages. Save it?", "intent": intent,
                "wording": wording, "confirm": stage13_approval.draft_hash(wording),
                "action": {"method": "POST", "route": "/api/typed-rules", "body": {"sentence": sentence, "confirm": stage13_approval.draft_hash(wording)}}}

    def clear_sender():
        """Sender-level clear through the pile: reply + token + route, never done here."""
        import pile
        p, err = person()
        if err:
            return err
        groups, held, excluded = pile.build(store, me)
        g = next((x for x in groups if x["sender"] == p["address"]), None)
        if not g:
            why = excluded.get(p["address"])
            return {"reply": (f"I won't offer to clear {p['name']}: {why}." if why else
                              f"{p['name']} isn't in the pile: their mail doesn't look like bulk mail, so I don't clear it in one go."), "intent": "clear"}
        wording = f"trash {g['count']} messages from 1 sender(s): {g['sender']}"
        return {"reply": f"{g['count']} messages from {p['name']} ({g['reason']}). They go to your provider's trash, recoverable. Clear them?",
                "intent": "clear", "wording": wording, "confirm": stage13_approval.draft_hash(wording),
                "action": {"method": "POST", "route": "/api/pile/clear",
                           "body": {"senders": [g["sender"]], "action": "trash", "confirm": stage13_approval.draft_hash(wording)}}}

    if intent == "clear":
        return clear_sender()

    if intent == "unsubscribe":
        from pipeline import stage15_unsubscribe as unsub
        p, err = person()
        if err:
            return err
        row = store.q("SELECT MAX(unsubscribe), MAX(one_click), MAX(sender_domain) FROM messages WHERE sender=?", p["address"])
        if not row or not row[0][0]:
            return {"reply": f"{p['name']} doesn't publish an unsubscribe header, so I can't stop them this way. I can file their mail away instead.", "intent": intent}
        header, one_click, domain = row[0]
        if store.history(p["address"], me)["replied"] > 0 or store.is_protected(p["address"], domain):
            return {"reply": f"I won't offer that for {p['name']}: you've written to them, or marked them important.", "intent": intent}
        if not unsub.options(header, bool(one_click))["can_one_click"]:
            return {"reply": f"{p['name']} only offers a web page to unsubscribe. I don't open those for you; the link is in their emails.", "intent": intent}
        wording = f"unsubscribe {p['address']}"
        return {"reply": f"Unsubscribe from {p['name']}? This can't be undone by me; only they can put you back. I'll watch for two weeks and tell you if they actually stopped.",
                "intent": intent, "wording": wording, "confirm": stage13_approval.draft_hash(wording),
                "action": {"method": "POST", "route": "/api/unsubscribe", "body": {"sender": p["address"], "confirm": stage13_approval.draft_hash(wording)}}}

    if intent == "draft":
        p, err = person()
        if err:
            return err
        rows = find_messages(store, address=p["address"], limit=1)
        if not rows:
            return {"reply": f"No message from {p['name']} to reply to.", "intent": intent}
        mid, pid, sender, name, subject, date, *_ = rows[0]
        return {"reply": f"I can draft a reply to {p['name']}'s message \"{(subject or '')[:50]}\" from {(date or '')[:10]}. You'll see it before anything is sent. Go ahead?",
                "intent": intent, "items": [_item(rows[0])],
                "action": {"method": "POST", "route": f"/api/messages/{pid}/draft", "body": {}}}

    if intent == "storage":
        import storage
        MB = 1024 * 1024
        total = store.one("SELECT COALESCE(SUM(size),0) FROM messages") or 0
        rows = store.q("SELECT sender, MAX(sender_name), MAX(sender_domain), COUNT(*), SUM(size) FROM messages "
                       "GROUP BY sender ORDER BY SUM(size) DESC LIMIT 5")
        lines = []
        for snd, nm, dom, n, sz in rows:
            prot = " (kept: you correspond with them)" if store.history(snd, me)["replied"] > 0 or store.is_protected(snd, dom) else ""
            lines.append(f"{(nm or snd)[:26]}: {sz / MB:.0f} MB in {n} messages{prot}")
        return {"reply": f"Your mail takes about {total / MB:.0f} MB. The biggest senders:\n" + "\n".join(lines)
                         + "\nThe Storage page lets you clear a sender's large mail after a preview.", "intent": intent,
                "items": [{"sender": r[0], "name": r[1], "messages": r[3], "mb": round(r[4] / MB)} for r in rows]}

    if intent == "brands":
        import brand
        cs = brand.companies(store, me)
        key = _clean(a.get("company") or a.get("who") or "").lower()
        if key in GENERIC or len(key) < 3:
            key = ""
        if key:
            g = cs.get(key) or next((v for k, v in cs.items()
                                     if key == k.split(".")[0] or re.search(rf"(^|[.\-]){re.escape(key)}([.\-]|$)", k)), None)
            if not g:
                # not offered as a company (you correspond with one of its addresses):
                # fall back to the busiest bulk sender under that name, one sender at a time
                a["who"] = key
                return clear_sender()
            company = next(k for k, v in cs.items() if v is g)
            go, keep = brand.split(g)
            wording = f"trash {len(go)} advertising messages from {company}"
            return {"reply": f"{company}: {g['n']} messages from {len(g['addresses'])} address(es). {len(go)} are advertising, {len(keep)} look like receipts or records and would be kept. Clear the {len(go)}?",
                    "intent": intent, "wording": wording, "confirm": stage13_approval.draft_hash(wording),
                    "action": {"method": "POST", "route": f"/api/brands/{company}/clear", "body": {"confirm": stage13_approval.draft_hash(wording)}}}
        top = sorted(cs.items(), key=lambda kv: -kv[1]["n"])[:6]
        if not top:
            return {"reply": "No company sends you bulk mail that I could group.", "intent": intent, "items": []}
        return {"reply": f"{len(cs)} companies send you bulk mail. The biggest:\n" + "\n".join(f"{k}: {v['n']} messages" for k, v in top)
                         + "\nSay \"clear <company>\" and I'll show what would go.", "intent": intent,
                "items": [{"company": k, "messages": v["n"]} for k, v in top]}

    if intent == "catchup":
        import catchup
        since = _since(a.get("days")) or catchup.infer_since(store)
        if not since:
            return {"reply": "I can't tell when you were last here. Say how many days, e.g. \"what did I miss in the last 5 days\".", "intent": intent, "needs": "days"}
        g = catchup.groups(store, me, since)
        arrived = sum(len(g[k]) for k in ("needs", "answered", "expired", "info")) + g["bulk"]
        lines = [f"{len(g['needs'])} still need you", f"{len(g['answered'])} answered by someone else",
                 f"{len(g['expired'])} expired", f"{len(g['info'])} for information", f"{g['bulk']} newsletters and offers, counted not listed"]
        needs = "\n".join(f"  {(sn or snd)[:22]}: {(sub or '')[:50]}" for mid, snd, sn, sub, d in g["needs"][:6])
        return {"reply": f"Since {since[:10]}, {arrived} messages arrived: " + ", ".join(lines) + "." + (f"\nStill need you:\n{needs}" if needs else ""),
                "intent": intent, "items": [{"messageId": mid, "sender": snd, "senderName": sn, "subject": sub, "date": (d or '')[:10]} for mid, snd, sn, sub, d in g["needs"][:6]]}

    if intent == "person":
        p, err = person()
        if err:
            return err
        addrs = store.addresses_of(store.person_of(p["address"])) or [(p["address"], "", 0)]
        alist = [x for x, _, _ in addrs]
        owe = [r for r in store.open_requests("ask") if r[8] in alist and r[4] == "me"]
        prom = [r for r in store.open_requests("promise") if r[4] in alist]
        q = ",".join("?" * len(alist))
        recent = store.q(f"SELECT subject, date_iso FROM messages WHERE sender IN ({q}) ORDER BY date_iso DESC LIMIT 4", *alist)
        h = store.history(p["address"], me)
        lines = [f"{p['name']}: {len(alist)} address(es), {h['sent']} messages from them, {h['replied']} from you to them."]
        if owe:
            lines.append("You owe them: " + "; ".join(f"{r[3][:40]}" + (f" by {r[5][:10]}" if r[5] else "") for r in owe[:3]))
        if prom:
            lines.append("You promised: " + "; ".join(f"{r[3][:40]}" + (f" by {r[5][:10]}" if r[5] else "") for r in prom[:3]))
        if store.is_protected(p["address"], p["address"].split("@")[-1]):
            lines.append("Marked important.")
        if recent:
            lines.append("Recent: " + "; ".join(f"{(su or '')[:40]} ({(d or '')[:10]})" for su, d in recent))
        return {"reply": "\n".join(lines), "intent": intent, "person": p["address"]}

    if intent == "forward":
        to = _clean(a.get("to", "")).lower()
        if not re.match(r"^[\w.+-]+@[\w-]+\.[\w.]+$", to):
            return {"reply": "Who should I forward them to? Type the address; I never take one out of an email.", "intent": intent, "needs": "to"}
        who = a.get("who", ""); addr = dom = ""
        if who:
            p, err = person(allow_domain=True)
            if err:
                return err
            addr, dom = p.get("address", ""), p.get("domain", "")
        rows = find_messages(store, words=a.get("words", ""), days=a.get("days"), address=addr, domain=dom, limit=25)
        if not rows:
            return {"reply": "I couldn't find the messages you mean. Say who they are from, or a word from the subject.", "intent": intent, "needs": "who"}
        mids = [r[0] for r in rows]
        wording = f"forward {len(mids)} to {to}"
        return {"reply": f"{len(rows)} message(s) to forward to {to}, as drafts you review first; nothing is sent by me:\n"
                         + "\n".join(_line(r) for r in rows[:6]) + ("\n…" if len(rows) > 6 else "") + "\nPrepare them?",
                "intent": intent, "wording": wording, "confirm": stage13_approval.draft_hash(wording), "items": [_item(r) for r in rows],
                "action": {"method": "POST", "route": "/api/forward-batch", "body": {"messageIds": mids, "to": to, "confirm": stage13_approval.draft_hash(wording)}}}

    if intent == "voice":
        from pipeline.stage19_voice import StyleStore, describe
        st = StyleStore()
        prof = st.profile("")
        return {"reply": ("Your drafts currently " + describe(prof) + "." if prof else "I haven't learned your writing voice yet; it comes from your sent mail.")
                         + " You can change greeting, sign-off, length, formality and contractions on the Voice page, per group of people.",
                "intent": intent, "profile": prof}

    if intent == "digest":
        import digest
        cfg = digest.load()
        when = _clean(a.get("when", "")).lower()
        choice = next((k for k in ("daily", "weekly", "monthly", "never", "off", "on") if k in when or k in text.lower()), "")
        if choice in ("off", "never"):
            cfg["digest"] = "never"; digest.save(cfg)
            return {"reply": "Digest turned off. Never is a fully supported choice; nothing else changes.", "intent": intent}
        if choice == "on":
            cfg["digest"] = "weekly"; digest.save(cfg)
            return {"reply": "Digest on, weekly. Say daily or monthly to change it.", "intent": intent}
        if choice:
            cfg["digest"] = choice; digest.save(cfg)
            return {"reply": f"Digest set to {choice}. It only goes out when there is something to say.", "intent": intent}
        return {"reply": f"Your digest is {cfg.get('digest', 'weekly')}" + (f", last sent {cfg['digest_last'][:10]}" if cfg.get("digest_last") else ", not sent yet")
                         + ". Say daily, weekly, monthly or never to change it.", "intent": intent}

    if intent == "calendar":
        import calendar_sync
        sug = calendar_sync.suggestions(store)
        sug_lines = "\n".join(f"  {t} on {d[:10]} ({src})" for k, t, d, src in sug[:5])
        if not calendar_sync.connected():
            return {"reply": "No calendar is connected. Connect one on the Calendar page." + (f"\nDates from your mail worth adding:\n{sug_lines}" if sug else ""),
                    "intent": intent, "connected": False}
        try:
            ev = calendar_sync.today_events()
        except Exception as e:
            return {"reply": f"Your calendar isn't responding ({str(e)[:40]}). Your mail features still work.", "intent": intent}
        ev_lines = "\n".join(f"  {w}  {t}" for w, t in ev) or "  nothing"
        return {"reply": f"Today:\n{ev_lines}" + (f"\nDates from your mail worth adding:\n{sug_lines}" if sug else ""), "intent": intent, "connected": True}

    # ── mode 2 ──────────────────────────────────────────────────────
    if intent == "read":
        question = a.get("question") or text
        who = a.get("who", ""); addr = dom = ""
        if who:
            p, err = person(allow_domain=True)
            if err:
                return err
            addr, dom = p.get("address", ""), p.get("domain", "")
        rows = find_messages(store, words=a.get("words", ""), days=a.get("days") or 60, address=addr, domain=dom, limit=4)
        if not rows and (a.get("words") or a.get("days")):
            rows = find_messages(store, address=addr, domain=dom, limit=4)          # loosen once
        docs = []
        for r in rows:
            mid, pid, sender, name, subject, date, domain, acct = r
            if stage03_sensitive.check(sender, subject or "", domain or "")["sensitive"]:
                continue                                                 # never opened, chat included
            body = store.body(mid) or ""
            if not body and body_of:
                try:
                    raw = body_of(mid, pid)
                    body = stage02_strip.strip(raw)["text"] if raw else ""
                except Exception:
                    body = ""
            if body:
                docs.append((name or sender, (date or "")[:10], subject or "", body))
        if not docs:
            return {"reply": "I can't find anything about that in your mail.", "intent": intent, "items": [_item(r) for r in rows]}
        blob = "\n\n".join(f"--- message {i+1} · from {n} · {d} · subject: {s}\n{stage10_redact.minimise(b, 1500)}" for i, (n, d, s, b) in enumerate(docs))
        redacted, mapping = stage10_redact.redact(blob, known_names)
        q_red, q_map = stage10_redact.redact(question, known_names)
        mapping.update(q_map)
        prompt = prompts.get("chat_answer", question=q_red, messages=redacted)
        try:
            out = model._json_from(model._generate(prompt))
        except Exception:
            return {"reply": "I couldn't read those messages just now. Try again in a minute.", "intent": intent}
        answer = str(out.get("answer", "")).strip()
        found = bool(out.get("found", bool(answer)))
        answer, leftover = stage10_redact.restore(answer, mapping)
        if not found or not answer or leftover:
            return {"reply": "I read the likely messages and couldn't find an answer to that.", "intent": intent,
                    "items": [_item(r) for r in rows]}
        src = "; ".join(f"{n}, {d}" for n, d, s, b in docs[:3])
        return {"reply": f"{answer}\n(from: {src})", "intent": intent, "items": [_item(r) for r in rows]}

    return {"reply": "I can't help with that from your mail. I can search, check who has replied, list what you owe or promised, "
                     "show today or catch you up, set reminders, mark people important, tell you about a person, clear or unsubscribe "
                     "bulk senders or a whole company, show what takes up space, forward messages as drafts, draft a reply, "
                     "describe your writing voice, set the digest, check your calendar, or answer a question about what an email says.",
            "intent": "unknown"}
