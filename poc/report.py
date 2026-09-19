"""
Report output. Takes the findings and writes a page.
"""

from datetime import datetime, timezone

CSS = """
:root{--bg:#F1F4F5;--s:#fff;--s2:#F7FAFA;--ink:#13212A;--ink2:#4C5F68;
--ink3:#7C8D95;--rule:#D2DBDF;--soft:#E4EBEE;--ac:#12626E;--warn:#9A4220}
@media(prefers-color-scheme:dark){:root{--bg:#0C161C;--s:#122029;--s2:#172931;
--ink:#E4EDF0;--ink2:#9BAFB7;--ink3:#6E848C;--rule:#22383F;--soft:#1B2E36;
--ac:#5FBECB;--warn:#E09070}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;
font:16px/1.6 -apple-system,"Segoe UI",Roboto,sans-serif}
.p{max-width:1000px;margin:0 auto;padding:44px 26px 90px}
.k{font:600 11px/1 ui-monospace,monospace;letter-spacing:.16em;
text-transform:uppercase;color:var(--ac)}
h1{font-size:38px;line-height:1.1;letter-spacing:-.02em;margin:12px 0 6px}
.sub{color:var(--ink2);margin:0 0 30px;max-width:62ch}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
gap:1px;background:var(--rule);border:1px solid var(--rule);margin-bottom:34px}
.g>div{background:var(--s);padding:16px 18px}
.g .v{font:600 26px/1 ui-monospace,monospace;color:var(--ac);
font-variant-numeric:tabular-nums}
.g .l{font-size:12px;color:var(--ink2);margin-top:7px;line-height:1.35}
h2{font:600 12px/1 ui-monospace,monospace;letter-spacing:.15em;
text-transform:uppercase;color:var(--ink3);margin:46px 0 4px;
padding-bottom:8px;border-bottom:2px solid var(--ink)}
.note{color:var(--ink2);font-size:14.5px;margin:12px 0 14px;max-width:68ch}
.note b{color:var(--ink)}
.tw{overflow-x:auto;border:1px solid var(--rule);background:var(--s)}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:460px}
th{text-align:left;font:600 10px/1 ui-monospace,monospace;letter-spacing:.1em;
text-transform:uppercase;color:var(--ink3);padding:9px 13px;
border-bottom:1px solid var(--rule);background:var(--s2);white-space:nowrap}
td{padding:8px 13px;border-bottom:1px solid var(--soft);vertical-align:top}
tr:last-child td{border-bottom:none}
td.n{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums;
text-align:right;white-space:nowrap}
td.d{color:var(--ink3);font-size:12.5px;font-family:ui-monospace,monospace}
.flag{border-left:3px solid var(--warn);padding:10px 0 10px 15px;
margin:14px 0;font-size:14.5px;color:var(--ink2);max-width:68ch}
footer{margin-top:56px;padding-top:18px;border-top:2px solid var(--ink);
font:11.5px/1.8 ui-monospace,monospace;color:var(--ink3)}
"""


def esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rows(data, cols):
    out = []
    for r in data:
        out.append("<tr>" + "".join(
            f"<td{cls}>{esc(fn(r))}</td>" for fn, cls in cols) + "</tr>")
    return "".join(out) or "<tr><td>nothing found</td></tr>"


def write(f, account, path="report.html"):
    pile = _rows(f["pile"], [
        (lambda r: r[1] or r[0], ""), (lambda r: r[0], ' class="d"'),
        (lambda r: f"{r[2]:,}", ' class="n"'), (lambda r: f"{r[3]:,}", ' class="n"'),
        (lambda r: f"{r[4]:.0f}", ' class="n"'),
        (lambda r: "yes" if r[5] else "—", ' class="n"')])

    dormant = _rows(f["dormant"], [
        (lambda r: r[1] or r[0], ""), (lambda r: r[0], ' class="d"'),
        (lambda r: f"{r[2]:,}", ' class="n"'), (lambda r: f"{r[3]:.0f}", ' class="n"')])

    big = _rows(f["big"], [
        (lambda r: r[1] or r[0], ""), (lambda r: (r[2] or "")[:65], ' class="d"'),
        (lambda r: f"{r[3]:.1f}", ' class="n"')])

    dom = _rows(f["by_domain"], [
        (lambda r: r[0], ""), (lambda r: f"{r[1]:,}", ' class="n"'),
        (lambda r: f"{r[2]:.0f}", ' class="n"')])

    human = _rows(f["human"], [
        (lambda r: r[1] or r[0], ""), (lambda r: r[0], ' class="d"'),
        (lambda r: f"{r[2]:,}", ' class="n"'), (lambda r: f"{r[3]:,}", ' class="n"')])

    cats = "".join(f"<tr><td>{esc(k)}</td><td class='n'>{v:,}</td></tr>"
                   for k, v in f["categories"])

    thread_note = ""
    if f["in_threads"] == 0:
        thread_note = ('<div class="flag"><b>No reply chains found in this mailbox.</b> '
                       'The "who is waiting on you" feature is built from the '
                       '<code>In-Reply-To</code> headers on sent mail, so it reports nothing '
                       'here — correctly. Everything else on this page is independent of '
                       'reply history.</div>')

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mailbox scan</title><style>{CSS}</style></head><body><div class="p">

<span class="k">Custodian &middot; proof of concept</span>
<h1>Mailbox scan</h1>
<p class="sub"><b>{esc(account)}</b> &mdash; envelopes only. No message was opened,
no AI was used, and nothing in the mailbox was changed.
{datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}.</p>

<div class="g">
<div><div class="v">{f['total']:,}</div><div class="l">messages scanned</div></div>
<div><div class="v">{f['senders']:,}</div><div class="l">distinct senders</div></div>
<div><div class="v">{f['unread']:,}</div><div class="l">never opened</div></div>
<div><div class="v">{f['gb']:.1f} GB</div><div class="l">storage used</div></div>
<div><div class="v">{f['bulk_total']:,}</div><div class="l">declared bulk</div></div>
</div>

<h2>The pile</h2>
<p class="note">Senders whose mail <b>declares itself</b> bulk &mdash; they set an
unsubscribe header themselves, which has been required on bulk mail since February
2024. This is not a guess about the sender; it is a fact they published.
<b>{f['bulk_total']:,} messages from {f['bulk_senders']:,} senders</b>, of which
<b>{f['one_click_senders']:,}</b> support one-click unsubscribe &mdash; actionable with
a single request and no browser.</p>
<div class="tw"><table><thead><tr><th>Sender</th><th>Address</th><th>Messages</th>
<th>Unopened</th><th>MB</th><th>1-click</th></tr></thead>
<tbody>{pile}</tbody></table></div>

<h2>Never once opened</h2>
<p class="note">Senders with eight or more messages where <b>every single one is still
unread</b>. <b>{f['dormant_senders']:,} senders, {f['dormant_messages']:,} messages.</b></p>
<p class="note">Note what this is <i>not</i>: a judgement about whether the sender is
important. Bank statements and shop offers are both machine-generated, and a sale is
junk to one person and the point of the mailbox to another. <b>This measures only what
this mailbox's owner has actually done.</b></p>
<div class="tw"><table><thead><tr><th>Sender</th><th>Address</th><th>Messages</th>
<th>MB</th></tr></thead><tbody>{dormant}</tbody></table></div>

<h2>Storage</h2>
<p class="note">Largest single messages, then where the space goes by sending domain.
Size is returned free with every listing &mdash; <b>no attachment was downloaded.</b></p>
<div class="tw"><table><thead><tr><th>Sender</th><th>Subject</th><th>MB</th></tr>
</thead><tbody>{big}</tbody></table></div>
<div style="height:14px"></div>
<div class="tw"><table><thead><tr><th>Domain</th><th>Messages</th><th>MB</th></tr>
</thead><tbody>{dom}</tbody></table></div>

<h2>People, not machines</h2>
<p class="note">Senders carrying no bulk marker &mdash; the correspondence a mail
assistant would actually work on. <b>{f['auto']:,}</b> messages are automatic replies
such as out-of-office notices, which are information rather than noise: they tell us
someone is away.</p>
<div class="tw"><table><thead><tr><th>Sender</th><th>Address</th><th>Messages</th>
<th>Unopened</th></tr></thead><tbody>{human}</tbody></table></div>

<h2>Conversations</h2>
<p class="note"><b>{f['threads']:,} threads</b>, with <b>{f['in_threads']:,}</b> messages
that are a reply to something. Rebuilt from the <code>Message-ID</code> and
<code>In-Reply-To</code> headers &mdash; the same mechanism the obligation ledger uses
to work out who owes whom a reply.</p>
{thread_note}

<h2>Gmail's own split</h2>
<p class="note">Gmail hands us its category labels free with every message. We read
them and build on top rather than fighting them.</p>
<div class="tw"><table><thead><tr><th>Category</th><th>Messages</th></tr></thead>
<tbody>{cats}</tbody></table></div>

<footer>
Custodian proof of concept &middot; envelope scan &middot; no message body was read<br>
No model was used. Nothing was moved, labelled or deleted.<br>
Findings are database queries over header data.
</footer>
</div></body></html>"""

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path
