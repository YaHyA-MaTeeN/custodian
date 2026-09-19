# CUSTODIAN — Project Context Document

**Purpose of this file:** paste this into any new AI chat to bring it fully up to speed. It contains every requirement, every decision made so far, and everything still open.

**Status:** planning complete for nodes A and B; component/data-flow diagram in progress.
**Last updated:** 31 Aug 2026

---

## 1. WHAT WE ARE BUILDING

> **An agent that runs your inbox for you. It clears the rubbish by itself, and asks you on WhatsApp before it sends anything as you.**

### The problem, measured
- Knowledge workers receive **~126 emails/day**
- They spend **2.6–3.1 hours/day** on email (~28% of the workweek)
- **Only 24%** of email is relevant; **only 12%** contains an action item
- They check their inbox **74 times a day**
- Each interruption costs **~23 minutes** to recover full focus

**The insight:** the problem is not volume, it is *uncertainty about timing*. People check 74 times a day because they cannot afford to miss the one email that mattered. **The product's job is to eliminate the checking**, not to make the inbox nicer.

### Why this differs from competitors
Superhuman, Shortwave, Serif, Fyxer, Cora, Gmail's own AI — **all of them make you better at being in your inbox.** None of them reduce the number of visits. We invert it: the agent works server-side and comes to you in chat.

### The governing rule
> **The more damage an action could cause, the more permission it needs.**

---

## 2. SOURCE — WHAT SIR ASKED FOR

From three recorded briefings. Full checklist:

| # | Requirement | Status |
|---|---|---|
| 1 | Attach to Gmail, Outlook, **or private/other mailboxes** | ✅ Designed |
| 2 | Read email, generate a response | ✅ |
| 3 | **Ask the user their tone first** | ✅ (added late — see §5) |
| 4 | **Learn tone and word choice from their sent replies** | ✅ |
| 5 | Ask "is this reply okay?" — **on WhatsApp** | ✅ |
| 6 | Calendar invites → automatic reminders | ✅ |
| 7 | Notifications on mobile; possibly laptop | ✅ WhatsApp covers both |
| 8 | Sort the mailbox — 5–6 tabs, or discuss them with the user | ✅ |
| 9 | Clean up the existing junk backlog | ✅ |
| 10 | Stay inside Gmail's / Outlook's own boundaries | ✅ |
| 11 | **No SMTP server, no email client** | ✅ Hard constraint |
| 12 | Red / amber / green alerts and tags | ✅ |
| 13 | Deadline reminders — 30 min for meetings, 2 days for bills, escalating | ✅ |
| 14 | User can dismiss and configure notifications | ✅ |
| 15 | **Text input; no long settings forms** (Gmail settings = anti-pattern) | ✅ |
| 16 | A rule change must find *other* rules of the same type | ✅ |
| 17 | Sensitive emails and OTPs never read | ✅ |
| 18 | Build trust — **prove** we don't read them | ⚠️ Partial |
| 19 | Don't send everything to frontier models | ✅ |
| 20 | Vector DB / RAG — needed or not? | ✅ Answered |
| 21 | Handle load — not fall over at four users | ✅ |
| 22 | **Don't store user email text; don't feed it all to an LLM** | ✅ |
| 23 | App? Chrome extension? Windows? Mac? | ✅ Answered: none |
| 24 | Lightweight base, but scalable | ✅ |
| 25 | Scope to one email account, or ten, or all | ✅ |
| 26 | **USPs — research what else can be added** | ⚠️ **Weakest area** |
| 27 | Small model, **10–100M params**, CPU-runnable | ✅ 22M classifier |
| 28 | Agent designed so the model underneath is swappable | ✅ |
| 29 | Agent → intermediary model → frontier: channel, workflow, data flow | 🔄 In progress |

### From the latest briefing (new)
| # | Requirement |
|---|---|
| 30 | **We do NOT delete. We group junk in one place; the user presses "delete all."** |
| 31 | **Don't compete with Google's spam filter.** Instead detect *important mail that landed in spam* and warn the user (with a "beware of links" caution) |
| 32 | **Group promotions by brand** — all Samsung ads together, all Apple ads together — so one action clears a whole sender |
| 33 | Build **on top of** Gmail's existing Primary/Promotions/Social split, not replacing it |
| 34 | **Bypass the LLM for learned patterns** — e.g. once we know a sender's booking-confirmation format, handle the next one with plain code |
| 35 | **A full set of prompts** is a deliverable — one per job, documented |
| 36 | Must work at real scale: sir cited an **18 GB mailbox** with hundreds of thousands of messages |
| 37 | Reminder categories and default timings — ask AI for generic defaults, then learn per user |

### Work split (sir's instruction)
- **Person A:** context document → deep research → synopsis + full feature list → review and prune it → bring to sir
- **Person B (me/us):** **the component / data-flow diagram** — every stage, its input, its output, the next stage's input, and the final output
- Both must stay in active discussion

---

## 3. THE TREE — HOW THE PROBLEM IS DECOMPOSED

```
ROOT — An agent that runs your inbox for you

├── A. SEE      — getting into the mailbox            [DONE]
├── B. KNOW     — understanding what arrived          [50%]
├── C. REACH    — getting to the human                [not started]
├── D. ACT      — doing things for you                [25%]
├── E. REMEMBER — tone and rules                      [25%]
├── F. PROTECT  — privacy                             [40%]
├── G. AFFORD   — cost                                [30%]
└── H. BUILD    — stack, phases, scale                [10%]
```

A–E are the path an email travels. F, G, H are constraints that cut across all of them.

---

## 4. MAILBOX COVERAGE

**Not Gmail alone.** One connector per family, all normalising to one internal format. Each connector **declares its capabilities** (`push`, `labels`, `folders`, `search`, `calendar`) and the product degrades gracefully and tells the user.

| Mailbox | Connector | What we get |
|---|---|---|
| Gmail / Google Workspace | Gmail API + OAuth | Full — instant push, labels, search, calendar |
| Outlook.com / Microsoft 365 | Microsoft Graph + OAuth | Full — instant push, folders + categories, calendar |
| Zoho Mail | Zoho REST API + OAuth | Full |
| Fastmail | JMAP | Full — best protocol of the four |
| Yahoo, AOL, GMX, Yandex, **university/company servers** (cPanel, Roundcube, on-prem Exchange) | IMAP + SMTP | **Reduced** — folders not labels; polled every 1–5 min, no instant push |
| **Proton Mail** | — | **Impossible.** End-to-end encrypted; Proton's own servers cannot read it either |
| **iCloud Mail** | — | **Declined.** No API; only route is asking users for a password, which contradicts what we sell |

**Build order:** Gmail + Graph first (covers nearly all work email, including Pakistani universities/companies on Workspace or M365) → then **one IMAP connector** (brings in Yahoo, AOL, and every self-hosted server at once) → Zoho and Fastmail after.

### Permissions
Four, and the user sees the exact list and can revoke instantly:
- **read**
- **label & archive**
- **send as you**
- **calendar**

**Never requested:** `messages.delete` (permanent, bypasses Trash). Requesting it would force a much more expensive annual security review.
**But delete IS available** as `messages.trash` — exactly what the bin icon does, recoverable 30 days, **already covered by `gmail.modify`**.

### Google's compliance requirement (verified)
- Restricted scopes need **CASA Tier 2** — a **self-scan** submitted to a lab, ~**$675/year** via Google's recommended assessor (TAC Security). **Nobody audits us on-site.**
- **Only Google requires this.** Microsoft, Zoho, Fastmail, IMAP: free, no equivalent.
- **Exemptions:** Testing mode (100 users, no review) · **internal install for a single organisation — no review, ever**
- Full-mailbox access (incl. permanent delete) would trigger **Tier 3** — a full penetration test. Avoided by design.

### How we learn new mail arrived
- **Door 1:** the provider notifies us (Gmail `users.watch` + Pub/Sub; Graph subscriptions)
- ⚠️ **Gmail's watch expires after 7 days, silently, with no error.** Renew **daily**, and **alarm on silence, not just on errors**
- **Door 2 (IMAP):** poll every 1–5 min, tiered by how active the user is. **Never hold persistent IDLE connections** — providers cap concurrent connections (Yahoo ~5 *per IP*, cPanel ~40 per IP), so a socket farm gets us blocked

### Scoping
**Per account.** A user connects several mailboxes and switches each on or off independently. Accounts that are off are **never opened at all** — not "read and ignored."

---

## 5. THE FOUR-LAYER PIPELINE

Every email falls through four layers. **Each either answers confidently or says "I don't know" and passes it up. No layer is permitted to guess.**

| Layer | Component | Cost | Handles (est.) |
|---|---|---|---|
| **1 · Header rules** | Our own code, ~200 lines | Free, microseconds | ~60% |
| **2 · Libraries** | `duckling` + `dateparser` | Free, milliseconds | ~10% |
| **3 · Our model** | SetFit on `all-MiniLM-L6-v2` | Free, our CPU, ~5 ms | ~25% |
| **4 · Frontier** | Claude Sonnet 5 | **Costs money** | ~5% — **writing only** |
| **Escape hatch** | Show the email to the user | Free | Anything nobody is sure about |

### Escalation rules
```
LAYER 1  no clear header signal                 → escalate
LAYER 2  duckling top result < 0.80             → escalate
         two results within 0.10 (ambiguous)    → escalate
         nothing found                          → escalate
LAYER 3  top category below calibrated threshold→ escalate
LAYER 4  or, if not a writing task              → SHOW THE USER
```

### Verification gate (on top of confidence)
```
model claims: deadline = 2026-09-15, quote = "before 15 September 2026"
  does that quote exist in the email?  ✗ → DISCARD
  is the date in the future?           ✗ → DISCARD
  does the date match the quote?       ✗ → DISCARD
```
**Confidence is not trust.** Every answer below layer 4 is checkable against the source text, so a wrong answer is caught automatically.

### The principle that decides everything
> **Anything with a checkable answer is done free, on our own machine. Only writing a reply — the one job with no automatic check — is paid for.**

---

## 6. THE MODEL

**`all-MiniLM-L6-v2` trained with SetFit — 22 million parameters, ~90 MB, ~5 ms per email on CPU. No GPU, ever.**

### Its three jobs
1. **Two labels per email:**
   - *What does the sender want?* → asking · proposing · promising · delivering · telling
   - *What is it about?* → meeting · money · work · account · personal · bulk
2. **Which of several dates is the real deadline**
3. **Is this a real person or automated?** — the case headers cannot settle (transactional mail and cold sales email both look personal)

### Why sort by "what do they want" and not by topic
Two emails both about a meeting:
- *"Confirming the meeting is Thursday 3pm"* → **telling** → no action
- *"Can we move Thursday to Friday?"* → **proposing** → needs a decision

**Topic doesn't tell you what to do. Speech act does.** Grounded in Cohen, Carvalho & Mitchell, *Learning to Classify Email into Speech Acts*, EMNLP 2004.

### Why 22M is enough
- It only classifies; it never writes
- DistilBERT (66M) benchmarks at 93–95% F1 on classification; MiniLM is faster with minor loss
- A larger model costs more and adds nothing for a fixed set of ~11 labels
- **Inside sir's 10–100M range** — achieved by removing writing from its job, not by compromising

### Why SetFit solves the cold-start problem
> **SetFit reaches ~92.7% accuracy from 8 labelled examples per class** — competitive with fully fine-tuning a 3× larger model on 3,000 examples, and ~19× faster to train.

11 labels × 8 = **~90 hand-labelled emails.** One afternoon, trains on a laptop.

### Why not use the frontier model for classification
| | Calls/user/month | Cost | Privacy |
|---|---|---|---|
| Frontier classifies everything | ~3,800 | ~$37 | Every email leaves |
| **Our model classifies, frontier writes** | ~240 | **~$2.40** | **Only replies leave, de-identified** |

### How it improves
Every user correction and every frontier escalation becomes a new labelled example. **Retrain monthly.** Escalations fall, cost falls. **The system gets cheaper as it gets older.**

### Priority scoring (separate from the classifier)
**scikit-learn logistic regression** — the same method Google published for Gmail Priority Inbox (Aberdeen & Pacovsky).
- Predicts **"will this person act on it?"** — measurable — not "is it important" — a feeling
- Signals: **what share of this sender's mail do you reply to** (strongest) · open rate · did you start the thread · are you the only recipient
- Global model + per-user correction
- **Explains itself:** *"you reply to 94% of this sender's mail, and it mentions tomorrow"*

### Cold start for a brand-new user
1. **The backlog scan is the training set.** We already see who they've replied to, going back years
2. A general starting model for signals true of everyone

### First-time senders (the hard case)
An important email from someone you've never heard from — a job offer, a first FBR notice.
- **When unsure, show it.** Hiding something important costs far more than showing something trivial
- Signals that work without history: were you singled out? does it look human-written? **is it a reply to a thread you started?** is the domain institutional?
- **An institution registry** — FBR, NADRA, banks, utilities, universities — important by definition, no history needed. **A hand-curated data asset no foreign competitor will build.**

---

## 7. INPUT — HOW THE USER GIVES INSTRUCTIONS

**Everything is a plain WhatsApp message. There is no settings screen anywhere.**

| Kind | Example | Handled by | Cost |
|---|---|---|---|
| **1. Answering us** | "send" · a button tap | Word matching, no model | Free |
| **2. Command about the last message** | "archive that" · "remind me tomorrow" | Our 22M classifier + context | Free |
| **3. A standing rule** | "stop reminding me two days before doctor appointments, two hours is enough" | Three layers, below | Free → pennies |
| **4. A question** | "what did FBR send me?" | Database query | Free |

### Kind 3 decomposes into three easy problems
| Piece | What it is | Handled by |
|---|---|---|
| "stop reminding me… is enough" | Which command (~10) | Our 22M classifier |
| "two days", "two hours" | Time values | **duckling** — already in the stack, reports confidence |
| "doctor appointments" | Which category | Our 22M classifier |

### The three input layers
| Layer | Model | Size | Handles |
|---|---|---|---|
| 1 | SetFit + duckling | 22M | The ~10 common command shapes |
| 2 | **Qwen3-0.6B + GBNF grammar** | 600M (~400 MB at 4-bit) | Unusual phrasings. **Grammar makes invalid output impossible** — 100% valid structure, 5–15% throughput cost. **Handles Urdu / Roman Urdu** |
| 3 | Claude Sonnet 5 | — | Genuinely novel — ~5× per user per month |

### Why a wrong parse is harmless
**The model proposes; the user confirms.** It never executes.
```
You:   stop reminding me 2 days before doctor appointments
Agent: Found 4 rules of type "appointment". Changing 2 days → 2 hours.
       Affects: doctor, dentist, physiotherapy, lab tests
       [Apply all] [Only doctor] [Cancel]
```
A wrong parse produces a wrong **proposal**, rejected with one tap. Never a wrong **action**. **Never generalise a rule silently.**

### Where settings live
Three sources, **none a form**: sensible defaults · the user correcting something · the user saying a sentence. At runtime only stored rules execute — **no model involved**. The dashboard merely lists rules with a delete button.

---

## 8. TONE AND WRITING STYLE

**Both a stored profile AND retrieved examples.** Sir asked for both.

### The style profile (stored, small, inspectable, editable)
```
Greeting        "Sir," to seniors · "Hi [name]," to peers
Sign-off        "Thank you," — 89% of replies
Length          Short. Median 47 words
Formality       Formal with supervisor · casual with team
Language        English, occasional Urdu with close contacts
Habits          Rarely uses bullets · often opens "Just confirming"
```
Built two ways: **three quick questions at signup** (sir: *"tone poochenge sab se pehle user se"*), then refined from the Sent folder. **The user can see and correct it.** It is derived structure, not content — permitted under our storage rule.

### The examples (retrieved, per draft)
1. Every sent email → converted to **384 numbers** by our 22M model. **We store the numbers and the message ID, not the text**
2. New email needing a reply → converted the same way
3. **pgvector finds the 5 closest** — pure arithmetic, no AI
4. Those 5 are **fetched fresh from the mailbox**, used, and discarded
5. Frontier model imitates them

**Research basis:** style-transfer literature finds **2–5 examples suffice and imitation plateaus at 4–5**; supervised fine-tuning does **not** beat in-context examples when style data is scarce. So we retrieve exactly **4–5**.

**The profile is the rule; the examples are the demonstration.** Both go into the prompt.

---

## 9. ACTIONS — THE RISK TIERS

| Tier | Where it lands | Approval | Undo |
|---|---|---|---|
| **0** Thinking | Our server only | **None ever** | — |
| **1** Tidying | Your mailbox, only you see it | **Once, per action type** | Instant (Trash: 30 days) |
| **2** Signal out | Someone else is told | **Per type** | Manual |
| **3** Speaks as you | **A person reads it** | **Every single time** | **Never** |
| **4** — | — | **Not built** | — |

### Tier 0 — our server, nothing changes
`read` · `classify` · `tag internally` · `extract deadline/amount` · `build sender memory` · `detect sensitive`

### Tier 1 — mailbox changes
| Action | Gmail | Graph | IMAP |
|---|---|---|---|
| label | `labels.create` once, then `messages.modify` + `addLabelIds` | `PATCH /messages/{id}` categories | No labels — folders |
| move to folder | applying a label *is* the move | `POST /messages/{id}/move` | `MOVE n Folder` |
| archive | `messages.modify`, remove `INBOX` | move to Archive | `MOVE n Archive` |
| **move to Trash** | `messages.trash` — **30-day undo, no extra permission** | move to Deleted Items | `MOVE n Trash` |
| mark read/unread | add/remove `UNREAD` | set `isRead` | `STORE n +FLAGS (\Seen)` |
| star/flag | `STARRED` label | `flag` property | `STORE n +FLAGS (\Flagged)` |
| **snooze** | **No API on any provider — we build it:** archive now + scheduled job restores it | | |

### Tier 2 — a signal goes out
| Action | How |
|---|---|
| **unsubscribe** | The `List-Unsubscribe` header **contains the address**. One `POST` (RFC 8058 one-click), or a `mailto:`. **Same on every door — it's in the email itself. No AI, no provider API** |
| RSVP | Google `events.patch` responseStatus · Graph `POST /events/{id}/accept` · IMAP: iCal REPLY over SMTP |
| create calendar event | `events.insert` · `POST /me/events` · CalDAV where available |
| set reminder | **Never touches the mailbox.** A row in our jobs table |

### Tier 3 — speaks in your name
| Action | How | Trap |
|---|---|---|
| **draft** | build prompt → **Presidio strips names** → Sonnet → restore names locally → show on WhatsApp | **The only step where anything leaves our servers** |
| **send** | `messages.send` + `threadId` · `POST /messages/{id}/reply` · IMAP: **SMTP then `APPEND` to Sent** | Needs `In-Reply-To` + `References` or it starts a new thread. **On IMAP, skip the APPEND and the user's Sent folder is missing their own email** |
| forward | same call, original quoted/attached | attachments must be re-attached |
| CC / delegate | same call with `cc` | adds a person — always individual approval |
| decline meeting | `events.patch` declined · `POST /events/{id}/decline` | organiser notified immediately |

### Tier 4 — not built
`messages.delete` (permanent, bypasses Trash) · change account settings · grant access · email a new recipient unprompted.
**No function exists in our code, and we never request the permission.** Two independent barriers.

### The model never acts
```
model returns a label → our code writes an instruction → provider checks our permission → provider performs it
```
**No model ever contacts a mailbox.** Every change is a line of our own code, logged and undoable.

---

## 10. THE CLEANUP (backlog)

**Sir's version, which supersedes my earlier design:**
> *"We will not delete anything for you unless you ask us to. **We will sort it for you, put it in one place so you can simply do a delete all.**"*

### How it works
1. **Scan all messages — envelope only.** Nothing is opened. For old mail we only need "is this junk?", which is answerable from the sender
2. **Group by sender/brand** — sir specifically: all Samsung ads together, all Apple ads together
3. **Present ~12 decisions, not 1,900** — one tap clears 412 LinkedIn emails
4. **Show the plan first. Nothing moves until approved**
5. **Collect the junk in one place. The user presses delete-all.** We never delete
6. **Show progress as it goes** — "41 newsletters, 412 from LinkedIn, **3 unpaid bills**". That last line is what sells it

### Quota reality (verified)
Gmail allows **250 units/user/second, 15,000 units/user/minute**, 1B/day per project. A 20,000-message backfill at ~5 units per read ≈ 200,000 units ≈ **13 minutes**. Safe. **The project-level ceiling (1.2M units/min) is the one to watch as user count grows — onboarding must be queued.**

### Spam — don't compete, rescue
Google's spam filter is better than anything we'd build. **Instead: detect important mail that landed in spam and warn the user**, with sir's exact caution: *"this looks like an important email and it is in spam. Beware of clicking any link, but we are sharing this with you."* **Nobody does this.**

---

## 11. PRIVACY

### The core rule
> **We read, but we don't keep.**

An email passes through **memory** (a whiteboard, wiped in seconds) and is never written to **storage** (the filing cabinet). We keep the **conclusions** — "from your professor, urgent, deadline Friday" — not the message.

**A break-in exposes seconds of activity, not years of history.**

### The four depths
| Depth | What it sees | Share of mail |
|---|---|---|
| 1 | Sender only | ~70% never opened |
| 2 | + subject | |
| 3 | Full message, **our machine only** | ~25% |
| 4 | Full message, **sent outside, names stripped** | ~5% — **replies only** |

**Nine functions out of ten never involve an outside company at all.**

### Sensitive mail
OTPs, banking, health, legal — detected from **sender + subject shape** *before anything else runs*, then **nothing opens them.** Not our model, not the frontier. **The most sensitive mail is the mail we read least.**

### Tokenized egress
`Presidio` replaces names, addresses, phone numbers, account numbers with placeholders (`<PERSON_1>`, `<AMOUNT_1>`) before anything leaves; restored locally after.
⚠️ **Its accuracy must be measured before the privacy claim is made publicly.** Presidio covers ~18 entity types and recall drops beyond them; `GLiNER` can be plugged in to widen coverage. **Low-confidence redaction must route back to layer 3 rather than out.**

### What we cannot currently claim
**Zero data retention is only available via an enterprise contract addendum requiring provider approval.** Standard terms retain inputs 7–30 days for abuse monitoring. **Do not claim ZDR.** The honest statement: *content is de-identified before it leaves, retained up to 30 days under standard terms, contractually never used for training.*

### Legal
- **Google Workspace policy forbids** using API-derived data to train generalized models. Hard constraint, and it matches our design
- **Pakistan has no data protection law in force.** The draft PDPB (unenacted since 2023) would require **"critical personal data" to stay on servers inside Pakistan** → **keep the storage layer region-configurable from day one**
- Build to GDPR standards regardless — our "store structure not content" rule already satisfies most of it

### Proving non-access — four levels
1. Policy (weak — everyone has one)
2. **Data Passport** — per-message record of what left, redacted how, to which model *(ship in V2)*
3. **Open-source the privacy gateway** *(ship in V2)*
4. **Hardware attestation** — confidential-computing GPUs run at 95–99% of native speed, 1–3 s attestation, available on major clouds *(roadmap)*

---

## 12. RAG / VECTOR DATABASE — VERDICT

| Use | Verdict | Why |
|---|---|---|
| **Style-example search** | ✅ **pgvector** | Needs similarity search. **Inside the PostgreSQL we already run** — no separate service |
| Vector index over the whole inbox | ❌ No | Most expensive; **requires storing content we promised not to keep**; email is thread-scoped, not corpus-scoped |
| Searching mail | ❌ Use theirs | Gmail/Outlook search is excellent. Building ours means storing content |
| "What did FBR send me?" | ❌ No | Plain SQL over fields we already extracted |

**`all-MiniLM-L6-v2` is natively an embedding model** — SetFit adds a classification head on top. **One 22M model gives us both classification and the style search.** No second model, no extra cost. **The vector store holds no content** — a fingerprint and a message ID.

---

## 13. THE CHANNEL — WHATSAPP

**WhatsApp Cloud API, direct from Meta.**

### Requirements (verified, Pakistan)
- Meta Business account (free)
- **Business verification: SECP or firm registration · FBR NTN · a live website with a privacy policy and contact page.** All must match Meta Business Manager records exactly
- A dedicated phone number not on regular WhatsApp
- Review: 24 hours to 15 working days

**This is a company paperwork task, not engineering. It is the only external dependency and should start immediately, in parallel with development.**

### Cost design
Messages we initiate must be **pre-approved templates, billed per message**. But **once the user replies, a 24-hour window opens where everything is free-form and free.**
→ **One template per user per day** opens the window; every approval, reminder and setting change that day rides inside it, free. Interactive buttons supported, so *Send / Edit / Ignore* are taps.

---

## 14. CLIENTS

**One backend, thin clients.** Mail arrives while the phone is asleep, so the agent must be server-side.

| Surface | When | Reasoning |
|---|---|---|
| **Web page** | V0 | Setup only, used once. **Required** — OAuth needs a web address to redirect back to |
| **WhatsApp** | V0 | The daily interface. Covers every OS at once, nothing to install |
| Mobile app | V3 | Real push, richer approvals. One cross-platform codebase |
| **Chrome extension** | **Never (V3 at earliest)** | **Manifest V3 kills the persistent background page.** An extension can only be a *view* onto a server agent, never the agent |
| Desktop app | **Skip** | WhatsApp Desktop already exists, free |
| Public SDK | Not now | Freezes interfaces we still change weekly |

**On-device agent — evaluated and rejected:** iOS gives ~30 seconds, 2–3× per hour, throttled, and **nothing at all in Low Power Mode**; Android's Doze demotes apps you don't open. **An on-device agent only works when the app is open — which replaces checking Gmail with checking us.** A "server sees envelopes only, phone handles bodies" hybrid is coherent and kept as a possible future privacy mode.

---

## 15. THE STACK — DECIDED

| Job | Choice |
|---|---|
| Language | **Python 3.12** |
| Web / API | **FastAPI** |
| Database | **PostgreSQL 16 + pgvector** |
| Background jobs | **Postgres jobs table + worker loop** (no Redis) |
| Email parsing | **`email`** (stdlib); `flanker` only if speed is measured as a problem |
| Dates, money | **`duckling`** — returns a probability, which is our escalation signal |
| Dates, more languages | **`dateparser`** — 200+ locales |
| Our model | **SetFit on `all-MiniLM-L6-v2`** — 22M params |
| Model runtime | **ONNX Runtime** — fastest CPU inference for this type |
| Priority score | **scikit-learn** logistic regression |
| Command parsing (unusual) | **Qwen3-0.6B + GBNF grammar** |
| Name stripping | **Presidio** (+ GLiNER if coverage needs widening) |
| Writing replies | **Claude Sonnet 5** ($2 / $10 per MTok), behind a swappable interface |
| Channel | **WhatsApp Cloud API** |

**No agent framework.** Our pipeline is deterministic by design; frameworks exist to manage the unpredictability we removed. **But the approval loop must be durable** — it waits hours for a human, and an approval lost to a server restart is a product failure. Pending state lives in the database, never in process memory.

### Where it runs
| Stage | Machine | Cost |
|---|---|---|
| Development | A laptop | $0 |
| First 100 users | **1 server: 4 vCPU, 8 GB RAM, 80 GB. No GPU** | ~$25/month |
| To 10,000 users | 4–6 workers, a read replica, 2 model instances | ~$700/month |

**Scaling is by addition** — more copies of stateless workers against shared PostgreSQL. No microservices, no Kubernetes, until measured need.

---

## 16. COST

| | |
|---|---|
| Every library and model listed | **$0 — all open source** |
| Running cost per user per month | **$1–3** |
| Naive (everything to a frontier model) | **$14–92** depending on model |
| **Saving, like-for-like same model** | **~15×** |
| Google security review (public launch only) | ~$675/year |
| **Competitors charge** | **$14–30 per user/month** |

**Verified pricing:** Haiku 4.5 $1/$5 · Sonnet 5 $2/$10 (the planned rise to $3/$15 was cancelled) · Opus 5 $5/$25. Cache reads 0.1×; batch 50% off.

### Two honest corrections
- **Prompt caching probably won't help us** — caches last 5 min / 1 hour, and our ~8 calls/day per user are too spread out. Most reads would miss
- **Newer models use a tokenizer producing ~30% more tokens** for the same text, so Sonnet 5 is effectively ~2.6× Haiku, not 2×
- **Self-hosting the frontier model is wrong** until ~100M tokens/day (~5,000 active users). Ops adds 3–5× to raw compute. **This does NOT apply to our 22M classifier**, which has no meaningful operational burden

---

## 17. COMPETITION

| Product | Price/mo | Where it stops |
|---|---|---|
| Superhuman | $30 | You still live in your inbox |
| Serif AI | $30 | Closest on voice. No privacy architecture |
| Fyxer | $22.50–30 | **Charges overage above a volume allotment** — a sign their cost model isn't solved |
| Cora | $20 | Narrower; no deadline layer |
| Shortwave | $14+ | Still an inbox you open |
| Gmail's own AI | Bundled | Google-only, assists while you read — not an agent |

### ⚠️ Raise this yourself: **Inbox Zero**
Open source, **~10,700 GitHub stars**, actively developed, TypeScript/Next.js, Gmail **and** Outlook, self-hostable. Already does triage, labelling, **drafting in your voice**, bulk unsubscribe.

**Why that's good news:** it validates the market, it's a free reference implementation (Gmail OAuth, watch renewal, label management, unsubscribe flows all solved in readable code — **read it in week one**), and its gaps map onto our positioning — inbox-first not chat-first, no privacy architecture, no cost cascade, no small-model tier, no deadline layer, nothing local to Pakistan.

### Where we win
1. **Chat-native, no client** — architectural, not featural. They can't copy without abandoning what they sell
2. **Structural privacy** — an architecture, not a feature. Retrofitting means rebuilding the data path
3. **Cost** — $1–3 to serve against a $14–30 market
4. **Deadline Radar** — nobody does this properly
5. **Local intelligence** — FBR, NADRA, banks, universities. No foreign competitor will build it
6. **Scope control** — the feature that gets a cautious user to try it at all

**1 and 2 are defensible. 3–6 are ours to lose on execution.** That's the honest framing.

---

## 18. OPEN / MUST MEASURE

| # | Item | Why it matters |
|---|---|---|
| 1 | **What share of a real inbox the free header rules actually handle** — assumed ~60% | **The entire cost model depends on this.** Method: export 1,000 emails with `format=metadata`, hand-label bulk/notification/needs-human, measure — and especially the **false-positive rate on "needs a human"**, which must be under 1% |
| 2 | **How often Presidio misses a real name** | **The privacy claim must not be made publicly until measured.** Build a 200–300 email labelled set |
| 3 | Model accuracy on real Pakistani email, not benchmark data | |
| 4 | **USPs** — sir asked for this explicitly and it's the thinnest area | |
| 5 | Testing-mode token expiry (believed ~7 days — unverified) | Affects whether pilot users must reconnect weekly |
| 6 | **The full prompt set** — one per job, documented | Sir named this as a deliverable |
| 7 | Reminder categories and default timings | Sir: get generic defaults from AI, then learn per user |

---

## 19. NEXT DELIVERABLE

**The component / data-flow diagram** — sir assigned this specifically:

> *"Poora data flow nikal ke dena hai... email read hogi, email read hone ke baad kis ke paas jayegi? Jis ke paas jayegi wo is ke upar kya kaam karega? Phir is ke baad next step kya hoga? Phir is ka output kya hoga, agle ka input kya hoga? Eventually sari pipeline jab run hogi tou final output kya hoga."*

Every stage: **its input → what it does → its output → the next stage's input**, through to the final output. The final output depends on the feature list, which is the other workstream.

---

## 20. THINGS THAT WOULD BE EASY TO GET WRONG

- **Gmail's watch expires silently after 7 days.** No error, mail just stops arriving. Renew daily; alarm on silence
- **Replies need `In-Reply-To` and `References`** or they start a new conversation
- **On IMAP, SMTP does not file your Sent copy.** You must `APPEND` it or the user's own email vanishes from Sent
- **Snooze has no API on any provider.** Build it yourself
- **IMAP `IDLE` doesn't scale** — providers cap connections per IP. Poll instead
- **Removing `CATEGORY_PROMOTIONS` puts the message in Primary** as a side effect
- **Labels must be created once and their ID stored**, not created per message
- **The user has several mailboxes, not one.** Model it that way from the first commit
- **Approval fatigue is a documented failure mode** — a human turned into a QA checker stops reading and just taps send. Approval must be graduated: silent for filing, batched for review, individual only for sending, earned autonomy after ~20 unchanged approvals

---

*Every factual claim here — API methods, prices, benchmark figures, legal requirements — was verified against primary documentation or published research. Percentages marked as estimates are exactly that.*
