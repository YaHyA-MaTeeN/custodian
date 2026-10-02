# Custodian backend — final report

October 2026. Everything in one place: what was built, what was tested, every
use case and its state, why some are unfinished, costs, hosting, and what is
left. Written in plain words.

---

## 1 · What Custodian is

An email assistant. A person connects their mailbox. Custodian reads every
email, decides what it is (a person asking for something, a newsletter, a
receipt, spam that is really important), labels it, and shows a short list
of what needs attention.

It can clean out bulk mail, unsubscribe from senders, set reminders, track
what people asked of you and what you promised, draft replies in your own
writing style, and answer questions you type.

Two promises run through all of it:

- **Nothing is ever deleted.** "Clear" moves mail to the provider's trash,
  where it can be recovered.
- **Nothing permanent happens without a yes.** Before clearing, unsubscribing
  or sending, the person sees the exact action ("trash 360 messages from
  LinkedIn") and must confirm it. The server refuses otherwise.

The backend is the server side and does all the thinking. The frontend
(the screens) is built separately and talks to the backend.

---

## 2 · What was built

| Part | What it does, simply |
|---|---|
| Mail connection (IMAP) | Logs in to the mailbox and reads, labels, archives, moves to trash, sends, undoes |
| The pipeline | 16 steps every email goes through to decide what it is. Mostly fixed rules; AI only where rules can't decide |
| Database | Stores what Custodian knows about the mail (not the mail itself). Each customer has their own private section |
| Accounts | Sign up, confirmation email, log in, log out, reset password |
| API | 94 routes: one for everything the screens need |
| The gate | Every permanent action needs the person's confirmation of the exact wording |
| Per-user mailboxes | Each user's mailbox password is stored encrypted; each user's requests open only their own mailbox |
| The worker | Runs all day with nobody watching. Checks every mailbox every 20 seconds, reads and labels new mail. Can never send or delete |
| The chat | The person types a sentence and the app does the right thing. Every feature can be reached by typing |
| Subscriptions | Free trial, confirm before charging, change plan, pause if a payment fails, cancel |
| Calendar | Shows today's events and adds dates from mail after a yes. Works with Google, and with iCloud, Yahoo, Zoho and others using the mailbox's own password. Can never change or delete an event |
| Handover | Handover document, personal data removed from the code, clean copy ready |

### How the chat works

1. The person types, for example, "has Ali replied to me?"
2. Gemini (Google's AI) reads the sentence with names hidden and says which
   feature it means: "check replies, person Ali". That is all Gemini does.
3. Our own code looks it up in our database and writes the answer:
   "No. You wrote to Ali on Tuesday and nothing has come back."

For a question about what an email says ("what did Ali ask me to do?"), the
email text goes to Gemini with names hidden, and the answer names the email
it came from. If the answer is not in the mail, the chat says so instead of
guessing. The chat never clears, unsubscribes or sends by itself: it shows
what would happen and waits for the yes, same as a button.

Gemini was chosen for the chat because it costs about $0.03 per user per
month and needs no training. Running our own model would need a few hundred
labelled example sentences first.

---

## 3 · Mail providers: what is actually tested

| Provider | State | Why |
|---|---|---|
| **Gmail** | **Working and tested** | 47 operations proven on a real mailbox: read every folder, label, archive, trash, rescue from spam, mark read, send, draft, forward, undo. Inbox count unchanged after the test |
| **Outlook / Hotmail** | **Not working yet** | Microsoft stopped accepting passwords in 2022. It needs a sign-in token, and for that the app must be registered with Microsoft once. Only a company Microsoft account can register it; personal accounts are refused (tried twice). The code is written and waits for the company's registration |
| **Yahoo** | Written, not tested | Uses the same standard as Gmail, so it should work. No real Yahoo account has been connected |
| **Zoho** | Written, not tested | Same |
| **iCloud** | Written, not tested | Same |
| Any other provider | Written, not tested | The server is worked out from the email address automatically |

---

## 4 · All 50 use cases

**41 built and tested, 9 partly done, none untouched.** "Built" means the
backend logic exists and was run on a real Gmail mailbox. The screens are
the frontend's work.

### Getting an account

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 1 | Register Account | Make an account with email and password | Built | A real confirmation email is sent and its link confirms the account. Tested |
| 2 | Sign In | Log in; signing in never gives mailbox access by itself | Partly | Email and password work. "Sign in with Google / Microsoft" not built |
| 3 | Start a Subscription | Card first, 7-day trial, cleanup locked until paid | Partly | All the rules work. No real payment company connected |
| 47 | Where My Data Is Stored | Show which region; move on request | Partly | Region shown, move request recorded. The move itself is done by hand |
| 48 | Change Plan | Upgrade now, downgrade at the next billing date | Partly | Rules work. No real payment company |
| 49 | Cancel Subscription | Runs to end of paid period; nothing in mailbox undone | Partly | Rules work. No real payment company |

### Connecting a mailbox

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 4 | Gmail by App Password | 16-character app password, connect over IMAP | Built | The default connection. Tested |
| 5 | Outlook by Microsoft Sign-In | Sign in on Microsoft's page, get a token | Partly | Code written. Waiting on Microsoft registration |
| 6 | Yahoo by App Password | Same as Gmail, Yahoo's steps | Partly | Written, not tested |
| 7 | Zoho by App Password | IMAP switched on in Zoho first | Partly | Written, not tested |
| 8 | iCloud by App-Specific Password | abcd-efgh-ijkl-mnop style password | Partly | Written, not tested |
| 9 | Any Other IMAP Mailbox | Work out the server from the address | Built | From the address ending, then the domain's mail records |
| 10 | Establish Mailbox Connection | Check the password, find folders, note what's allowed | Built | Checks the password for real before storing it, encrypted |
| 11 | Gmail by Google Sign-In | Google's own door | Built | Optional second door. Public use needs Google's paid security review |
| 12 | Upgrade to Google Sign-In | Switch doors without losing anything | Built | |
| 13 | Disconnect a Mailbox | Erase our copy, list what is lost | Built | Mailbox itself untouched |
| 50 | Identify the Mail Provider | Which company runs this address | Built | |

### The cleanup

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 14 | Scan Mailbox History | Read all old mail headers, resumable | Built | Progress shown: "read 1,200 of 7,300" |
| 15 | Review and Clear the Pile | Bulk senders grouped with reasons | Built | Trash or archive, after confirmation. Test mailbox: 6,683 messages in 91 groups |
| 16 | Clear a Brand's Mail | A company's many addresses as one | Built | Adverts cleared, receipts kept. Test mailbox: 68 companies |
| 17 | Unsubscribe | One-click unsubscribe, then watch | Built | Checks for 14 days whether they really stopped |
| 18 | Reclaim Storage Space | Largest messages, grouped | Built | Protected senders marked |
| 46 | The First Cleanup | Unsubscribe, pile, brands, space in order | Built | One confirmation each |

### New mail every day

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 19 | Prioritise New Mail | Person or machine, what they want, labelled | Built | Every decision stored with its reason |
| 20 | Recover Mail from Spam | Find real mail wrongly in spam | Built | Never moved automatically |
| 21 | Inspect a Suspicious Message | Text only, real link destinations | Built | |
| 22 | Track Unanswered Outgoing Mail | Your questions nobody answered | Built | |
| 23 | Commitments from Structured Mail | Bookings, orders, invoices become dates | Built | |
| 24 | Deadline Warnings | Reminder ahead of a deadline | Built | |
| 33 | Requests and Their Deadlines | What was asked, of whom, by when | Built | Test mailbox: 12 requests found |
| 36 | Resurface Unread Important Mail | One line, once | Built | |

### Replying

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 25 | Generate a Reply Draft | Draft in your own style | Built | Names hidden from the AI; sent only after yes |
| 26 | Send a Quick Answer | Three fixed short answers | Built | No AI used |
| 35 | Forward a Batch | Up to 25 messages as drafts | Built | Recipient only from what the user types |
| 42 | Tune My Writing Voice | See and change how drafts sound | Built | Learned from sent mail |

### Seeing your mail

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 27 | Unified Inbox | All mailboxes in one list | Built | |
| 28 | Search | Across all mailboxes | Built | Sender, subject, date. Not inside message text |
| 39 | Catch Up After Time Away | Needs you / answered / expired / info | Built | |
| 40 | Where a Conversation Stands | Who asked what, who waits on whom | Built | |
| 41 | Everything About One Person | Their addresses, what is owed both ways | Built | |
| 43 | Work Through Today | One ordered list | Built | |

### Control and trust

| # | Use case | What it means | State | How |
|---|---|---|---|---|
| 29 | Correct a Decision | Overrule any decision | Built | |
| 30 | Undo an Action | Everything reversible, log in plain words | Built | |
| 31 | Weekly Digest | One summary on your schedule | Built | Nothing sent when there's nothing to say |
| 32 | Export or Erase My Data | Everything we hold, or nothing | Built | |
| 34 | Connect a Calendar | Read today, add dates after "add this?" | Built | Google Calendar, plus iCloud, Yahoo, Zoho and other providers through the common calendar standard (CalDAV), using the mailbox's own app password. Can only read and add, never change or delete. Tested against a real calendar server. Outlook's calendar waits on the same Microsoft registration as Outlook mail |
| 37 | Follow-Up Reminder | Remind without moving the message | Built | |
| 38 | Rule in Plain English | One sentence becomes a rule | Built | Interpretation shown back before saving |
| 44 | Mark a Person Important | Never cleared, always on top | Built | |
| 45 | Track What You Promised | "I'll send it Friday" from sent mail | Built | |

---

## 5 · Why 9 use cases are only partly done

None of them is waiting on more coding from our side alone. Each one needs
something from outside.

| Use cases | What is missing | What it needs |
|---|---|---|
| **3, 48, 49** Subscription, change plan, cancel | Taking real money | A payment company (e.g. Stripe) chosen and an account opened. All the rules are already built and tested; connecting the company is three functions to fill in |
| **5** Outlook | A Microsoft app registration | The company's Microsoft 365 admin, about 15 minutes, free. Only the "client ID" is needed back |
| **6, 7, 8** Yahoo, Zoho, iCloud | A real test | One test account for each. About an afternoon of testing |
| **2** Sign in with Google / Microsoft | The sign-in button for the account itself | A Google and Microsoft login setup for the website. Email and password already work |
| **47** Data region | Moving the data | Done by hand by whoever runs the servers: copy, check, switch, erase old copy |

---

## 6 · How everything was tested

Every test runs against real systems (the real database, a real Gmail
mailbox, real emails) and cleans up after itself. Each one can be re-run.

| Test | What it proves |
|---|---|
| IMAP audit | 47 mailbox operations on a real Gmail, inbox count unchanged |
| Accounts test | Sign-up → confirmation → login → logout → reset, 14 steps |
| Email test | A real confirmation email arrives in about 10 seconds and its link works |
| Mailbox test | Each account opens only its own mailbox; a second account is refused |
| API test | Every permanent action is refused without the confirmation |
| Chat test | 22 real sentences, every feature, all answered correctly |
| Subscription test | The whole life of a subscription, 21 checks: trial, lock, confirm, upgrade, downgrade, failed payment, pause, restore, cancel, end |
| Calendar test | 20 checks against a real calendar server: today's events (cancelled and declined ones left out), adding only with confirmation, no invites sent, a No remembered, no way to change or delete |
| Worker | One full pass reading and labelling mail |

---

## 7 · Costs

All figures are estimates from real measurements on one laptop and one test
mailbox, then scaled up. Treat them as within a factor of two.

### The AI models

| Model | Job | Runs on | Size | Speed per email |
|---|---|---|---|---|
| Classifier | What kind of email, does it need a reply | Our server | 550 MB, 1.7 GB memory | 66 ms |
| Name spotter | Finds names to hide before anything goes to Google | Our server | 1.1 GB, 1 GB memory | 69 ms |
| Gemini Flash-Lite | Reading requests, drafting replies, rules, chat | Google | none of ours | 1–3 seconds |

About 70% of email is handled by rules alone, with no AI.

### One user, one day (assumed)

| Item | Value |
|---|---|
| Emails received | 120 |
| Handled by rules only | 84 |
| Through our own models | 36 |
| Sent to Gemini | 26 calls |
| Database growth | 120 KB (measured: 7,391 emails = 7.5 MB) |

### By number of users, per month

| Users | Servers | Memory | Database | Gemini cost | **Total** |
|---|---|---|---|---|---|
| 10 | 1 | 8 GB | 0.2 GB | $0–2 | **€15–25** |
| 100 | 1 | 8 GB | 2 GB | $20 | **€45–60** |
| 1,000 | 3 | 40 GB | 20 GB | $190 | **€300–400** |
| 10,000 | 24 | 380 GB | 200 GB | $1,900 | **€2,800–3,500** |

About €0.30 per user per month at scale.

### Using an AI service vs running AI ourselves

| Model | Cheaper option | Why |
|---|---|---|
| Classifier and name spotter | **Run ourselves** | They fit on the server we already need, costing nothing extra. Renting them costs about $48 a month even when idle. The name spotter must stay with us anyway: its job is to hide private details before anything leaves |
| Gemini (reading, drafting, chat) | **Use Google's service** | Running our own equivalent needs a graphics server at about $580 a month, used or not. Google's service is cheaper until roughly 20,000 users |

| Users | Everything as a service | Everything ourselves | **Mixed (chosen)** |
|---|---|---|---|
| 10 | €60 | €560 | **€15** |
| 100 | €85 | €570 | **€50** |
| 1,000 | €400 | €850 | **€350** |
| 10,000 | €2,900 | €4,500 | **€2,900** |

### Cheapest way to start

| Item | Choice | Cost |
|---|---|---|
| Server | One 4-core, 8 GB server running everything | about €11 a month |
| Database | Free tier of a hosted Postgres | €0 to start |
| Gemini | Free tier | €0 to start |
| Confirmation emails | Free tier of an email service | €0 |
| **Total** | | **about €11–15 a month** until roughly 25 users |

---

## 8 · Hosting

- **Today:** nothing is deployed. Everything runs on a laptop, with the
  database on a hosted Postgres service.
- **To go live:** one small server running the API and the worker, with the
  database in the same region as the server so they are close to each
  other. Where to host is the company's choice.
- **One thing measured:** with the database far from the server, a single
  page could wait 1 to 3 seconds on the network. Putting both in the same
  region removes this.
- **At larger scale:** the worker checks each mailbox every 20 seconds. Push
  notifications from the providers, where they offer them, would cut the
  number of servers needed at 1,000+ users.

---

## 9 · What is left

1. **Connect a payment company** for subscriptions.
2. **Deploy** to a server.
3. **Microsoft registration** for Outlook, then test it.
4. **Test Yahoo, Zoho, iCloud** with one real account each.
5. **Sign in with Google / Microsoft** for the account.
6. **Search inside message text** (today: sender, subject, date).
7. **Google's security review**, only if the optional Google sign-in door is
   offered to the public (Google charges for it, several thousand dollars a
   year). The default IMAP connection does not need it.

---

## 10 · Safety rules the system keeps

- Nothing is ever deleted from a mailbox. Trash is a move.
- Nothing permanent happens without the person confirming the exact wording.
  This is enforced by the server, not just the screen.
- Names and private details are hidden before any text goes to Google.
- Bank, doctor, lawyer and HR emails are never opened at all.
- What the person types is an instruction; what an email says is only data.
  An email cannot instruct the system.
- Each customer's data sits in its own private section of the database.
- Passwords are never stored readable. Mailbox passwords are encrypted with
  a key that is not in the database.
- The worker and the chat never do anything permanent on their own.

---

## 11 · Where everything is

- **Code:** the GitHub repository, plus a clean copy with no history for the
  company.
- **Handover document:** `HANDOVER.md` — what was personal and must be
  recreated under company accounts, how to run and check everything in an
  hour, what is unfinished.
- **Route contract for the frontend:** `docs/API.md`.
- **Design document:** `docs/Custodian-Backend-Design.pdf`.
