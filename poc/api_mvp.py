"""
The routes that make every use case reachable from the browser.

⚠️ NOTHING HERE DECIDES ANYTHING. Every route calls the same function the
terminal script calls — pile.build, rules.interpret, spam_rescue.score,
stage18_requests.extract — and returns what it returned. A second copy of a
decision is a second thing that can disagree with the first.

⚠️ THE GATE IS THE SAME GATE. Anything irreversible — clear, unsubscribe,
send — is two steps: a PREVIEW that returns the exact wording and a `confirm`
token derived from it, and the ACTION that refuses unless the caller sends
that token back. The token is stage 13's own draft hash; the wording shown
is the wording acted on. A frontend cannot skip it, because the backend
never acts without it.

⚠️ RECIPIENTS COME FROM THE USER (BR-129). No route takes an address out of
a message. The send route sends from the account the message arrived at.
"""

import os
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel

import connect
from api_auth import Account, current_account, store_for, account_email
from pipeline import (stage02_strip, stage03_sensitive, stage04_headers, stage10_redact,
                      stage13_approval, stage17_quick, stage18_requests)


def _confirm_token(wording: str) -> str:
    return stage13_approval.draft_hash(wording)


def _approval(action: str, wording: str, confirm: str) -> stage13_approval.Approval:
    """The gate, for the API. Refuses unless the token matches this exact wording."""
    if not confirm or confirm != _confirm_token(wording):
        raise HTTPException(409, "Not confirmed. Ask for the preview again and send back its confirm token.")
    ap = stage13_approval.Approval(action, draft=wording)
    ap.granted = True
    return ap


def _conn(account: Optional[Account], address: str = ""):
    """
    This account's own mailbox connection, opened from the vault and pooled.
    address empty → the account's first connected mailbox. Single-user mode:
    the API's one mailbox, as before.
    """
    import mailboxes
    return mailboxes.conn_for(account, store_for(account), address)


def _conns(account: Optional[Account]):
    """[(address, connection)] for every connected mailbox of this account."""
    import mailboxes
    if account is None:
        c = _conn(None)
        return [(c.account_email(), c)]
    st = store_for(account)
    out = []
    for address, provider, route, level, state, at in st.mailboxes():
        if state == "connected":
            out.append((address, mailboxes.conn_for(account, st, address)))
    if not out:
        raise HTTPException(409, "Connect a mailbox first.")
    return out


def _conn_msg(account: Optional[Account], s, message_id: str):
    """The connection for the mailbox a stored message arrived at."""
    import mailboxes
    return mailboxes.conn_for_message(account, s, message_id)


def _live(conn, pid, mid):
    return connect.live_id(conn, pid, mid) or pid


class Confirm(BaseModel):
    confirm: str = ""


# ══════════════════════════ today, asks, reminders ══════════════════════

class ReminderIn(BaseModel):
    messageId: str
    on: str
    note: str = ""


class ScanIn(BaseModel):
    days: Optional[int] = None


def register(app):

    @app.post("/api/today/{n}/dismiss")
    def today_dismiss(n: int, account: Optional[Account] = Depends(current_account)):
        import today
        s = store_for(account)
        items = today.build(s)
        if not 1 <= n <= len(items):
            raise HTTPException(404, "no such item")
        kind, text, note, mid = items[n - 1]
        if kind == "unread":
            s.mark_reported(mid, "unread_important")
        sender = s.one("SELECT sender FROM messages WHERE message_id=?", mid)
        if sender:
            s.add_correction("sender", sender, was=kind, should_be="dismissed", source="app")
        return {"ok": True}

    @app.post("/api/asks/scan")
    def asks_scan(body: ScanIn, account: Optional[Account] = Depends(current_account)):
        import asks
        s = store_for(account)
        before = len(s.open_requests())
        for addr, c in _conns(account):
            asks.scan_incoming(c, s, addr, days=body.days)
        return {"found": len(s.open_requests()) - before}

    @app.post("/api/asks/promises/scan")
    def promises_scan(account: Optional[Account] = Depends(current_account)):
        import asks
        s = store_for(account)
        before = len(s.open_requests("promise"))
        for addr, c in _conns(account):
            asks.scan_sent(c, s, addr)
        closed = asks.close_delivered(s, account_email(account))
        return {"found": len(s.open_requests("promise")) - before, "closed": closed}

    @app.post("/api/asks/{rid}/done")
    def asks_done(rid: int, account: Optional[Account] = Depends(current_account)):
        store_for(account).set_request_status(rid, "done")
        return {"ok": True}

    @app.post("/api/asks/{rid}/dismiss")
    def asks_dismiss(rid: int, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        r = next((x for x in s.open_requests() if x[0] == rid), None)
        s.set_request_status(rid, "dismissed")
        if r and r[8]:
            s.add_correction("sender", r[8], was="request", should_be="not a request")
        return {"ok": True}

    @app.post("/api/reminders")
    def reminder_set(body: ReminderIn, account: Optional[Account] = Depends(current_account)):
        import remind
        s = store_for(account)
        row = s.q("SELECT provider_id, subject FROM messages WHERE message_id=?", body.messageId)
        if not row:
            raise HTTPException(404, "no such message")
        due = remind.when(body.on)
        if not due:
            raise HTTPException(400, f"could not read a date from '{body.on}'")
        if due < datetime.now():
            raise HTTPException(400, "That date has already passed.")
        s.add_reminder(message_id=body.messageId, provider_id=row[0][0], kind="remind",
                       due=due, subject=(row[0][1] or "")[:80], why=body.note or "")
        s.record_action(body.messageId, row[0][0], "remind", due.strftime("%Y-%m-%d"))
        return {"ok": True, "due": due.isoformat(),
                "note": "It stays in your inbox until then — we are not hiding it."}

    @app.delete("/api/reminders/{message_id}")
    def reminder_cancel(message_id: str, account: Optional[Account] = Depends(current_account)):
        store_for(account).clear_reminder(message_id, "remind")
        return {"ok": True}

    @app.get("/api/catchup")
    def catchup_view(since: str = "", account: Optional[Account] = Depends(current_account)):
        import catchup
        s = store_for(account)
        since = since or catchup.infer_since(s)
        if not since:
            return {"days": 0, "arrived": 0}
        days = (datetime.now() - datetime.fromisoformat(since[:19])).days
        g = catchup.groups(s, account_email(account), since)
        row = lambda r: {"messageId": r[0], "sender": r[1], "senderName": r[2], "subject": r[3], "date": r[4]}
        return {"days": days, "since": since,
                "arrived": sum(len(g[k]) for k in ("needs", "answered", "expired", "info")) + g["bulk"],
                "needs": [row(r) for r in g["needs"]], "answered": [row(r) for r in g["answered"]],
                "expired": [row(r) for r in g["expired"]], "info": [row(r) for r in g["info"]],
                "bulk": g["bulk"], "unsure": g["unsure"]}

    class MarkRead(BaseModel):
        messageIds: list

    @app.post("/api/catchup/mark-read")
    def catchup_mark_read(body: MarkRead, account: Optional[Account] = Depends(current_account)):
        s = store_for(account); n = 0
        for mid in body.messageIds[:500]:
            pid = s.one("SELECT provider_id FROM messages WHERE message_id=?", mid)
            if not pid:
                continue
            try:
                c = _conn_msg(account, s, mid)
                c.mark_read(_live(c, pid, mid), mid)
                s.record_action(mid, pid, "mark_read", "catch-up"); n += 1
            except Exception:
                pass
        return {"marked": n}

    # ══════════════════════ replying and sending ══════════════════════

    @app.post("/api/messages/{provider_id}/draft")
    def draft(provider_id: str, account: Optional[Account] = Depends(current_account)):
        """UC-25: redact → write in the user's voice → restore locally. Nothing sent."""
        import agent
        from pipeline import model
        s = store_for(account)
        row = s.q("SELECT message_id, sender, sender_name, sender_domain, subject, account "
                  "FROM messages WHERE provider_id=?", provider_id)
        if not row:
            raise HTTPException(404, "no such message")
        mid, sender, sname, domain, subject, acct = row[0]
        c = _conn(account, acct or "")
        if stage03_sensitive.check(sender, subject or "", domain or "")["sensitive"]:
            raise HTTPException(409, "This message is never opened — sensitive by sender and subject.")
        raw = connect.fetch_verified(c, provider_id, mid)
        text = stage02_strip.strip(raw)["text"]
        names = agent.known_names(s)
        redacted, mapping = stage10_redact.redact(stage10_redact.minimise(text), names)
        sender_tok, _ = stage10_redact.redact(sname or sender, names)
        examples, profile, summary = agent.voice(text[:400], domain or "")
        body = model.draft_reply(redacted, subject or "", sender_tok, examples, profile)
        final, leftover = stage10_redact.restore(body, mapping)
        if leftover:
            raise HTTPException(502, "Could not restore every name in the draft, so it was discarded.")
        return {"draft": final, "confirm": _confirm_token(final), "account": acct or account_email(account),
                "voice": summary, "note": "We never send without your yes. This is a draft."}

    class DraftIn(BaseModel):
        body: str

    @app.post("/api/messages/{provider_id}/drafts")
    def to_drafts(provider_id: str, body: DraftIn, account: Optional[Account] = Depends(current_account)):
        """Write the draft into the mailbox's own Drafts folder, threaded. Reversible."""
        s = store_for(account)
        row = s.q("SELECT message_id, sender, subject, refs FROM messages WHERE provider_id=?", provider_id)
        if not row:
            raise HTTPException(404, "no such message")
        mid, sender, subject, refs = row[0]
        c = _conn_msg(account, s, mid)
        d = c.create_draft(to=sender, subject=f"Re: {subject or ''}", body=body.body,
                           in_reply_to=mid, references=refs or mid)
        s.record_action(mid, provider_id, "draft", f"to {sender}", before=str(d.get("id", "")))
        return {"ok": True, "draftId": str(d.get("id", ""))}

    @app.get("/api/messages/{provider_id}/quick")
    def quick(provider_id: str, account: Optional[Account] = Depends(current_account)):
        """UC-26: at most three fixed answers, no model."""
        s = store_for(account)
        row = s.q("SELECT message_id, subject FROM messages WHERE provider_id=?", provider_id)
        if not row:
            raise HTTPException(404, "no such message")
        mid, subject = row[0]
        c = _conn_msg(account, s, mid)
        text = s.body(mid) or stage02_strip.strip(connect.fetch_verified(c, provider_id, mid))["text"]
        out = [{"key": o["key"], "text": o["text"], "confirm": _confirm_token(o["text"])}
               for o in stage17_quick.suggest(text, subject or "")]
        return {"suggestions": out, "note": "Rules only - no model ran. Send one back with its confirm token."}

    class SendIn(BaseModel):
        body: str
        confirm: str = ""

    @app.post("/api/messages/{provider_id}/send")
    def send(provider_id: str, body: SendIn, account: Optional[Account] = Depends(current_account)):
        """Sends only with the confirm token for THIS exact body, from the account it arrived at."""
        ap = _approval("send", body.body, body.confirm)
        s = store_for(account)
        row = s.q("SELECT message_id, sender, subject, refs, thread_id, account FROM messages "
                  "WHERE provider_id=?", provider_id)
        if not row:
            raise HTTPException(404, "no such message")
        mid, sender, subject, refs, tid, acct = row[0]
        if account is None and acct and account_email(None) and acct.lower() != account_email(None).lower():
            raise HTTPException(409, f"This message arrived at {acct}; a reply may only leave from there.")
        c = _conn(account, acct or "")       # the reply leaves from the mailbox it arrived at
        if s.already_replied(mid):
            raise HTTPException(409, "You already replied to this message.")
        r = stage13_approval.execute(c, "send", _live(c, provider_id, mid), draft=body.body,
                                     approval=ap, to=sender, subject=f"Re: {subject or ''}",
                                     in_reply_to=mid, references=refs or mid, thread_id=tid or "")
        if not r["done"]:
            raise HTTPException(502, r["reason"])
        s.mark_replied(mid, r.get("sent_id", ""))
        s.record_action(mid, provider_id, "send", f"to {sender}")
        return {"ok": True, "sentId": r.get("sent_id", "")}

    # ── batch forward, recipients ─────────────────────────────────────

    class ForwardIn(BaseModel):
        messageIds: list
        to: str
        note: str = ""
        confirm: str = ""

    def _forward_plan(s, body, me):
        to = (body.to or "").lower().strip()
        if not re.match(r"^[\w.+-]+@[\w-]+\.[\w.]+$", to):
            raise HTTPException(400, "The recipient must be an address you typed or saved.")
        if len(body.messageIds) > 25:
            raise HTTPException(409, f"That is {len(body.messageIds)} messages. Narrow it to 25 or fewer.")
        rows = []
        for mid in body.messageIds:
            r = s.q("SELECT provider_id, message_id, sender, subject, date_iso, account FROM messages "
                    "WHERE message_id=?", mid)
            if r:
                rows.append(r[0])
        wording = f"forward {len(rows)} to {to}" + (f" with note: {body.note}" if body.note else "")
        return to, rows, wording

    @app.post("/api/forward-batch/preview")
    def forward_preview(body: ForwardIn, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        to, rows, wording = _forward_plan(s, body, account_email(account))
        return {"to": to, "drafts": [{"messageId": r[1], "subject": r[3], "account": r[5]} for r in rows],
                "confirm": _confirm_token(wording), "note": "Every one is a draft. Nothing is sent."}

    @app.post("/api/forward-batch")
    def forward_batch(body: ForwardIn, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        to, rows, wording = _forward_plan(s, body, account_email(account))
        if body.confirm != _confirm_token(wording):
            raise HTTPException(409, "Not confirmed — send back the preview's confirm token.")
        written = []
        try:
            for pid, mid, snd, subject, date, acct in rows:
                c = _conn(account, acct or "")
                text = stage02_strip.strip(connect.fetch_verified(c, pid, mid))["text"]
                content = (f"{body.note}\n\n" if body.note else "") + \
                          f"---------- Forwarded message ----------\nFrom: {snd}\nDate: {date}\n" \
                          f"Subject: {subject}\n\n{text[:4000]}"
                d = c.create_draft(to=to, subject=f"Fwd: {subject or ''}", body=content)
                written.append((d.get("id"), d.get("message_id", "")))
                s.record_action(mid, pid, "draft", f"forward to {to}", before=str(d.get("id")))
        except Exception as e:
            for did, dmid in written:
                try:
                    c.delete_draft(did, dmid)
                except Exception:
                    pass
            raise HTTPException(502, f"Could not prepare all of these, so none were prepared. ({str(e)[:60]})")
        return {"written": len(written), "note": "Waiting in your Drafts folder. Nothing has been sent."}

    @app.get("/api/recipients")
    def recipients(account: Optional[Account] = Depends(current_account)):
        return {"recipients": [{"address": a, "label": l} for a, l in store_for(account).saved_recipients()]}

    class RecipientIn(BaseModel):
        address: str
        label: str = ""

    @app.post("/api/recipients")
    def recipient_add(body: RecipientIn, account: Optional[Account] = Depends(current_account)):
        store_for(account).save_recipient(body.address, body.label)
        return {"ok": True}

    # ── voice ─────────────────────────────────────────────────────────

    def _voice_store():
        from pipeline.stage19_voice import StyleStore
        return StyleStore()

    @app.get("/api/voice")
    def voice_get(domain: str = "", account: Optional[Account] = Depends(current_account)):
        from pipeline.stage19_voice import describe
        st = _voice_store()
        p = st.profile(domain)
        return {"profile": p, "description": describe(p) if p else "neutral professional voice",
                "groups": st.groups()}

    class VoiceIn(BaseModel):
        field: str
        value: str
        domain: str = ""

    @app.put("/api/voice")
    def voice_set(body: VoiceIn, account: Optional[Account] = Depends(current_account)):
        import voice
        if body.field not in voice.FIELDS:
            raise HTTPException(400, f"fields: {', '.join(voice.FIELDS)}")
        _voice_store().set_field(body.field, body.value, body.domain)
        return {"ok": True}

    # ══════════════════════ the cleanup ═══════════════════════════════

    class Senders(BaseModel):
        senders: list = []
        all: bool = False
        confirm: str = ""

    def _pile_plan(s, me, body):
        import pile
        groups, held, excluded = pile.build(s, me)
        chosen = groups if body.all else [g for g in groups if g["sender"] in {x.lower() for x in body.senders}]
        n = sum(g["count"] for g in chosen)
        wording = f"trash {n} messages from {len(chosen)} sender(s)" + ("" if body.all else ": " + ", ".join(g["sender"] for g in chosen))
        return chosen, n, wording

    @app.post("/api/pile/preview")
    def pile_preview(body: Senders, account: Optional[Account] = Depends(current_account)):
        chosen, n, wording = _pile_plan(store_for(account), account_email(account), body)
        return {"count": n, "senders": [g["sender"] for g in chosen], "wording": wording,
                "confirm": _confirm_token(wording),
                "note": "They go to your provider's trash, where you can still recover them."}

    @app.post("/api/pile/clear")
    def pile_clear(body: Senders, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        chosen, n, wording = _pile_plan(s, account_email(account), body)
        ap = _approval("trash", wording, body.confirm)
        done = failed = 0
        for g in chosen:
            for pid, mid, subject in g["ids"]:
                c = _conn_msg(account, s, mid)
                r = stage13_approval.execute(c, "trash", _live(c, pid, mid), draft=wording, approval=ap)
                if r["done"]:
                    s.record_action(mid, pid, "trash", (subject or "")[:70], before="INBOX"); done += 1
                else:
                    failed += 1
        return {"moved": done, "failed": failed}

    class Sender(BaseModel):
        sender: str
        confirm: str = ""

    @app.post("/api/pile/rescue")
    def pile_rescue(body: Sender, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        s.add_correction("sender", body.sender.lower(), was="pile", should_be="keep", source="app")
        s.record_action("", "", "correction", f"rescued {body.sender} from the pile")
        return {"ok": True}

    @app.get("/api/brands")
    def brands(account: Optional[Account] = Depends(current_account)):
        import brand
        cs = brand.companies(store_for(account), account_email(account))
        out = []
        for key, g in sorted(cs.items(), key=lambda kv: -kv[1]["n"]):
            go, keep = brand.split(g)
            out.append({"company": key, "messages": g["n"], "addresses": len(g["addresses"]),
                        "certain": g["certain"], "advertising": len(go), "records": len(keep)})
        return {"companies": out}

    @app.get("/api/brands/{company}")
    def brand_one(company: str, account: Optional[Account] = Depends(current_account)):
        import brand
        cs = brand.companies(store_for(account), account_email(account))
        g = cs.get(company.lower())
        if not g:
            raise HTTPException(404, "not in the list — no bulk mail, or you correspond with them")
        go, keep = brand.split(g)
        wording = f"trash {len(go)} advertising messages from {company.lower()}"
        return {"company": company.lower(), "addresses": sorted(g["addresses"]), "certain": g["certain"],
                "advertising": [{"messageId": m, "subject": sub} for _, _, m, sub in go],
                "protected": [{"messageId": m, "subject": sub} for _, _, m, sub in keep],
                "confirm": _confirm_token(wording), "wording": wording}

    @app.post("/api/brands/{company}/clear")
    def brand_clear(company: str, body: Confirm, account: Optional[Account] = Depends(current_account)):
        import brand
        s = store_for(account)
        g = brand.companies(s, account_email(account)).get(company.lower())
        if not g:
            raise HTTPException(404, "not offered")
        go, keep = brand.split(g)
        wording = f"trash {len(go)} advertising messages from {company.lower()}"
        ap = _approval("trash", wording, body.confirm)
        done = 0
        for snd, pid, mid, subject in go:
            c = _conn_msg(account, s, mid)
            r = stage13_approval.execute(c, "trash", _live(c, pid, mid), draft=wording, approval=ap)
            if r["done"]:
                s.record_action(mid, pid, "trash", (subject or "")[:70], before="INBOX"); done += 1
        return {"moved": done, "kept": len(keep)}

    @app.post("/api/brands/{company}/protect")
    def brand_protect(company: str, account: Optional[Account] = Depends(current_account)):
        import brand
        brand.protect(store_for(account), company.lower())
        return {"ok": True}

    @app.get("/api/unsubscribe")
    def unsub_list(account: Optional[Account] = Depends(current_account)):
        import unsubscribe
        s = store_for(account)
        rows = unsubscribe.candidates(s, account_email(account))
        return {"ready": [{"sender": a, "name": n, "messages": c, "opened": o} for a, n, c, o, ok, h, m in rows if ok],
                "cannot": [{"sender": a, "name": n, "messages": c,
                            "why": "web page only" if h else ("by email only" if m else "no method"),
                            "link": h} for a, n, c, o, ok, h, m in rows if not ok],
                "watching": [{"sender": a, "requestedAt": str(r), "outcome": o} for a, r, o, _ in s.unsubscribes()]}

    @app.post("/api/unsubscribe/preview")
    def unsub_preview(body: Sender, account: Optional[Account] = Depends(current_account)):
        wording = f"unsubscribe {body.sender.lower()}"
        return {"wording": wording, "confirm": _confirm_token(wording),
                "note": "This cannot be undone by us. Only the sender can put you back."}

    @app.post("/api/unsubscribe")
    def unsub_do(body: Sender, account: Optional[Account] = Depends(current_account)):
        from pipeline import stage15_unsubscribe as unsub
        s = store_for(account)
        sender = body.sender.lower()
        wording = f"unsubscribe {sender}"
        ap = _approval("unsubscribe", wording, body.confirm)
        row = s.q("SELECT MAX(unsubscribe), MAX(one_click), MAX(sender_domain) FROM messages WHERE sender=?", sender)
        if not row or not row[0][0]:
            raise HTTPException(404, "this sender publishes no unsubscribe header")
        header, one_click, domain = row[0]
        if s.history(sender, account_email(account))["replied"] > 0 or s.is_protected(sender, domain):
            raise HTTPException(409, "not offered — you have replied to this sender, or marked them important")
        o = unsub.options(header, bool(one_click))
        if not o["can_one_click"]:
            raise HTTPException(409, "this sender only offers a web page; we will not open it for you")
        pid, mid = s.q("SELECT provider_id, message_id FROM messages WHERE sender=? ORDER BY date_iso DESC LIMIT 1", sender)[0]
        c = _conn_msg(account, s, mid)
        r = stage13_approval.execute(c, "unsubscribe", pid, draft="", approval=ap,
                                     extra={"unsubscribe": header, "one_click": bool(one_click)})
        if not r["done"]:
            raise HTTPException(502, r["reason"])
        s.note_unsubscribe(sender)
        s.record_action("", pid, "unsubscribe", sender)
        return {"ok": True, "note": "We will watch for two weeks and tell you whether they actually stopped."}

    @app.get("/api/unsubscribe/outcomes")
    def unsub_outcomes(account: Optional[Account] = Depends(current_account)):
        import unsubscribe
        s = store_for(account)
        now = datetime.now()
        for sender, requested_at, outcome, checked_at in s.unsubscribes():
            days = (now - datetime.fromisoformat(str(requested_at)[:19])).days
            after = s.one("SELECT COUNT(*) FROM messages WHERE sender=? AND date_iso > ?", sender, str(requested_at)[:19])
            if days >= unsubscribe.WATCH_DAYS or after:
                s.set_unsubscribe_outcome(sender, "ignoring" if after else "stopped")
        return {"stopped": [r[0] for r in s.unsubscribes("stopped")],
                "ignoring": [r[0] for r in s.unsubscribes("ignoring")],
                "watching": [r[0] for r in s.unsubscribes("watching")]}

    @app.get("/api/storage")
    def storage_view(account: Optional[Account] = Depends(current_account)):
        import storage
        s = store_for(account); me = account_email(account)
        MB = 1024 * 1024
        largest = [{"providerId": pid, "sender": snd, "senderName": nm, "subject": sub, "date": str(d or "")[:10],
                    "mb": round(sz / MB, 1), "protected": storage.protected(s, me, snd, dom, sub)}
                   for pid, snd, nm, dom, sub, d, sz in s.q(
                       "SELECT provider_id, sender, sender_name, sender_domain, subject, date_iso, size "
                       "FROM messages ORDER BY size DESC LIMIT 25")]
        senders = []
        for snd, nm, dom, n, sz in s.q("SELECT sender, MAX(sender_name), MAX(sender_domain), COUNT(*), SUM(size) "
                                       "FROM messages GROUP BY sender ORDER BY SUM(size) DESC LIMIT 15"):
            prot = s.history(snd, me)["replied"] > 0 or s.is_protected(snd, dom)
            senders.append({"sender": snd, "name": nm, "messages": n, "mb": round(sz / MB), "protected": prot})
        return {"totalMb": round(s.one("SELECT COALESCE(SUM(size),0) FROM messages") / MB),
                "largest": largest, "bySender": senders}

    @app.get("/api/spam")
    def spam_view(account: Optional[Account] = Depends(current_account)):
        import spam_rescue
        s = store_for(account)
        out = []
        for addr, c in _conns(account):
            for env in c.spam_envelopes(limit=100):
                pts, why = spam_rescue.score(s, addr, env)
                if pts >= spam_rescue.THRESHOLD:
                    out.append({"providerId": env.provider_id, "messageId": env.message_id, "sender": env.sender,
                                "subject": env.subject, "date": env.date, "reasons": why, "account": addr})
        return {"likely": out, "note": "Nothing here is presented as safe. Look before you act."}

    @app.post("/api/spam/{provider_id}/rescue")
    def spam_rescue_do(provider_id: str, mailbox: str = "", account: Optional[Account] = Depends(current_account)):
        s = store_for(account); c = _conn(account, mailbox)
        try:
            c.rescue_from_spam(provider_id)
        except Exception as e:
            raise HTTPException(502, f"could not rescue: {str(e)[:70]}")
        s.record_action("", provider_id, "rescue_from_spam", "", before="SPAM")
        return {"ok": True}

    # ══════════════════════ rules, people ═════════════════════════════

    class Sentence(BaseModel):
        sentence: str
        confirm: str = ""

    @app.post("/api/typed-rules/interpret")
    def rule_interpret(body: Sentence, account: Optional[Account] = Depends(current_account)):
        import rules
        r = rules.interpret(body.sentence)
        if "unclear" in r:
            return {"unclear": r["unclear"]}
        n = rules.count_matches(store_for(account), r["match_kind"], r["match_value"])
        return {"matchKind": r["match_kind"], "matchValue": r["match_value"], "action": r["action"],
                "actionArg": r["action_arg"], "plain": r["plain"], "wouldMatch": n,
                "confirm": _confirm_token(r["plain"])}

    @app.post("/api/typed-rules")
    def rule_create(body: Sentence, account: Optional[Account] = Depends(current_account)):
        import rules
        r = rules.interpret(body.sentence)
        if "unclear" in r:
            raise HTTPException(400, r["unclear"])
        if body.confirm != _confirm_token(r["plain"]):
            raise HTTPException(409, "Confirm the interpretation first — send back the interpret call's token.")
        s = store_for(account)
        rid = s.add_rule(body.sentence, r["match_kind"], r["match_value"], r["action"], r["action_arg"], r["plain"])
        s.record_action("", "", "correction", f"rule {rid}: {r['plain'][:60]}")
        return {"id": rid, "plain": r["plain"]}

    @app.delete("/api/typed-rules/{rid}")
    def rule_delete(rid: int, account: Optional[Account] = Depends(current_account)):
        store_for(account).remove_rule(rid)
        return {"ok": True}

    @app.post("/api/people/{address}/important")
    def person_important(address: str, account: Optional[Account] = Depends(current_account)):
        import uuid
        s = store_for(account); address = address.lower()
        addrs = sorted({a for a, _, _ in s.addresses_of(address)} | {address})
        gid = f"important-{uuid.uuid4().hex[:8]}"
        plain = f"{address}: never cleared, unsubscribed or swept; always at the top"
        for a in addrs:
            s.add_rule(f"this person matters: {address}", "person", a, "protect", "", plain, gid)
            s.add_rule(f"this person matters: {address}", "person", a, "top", "", plain, gid)
        return {"ok": True, "addresses": addrs}

    @app.delete("/api/people/{address}/important")
    def person_unimportant(address: str, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        gids = {r[7] for r in s.rules_for(address.lower()) if r[7] and r[7].startswith("important-")}
        return {"removed": sum(s.remove_rule_group(g) for g in gids)}

    @app.get("/api/people/{address}")
    def person(address: str, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        person_ = s.person_of(address.lower())
        addrs = s.addresses_of(person_)
        alist = [a for a, _, _ in addrs]
        owe = [r for r in s.open_requests("ask") if r[8] in alist and r[4] == "me"]
        prom = [r for r in s.open_requests("promise") if r[4] in alist]
        q = ",".join("?" * len(alist))
        recent = s.q(f"SELECT subject, date_iso, sender, account FROM messages WHERE sender IN ({q}) "
                     f"ORDER BY date_iso DESC LIMIT 8", *alist)
        return {"person": person_,
                "addresses": [{"address": a, "evidence": e, "byOwner": bool(b)} for a, e, b in addrs],
                "youOwe": [{"id": r[0], "what": r[3], "due": r[5]} for r in owe],
                "youPromised": [{"id": r[0], "what": r[3], "due": r[5]} for r in prom],
                "recent": [{"subject": su, "date": str(d or "")[:10], "sender": sn, "account": ac}
                           for su, d, sn, ac in recent],
                "important": s.is_protected(person_, person_.split("@")[-1])}

    class Link(BaseModel):
        a: str
        b: str

    @app.post("/api/people/link")
    def people_link(body: Link, account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        s.link_addresses(body.b.lower(), s.person_of(body.a.lower()), "you said so", by_owner=True)
        return {"ok": True}

    @app.post("/api/people/split")
    def people_split(body: dict, account: Optional[Account] = Depends(current_account)):
        store_for(account).split_person(str(body.get("address", "")))
        return {"ok": True}

    # ══════════════════════ threads, search, digest, calendar ═════════

    @app.get("/api/threads/{message_id}")
    def thread_state(message_id: str, account: Optional[Account] = Depends(current_account)):
        import threads
        s = store_for(account); me = account_email(account).lower()
        msgs = threads.thread_of(s, message_id)
        people_ = sorted({(sn or snd) for _, _, snd, sn, *_ in msgs})
        if len(msgs) < 3:
            return {"participants": people_, "messages": len(msgs), "state": None}
        msgs = msgs[-threads.MAX_MESSAGES:]
        asks_ = []
        for i, (m, pid, snd, sn, subject, date, to) in enumerate(msgs):
            try:
                c = _conn_msg(account, s, m)
                text = stage02_strip.strip(connect.fetch_verified(c, pid, m))["text"]
            except Exception:
                continue
            direction = "sent" if snd.lower() == me else "incoming"
            for it in stage18_requests.extract(text, subject, direction):
                asker = "you" if direction == "sent" else (sn or snd)
                owed_by = asker if it["who"] == "sender" else ("you" if (it["who"] == "me" and direction == "incoming") else "them")
                later = [x for x in msgs[i + 1:] if (x[2].lower() == me) == (owed_by == "you")]
                asks_.append({"what": it["what"], "askedBy": asker, "owedBy": owed_by, "answered": bool(later),
                              "messageId": m, "date": (date or "")[:10], "due": it["due"][:10]})
        if not asks_:
            return {"participants": people_, "messages": len(msgs), "unsure": True}
        return {"participants": people_, "messages": len(msgs), "questions": asks_,
                "waitingOnYou": sorted({a["askedBy"] for a in asks_ if not a["answered"] and a["owedBy"] == "you"}),
                "latest": {"from": msgs[-1][3] or msgs[-1][2], "date": (msgs[-1][5] or "")[:10]}}

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=1), account: str = "", days: int = 0,
               who: Optional[Account] = Depends(current_account)):
        s = store_for(who)
        like = f"%{q}%"
        sql = ("SELECT message_id, provider_id, sender, sender_name, subject, date_iso, account FROM messages "
               "WHERE (subject LIKE ? OR sender LIKE ? OR sender_name LIKE ?)")
        args = [like, like, like]
        if account:
            sql += " AND account=?"; args.append(account)
        if days:
            sql += " AND date_iso > ?"; args.append((datetime.now() - timedelta(days=days)).isoformat()[:19])
        rows = s.q(sql + " ORDER BY date_iso DESC LIMIT 100", *args)
        seen, out = set(), []
        for mid, pid, snd, sn, sub, d, ac in rows:
            if mid in seen:
                continue
            seen.add(mid)
            out.append({"messageId": mid, "providerId": pid, "sender": snd, "senderName": sn,
                        "subject": sub, "date": str(d or "")[:16], "account": ac})
        back_to = s.one("SELECT MIN(date_iso) FROM messages WHERE date_iso != ''")
        return {"results": out, "coverage": {"mailboxes": s.one("SELECT COUNT(DISTINCT account) FROM messages"),
                                             "backTo": str(back_to or "")[:10]},
                "note": "Envelope search — sender, subject, date. Not inside message text (BR-103, open)."}

    @app.get("/api/digest/settings")
    def digest_settings(account: Optional[Account] = Depends(current_account)):
        import digest
        s_ = digest.load()
        return {"frequency": s_.get("digest", "weekly"), "lastSent": s_.get("digest_last", "")}

    class DigestIn(BaseModel):
        frequency: str

    @app.put("/api/digest/settings")
    def digest_set(body: DigestIn, account: Optional[Account] = Depends(current_account)):
        import digest
        if body.frequency not in ("daily", "weekly", "monthly", "never"):
            raise HTTPException(400, "daily, weekly, monthly or never")
        s_ = digest.load(); s_["digest"] = body.frequency; digest.save(s_)
        return {"ok": True}

    @app.get("/api/calendar/today")
    def calendar_today(account: Optional[Account] = Depends(current_account)):
        import calendar_sync
        if not calendar_sync.TOKEN.exists():
            return {"connected": False}
        try:
            return {"connected": True, "events": [{"when": w, "title": t} for w, t in calendar_sync.today(calendar_sync.service())]}
        except Exception as e:
            return {"connected": True, "error": f"calendar isn't responding ({str(e)[:40]}). Your mail features still work."}

    @app.get("/api/calendar/suggestions")
    def calendar_suggestions(account: Optional[Account] = Depends(current_account)):
        import calendar_sync
        return {"suggestions": [{"n": i, "key": k, "title": t, "date": d, "source": src}
                                for i, (k, t, d, src) in enumerate(calendar_sync.suggestions(store_for(account)), 1)]}

    # ══════════════════════ mailboxes ═════════════════════════════════

    class Address(BaseModel):
        address: str

    @app.post("/api/mailboxes/identify")
    def identify(body: Address):
        host = connect.host_for(body.address)
        provider = ("gmail" if "gmail" in host else "outlook" if "office365" in host else
                    "yahoo" if "yahoo" in host else "zoho" if "zoho" in host else
                    "icloud" if "me.com" in host else "other")
        route = "microsoft_signin" if provider == "outlook" else "app_password"
        return {"provider": provider, "route": route, "server": host}

    class ConnectIn(BaseModel):
        address: str
        appPassword: str

    @app.post("/api/mailboxes/connect")
    def mailbox_connect(body: ConnectIn, account: Optional[Account] = Depends(current_account)):
        """
        UC-04/06/07/08/09 + UC-10. Verify before storing; store encrypted;
        never log. The password is checked for the provider's shape first so
        a normal password is caught before anything is sent (BR-14).
        """
        from connectors.imap import ImapConnector
        pw = body.appPassword.replace(" ", "")
        host = connect.host_for(body.address)
        if "gmail" in host and len(pw) != 16:
            raise HTTPException(400, "That's your normal password. Gmail needs a 16-character app password. "
                                     "If you can't find App passwords in your Google account, 2-Step Verification is off — turn it on first.")
        if "zoho" in host and len(pw) != 12:
            raise HTTPException(400, "That doesn't look like a Zoho app password. It should be 12 characters.")
        if "me.com" in host and not re.match(r"^[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}$", pw):
            raise HTTPException(400, "This looks like your normal Apple password. You need an app-specific password like abcd-efgh-ijkl-mnop.")
        try:
            c = ImapConnector(host, body.address, pw)
        except Exception as e:
            msg = str(e)
            if "Application-specific password required" in msg:
                raise HTTPException(400, "That's your normal password. Gmail needs an app password.")
            if "yet to enable IMAP" in msg:
                raise HTTPException(400, "Zoho says IMAP isn't available for this mailbox. This is a Zoho setting, not a problem with your password.")
            raise HTTPException(400, f"Could not connect: {msg[:80]}")
        level = c.access_level()
        s = store_for(account)
        mailbox_id = s.register_mailbox(c) if hasattr(s, "register_mailbox") else 0
        if mailbox_id and os.environ.get("CUSTODIAN_SECRET"):
            _vault_put(s, mailbox_id, pw)
        return {"ok": True, "accessLevel": level, "capabilities": {
                    "labels": c.supports_labels, "categories": c.supports_categories,
                    "threads": c.supports_threads, "send": c.supports_send},
                "promise": "We never delete your email, and nothing is sent without your yes.",
                "warning": "If you change your account password, this connection will stop. You would just need a new app password."}

    @app.get("/api/mailboxes")
    def mailboxes(account: Optional[Account] = Depends(current_account)):
        s = store_for(account)
        if hasattr(s, "mailboxes"):
            return {"mailboxes": [{"address": a, "provider": p, "route": r, "accessLevel": l, "state": st,
                                   "connectedAt": str(at)} for a, p, r, l, st, at in s.mailboxes()]}
        return {"mailboxes": [{"address": account_email(None), "provider": "gmail", "route": "app_password",
                               "accessLevel": "full", "state": "connected"}]}

    class Disconnect(BaseModel):
        confirm: str = ""

    @app.delete("/api/mailboxes/{address}")
    def mailbox_disconnect(address: str, body: Disconnect, account: Optional[Account] = Depends(current_account)):
        if body.confirm != "disconnect":
            raise HTTPException(409, "Send confirm: \"disconnect\" to proceed.")
        s = store_for(account); address = address.lower()
        n = s.one("SELECT COUNT(*) FROM messages WHERE LOWER(COALESCE(account,''))=?", address)
        lost = [{"subject": su, "due": str(d)[:10]} for su, d in s.q(
            "SELECT r.subject, r.due FROM reminders r JOIN messages m USING(message_id) "
            "WHERE r.done=0 AND LOWER(COALESCE(m.account,''))=?", address)]
        mids = [r[0] for r in s.q("SELECT message_id FROM messages WHERE LOWER(COALESCE(account,''))=?", address)]
        q = ",".join("?" * len(mids)) if mids else "''"
        for table in ("reminders", "decisions", "actions", "bodies", "requests"):
            try:
                s.db.execute(f"DELETE FROM {table} WHERE message_id IN ({q})", mids)
            except Exception:
                pass
        s.db.execute("DELETE FROM messages WHERE LOWER(COALESCE(account,''))=?", (address,))
        s.db.commit()
        if hasattr(s, "conn"):
            s.conn.execute("DELETE FROM public.credentials WHERE mailbox_id IN "
                           "(SELECT id FROM public.mailboxes WHERE address=%s)", (address,))
            s.conn.execute("UPDATE public.mailboxes SET state='disconnected' WHERE address=%s", (address,))
            s.conn.commit()
        s.record_action("", "", "disconnect", address)
        if account is not None:
            import mailboxes
            mailboxes.drop(account.email, address)
        return {"ok": True, "erased": {"messages": n},
                "willStay": ["every label", "every cleared message", "every draft already in the mailbox"],
                "lost": lost,
                "toFinish": "Delete the app password you created for us at your provider — only you can do that."}


# ── the credential vault ─────────────────────────────────────────────────
#
# ⚠️ Encrypted with a key that lives ONLY in the environment (CUSTODIAN_SECRET),
# never in the database, so the credentials table is useless without the
# running service. Fernet (AES-128-CBC + HMAC) from the cryptography package.

def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("CUSTODIAN_SECRET", "")
    if not key:
        raise RuntimeError("CUSTODIAN_SECRET is not set")
    return Fernet(key.encode())


def _vault_put(s, mailbox_id: int, secret: str) -> None:
    token = _fernet().encrypt(secret.encode())
    s.conn.execute("INSERT INTO public.credentials (mailbox_id, kind, ciphertext) VALUES (%s, 'app_password', %s) "
                   "ON CONFLICT (mailbox_id) DO UPDATE SET ciphertext=EXCLUDED.ciphertext, updated_at=now()",
                   (mailbox_id, token))
    s.conn.commit()


def vault_get(s, mailbox_id: int) -> str:
    r = s.conn.execute("SELECT ciphertext FROM public.credentials WHERE mailbox_id=%s", (mailbox_id,)).fetchone()
    return _fernet().decrypt(bytes(r[0])).decode() if r else ""
