# The 50 use cases, in brief — and what was built on 19 September

Umar's Use Case Template v2.0 (9 September 2026), each in one to three lines,
with its state in the POC after the build on 19 September 2026.

Legend: **built** works today · **partly** the pieces exist · **not built** ·
**not POC** product/commercial layer · **decision** needs sir and Umar first.

Full review with problems and verdicts: `Custodian-Use-Case-Review.pdf`.

---

## Getting an account — not POC work

1. **Register Account** — Make an account with email + password, or Google/Microsoft just to prove who you are. *(not POC)*
2. **Sign In** — Four ways in, all reaching the same account. Signing in never gives mailbox access. *(not POC)*
3. **Start a Subscription** — Card first, 7-day trial, cleanup locked until paid. Miss a payment: stop, don't delete. *(not POC)*
47. **Where My Data Is Stored** — One line in settings; move on request. *(not POC)*
48. **Change Plan** — Upgrade now, downgrade next billing date. *(not POC)*
49. **Cancel Subscription** — Runs to the end of the paid period; nothing in the mailbox undone. *(not POC)*

## Connecting a mailbox

4. **Gmail by App Password** — Google's steps, 16-character password, IMAP. *(built — the default door)*
5. **Outlook by Microsoft Sign-In** — No passwords; sign in on Microsoft's page, IMAP with the token. *(built, untested live: `outlook.py` + XOAUTH2 in the IMAP connector; needs an app registration)*
6. **Yahoo by App Password** — Same as Gmail with Yahoo's quirks. *(partly — server known, flow untested)*
7. **Zoho by App Password** — IMAP on in one place, password made in another, regional servers. *(partly)*
8. **iCloud by App-Specific Password** — `abcd-efgh-ijkl-mnop`, username derived. *(partly)*
9. **Any Other IMAP Mailbox** — Server from the address: known endings → MX records → `imap.<domain>`. *(built — `connect.host_for()` does the chain; manual entry not built)*
10. **Establish Mailbox Connection** — Prove the credential, find folders, record access level. *(partly — capability detection built; read-only detection added: `access_level()`)*
11. **Gmail by Google Sign-In** — OAuth with the narrowest scope. *(built — the API door)*
12. **Upgrade to Google Sign-In** — Switch in place, same account checked, nothing lost. *(built — `upgrade.py`)*
13. **Disconnect a Mailbox** — End access, destroy the credential, erase our index, list what is lost. *(built — `my_data.py --disconnect`)*
50. **Identify the Mail Provider** — Known endings, then MX records. *(built — `connect.mx_hosts()`; ocloudsolutions.com → Microsoft 365, anthropic.com → Google)*

## The cleanup

14. **Scan Mailbox History** — Envelopes in bulk, read-only, resumable. *(built)*
15. **Review and Clear the Pile** — Grouped, explained, five safety rules, provider trashes on your click. *(built — `pile.py`: 6,683 messages in 91 groups on the test mailbox, 9 records held back)*
16. **Clear a Brand's Mail** — A dozen addresses as one company; advertising cleared, receipts kept. *(built — `brand.py`: 68 companies; DKIM domain when present, else domain + name, marked "less certain")*
17. **Unsubscribe from a Sender** — Machine-readable route only; watch afterwards. *(built — `unsubscribe.py` incl. `--check` for stopped / ignoring)*
    **Link-only senders:** we do not click. Marked "cannot be stopped this way", the link is yours, and we offer to file their mail instead — filing, not stopping.
18. **Reclaim Storage Space** — Largest messages, grouped, protected ones marked. *(built — `storage.py`)*
46. **The First Cleanup** — Unsubscribe → pile → brand → space, one confirmation each. *(built — `cleanup.py`)*

## New mail, every day

19. **Prioritise Newly Arrived Mail** — Bulk or personal, what they want, reasons, labels, nothing hidden. *(built)*
20. **Recover Important Mail from Spam** — Score on unfakeable signals; never move automatically. *(built — `spam_rescue.py`; Authentication-Results now indexed on both doors)*
21. **Inspect a Suspicious Message Safely** — Text only, no images, links with real destinations, sender in full. *(built — the web page's message view)*
22. **Track Unanswered Outgoing Mail** — Your questions with no reply. *(built, API door only)*
23. **Record Commitments from Structured Mail** — Bookings, orders, invoices from embedded data. *(built)*
24. **Warn About an Approaching Deadline** — By type, learned lead time. *(built)*
33. **Identify a Request and Its Deadline** — What was asked, of whom, by when; unsure → nothing. *(built — stage 18 + `asks.py --scan`; 12 requests found on the test mailbox; quality depends on the cheap filter)*
36. **Resurface an Unread Important Message** — One line, once. *(built — in `today.py` and the brief)*

## Replying

25. **Generate a Reply Draft** — Redact, draft in your voice, into Drafts, never send. *(built — plus the gated send; decision needed)*
26. **Send a Quick Answer** — Fixed one-tap answers; the tap is the approval. *(built as suggestions + gated send; contradicts 25; decision needed)*
35. **Forward a Batch to Someone** — Drafts only, recipient from you, review first, all or nothing. *(built — `forward_batch.py`)*
42. **Tune My Writing Voice** — See and change the recipe; voices per group; your setting wins. *(built — `voice.py`; drafts use the per-domain voice)*

## Seeing your mail

27. **View the Unified Inbox** — One list, account per row, duplicates collapsed, live fetch. *(built)*
28. **Search Across All Mailboxes** — Our index, envelope only; full text still open. *(built)*
39. **Catch Up After Time Away** — Still needs you · answered by someone else · expired · for information. *(built — `catchup.py`)*
40. **See Where a Conversation Stands** — Who, what's open, who waits on whom; state not story. *(built — `threads.py`; participants-only when unsure)*
41. **See Everything About One Person** — Addresses linked on evidence, owed both ways, split in one click. *(built — `people.py`)*
43. **Work Through Today** — One ordered list: due, promised, asked, unread-important, waiting, spam. *(built — `today.py`, also `/api/today`)*

## Control and trust

29. **Correct a Decision** — Reason on every item; correct in place or in Gmail; next message. *(built)*
30. **Undo an Action** — Every action reversible, log in plain words. *(built — both doors)*
31. **Receive the Weekly Digest** — One message on your schedule; silence when nothing. *(built — `digest.py --frequency / --run / --schedule`; sent from the owner's mailbox, not our own address — stated)*
32. **Export or Erase My Data** — Everything we hold, or nothing. *(built)*
34. **Connect a Calendar** — Read today; add important dates after "Add this?"; never change or delete. *(built for Google — `calendar_sync.py`, calendar scope only; CalDAV for other providers not built; live sign-in not exercised here)*
37. **Set a Follow-Up Reminder** — Not snooze; the message never moves. *(built — `remind.py`)*
38. **Create a Rule in Plain English** — One sentence, interpretation shown back, confirmed, then no AI. *(built — `rules.py`; "clear" and "forward" become approval items; the sorter obeys label rules)*
44. **Mark a Person as Important** — Never in the pile, never unsubscribed, always at the top. *(built — `important.py`; every stage consults it)*
45. **Track What You Promised** — Your sent mail read for "I'll send it by Friday". *(built — `asks.py --promises`)*

---

## Where it stands after 19 September

- **38 built** (some with stated limits: Outlook and the calendar need a real sign-in to exercise; UC-22 is API-door only).
- **4 partly** — the Yahoo / Zoho / iCloud flows and manual server entry: the servers are known, the guided screens are not.
- **6 not POC** — accounts, sign-in, billing, plan changes, data region.
- **2 decisions still open** — sending (UC-25 vs UC-26 vs sir's brief) and chat (UC-38 vs sir's text-input mandate). Both paths exist in the code; nothing was removed.

## New commands

```
python today.py                 python asks.py --scan / --promises
python pile.py                  python brand.py
python unsubscribe.py           python storage.py
python spam_rescue.py           python catchup.py
python threads.py N             python people.py
python remind.py N --on thursday --note "…"
python important.py x@y.com     python rules.py "never touch mail from x@y.com"
python forward_batch.py --from x@y.com --to me@myco.com
python voice.py                 python digest.py --frequency weekly
python calendar_sync.py --connect / --today / --suggest
python upgrade.py               python my_data.py --disconnect x@y.com
python cleanup.py               python outlook.py --connect you@outlook.com
```

New API routes for the web app: `/api/today`, `/api/asks`, `/api/pile`, `/api/typed-rules`.
