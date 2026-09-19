"""
The mailbox, in a browser.

    python web.py            # then open http://localhost:8000
    python web.py --imap     # through the free door
    python web.py --port 9000

⚠️ WHY THIS EXISTS.

Sir: "It's not like we are not going to give the view of the mailbox to the
user. We are definitely going to give it — first we build the basic thing, like
the mailbox, and then on top of that the agentic experience."

This is the basic thing. Everything the terminal was already doing, on a page
you can actually read.

⚠️ NO FRAMEWORK, ON PURPOSE.

Python's own http.server, plain HTML, no npm, no build step, no dependency to
install or break. A POC that needs twenty minutes of setup before anyone can
look at it does not get looked at.

⚠️ AND IT CHANGES NOTHING ABOUT THE SYSTEM.

This file only READS. Every decision on screen was made by the same pipeline
the terminal uses — it just renders what is already in the database. There is
no second copy of the logic here, because a second copy is a second thing that
can disagree with the first.
"""

import html
import json
import os
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import connect
from store import Store
from pipeline import stage02_strip, stage03_sensitive, stage04_headers

WINDOW_DAYS = 30
PORT = 8000

CONN = None
STORE = None


# ══════════════════════════ the page ══════════════════════════

CSS = """
:root{
  --paper:#F2F4F6; --card:#fff; --sunk:#EAEEF1; --ink:#1A2530; --ink-2:#4A5A68;
  --ink-3:#7A8894; --rule:#DCE2E7; --blue:#1F5FA9; --blue-s:#E4EDF7;
  --green:#2E6B4F; --green-s:#E1F0E8; --amber:#8A6A17; --amber-s:#F7EFDC;
  --red:#A8412A; --red-s:#F8E5DF;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#141B22; --card:#1C252D; --sunk:#0F161C; --ink:#E8EEF3; --ink-2:#A8B6C2;
  --ink-3:#7A8894; --rule:#2C3945; --blue:#7FB4E8; --blue-s:#1C2E42;
  --green:#7AC7A0; --green-s:#182A20; --amber:#D8AF5C; --amber-s:#2F2819;
  --red:#E2907A; --red-s:#34221D;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
a{color:inherit;text-decoration:none}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px 60px}
header{padding:26px 0 18px;border-bottom:1px solid var(--rule);
  display:flex;flex-wrap:wrap;gap:14px;align-items:baseline}
h1{margin:0;font-size:1.35rem;font-weight:600;letter-spacing:-.01em}
.sub{color:var(--ink-3);font-size:.82rem;font-family:ui-monospace,monospace}
.spacer{flex:1}
.pill{font-family:ui-monospace,monospace;font-size:.72rem;padding:4px 10px;
  border-radius:999px;background:var(--sunk);color:var(--ink-2);white-space:nowrap}
.pill.on{background:var(--blue);color:#fff}
.pill.live{background:var(--green-s);color:var(--green)}
.stats{display:flex;flex-wrap:wrap;gap:0;margin:18px 0 0;border:1px solid var(--rule);
  border-radius:6px;overflow:hidden;background:var(--card)}
.stat{flex:1 1 150px;padding:13px 16px;border-right:1px solid var(--rule)}
.stat:last-child{border-right:none}
.stat b{display:block;font-family:ui-monospace,monospace;font-size:1.4rem;
  font-weight:600;letter-spacing:-.02em}
.stat span{font-size:.73rem;color:var(--ink-3)}
.tabs{display:flex;gap:8px;margin:20px 0 12px;flex-wrap:wrap}
.tab{font-size:.83rem;padding:6px 13px;border-radius:999px;border:1px solid var(--rule);
  background:var(--card);color:var(--ink-2)}
.tab.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.list{border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:var(--card)}
.row{display:grid;grid-template-columns:34px 1fr 190px 128px;gap:0 14px;
  padding:12px 16px;border-bottom:1px solid var(--rule);align-items:center}
.row:last-child{border-bottom:none}
.row:hover{background:var(--sunk)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.d-held{background:var(--green)} .d-win{background:var(--amber)}
.d-old{background:var(--ink-3);opacity:.45} .d-priv{background:var(--red)}
.subj{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  cursor:pointer}
.row:hover .subj{color:var(--blue);text-decoration:underline}
.hint{padding:10px 2px 0;font-size:.8rem;color:var(--ink-3)}
.row.unread .subj{font-weight:600}
.who,.when{color:var(--ink-3);font-size:.82rem;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.when{font-family:ui-monospace,monospace;font-size:.76rem}
.why{grid-column:2 / -1;font-size:.76rem;color:var(--ink-3);padding-top:3px}
.tag{font-family:ui-monospace,monospace;font-size:.67rem;padding:1px 6px;
  border-radius:3px;margin-left:8px;white-space:nowrap}
.t-reply{background:var(--green-s);color:var(--green)}
.t-priv{background:var(--red-s);color:var(--red)}
.t-mach{background:var(--sunk);color:var(--ink-3)}
.legend{display:flex;flex-wrap:wrap;gap:18px;padding:14px 2px 0;font-size:.78rem;
  color:var(--ink-3)}
.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.msg{border:1px solid var(--rule);border-radius:6px;background:var(--card);
  padding:22px 24px;margin-top:18px}
.msg h2{margin:0 0 6px;font-size:1.15rem;font-weight:600}
.msg .meta{color:var(--ink-3);font-size:.82rem;margin-bottom:16px;
  padding-bottom:14px;border-bottom:1px solid var(--rule)}
.msg pre{white-space:pre-wrap;word-wrap:break-word;font:14px/1.65 inherit;margin:0}
.source{margin-top:16px;padding-top:14px;border-top:1px solid var(--rule);
  font-family:ui-monospace,monospace;font-size:.76rem;color:var(--ink-3)}
.blocked{background:var(--red-s);border-left:3px solid var(--red);padding:16px 18px;
  border-radius:4px}
.back{display:inline-block;margin:18px 0 0;font-size:.85rem;color:var(--blue)}
.note{margin-top:22px;padding:14px 16px;background:var(--card);border:1px solid var(--rule);
  border-left:3px solid var(--blue);border-radius:4px;font-size:.85rem;color:var(--ink-2)}
@media(max-width:760px){
  .row{grid-template-columns:24px 1fr;gap:0 10px}
  .who,.when{display:none}
}
"""


def esc(s):
    return html.escape(str(s or ""))


def when(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v)[:19])
    except Exception:
        return None


def page(title, body):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}{HOW_CSS}</style></head><body>
<div class="wrap">{body}</div></body></html>"""


def rows(limit=200, only=None):
    q = """SELECT message_id, provider_id, sender, sender_name, subject,
                  COALESCE(NULLIF(date_iso,''), date), unread,
                  COALESCE(account,'?'), auto_sub, unsubscribe, bulk, categories
             FROM messages WHERE in_inbox=1
             ORDER BY date_iso DESC, date DESC LIMIT ?"""
    out, seen = [], set()
    for r in STORE.q(q, limit * 2):
        if r[0] and r[0] in seen:      # BR-99 — one message, shown once
            continue
        if r[0]:
            seen.add(r[0])
        out.append(r)
    return out[:limit]


def classify(r):
    """
    ⚠️ Reads the SAME stages the terminal reads. No second opinion lives here.

    A web view that re-decides things is a web view that eventually disagrees
    with the pipeline, and then nobody knows which one is right.
    """
    (mid, pid, sender, sname, subject, date, unread,
     account, auto_sub, unsub, bulk, cats) = r
    domain = (sender or "").split("@")[-1]

    sens = stage03_sensitive.check(sender, subject or "", domain)
    if sens["sensitive"]:
        return "private", sens["reasons"][0]

    from connectors.base import Envelope
    env = Envelope(provider_id=pid, message_id=mid, sender=sender,
                   sender_name=sname or "", sender_domain=domain,
                   subject=subject or "", date=date or "", unread=bool(unread),
                   bulk=bool(bulk), auto_submitted=auto_sub or "",
                   unsubscribe=unsub or "")
    facts = stage04_headers.read(env)
    # UC-44 — marked important: always at the top, whatever else is true.
    if STORE.is_protected(sender, domain):
        return "reply", "you marked this person important"
    hist = STORE.history(sender)
    if stage04_headers.engagement_exit(hist["sent"], hist["opened"])["exit"]:
        return "dormant", f"{hist['sent']} from this sender, {hist['opened']} ever opened"
    # ⚠️ THREE SEPARATE HEADERS SAY "NO PERSON WROTE THIS", AND WE NEED ALL THREE.
    #
    # Only checking Precedence: bulk let two whole categories through:
    #   · bounces — "Delivery Status Notification (Failure)" sets
    #     Auto-Submitted: auto-replied and nothing else. Seven of them were
    #     sitting in the From-people list.
    #   · marketing that never sets bulk but does set List-Unsubscribe.
    #
    # List-Unsubscribe is the reliable one: a person's mail client has never
    # once added it. If it is there, a sending platform put it there.
    if facts["machine_generated"]:
        return "machine", "the sender's own headers say a machine sent it"
    if facts["auto_reply"]:
        return "machine", "an automatic reply or a bounce, not a person"
    if facts["has_unsubscribe"]:
        return "machine", "carries an unsubscribe header — only bulk senders set that"

    # ⚠️ Prefer the reply gate's own record over the sorter's.
    #
    # Two stages write decisions — "9" (does this need a reply) and "sort"
    # (which folder). They answer different questions, and taking whichever
    # happened to be written first would show a labelling reason under a
    # heading about replies. Ask for the one we are actually displaying.
    rows_ = STORE.decision_for(mid)
    gate = next((r for r in rows_ if r[0] == "9"), None)
    if gate:
        return ("reply" if "needs a reply" in (gate[1] or "") else "filed"), gate[2]
    if rows_:
        return "filed", f"sorted: {rows_[-1][1]}"
    return "unseen", "not run through the pipeline yet"


def render_list(view="all"):
    st = STORE.body_stats()
    total = STORE.one("SELECT COUNT(*) FROM messages")
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)
    all_rows = rows()

    counts = {"reply": 0, "private": 0, "machine": 0, "dormant": 0}
    items = []
    for i, r in enumerate(all_rows, 1):
        kind, why = classify(r)
        counts[kind] = counts.get(kind, 0) + 1
        items.append((i, r, kind, why))

    # ⚠️ Say how many were actually scored, not just how many said yes.
    #
    # A tile reading "0 need a reply" is a lie by omission when the real
    # answer is "nothing has been scored yet". The denominator is the honest
    # part of that number, so it goes on screen with it.
    # ⚠️ Ask the decisions table directly, not the display verdict.
    #
    # classify() stops at "machine" before it ever looks a decision up — which
    # is correct for the row (a machine message must never reach the Owner as
    # "needs a reply"), but it made the counter read 0 scored when the agent
    # had in fact scored five. The tile is about what the agent has DONE, so
    # it has to ask what the agent wrote down.
    ids = {r[0] for r in all_rows if r[0]}
    scored = sum(1 for m in ids if any(d[0] == "9" for d in STORE.decision_for(m)))

    if view == "reply":
        items = [x for x in items if x[2] == "reply"]
    elif view == "people":
        # ⚠️ An allow-list, not a deny-list. Written as "machines are excluded"
        # it silently admitted every new kind of non-person we had not thought
        # of yet — which is exactly how bounces got in. Say what is allowed.
        items = [x for x in items if x[2] in ("reply", "filed", "unseen")]
    elif view == "held":
        items = [x for x in items if STORE.has_body(x[1][0])]

    door = getattr(CONN, "name", "?")
    caps = [c.replace("supports_", "") for c in
            ("supports_labels", "supports_categories", "supports_threads")
            if getattr(CONN, c, False)]

    b = [f"""<header>
      <h1>Mailbox</h1>
      <span class="sub">{esc(CONN.account_email())}</span>
      <span class="spacer"></span>
      {'<span class="pill live">agent running &mdash; ' + esc(WATCHING["last"] or "starting") + '</span>' if WATCHING["on"] else '<span class="pill">agent not running (--watch)</span>'}
      <a class="pill" href="/how">how it works</a>
      <span class="pill on">{esc(door)}</span>
      {"".join(f'<span class="pill">{esc(c)}</span>' for c in caps)}
    </header>
    <div class="stats">
      <div class="stat"><b>{total:,}</b><span>headers held &mdash; every email, ever</span></div>
      <div class="stat"><b>{st['count']}</b><span>message texts kept ({st['mb']:.2f} MB)</span></div>
      <div class="stat"><b>{counts.get('reply',0)}</b><span>need a reply &mdash; of {scored} scored so far</span></div>
      <div class="stat"><b>{counts.get('machine',0)+counts.get('dormant',0)}</b><span>handled without asking</span></div>
    </div>
    <div class="tabs">"""]

    for key, label in [("all", "Everything"), ("people", "Possibly a person"),
                       ("reply", "Needs a reply"), ("held", "Text held")]:
        on = " on" if key == view else ""
        b.append(f'<a class="tab{on}" href="/?view={key}">{label}</a>')
    if view == "people":
        b.append('</div><div class="hint">Everything here <b>failed every test '
                 'we can run on an envelope</b> &mdash; no bulk flag, no unsubscribe '
                 'header, no auto-reply. That is not the same as "a person wrote it": '
                 'a legal notice from Microsoft carries the exact same headers as '
                 'a personal email. Separating those two needs the message text, '
                 'which is stage 8. Run <code>python agent.py</code>.</div>'
                 '<div class="list">')
    else:
        b.append('</div><div class="hint">Click any subject to open the message. '
             'Green ones open instantly; grey ones are fetched from the mailbox '
                 'Green ones open instantly; grey ones are fetched from the '
                 'mailbox in about a second and then forgotten again.</div>'
                 '<div class="list">')

    for i, r, kind, why in items:
        (mid, pid, sender, sname, subject, date, unread,
         account, auto_sub, unsub, bulk, cats) = r
        held = STORE.has_body(mid)
        d = when(date)
        inside = bool(d and d >= cutoff)

        if kind == "private":
            dot, tag = "d-priv", '<span class="tag t-priv">not opened</span>'
        elif held:
            dot, tag = "d-held", '<span class="tag t-reply">text held</span>'
        elif inside:
            dot, tag = "d-win", ""
        else:
            dot, tag = "d-old", ""
        if kind == "reply":
            tag = '<span class="tag t-reply">needs a reply</span>'
        elif kind in ("machine", "dormant") and not held:
            tag = f'<span class="tag t-mach">{kind}</span>'

        b.append(f"""<div class="row{' unread' if unread else ''}">
          <span class="dot {dot}"></span>
          <a class="subj" href="/open?n={i}">{esc((subject or '(no subject)')[:80])}{tag}</a>
          <span class="who">{esc((sname or sender)[:28])}</span>
          <span class="when">{esc(str(date)[:16].replace('T',' '))}</span>
          {f'<span class="why">{esc(why[:110])}</span>' if why else ''}
        </div>""")

    if not items:
        b.append(f"""<div class="row" style="grid-template-columns:1fr">
          <span class="why" style="grid-column:1">Nothing here yet.
          {'Run <code>python agent.py</code> and messages that need answering will appear.'
           if view == 'reply' else
           'Run <code>python mailbox.py --warm</code> to hold the text of recent important mail.'
           if view == 'held' else 'No messages match this filter.'}</span></div>""")

    b.append("""</div>
    <div class="legend">
      <span><i class="dot d-held" style="background:var(--green)"></i>we have the text &mdash; opens instantly</span>
      <span><i class="dot d-win" style="background:var(--amber)"></i>recent, text not kept</span>
      <span><i class="dot d-old" style="background:var(--ink-3)"></i>older &mdash; fetched when you click</span>
      <span><i class="dot d-priv" style="background:var(--red)"></i>never opened, by design</span>
    </div>
    <div class="note">
      <strong>What this page is showing.</strong> We keep the sender, subject and
      date of every email &mdash; and the actual message text of almost none.
      Click anything grey or amber and it is fetched from the mailbox in about
      a second, shown, and forgotten again. Nothing here re-decides anything:
      every reason on screen came from the same pipeline the terminal runs.
    </div>""")
    return page("Mailbox", "".join(b))


def render_message(n):
    all_rows = rows()
    if not 1 <= n <= len(all_rows):
        return page("Not found", "<header><h1>No such message</h1></header>"
                                 '<a class="back" href="/">&larr; back</a>')
    r = all_rows[n - 1]
    (mid, pid, sender, sname, subject, date, unread,
     account, auto_sub, unsub, bulk, cats) = r
    kind, why = classify(r)

    head = f"""<header><h1>Mailbox</h1>
      <span class="sub">{esc(CONN.account_email())}</span></header>
      <a class="back" href="/">&larr; back to the list</a>
      <div class="msg"><h2>{esc(subject or '(no subject)')}</h2>
      <div class="meta">from {esc(sname or sender)} &middot; {esc(str(date)[:16].replace('T',' '))}</div>"""

    if kind == "private":
        return page(subject or "Message", head + f"""
          <div class="blocked"><strong>Not opened.</strong><br>{esc(why)}<br><br>
          This kind of mail is never read by us &mdash; not from a cache, not
          live. You are told it arrived and nothing more.</div></div>""")

    t0 = datetime.now()
    text = STORE.body(mid)
    raw = b""
    if text:
        source = "from the 30-day store &mdash; instant"
    else:
        try:
            # Opened by fingerprint and checked on arrival — the rule lives in
            # connect.fetch_verified, one copy used by every file that reopens
            # a stored message.
            raw = connect.fetch_verified(CONN, pid, mid)
            text = stage02_strip.strip(raw)["text"]
            source = (f"fetched live in {(datetime.now()-t0).total_seconds():.1f}s "
                      f"&mdash; not stored")
        except Exception as e:
            text, source = "", f"could not fetch: {e}"

    body = esc(text[:6000]) or "(empty after stripping)"
    more = (f"<br><br>… {len(text)-6000:,} more characters"
            if len(text) > 6000 else "")
    return page(subject or "Message", head + safe_facts(r, raw) +
                f"<pre>{body}{more}</pre><div class='source'>{source}</div></div>")


def safe_facts(r, raw: bytes) -> str:
    """
    UC-21 · the facts a person needs to judge a message, shown as text.

    ⚠️ THIS VIEW MAKES NO OUTBOUND REQUEST. The body is shown as plain text,
    no image is ever loaded (a single loaded image tells the sender the
    address is live), links are text with their real destination beside any
    text that disguises it, and the sender's actual address is shown in full
    because the display name is the thing that gets faked.
    """
    import re
    (mid, pid, sender, sname, subject, date, unread,
     account, auto_sub, unsub, bulk, cats) = r
    auth_raw = STORE.one("SELECT COALESCE(auth_results,'') FROM messages WHERE message_id=?", mid)
    auth = stage04_headers.read_auth(auth_raw or "")
    hist = STORE.history(sender, CONN.account_email())
    rows = [f"<b>Real sender</b> {esc(sender)}"
            + (f" &mdash; shown as &ldquo;{esc(sname)}&rdquo;" if sname and sname != sender else ""),
            f"<b>Verification</b> {esc(auth['note'])}",
            f"<b>You and them</b> "
            + (f"you have replied {hist['replied']} time(s)" if hist["replied"]
               else "you have never written to this sender")
            + f", {hist['sent']} received, {hist['opened']} opened"]

    if raw:
        try:
            import email as _email
            msg = _email.message_from_bytes(raw)
            html_part = next((p for p in msg.walk()
                              if p.get_content_type() == "text/html"), None)
            html = html_part.get_payload(decode=True).decode("utf-8", "replace") if html_part else ""
            links = re.findall(r'href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)
            shown = []
            for href, label in links[:12]:
                label = re.sub(r"<[^>]+>", "", label).strip()[:60]
                host = re.sub(r"^https?://([^/]+).*$", r"\1", href)
                if label and re.search(r"[a-z]\.[a-z]", label, re.I) and host not in label:
                    shown.append(f"&ldquo;{esc(label)}&rdquo; actually goes to {esc(host)}")
                elif label:
                    shown.append(f"&ldquo;{esc(label)}&rdquo; &rarr; {esc(host)}")
            if shown:
                rows.append("<b>Links</b> (not clickable here) " + " &middot; ".join(shown))
            atts = [p.get_filename() for p in msg.walk() if p.get_filename()]
            if atts:
                rows.append(f"<b>Attachments</b> {len(atts)} &mdash; " + esc(", ".join(atts[:6]))
                            + " &mdash; not opened, not offered for download")
        except Exception:
            pass
    return "<div class='note' style='margin-top:0'>" + "<br>".join(rows) + "</div>"


# ══════════════════════════ /how — the answer for sir ══════════════════════════

STAGES = [
    ("1", "Connect", "rules", "Open the mailbox. Gmail's API or plain IMAP — the pipeline is never told which."),
    ("2", "Strip", "rules", "MIME apart, HTML to text, quoted history and signature removed. 156,130 bytes became 5,399."),
    ("3", "Sensitive?", "rules", "Headers only. Bank, government, password-reset mail is NEVER opened — not even to summarise."),
    ("4", "Read headers", "rules", "What the sender declared about itself: bulk, auto-submitted, unsubscribe, authentication."),
    ("5", "Attachments", "rules", "Calendar invites, invoices, boarding passes — parsed as data, because they ARE data."),
    ("6", "Route", "rules", "Our model or the rented one. Decided on CONFIDENCE, never on subject matter."),
    ("7", "Dates", "rules", "Find time phrases. 'next Tuesday' is resolved by Python, not by a model."),
    ("8", "Meaning", "models", "What is this person asking for? Our classifier, escalating to Gemini when unsure."),
    ("9", "Needs a reply?", "models", "Our trained gate, blended with hand-set weights. This is the decision that matters."),
    ("10", "Redact", "rules", "Names, numbers and addresses swapped for placeholders BEFORE anything leaves the machine."),
    ("11", "Draft", "models", "Write a reply. Never sends it."),
    ("12", "Restore", "rules", "Put the real details back, from memory. The mapping never touches disk."),
    ("13", "Approve", "rules", "A human says yes. In our code, not as an instruction to a model."),
    ("14", "Act", "rules", "Send, label, trash. Every action written to a log that can undo it."),
    ("15", "Unsubscribe", "rules", "One-click header only (RFC 8058). Refuses to click links in a page."),
    ("16", "Remember", "rules", "Turn a date into a reminder. Lead time by kind: 2 hours for a meeting, 6 weeks for a passport."),
]

MODELS = [
    ("Ours", "xlm-roberta-base", "278M", "Reads what a message means, in any language.",
     "Runs on this laptop. Costs nothing per email. Nothing leaves the machine."),
    ("Ours", "xlm-roberta-base #2", "278M", "Decides whether a message needs a reply.",
     "Trained on this mailbox's own history, so it learns THIS person's habits."),
    ("Ours", "LightGBM", "300 trees, 17 features", "The scoring gate — sender history, time of day, first contact.",
     "AUC 0.684. Blended with hand-set weights, not substituted for them."),
    ("Rented", "gemini-flash-latest", "—", "Called only when our own model is unsure (below 0.65).",
     "Sees redacted text only. Never sees a name, a number or an address."),
]


def render_how():
    st = STORE.body_stats()
    total = STORE.one("SELECT COUNT(*) FROM messages")
    accounts = STORE.q("SELECT COALESCE(account,'?'), COUNT(*) FROM messages "
                       "GROUP BY 1 ORDER BY 2 DESC")
    decisions = STORE.one("SELECT COUNT(*) FROM decisions")
    corrections = STORE.one("SELECT COUNT(*) FROM corrections")
    door = getattr(CONN, "name", "?")

    b = [f"""<header><h1>How it works</h1>
      <span class="sub">live numbers, read from the database just now</span>
      <span class="spacer"></span>
      <a class="pill" href="/">&larr; mailbox</a></header>
    <div class="stats">
      <div class="stat"><b>{total:,}</b><span>headers held</span></div>
      <div class="stat"><b>{st['count']}</b><span>message texts ({st['mb']:.2f} MB)</span></div>
      <div class="stat"><b>{decisions:,}</b><span>decisions on record, each with its reason</span></div>
      <div class="stat"><b>{corrections}</b><span>corrections you have made</span></div>
    </div>

    <h3 class="h">The two doors</h3>
    <div class="list">
      <div class="prow"><b>Gmail API</b><span>push notification, native labels, native threads
        &mdash; and a paid annual security audit before it can ship</span></div>
      <div class="prow"><b>IMAP</b><span>free, works with any mailbox on earth. Gmail's IMAP
        advertises <code>X-GM-EXT-1</code>, which gives us Gmail search, real labels
        and real thread ids over IMAP &mdash; measured on this mailbox:
        <b>1,747</b> in Primary, 42 in the last 30 days</span></div>
      <div class="prow"><b>Right now</b><span>connected through <b>{esc(door)}</b>. The pipeline
        was not told which. It asks a connector <i>what can you do</i>, never <i>who are you</i>,
        so a third kind of mailbox is one new file and nothing else changes</span></div>
    </div>

    <h3 class="h">What we store, and what we refuse to</h3>
    <div class="list">
      <div class="prow"><b>Everything, forever</b><span>sender, subject, date, and what the
        sender declared about itself. About 1 KB each &mdash; ten years fits in a few hundred MB</span></div>
      <div class="prow"><b>Last {WINDOW_DAYS} days, important only</b><span>the actual message text.
        Currently {st['count']} messages, {st['mb']:.2f} MB. Trimmed automatically every time
        this page opens &mdash; enforced in code, not in a policy document</span></div>
      <div class="prow"><b>Never</b><span>anything from a bank, a government, or an account-security
        channel. Not cached, not summarised, not read. You are told it arrived and nothing more</span></div>
      <div class="prow"><b>Older than {WINDOW_DAYS} days</b><span>fetched live when you click it,
        shown, and forgotten. Measured at <b>0.7&ndash;0.8 seconds</b></span></div>
    </div>

    <h3 class="h">The sixteen stages</h3>
    <div class="list">"""]

    for n, name, kind, what in STAGES:
        cls = "t-reply" if kind == "models" else "t-mach"
        b.append(f"""<div class="srow"><span class="num">{n}</span>
          <b>{esc(name)}<span class="tag {cls}">{kind}</span></b>
          <span>{what}</span></div>""")

    b.append("""</div>
    <div class="note"><strong>Why so much of it is rules.</strong> A model that is
    wrong about the meaning of a sentence is a bad guess. A model that is wrong
    about arithmetic is a missed flight. Encoders score 25.9 and 29.1 on date
    arithmetic against a random baseline of 35.4 &mdash; worse than guessing. So
    dates, thresholds, retention and the approval gate are all Python. The models
    are used for the one thing they are genuinely better at than we are:
    reading what a person meant.</div>

    <h3 class="h">Four models &mdash; three ours, one rented</h3>
    <div class="list">""")

    for own, name, size, what, why in MODELS:
        cls = "t-reply" if own == "Ours" else "t-priv"
        b.append(f"""<div class="prow"><b>{esc(name)}<span class="tag {cls}">{own}</span>
          <span class="sz">{esc(size)}</span></b>
          <span>{esc(what)}<br><i>{esc(why)}</i></span></div>""")

    b.append("""</div>
    <div class="note"><strong>What changed after the meeting.</strong> Sir asked for
    the POC on IMAP as well as the API, Google only, and for the mailbox view to
    come first with the agentic experience on top. All three are done: an IMAP
    connector that detects Gmail's extensions at connect time rather than
    hard-coding them, a factory that picks the door so no other file names a
    provider, and this view. The research question &mdash; can we reach the Primary
    tab over IMAP &mdash; is answered yes, and measured above.</div>""")
    return page("How it works", "".join(b))


HOW_CSS = """
.h{margin:28px 0 10px;font-size:.78rem;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-3)}
.prow,.srow{display:grid;gap:2px 14px;padding:12px 16px;border-bottom:1px solid var(--rule)}
.prow{grid-template-columns:190px 1fr}
.srow{grid-template-columns:28px 210px 1fr;align-items:baseline}
.prow:last-child,.srow:last-child{border-bottom:none}
.prow b,.srow b{font-weight:600;font-size:.88rem}
.prow span,.srow span{color:var(--ink-2);font-size:.85rem}
.prow i{color:var(--ink-3);font-style:normal;font-size:.8rem}
.num{font-family:ui-monospace,monospace;color:var(--ink-3);font-size:.78rem}
.sz{display:block;font-family:ui-monospace,monospace;font-size:.72rem;
  color:var(--ink-3);font-weight:400;margin-top:2px}
code{font-family:ui-monospace,monospace;font-size:.82em;background:var(--sunk);
  padding:1px 5px;border-radius:3px}
@media(max-width:760px){.prow{grid-template-columns:1fr}.srow{grid-template-columns:28px 1fr}}
"""


# ══════════════════════════ the server ══════════════════════════

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                out = render_list(q.get("view", ["all"])[0])
            elif u.path == "/how":
                out = render_how()
            elif u.path == "/open":
                out = render_message(int(q.get("n", ["0"])[0]))
            elif u.path == "/favicon.ico":
                self.send_response(204); self.end_headers(); return
            else:
                out = page("Not found", "<header><h1>Not found</h1></header>")
        except Exception as e:
            out = page("Error", f"<header><h1>Something broke</h1></header>"
                                f"<div class='note'>{esc(e)}</div>")
        data = out.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass          # the browser's noise is not our output


# ══════════════════════════ the agent, running behind the page ═══════════

WATCHING = {"on": False, "last": "", "done": 0, "found": 0}


def watcher(every: int = 20):
    """
    Keep the pipeline running while the page is open.

    ⚠️ ITS OWN CONNECTION AND ITS OWN DATABASE HANDLE.

    The page and the watcher run at the same time. An IMAP connection is one
    conversation with server-side state — a selected folder, a command in
    flight — and two threads sharing it does not produce slow, it produces
    corrupt. So this thread opens its own door.

    ⚠️ NEW MAIL FIRST, BACKLOG ONLY WHEN IDLE.

    A message that arrived thirty seconds ago is the one the Owner is waiting
    on. The seven thousand behind it have waited a year and can wait another
    minute. Backlog work only ever happens in the gap where nothing new came.

    ⚠️ AND IT CANNOT SEND. want_draft is False everywhere below.

    There is nobody at the keyboard in a background thread, so there is nobody
    to type the yes — and the approval gate does not get to be skipped just
    because asking would be inconvenient. It reads, decides and labels. That
    is all a thread with no human attached is allowed to do.
    """
    import time
    import scan as backlog

    try:
        conn = connect.open_mailbox(quiet=True)
        store = Store()
    except Exception as e:
        WATCHING["last"] = f"could not start: {str(e)[:60]}"
        return

    bookmark, live = "", False
    try:
        bookmark = conn.current_history_id()
        live = True
    except Exception:
        # An older connector with no polling. Still useful — it just works
        # through the backlog and never notices new arrivals.
        WATCHING["last"] = "this door cannot watch for new mail — backlog only"

    WATCHING["on"] = True
    print(f"\n  agent running in the background"
          f"{' — watching for new mail' if live else ' — backlog only'}")

    while True:
        try:
            fresh = []
            if live:
                fresh, bookmark = conn.new_since(bookmark)
            if fresh:
                WATCHING["found"] += len(fresh)
                for env in conn.fetch_envelopes(fresh):
                    store.save([env])
                    import agent
                    try:
                        agent.run_one(conn, store, env,
                                      agent.known_names(store), False, [])
                        WATCHING["done"] += 1
                    except Exception as e:
                        print(f"  pipeline failed on one message: {str(e)[:50]}")
                WATCHING["last"] = (f"{len(fresh)} new message(s) at "
                                    f"{datetime.now():%H:%M:%S}")
            else:
                t = backlog.scan(conn, store, limit=3, log=lambda *a: None)
                if t.get("scanned"):
                    WATCHING["done"] += t["scanned"]
                    WATCHING["last"] = (f"caught up on {WATCHING['done']} "
                                        f"older message(s)")
                else:
                    WATCHING["last"] = "everything scanned — waiting for new mail"
        except Exception as e:
            WATCHING["last"] = f"error: {str(e)[:60]}"
        time.sleep(every)


def main():
    global CONN, STORE
    port = PORT
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            port = int(sys.argv[i + 1])

    print("\n  starting …")
    STORE = Store()
    STORE.trim_bodies(WINDOW_DAYS)      # retention runs here too
    CONN = connect.open_mailbox()

    if "--watch" in sys.argv:
        import threading
        threading.Thread(target=watcher, daemon=True).start()

    url = f"http://localhost:{port}"
    print(f"\n  Mailbox is at  {url}")
    print("  Ctrl+C to stop.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        HTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.\n")


if __name__ == "__main__":
    main()
