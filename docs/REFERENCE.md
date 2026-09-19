# Reference — everything in the system

Working reference for building the mail agent. Written to be read by someone who has to
implement this, not someone being sold it.

**How to read this.** Every part opens with an **In plain terms** box — that is the version to read if you just want to understand what the stage does. Everything after it is the detail you need when you are actually writing the code. **You can read only the boxes and still follow the whole system.**

**Marking.** Anything marked `[verify]` is something I worked out from published
figures rather than measured — check it before quoting it as fact. Anything marked
`[unknown]` genuinely has no published answer and needs a pilot mailbox.

Started 3 Sept 2026.

---

# Part 1 — The four doors

Stage 1 of the pipeline says `Gmail API · Graph · JMAP · IMAP`. Those are four different
ways to reach a mailbox. They are not interchangeable, and the differences decide a lot of
the architecture. This part explains each one properly.

The key idea to hold: **we are not writing four mail agents.** We write one, and put a thin
adapter in front of each door. Every adapter answers the same questions — *give me new
mail*, *label this*, *send this* — and **declares what it can and cannot do**, so the rest
of the pipeline never has to know which door it came through.

---

## 1.1 IMAP — the universal one

> **In plain terms.** Your email does not live on your phone. It lives on a computer somewhere else, and your phone asks that computer for it every time you open the app. **IMAP is the language used to do the asking.** It is old and slow, but every mail server on earth speaks it — think of it as English at an airport. **We use it for every mailbox that is not Gmail or Outlook**, and it is the thing that makes "works with any mailbox" a true statement rather than a marketing one.

**What it is.** Internet Message Access Protocol. A text protocol, spoken over a TCP
socket, that lets a client read and manipulate mail *stored on a server*. It is the reason
you can read the same mailbox from your phone and your laptop and see the same state.

**The specs.**

| | |
|---|---|
| RFC 3501 | IMAP4rev1 (2003) — what essentially everything implements |
| RFC 9051 | IMAP4rev2 (2021) — cleaned up, folds in common extensions, low adoption so far |
| RFC 5321 | SMTP — **sending is a different protocol entirely** |
| RFC 6409 | Message submission, port 587 |

**How a session actually looks.** You open a TLS socket to port 993, and then it is a
conversation in plain text. Every command you send carries a tag you invent; the server
replies with untagged lines starting `*`, then a tagged line telling you the command
finished.

```
S: * OK [CAPABILITY IMAP4rev1 IDLE MOVE CONDSTORE] Ready
C: a001 LOGIN user@example.com hunter2
S: a001 OK LOGIN completed
C: a002 SELECT INBOX
S: * 4213 EXISTS
S: * OK [UIDVALIDITY 1234567890]
S: * OK [UIDNEXT 8891]
S: a002 OK [READ-WRITE] SELECT completed
C: a003 UID FETCH 8850:* (UID FLAGS BODY.PEEK[HEADER])
S: * 4210 FETCH (UID 8850 FLAGS (\Seen) BODY[HEADER] {842}
S: ...
S: a003 OK FETCH completed
```

**It is stateful.** The connection remembers which folder you have selected. There are four
states: not authenticated, authenticated, selected, logout. You cannot fetch a message
without selecting its folder first. **One folder at a time, per connection.**

**The commands that matter.**

| Command | What it does |
|---|---|
| `CAPABILITY` | Ask what extensions this server supports. **Always do this first** — servers differ wildly |
| `LOGIN` / `AUTHENTICATE` | Password, or SASL. For Gmail and Outlook you use `AUTHENTICATE XOAUTH2` with an OAuth token, not a password |
| `LIST` | Enumerate folders |
| `SELECT` / `EXAMINE` | Open a folder (read-write / read-only) |
| `FETCH` | Get message data. `BODY.PEEK[]` fetches **without** marking as read — use this, always |
| `SEARCH` | Server-side search. Weak compared to Gmail's |
| `STORE` | Change flags — mark read, flag, mark deleted |
| `COPY` / `MOVE` | Move between folders. `MOVE` is an extension (RFC 6851); fall back to COPY + STORE + EXPUNGE |
| `EXPUNGE` | Actually remove messages flagged `\Deleted` |
| `APPEND` | Put a message *into* a folder — this is how you save a draft |
| `IDLE` | Ask the server to push updates instead of polling (RFC 2177) |

**Two numbering systems, and this trips everyone up.**

- **Sequence numbers** — 1, 2, 3… position in the folder. **They shift when anything is
  deleted.** Never store these.
- **UIDs** — stable identifiers within a folder. Store these. But they are only meaningful
  together with the folder's `UIDVALIDITY`; if the server changes `UIDVALIDITY`, every UID
  you cached is meaningless and you must resync from scratch.

**Flags.** `\Seen`, `\Answered`, `\Flagged`, `\Deleted`, `\Draft`, `\Recent`, plus
server-defined keywords. Note there is **no concept of a label** — a message lives in
exactly one folder.

**Extensions worth knowing.**

| Extension | RFC | Why you care |
|---|---|---|
| `IDLE` | 2177 | The only push mechanism. Server tells you when mail arrives. **One folder per connection**, and connections must be renewed roughly every 29 minutes |
| `CONDSTORE` | 7162 | Every message gets a modification sequence. Lets you ask *"what changed since modseq X"* instead of re-scanning |
| `QRESYNC` | 7162 | Fast resync after being offline — tells you what was deleted too |
| `MOVE` | 6851 | Atomic move. Without it, moving is three commands and can half-fail |
| `SPECIAL-USE` | 6154 | Tells you which folder is Sent, Drafts, Trash, Archive — otherwise you are **guessing from folder names in the user's language** |
| `COMPRESS` | 4978 | Deflate the connection. Meaningful over slow links |
| `OBJECTID` | 8474 | Stable IDs that survive moves. Rare |

**What IMAP cannot do.**

- **No labels.** One folder per message.
- **No server-side threading** worth using. You reconstruct threads yourself from
  `Message-ID` / `In-Reply-To` / `References`.
- **Push is weak.** `IDLE` holds a connection open per folder. Watching 5 folders for 1,000
  users is 5,000 open sockets.
- **Bulk operations are slow.** No batching primitive.
- **Connection limits.** Gmail allows 15 simultaneous IMAP connections per account
  `[verify]`. Other providers vary and often do not document it.
- **Sending is a separate protocol** — SMTP on port 587, with its own auth.

**When we use it.** Everything that is not Gmail, Outlook, or a JMAP server. Which is a
lot: company mail servers, cPanel hosting, Zoho, Yahoo, ProtonMail Bridge, Rediffmail,
university mail. **This is the door that makes "any mailbox" true.**

**Library.** Python's stdlib `imaplib` works but is unpleasant — it returns raw bytes and
leaves parsing to you. Use **`imapclient`** instead; it wraps `imaplib`, parses responses
into Python types, and handles IDLE. For sending, stdlib `smtplib` is fine.

---

## 1.2 Gmail API — Google's own

> **In plain terms.** Google built its own, better way of talking to Gmail. It understands labels and conversations properly, it can search the way the Gmail search box does, and **it can tell us the instant mail arrives instead of us having to keep asking.** The catch is obvious: it only works for Gmail. This is the door we build first, because most people are on Gmail.

**What it is.** Not IMAP. A REST API over HTTPS returning JSON, specific to Gmail. You make
ordinary HTTP requests to `https://gmail.googleapis.com/gmail/v1/...` with an OAuth bearer
token.

**Why it exists.** Gmail's data model does not fit IMAP. Gmail has **labels**, not folders —
one message can carry many. It has real threads. It has a search engine. IMAP can only
pretend to expose these.

**The resources.**

| Resource | What it holds |
|---|---|
| `users.messages` | Individual messages. The main one |
| `users.threads` | Conversations, as first-class objects |
| `users.labels` | Labels — both Gmail's own (`INBOX`, `UNREAD`, `SPAM`, `TRASH`, `STARRED`) and ones we create |
| `users.drafts` | Drafts |
| `users.history` | **The change feed.** Explained below — this is the important one |
| `users.settings` | Filters, forwarding, vacation responder, delegates |

**The methods we use.**

| Method | Purpose | Notes |
|---|---|---|
| `messages.list` | Get message IDs matching a query | Supports the full Gmail search syntax in `q` |
| `messages.get` | Fetch one message | **Four formats** — see below |
| `messages.modify` | Add/remove labels | This is how you label, archive, and mark read |
| `messages.trash` | Move to Trash | **Recoverable 30 days. This is our delete** |
| `messages.untrash` | Undo the above | |
| `messages.delete` | **Permanent.** Needs full-mailbox scope | We never call this |
| `messages.send` | Send | |
| `drafts.create` | Save a draft | |
| `labels.create` | Make a label | Once per label, not per message |
| `history.list` | What changed since X | |
| `users.watch` | Turn on push | |

**The four fetch formats — this matters for cost and privacy.**

| Format | Returns | Quota |
|---|---|---|
| `minimal` | IDs and label IDs only | 5 units |
| `metadata` | Headers only, **no body** | 5 units |
| `full` | Parsed payload including body | 5 units |
| `raw` | The entire original message, base64url | 5 units |

**We use `metadata` for the day-one backfill** — it gives sender, date, subject, threading
headers, and the unsubscribe stamp, **without ever fetching a body.** That is what makes
the envelope-only backfill honest rather than a technicality.

**Change tracking — `history.list`.** Every mailbox has a monotonically increasing
`historyId`. You store the latest one you have seen; later you ask *"what happened since
`historyId` = N?"* and get back a list of messages added, deleted, and label changes.

**The catch: Google only keeps history for about a week `[verify]`.** If your worker has
been down longer than that, `history.list` returns `404` and **you must fall back to a full
resync.** Write that fallback on day one; it will fire.

**Push — `users.watch` + Pub/Sub.** Real push, and it is good, but it has moving parts:

1. Create a **Google Cloud Pub/Sub** topic and a subscription.
2. Grant `gmail-api-push@system.gserviceaccount.com` publish rights on that topic.
3. Call `users.watch` naming the topic.
4. Gmail publishes a tiny message — just the email address and the new `historyId` — every
   time the mailbox changes.
5. You then call `history.list` to find out what actually happened.

**The watch expires in 7 days and must be renewed.** Renew daily, not weekly. The push
payload never contains mail content — it is only a nudge.

**Quota.** Google charges "quota units" per call, not per request.

| | |
|---|---|
| Per-project | 1,200,000 units/minute `[verify]` |
| Per-user | 15,000 units/minute, i.e. ~250 units/second `[verify]` |
| `messages.get` | 5 units |
| `messages.list` | 5 units |
| `messages.modify` | 5 units |
| `messages.send` | 100 units |

**The per-user limit is what binds us**, not the project limit. Reading 40,000 envelopes at
5 units each is 200,000 units — at 250/second, **about 13 minutes.** That is where the
day-one backfill estimate comes from. `[verify]` — published quota figures have changed
before, so check the live page.

Exceeding it returns `429` with `rateLimitExceeded`. **Exponential backoff with jitter is
mandatory**, not optional.

**Search.** The `q` parameter takes the same syntax as the Gmail search box —
`from:`, `has:attachment`, `newer_than:2d`, `label:`, `is:unread`. This runs on Google's
side and is genuinely powerful. **Losing it is the real cost of asking for a narrower
scope** — the metadata-only scope blocks server-side search.

**Library.** `google-api-python-client` plus `google-auth-oauthlib`. Verbose, but it is the
official one and it handles token refresh.

---

## 1.3 Microsoft Graph — Outlook and Microsoft 365

> **In plain terms.** Microsoft's version of the same idea, for Outlook and Microsoft 365. One extra advantage worth knowing: **the same permission that opens the mail also opens the calendar** — so checking whether someone is free is one more question, not a second integration. This is the door we build second.

**What it is.** A single REST API across all of Microsoft 365 — mail, calendar, contacts,
files, Teams, users. Mail is one part of it. Base URL
`https://graph.microsoft.com/v1.0/`.

**Why it matters that it is unified.** The same token that reads mail can read the
calendar. When we want to check whether a proposed meeting time is free, **that is one more
endpoint, not a second integration.** Gmail splits these across separate APIs.

**The shape.**

| Endpoint | What |
|---|---|
| `/me/messages` | All messages |
| `/me/mailFolders` | Folders — `inbox`, `archive`, `deleteditems`, `drafts`, `sentitems` are well-known names |
| `/me/mailFolders/{id}/messages` | Messages in a folder |
| `/me/messages/{id}/reply` | Reply, in one call |
| `/me/messages/{id}/forward` | Forward |
| `/me/messages/{id}/move` | Move to a folder — **this is how you archive and how you trash** |
| `/me/sendMail` | Send a new message |
| `/subscriptions` | Webhooks |

**Folders, not labels — but there are categories.** Outlook is folder-based, so a message
lives in one folder. However `categories` is a string array on every message, and it
behaves close enough to labels for our purposes. **Our connector maps "label" to
`categories` on Graph and to real labels on Gmail**, and the pipeline never knows.

**OData query parameters.** Graph speaks OData, which means you get real query power in the
URL:

```
/me/messages?$select=subject,from,receivedDateTime,internetMessageId
            &$filter=receivedDateTime ge 2026-09-01T00:00:00Z
            &$top=50
            &$orderby=receivedDateTime desc
```

**`$select` is not optional for us** — without it Graph returns the full message including
body on every list call. **With it, we get envelopes only.** This is Graph's equivalent of
Gmail's `format=metadata`, and it is how the envelope-only backfill works on this door.

**Change tracking — delta queries.** Call
`/me/mailFolders/{id}/messages/delta`. The response includes a `@odata.deltaLink`. Save it;
next time, call that link and get only what changed. **Cleaner than Gmail's history model
and it does not silently expire after a week** — though delta tokens can still be
invalidated, so the full-resync fallback is still required.

**Push — subscriptions.** `POST /subscriptions` with a notification URL. Microsoft
immediately calls your URL with a validation token you must echo back within 10 seconds.
After that you get notifications on change.

- **Maximum lifetime for mail subscriptions is about 3 days** (4,230 minutes) `[verify]`,
  so renewal is again a scheduled job.
- Your endpoint **must be public HTTPS with a valid certificate.** This is a real
  deployment constraint — no localhost, no self-signed.
- Notifications can optionally include the changed resource data, **encrypted with a public
  key you supply.** Useful, but adds key management.

**Throttling.** Graph returns `429` with a `Retry-After` header. **Honour that header
exactly** — Microsoft escalates against clients that ignore it. Published limits are roughly
10,000 requests per 10 minutes per app per mailbox, and 4 concurrent requests per mailbox
`[verify]`. The concurrency limit is the one that catches people.

**Batching.** `POST /$batch` with up to 20 requests in one call. Counts as 20 against
throttling, but saves round trips.

**Auth.** Microsoft Entra ID (what used to be Azure AD). Two very different modes:

- **Delegated** — acting as a signed-in user. `Mail.ReadWrite`, `Mail.Send`. **This is
  ours.**
- **Application** — acting as itself, across the whole tenant. `Mail.ReadWrite.All`.
  Enormous power, needs admin consent. **We do not ask for this.**

**Library.** `msgraph-sdk` (the official one) or just `httpx` against the REST endpoints.
The REST surface is clean enough that the SDK is optional — and skipping it means fewer
dependency headaches.

---

## 1.4 JMAP — the modern one nobody uses yet

> **In plain terms.** A modern replacement for IMAP that fixes nearly everything wrong with it — **it can even do a search and fetch the results in a single round trip**, which neither Google nor Microsoft can. The problem is simple: almost nobody runs it. Fastmail invented it and uses it; Google and Microsoft ignore it. **We support it because the work is small and Fastmail users are exactly the privacy-minded professionals we are aiming at.** Build it last.

**What it is.** JSON Meta Application Protocol. A deliberate attempt to replace IMAP with
something designed for how software is actually written now: JSON over HTTPS, with sync and
batching built into the protocol rather than bolted on.

**The specs.** RFC 8620 (core), RFC 8621 (mail), RFC 8887 (WebSocket transport).

**How it works.** You `POST` one JSON object to a single endpoint. Inside it is an array of
method calls, executed in order.

```json
{
  "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
  "methodCalls": [
    ["Email/query",  { "accountId": "u1", "filter": {"inMailbox": "inbox"} }, "c0"],
    ["Email/get",    { "accountId": "u1", "#ids": {
        "resultOf": "c0", "name": "Email/query", "path": "/ids" },
        "properties": ["subject", "from", "receivedAt"] }, "c1"]
  ]
}
```

**Look at what that does.** The second call uses the *result of the first* — `#ids` with a
`resultOf` back-reference — **in the same HTTP request.** Search and fetch, one round trip.
Neither Gmail nor Graph can do that. Over a slow link this is a genuinely large difference.

**The objects.** `Mailbox`, `Thread`, `Email`, `EmailSubmission`, `Identity`,
`SearchSnippet`, `VacationResponse`.

**The methods, uniform across every type.**

| Method | Purpose |
|---|---|
| `Foo/get` | Fetch by id |
| `Foo/set` | Create, update, destroy — **all three in one call** |
| `Foo/query` | Search, returns ids |
| `Foo/changes` | **What changed since state X** |
| `Foo/queryChanges` | How a *search result* changed since state X |

**Sync is in the protocol, not an extension.** Every type carries a `state` string. You
keep it; you ask `Email/changes` with it; you get back `created`, `updated`, `destroyed`.
**This is what CONDSTORE and QRESYNC bolt onto IMAP and what `history.list` does at Gmail —
except here it is simply how the protocol works.**

**Push.** Three options: Server-Sent Events, WebSocket (RFC 8887), or `PushSubscription` for
webhooks. **No Pub/Sub topic to provision, no renewal dance.**

**Discovery.** `GET /.well-known/jmap` returns the session object: the API URL, the upload
and download URLs, the capabilities the server supports, and which accounts the token can
reach. **One request and you know everything about the server.**

**The problem: almost nobody runs it.**

| Runs JMAP | Does not |
|---|---|
| Fastmail (wrote it) | **Gmail** |
| Topicbox | **Outlook / Microsoft 365** |
| Cyrus IMAP | Yahoo |
| Stalwart | Zoho |
| Apache James | Proton |

**So why support it at all?** Because the adapter is small, because Fastmail users are
disproportionately the privacy-conscious professionals we are aiming at, and because if it
ever does get adopted it is the best door of the four. **Build it third, after Gmail and
Graph — not first.**

**Library.** Thin. `jmapc` exists for Python but is not heavily maintained `[verify]`. It is
plain JSON over HTTPS, so `httpx` plus our own small wrapper is a defensible choice.

---

## 1.5 The four side by side

| | IMAP | Gmail API | Graph | JMAP |
|---|---|---|---|---|
| **Transport** | TCP text protocol | HTTPS REST/JSON | HTTPS REST/JSON | HTTPS JSON |
| **Stateful?** | Yes — one folder at a time | No | No | No |
| **Auth** | Password or SASL XOAUTH2 | OAuth 2.0 | OAuth 2.0 via Entra | Bearer / OAuth |
| **Labels or folders** | Folders only | **Labels** | Folders + categories | Both |
| **Threads** | You build them | **First-class** | Conversation id | **First-class** |
| **Change tracking** | CONDSTORE/QRESYNC, if supported | `history.list`, ~7-day window | **Delta links** | **Built into every type** |
| **Push** | IDLE, one folder per socket | Pub/Sub, renew weekly | Webhook, renew ~3 days | SSE / WebSocket |
| **Batching** | No | Batch endpoint | `$batch`, 20 max | **Native, with back-references** |
| **Server-side search** | Weak | **Excellent** | Good (OData + `$search`) | Good |
| **Envelope-only fetch** | `BODY.PEEK[HEADER]` | `format=metadata` | `$select` | `properties` |
| **Coverage** | **Everything** | Gmail only | Microsoft only | ~nobody |
| **Build order** | 3rd | **1st** | **2nd** | 4th |

---

## 1.6 What the connector actually is, in our code

One interface. Four implementations. **Every implementation must answer what it can do**,
because the pipeline behaves differently depending on the answer.

```python
class MailConnector(Protocol):
    # --- capability declaration: the pipeline reads these ---
    supports_push: bool            # else we poll
    supports_labels: bool          # else we map labels to folders
    supports_server_search: bool   # else we filter locally
    supports_incremental_sync: bool
    max_fetch_per_second: float    # drives our own rate limiter

    # --- reading ---
    def list_envelopes(self, since: SyncToken) -> Iterator[Envelope]: ...
    def fetch_body(self, msg_id: str) -> RawMessage: ...

    # --- acting ---
    def apply_label(self, msg_id: str, label: str) -> None: ...
    def archive(self, msg_id: str) -> None: ...
    def mark_read(self, msg_id: str) -> None: ...
    def trash(self, msg_id: str) -> None: ...
    def send(self, message: OutgoingMessage) -> str: ...
    def save_draft(self, message: OutgoingMessage) -> str: ...
```

**Why capability flags rather than checking the provider name.** If the pipeline ever asks
*"is this Gmail?"* we have leaked provider knowledge into the core, and adding a fifth door
means editing the core. Asking *"can you push?"* means a new door is genuinely a new file
and nothing else.

**The other half of the connector's job is normalising identity.** Gmail gives you a message
id and a thread id. Graph gives you a different id and a `conversationId`. IMAP gives you
UID plus folder plus UIDVALIDITY. **These are not comparable.** The one thing all four
have is the `Message-ID` header, which is generated by the sending client and is globally
unique. **We key our own database on `Message-ID`** and store the provider's id alongside
it as an opaque handle for making calls.

---

# Part 2 — The tech stack, and why

> **In plain terms.** The list of tools we build the system out of, and the argument for each one. The short version: **Python, because every library we need is Python-first. One database instead of three. And no graphics card, because nothing here needs one.** The last table is the one to read before a meeting — it lists what we deliberately are *not* using, and why.

## The recommendation

| Layer | Choice | Version |
|---|---|---|
| Language | **Python** | 3.12 |
| Web framework | **FastAPI** + uvicorn | |
| Database | **PostgreSQL** + pgvector | 16 |
| Migrations | **Alembic** | |
| DB access | **SQLAlchemy 2.0** | |
| Job queue | **A Postgres table** | — |
| HTTP client | **httpx** | |
| Model inference | **ONNX Runtime** | |
| Model training | **PyTorch + transformers** | |
| ONNX export | **optimum** | |
| Trees | **LightGBM** | |
| Frontier model | **anthropic** SDK | |
| Config | **pydantic-settings** | |
| Logging | **structlog** | |
| Tests | **pytest** | |
| Packaging | **uv** | |
| Deployment | **Docker** on a VM | |

## Why Python

**The honest reason: every library we need is Python-first, and several are Python-only.**

Presidio, the transformers ecosystem, LightGBM's best-supported bindings, ONNX Runtime,
SetFit, `email-reply-parser`, `icalendar`, `factur-x` — all Python. In Node or Go we would
be reimplementing or shelling out to Python anyway.

**The objection is speed**, and it is worth answering properly rather than waving away:

- Our hot path is **ONNX Runtime**, which is C++ and **releases the GIL during inference.**
  So model inference genuinely runs in parallel across threads.
- Everything else per email — parsing, stripping, header rules — is **microseconds.** Even
  10× slower than Go is still microseconds.
- The slow parts are **network waits**, and `async` handles those regardless of language.

**Where Python would actually hurt** is a high-frequency, CPU-bound, single-request-latency
workload. **This is the opposite of that**: batch work, in the background, where nothing is
waiting on us.

## Why FastAPI

We need HTTP endpoints for three things: the OAuth callback, the provider webhooks (Graph
needs a public HTTPS endpoint), and the WhatsApp webhook. That is the entire web surface —
**this is not a web app.**

FastAPI gives async natively (all three of those are I/O-bound), request validation from
type hints via Pydantic, and automatic API docs. **Flask would also work.** Django would be
bringing a cathedral to a shed.

## Why PostgreSQL, and why only PostgreSQL

**One database for everything**: our data, the job queue, and the writing-style vectors via
`pgvector`.

**The argument against a separate vector database** is that we have one small vector job —
finding 4–5 of the user's own past replies that match the current situation. That is
thousands of vectors per user, not millions. **pgvector handles it comfortably, and it
means one thing to back up, one thing to secure, one connection string.**

Adding Pinecone or Qdrant would mean a second system to operate for a job Postgres already
does.

## Why the job queue is a table

```sql
CREATE TABLE jobs (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,
    payload     JSONB NOT NULL,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts    INT NOT NULL DEFAULT 0,
    locked_by   TEXT,
    locked_at   TIMESTAMPTZ
);
CREATE INDEX ON jobs (run_at) WHERE locked_by IS NULL;
```

Workers claim jobs with:

```sql
SELECT * FROM jobs
 WHERE locked_by IS NULL AND run_at <= now()
 ORDER BY run_at
 FOR UPDATE SKIP LOCKED
 LIMIT 10;
```

`FOR UPDATE SKIP LOCKED` is the whole trick: **multiple workers can pull from the same
table without ever colliding**, and Postgres handles the locking.

**Why not Celery or Redis?** Because reminders are *already* rows with a time on them.
Putting them in Redis means the reminder exists in two places and they can disagree. **A
job queue in the same transaction as the data it is about cannot drift out of sync with
it** — you either committed both or neither.

The trade is throughput. Postgres queues top out in the thousands of jobs per second
`[verify]`, well past anything we need. **Revisit if that ever becomes the bottleneck; it
will not be soon.**

## Why ONNX Runtime rather than PyTorch in production

Same model, different engine. Measured elsewhere at roughly **14× faster on CPU** for a
comparable encoder — a bigger win than quantisation gives.

**The workflow:** train in PyTorch, export to ONNX with `optimum`, quantise to int8, ship
the `.onnx` file. **Production never imports PyTorch at all** — which also cuts the
container from gigabytes to megabytes.

## Why LightGBM

Stage 9 is tabular data — 65 numeric and categorical features. **Gradient-boosted trees are
the correct tool for tabular data**, and this is not a close call.

LightGBM over XGBoost mostly for training speed and native categorical handling. **CatBoost
is a legitimate alternative** and worth testing on our own data — it handles categoricals
differently and sometimes wins. All three are a one-line swap.

## What we are deliberately not using

| Not using | Why |
|---|---|
| **Kubernetes** | One VM. Adding an orchestrator for one machine is a second system to debug |
| **A vector database** | pgvector covers our one small vector job |
| **Redis** | The job queue lives in Postgres; nothing else needs a cache yet |
| **Celery** | Same |
| **LangChain / agent frameworks** | Our pipeline is deterministic with models at the leaves. A framework designed for the model to choose its own path is the *opposite* of this design |
| **A GPU** | Both small models run on CPU. The writer is an API call |
| **Node or Go** | See above — the libraries are not there |

**The LangChain one is worth being able to defend**, because it is the obvious question.
The whole security argument rests on the model never deciding what happens next. An agent
framework exists to let the model decide what happens next. **Adopting one would delete our
main safety property.**

---

---

# Part 3 — Stage 2: Parse and strip

> **In plain terms.** An email arrives as a messy blob with the entire previous conversation repeated inside it — you know how you scroll down and see the whole thread again. **This stage throws that away and keeps only the new words.** It is the single biggest cost saving in the system: the email gets about **85% smaller before anything reads it.**

**What the stage does.** Takes the raw bytes of a message and produces clean text —
the new words only, with the quoted conversation, the signature, the HTML and the
attachments removed.

**Why it is second and not later.** Everything downstream is priced per token or per
character. Stripping here makes every later stage cheaper. **Measured elsewhere at ~85%
token reduction** on 938 real emails, median message 966 tokens → 124.

---

## 2.1 `email` — the standard library

**What it is.** Python's built-in email package. Turns bytes into an `EmailMessage` object.
Nothing to install.

```python
from email import message_from_bytes
from email.policy import default

msg = message_from_bytes(raw_bytes, policy=default)
```

**The `policy=default` argument is not optional.** Without it you get the legacy
`compat32` policy from Python 2 days, which returns raw encoded header strings — you would
see `=?utf-8?B?SGVsbG8=?=` instead of `Hello`. **With `default`, headers are decoded for
you and `get_body()` exists.**

**What an email actually contains.** This is where people are surprised. A typical email is
a tree:

```
multipart/mixed
├── multipart/alternative
│   ├── text/plain      ← the message, as plain text
│   └── text/html       ← the same message, as HTML
└── application/pdf     ← the attachment
```

So **one email commonly contains the same message twice**, and we must pick. Plus
`multipart/related` wraps HTML with its inline images.

**The methods that matter.**

| Call | Returns |
|---|---|
| `msg.get_body(('plain','html'))` | The best body part, preferring plain |
| `msg.iter_attachments()` | Just the attachments |
| `msg.walk()` | Every part, depth-first |
| `part.get_content()` | Decoded content — handles base64 and quoted-printable for you |
| `part.get_content_type()` | e.g. `text/html` |
| `msg['Subject']` | Decoded header |
| `msg.get_all('Received')` | All instances of a repeated header |

**The charset trap.** `get_content_charset()` returns what the sender *claimed*. Senders
lie, and some declare nothing. Always decode defensively:

```python
charset = part.get_content_charset() or 'utf-8'
text = part.get_payload(decode=True).decode(charset, errors='replace')
```

**`errors='replace'` rather than letting it throw** — one badly encoded email must not kill
the worker.

**Which body to take.** Prefer `text/plain` when present; it is already clean. Fall back to
`text/html` and convert. **Some senders send HTML only, and some send a plain part that is
just "Please enable HTML"** — so check that the plain part has real content before trusting
it.

---

## 2.2 `email-reply-parser` — cutting the quoted history

**What it is.** Splits a reply into fragments and tells you which are new and which are
quoted. A Python port of GitHub's original Ruby library, which they wrote because their
issue-by-email feature kept including entire threads.

```python
from email_reply_parser import EmailReplyParser
new_text = EmailReplyParser.parse_reply(body_text)
```

**How it works.** It walks the message **backwards** from the end, splitting on blank lines
into fragments, and marks each as quoted, a signature, or hidden. Reversed order matters
because quoting is nested — the deepest quote is at the bottom.

It matches on: lines starting `>`, the `On <date>, <person> wrote:` header in many
languages, `-----Original Message-----`, and signature markers like `--`.

**Why this one and not `talon`.**

| | email-reply-parser | talon |
|---|---|---|
| Accuracy on a public comparison | **86.3%** | 82.4% |
| Maintained | Yes | **ML path broken on modern Python** |
| Dependencies | None | scikit-learn, numpy — and pinned to old versions |

**talon** is Mailgun's, and its rule-based path (`talon.quotations.extract_from_plain`)
still works. But its signature-extraction path needs an old scikit-learn that will fight
every other dependency we have. **Not worth the pain for 4 points less accuracy.**

**Other options:** `quotequail` (lighter, less accurate), `mailparser` (different trade-offs).

**The failure mode you must handle.** About **2% of replies strip to nearly nothing** —
someone replies with just "ok" above a long quote, or the quote markers are unusual and it
over-cuts.

```python
stripped = EmailReplyParser.parse_reply(body)
if len(stripped.strip()) < 20:
    stripped = body          # fall back to the whole thing
```

**Without that guard we silently classify empty strings**, and nothing tells us.

---

## 2.3 `selectolax` — HTML to text

**What it is.** A Python wrapper around Modest/Lexbor, HTML parsers written in C. Very fast.

```python
from selectolax.parser import HTMLParser
text = HTMLParser(html).text(separator=' ')
```

**Why not BeautifulSoup.** BeautifulSoup is friendlier but noticeably slower, and we do this
on every email. We only need "give me the text" — we are not navigating the DOM.

**Why not `trafilatura` or `readability`.** These are the obvious suggestions and **they are
actively wrong for us.** They are built to extract *the article* from a news page and throw
away everything else — navigation, footers, boilerplate.

**In an email, the "boilerplate" is the data.** The order number, the amount, the due date,
the unsubscribe link — those live in exactly the regions these libraries delete. **They
solve the inverse of our problem.**

**One practical detail:** strip `<style>` and `<script>` content before taking text, or CSS
rules end up in your string.

---

## 2.4 What comes out of stage 2

```python
@dataclass
class ParsedEmail:
    message_id: str          # from the header — our primary key
    thread_refs: list[str]   # In-Reply-To + References
    sender: str
    recipients: list[str]
    cc: list[str]
    subject: str
    date: datetime
    headers: dict            # everything, for stages 3 and 4
    body_text: str           # stripped, cleaned  ← the 85% saving
    attachments: list[Attachment]   # metadata only; bytes fetched on demand
    had_html: bool
    strip_ratio: float       # log it — this is how we verify the 85%
```

**Log `strip_ratio` from day one.** It is how we confirm the 85% claim on our own mail
rather than repeating someone else's number.

---

# Part 4 — Stage 3: The sensitive gate

> **In plain terms.** Before anything opens an email, we check whether it should be opened at all. **Bank codes, medical results, legal papers — these stop here**, and only the sender and the subject line are ever looked at. It runs first on purpose: **if it ran any later, something would already have read the email before we decided it should not be read.**

**What the stage does.** Decides whether this email should be opened at all. Sees **only
headers and subject** — never the body.

**Why it is third.** If it ran anywhere later, something would already have read the body
before we decided the body should not be read. **The ordering is the entire safety
property.** It is worth stating in code:

```python
# This function must never receive a body. The signature enforces it.
def is_sensitive(headers: dict, subject: str) -> bool:
    ...
```

**No library.** This is our own rules, and it should stay that way — a model here would be
probabilistic about exactly the thing we want to be certain about.

**What the rules check.**

| Signal | Example |
|---|---|
| Sender domain on a list | banks, hospitals, government, law firms |
| Sender local-part | `otp@`, `noreply-security@`, `alerts@` |
| Subject patterns | "verification code", "one-time", "OTP", "your statement", "test results" |
| Known transactional shapes | 6-digit code in the subject |
| User-added senders | the user marks a sender private, forever |

**Both failure directions, honestly.**

- **False positive** — we treat ordinary mail as sensitive. Cost: the user gets a
  notification instead of a summary. **Mild.**
- **False negative** — sensitive mail goes down the normal path. It still hits stage 4 and
  stage 9, and **most sensitive mail is transactional and exits at stage 4 anyway**. It
  reaches a model only if it looks like it needs a reply. **Not catastrophic, but this is
  the one to tune toward over-triggering.**

**Building the list.** Start with Pakistani banks (HBL, Meezan, UBL, MCB, Alfalah, Askari,
JS, Faysal), the telcos, FBR, NADRA, SECP, then the international ones. **The list is a
config file, not code** — it changes without a deploy.

---

# Part 5 — Stage 4: Header rules

> **In plain terms.** Every email carries hidden information the sender filled in — including, on bulk mail, an unsubscribe stamp that has been **legally required since 2024.** This stage reads those, **and it reads only facts.** It can tell you an email was machine-generated. **It cannot tell you whether it matters** — bank statements and Daraz sales are both machine-generated. **That judgement belongs to stage 9, using this person's own behaviour.** See 4.4.

**What the stage does.** Extracts facts from the headers — was this machine-generated, does it
carry an unsubscribe stamp, who really sent it — **by reading what the sender declared, not by
guessing.**

**No model, ~200 lines.** Every check here is reading a field somebody else filled in.

**⚠️ What the stage does NOT do: decide whether the email matters.** See 4.4 — that distinction
is load-bearing and easy to get wrong.

---

## 4.1 `List-Unsubscribe` — the bulk signal

**The specs.** RFC 2369 defines the header; RFC 8058 adds one-click.

```
List-Unsubscribe: <https://sender.com/u/abc123>, <mailto:unsub@sender.com>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

**Why it is reliable.** Since **February 2024** Google and Yahoo require it on any sender
doing more than 5,000 messages a day to their users, as a deliverability condition. Senders
who omit it get filtered. **So it is near-universal on exactly the mail we want to detect.**

**How to act on it.** RFC 8058 one-click is a bare HTTPS POST:

```python
httpx.post(url, data={"List-Unsubscribe": "One-Click"})
```

**No cookies, no auth, no redirects** — the RFC forbids the sender from redirecting. The URL
itself carries the opaque recipient identifier.

**Traps.**

- Some senders provide **only** `mailto:` — legal under RFC 2369, common on Mailman lists.
  One-click is not available; we would have to send an email.
- `List-Unsubscribe` present **without** `List-Unsubscribe-Post` means one-click is **not**
  offered. **Check both.**
- Multiple comma-separated URIs — take the `https` one, not simply the first.
- Headers fold across lines. **Use `email.headerregistry`, not a regex.**
- **RFC 8058 forbids POSTing without user consent**, which is why unsubscribe needs approval.

---

## 4.2 The other machine-mail markers

| Header | Spec | Values / meaning |
|---|---|---|
| `Precedence` | non-standard | `bulk`, `list`, `junk`. RFC 3834 explicitly says interpretation varies — **use as a hint, never alone** |
| `Auto-Submitted` | RFC 3834 | `no`, `auto-generated`, `auto-replied`; `auto-notified` comes from **RFC 5436**, not 3834 |
| `X-Auto-Response-Suppress` | Microsoft | `None`, `All`, `DR`, `NDR`, `RN`, `NRN`, `OOF`, `AutoReply` |
| `List-ID` | RFC 2919 | Stable, globally unique mailing-list identity. **Better than clustering on subject lines** |
| `Feedback-ID` | Google | `a:b:c:SenderId` — a campaign identifier, lets us group without reading |

**If we ever send automatically, honouring `Auto-Submitted != no`, `Precedence: bulk` and
`X-Auto-Response-Suppress` is the difference between a well-behaved system and a mail
loop.**

---

## 4.3 Authentication headers — free identity, one hard rule

**The spec.** RFC 8601, `Authentication-Results`.

```
Authentication-Results: mx.google.com;
       dkim=pass header.i=@hbl.com;
       spf=pass smtp.mailfrom=hbl.com;
       dmarc=pass header.from=hbl.com
```

**Why this is free.** Our provider already did the cryptography. **We read the verdict —
no DNS lookups, no signature checks.**

**⚠️ The rule that makes it safe.** RFC 8601 requires a conforming server to delete any
`Authentication-Results` header claiming to be from inside its own trust boundary that did
not come from a trusted MTA. So:

> **Take only the topmost header whose `authserv-id` is our own provider's
> (`mx.google.com`, `spf.protection.outlook.com`). Every header below it was written by
> whoever sent the mail.**

**Parsing "the Authentication-Results header" without checking who stamped it is an
exploitable bug**, not a style issue.

**The better identity key: `DKIM-Signature`'s `d=` field.** It is the cryptographically
verified organisational domain of whoever actually sent the mail. Survives display-name
spoofing.

Two caveats: a message can carry several `DKIM-Signature` headers — **pick the DMARC-aligned
one, not the first**; and `d=` is often the ESP's domain (`sendgrid.net`) rather than the
brand's.

**Why not the `X-` headers.** `X-Mailer`, `X-SES-Outgoing`, `X-Mailgun-Sid` and friends do
identify ESPs in practice, but **most are undocumented and change without notice.** Only
SendGrid's `X-SMTPAPI` is properly specified. **Use them as hints; never let a missing
one change behaviour.**

---

## 4.4 ⚠️ Machine-generated is not the same as unimportant

**This is the mistake to avoid, and the first version of this design made it.**

It is tempting to treat "has `List-Unsubscribe`" as "is junk". It is not. Look at what is
machine-generated:

| Machine-generated | Matters? |
|---|---|
| A shop's sale email | **Depends entirely on the person** |
| A newsletter | **Depends entirely on the person** |
| A bank statement | Usually yes |
| An order confirmation | Usually yes |
| A flight booking | Usually yes |
| A password reset | Usually yes |
| An electricity bill | Usually yes |

**And "depends on the person" is not a hedge — it is the actual answer.** A sale email is
noise to most people and the entire reason someone opened the mailbox if they are waiting on
a price drop. **Any category list we write will be wrong for somebody**, and there are
thousands of cases we would never think of: job alerts, class schedules, shipment tracking,
court notices, property listings.

### The fix: measure behaviour, do not define categories

**We do not need to know whether shop emails are important. We need to know whether *this
person* opens them.**

And we already have that. **The day-one envelope backfill includes the read/unread state of
every message**, so from hour two we know:

```
Daraz        312 messages    309 never opened    0 replies
K-Electric    14 messages     14 opened          2 replies
Ali           47 messages     47 opened         41 replies
```

**No taxonomy. No categories. Just what this person actually did.**

The same sender gets opposite treatment for two different users, **which is correct**, and
it costs nothing because it is the same sender-history table stage 9 already uses.

### So what actually exits at stage 4

**Nothing exits by category.** Two things exit by evidence:

1. **A rule the user set themselves** — "never show me anything from this sender"
2. **A sender with no engagement at all** — 20+ messages, zero opened, zero replied

**Everything else continues**, and stage 5 catches most of it with templates — still no model.

**When in doubt, let it through.** An unnecessary email costs a fraction of a cent. A hidden
bill costs a customer.

### The rule to write into the design

> **A rule may route mail. It may never discard it. The user is the only thing that deletes.**

### Note this is the same lesson as stage 9

Stage 9 found that the *words* predict almost nothing (0.511) and the person's *own history*
predicts nearly everything (0.692). **Stage 4 is the same principle one stage earlier:** stop
judging the mail, measure the person.

## 4.5 Out-of-office replies are information, not noise

Two different uses of `Auto-Submitted` get confused. They are unrelated.

**Reading it on incoming mail.** An out-of-office carries `Auto-Submitted: auto-replied`.
**Do not discard these** — they are useful. *"You emailed Ali. He is away until the 12th."*
**That should pause the obligation**, not vanish.

**Respecting it when we send.** If we ever send automatically and the far side is also
automated, **you get an infinite loop** — their auto-reply triggers ours triggers theirs.
So before sending we check `Auto-Submitted != no`, `Precedence: bulk`, and
`X-Auto-Response-Suppress`.

**The first is about classifying. The second is about not melting a mail server. They have
nothing to do with each other.**

---

## 4.6 Spam — why it is not in the pipeline, and the one thing we do add

> **In plain terms.** We do not detect spam, because the mail provider already did it before
> the message reached the inbox. What we *do* add is the opposite: catching the cases where
> the provider's filter was **wrong** and buried a real email.

### We do not filter spam, and we should not

Gmail, Outlook and essentially every mail server run a spam filter before mail reaches the
inbox. **We read the Inbox. Spam is already gone.**

Building our own would be a bad trade:

| | The provider | Us |
|---|---|---|
| Messages to learn from | billions per day | a few thousand mailboxes |
| Years of accumulated signal | 20+ | 0 |

And spam is **adversarial** — attackers actively work around filters, so a filter needs
permanent maintenance. **It is a treadmill, for a problem that arrives already solved.**

### What happens to spam that gets through

Nothing special, and that is the point. An unknown sender with no reply history, carrying
bulk markers, **scores near zero at stage 9.** It lands in the daily brief; no draft is
written; it costs us nothing.

**The system degrades gracefully because it never assumed the mail was legitimate.**

### ⚠️ Malicious mail is a security problem, not a filtering one

Spam that gets through is also the **prompt-injection** vector — an email written to reach
the inbox *and* carry instructions aimed at the agent.

**A better spam filter would not help.** What helps is the architecture: the approval gate
lives in our code, the model that reads untrusted mail never holds the power to send, and
there is one egress point. See Part 13.

### Impersonation, by contrast, IS ours to catch

Different problem, and stage 4 already has what it needs:

```
From: HBL <alerts@hbl-secure-verify.com>
Authentication-Results: mx.google.com; dkim=fail; spf=fail
```

**It claims to be the bank. The cryptography says otherwise.** That is detectable and free,
and worth surfacing. What we *cannot* catch is well-made phishing from a domain that passes
its own checks — **nobody catches those reliably.**

### The feature: rescuing the filter's false positives

Spam filters err both ways, and the second kind is the one users actually complain about —
**a real email buried in Spam and never seen.**

**Once a day, read the spam folder's envelopes only.** Never a body, never a model.

```python
for env in connector.list_spam_envelopes(since=yesterday):
    if not sender_has_engagement(env.sender):   continue
    if not env.auth_passed:                     continue   # ← the safety catch
    surface_in_daily_brief(env)
```

### Worked example — one day's run

**Step 1 — ask for the spam folder's list.** Same call as the inbox, different folder.
`in:spam` on Gmail, the `junkemail` folder on Graph, `\Junk` on IMAP. **Headers only.**

```
from: ali@company.com       "Q3 report"
from: winner@lottery.tk     "YOU HAVE WON"
from: noreply@shop.com      "50% OFF TODAY"
```

**Step 2 — do we know this sender?** Straight lookup in `sender_history`.

```
ali@company.com     47 emails, 41 replies      ✓ known
winner@lottery.tk   never seen                  ✗ skip
noreply@shop.com    312 emails, 0 ever opened   ✗ skip
```

**Two of three are gone already, on a table lookup.**

**Step 3 — is it cryptographically genuine?** Read the stamp our own provider applied on
arrival (same header, same trust rule as 4.3):

```
Authentication-Results: mx.google.com; dkim=pass; spf=pass
```

`pass` → it really did come from that domain. `fail` → the name was forged; **leave it in
Spam.**

**Step 4 — surface it.**

> *"An email from Ali went to Spam — 'Q3 report'"*

They say yes, we move it back. One call, reversible.

```
read spam folder headers
      ↓
known sender?      no → skip
      ↓ yes
auth passed?       no → skip          ← this is what stops forgery
      ↓ yes
put it in the daily brief
```

**Four checks. No model. No body ever opened.**

### ⚠️ The safety catch is the whole design

**Sender addresses are trivially forged.** Without the second condition this feature becomes
an attack:

> An attacker sends from a forged `ali@company.com`. It lands in spam **precisely because the
> cryptography failed.** We surface it as *"an email from Ali went to Spam"* — **undoing the
> filter's correct decision, with our credibility attached to it.**

**So: only surface a message whose authentication headers passed.** If DKIM or SPF failed,
that is very likely *why* it was filtered. **Leave it there.**

What survives both conditions is exactly the real case: **a cryptographically verified sender
you have genuine history with, that the filter got wrong.**

### What it costs to build

| Piece | Work |
|---|---|
| Connector: `supports_spam_folder`, `list_spam_envelopes`, `mark_not_spam` | small, per door |
| Gmail | `q=in:spam`; rescue = remove `SPAM`, add `INBOX` |
| Graph | `junkemail` well-known folder; rescue = move to inbox |
| IMAP | `\Junk` via SPECIAL-USE; rescue = `MOVE` to INBOX |
| JMAP | mailbox role `junk` |
| Scheduler | one daily job |
| Permissions | **none new** — `gmail.modify` and `Mail.ReadWrite` already cover it |

**Approval:** not required. Moving a message out of Spam is reversible, and it appears in the
daily brief where the user confirms it anyway.

**Side benefit:** marking a message not-spam **teaches the provider's own filter**, so the
same sender is less likely to be misfiled again.

---

# Part 6 — Stage 5: Structure and templates

> **In plain terms.** Two free wins. **Some emails arrive with the answer already attached** — a meeting invite contains the exact time in a machine-readable file, and some invoices carry the full invoice as data inside the PDF. And **some senders use the same layout every month**, so once we learn where the amount sits on your electricity bill, we never need a model for that sender again. **No AI on either path.**

**What the stage does.** Extracts facts without any model — first from mail that arrives
already structured, then from senders whose layout we have learned.

**Two completely different mechanisms.** Keep them separate in your head.

---

## 5.1 Already-structured: `icalendar`

**What it is.** Parses iCalendar (`.ics`) files — the format meeting invites travel in.

```python
from icalendar import Calendar
cal = Calendar.from_ical(ics_bytes)
for ev in cal.walk('VEVENT'):
    start = ev.get('DTSTART').dt
    summary = str(ev.get('SUMMARY'))
```

**The specs.** RFC 5545 (the format), RFC 5546 (iTIP — the scheduling workflow),
RFC 6047 (iMIP — how it rides in email).

**How to recognise one.** A MIME part with `Content-Type: text/calendar`. **RFC 6047 says a
`text/calendar` part without a `method=` parameter is not a scheduling message** — treat it
as a plain attachment.

The methods are `PUBLISH`, `REQUEST`, `REPLY`, `ADD`, `CANCEL`, `REFRESH`, `COUNTER`,
`DECLINECOUNTER`. `REQUEST` is an invitation; `CANCEL` kills it.

**Coverage.** Outlook and Exchange send iCalendar to external recipients **by default**;
Google Calendar does too. The failure case is Outlook forced into Rich Text, which sends
`winmail.dat` (TNEF) instead — **a configuration mistake, not a default.**

**⚠️ Timezones are the real cost here.** Microsoft ships non-IANA zone names like
`W. Europe Standard Time`, and sometimes quoted display names like
`"(UTC-05:00) Eastern Time (US & Canada)"`. Resolve in four tiers:

1. Use the `VTIMEZONE` block embedded in the file — **always prefer this**
2. Try the TZID as an IANA name
3. Map via CLDR's `windowsZones.xml` — note the mapping is one-to-many; only
   `territory="001"` is single-valued
4. Fall back to floating time

**Two more traps.** `DTSTART:16010101T030000` appears in Microsoft VTIMEZONE blocks — that
is the Windows epoch, and date libraries that reject pre-1900 dates break on it. And **for
all-day events `DTEND` is exclusive** — `DTSTART:20260628` / `DTEND:20260709` means the 28th
*through the 8th*, not the 9th.

**Recurrence.** `icalendar` parses `RRULE` but **does not expand it.** Add
`recurring-ical-events`:

```python
import recurring_ical_events
events = recurring_ical_events.of(cal).between(start, end)
```

**Do not use `ics.py`** — its own docs state it has no recurrence support and that this is
still pending before 1.0, four years after the last dev release.

**Deduplication is specified, not guesswork.** RFC 5546: primary key is `UID` plus
`RECURRENCE-ID`; higher `SEQUENCE` wins; ties broken by latest `DTSTAMP`. **A naive
`dict[UID]` loses single-instance overrides**, which arrive as extra VEVENTs sharing the
master's UID.

---

## 5.2 Already-structured: `factur-x`

**What it is.** Reads the structured invoice XML embedded inside a PDF.

```python
from facturx import get_facturx_xml_from_pdf
name, xml = get_facturx_xml_from_pdf(pdf_bytes)
```

**Why this exists.** Germany has required businesses to be **able to receive** structured
e-invoices since **1 January 2025** — and the finance ministry confirmed that **having an
email address is sufficient** to meet that requirement. So a German B2B invoice arriving as
a PDF often carries the complete invoice as machine-readable XML inside it.

**The four filenames to check** — note the capitalisation difference, which case-sensitive
matching will miss:

```
factur-x.xml   zugferd-invoice.xml   xrechnung.xml   ZUGFeRD-invoice.xml
```

**Current spec is Factur-X 1.09.2 / ZUGFeRD 2.5.2** (August 2026). Profiles run MINIMUM,
BASIC WL, BASIC, EN 16931, EXTENDED.

**The practical rule: for every PDF attachment, check the embedded-file table before doing
anything expensive.** It is a cheap read of the PDF catalog, and a hit gives a
schema-validated invoice instead of an OCR gamble.

**Honest scope.** This mostly matters for Germany and France. Italy, Poland and Belgium
route invoices over dedicated networks that **never touch email.**

---

## 5.3 Learned templates: `datasketch` + `parsel`

**The problem.** Your electricity bill has the same layout every month. Once we know where
the amount sits, we never need a model for that sender again.

**Step 1 — group emails with the same skeleton.** `datasketch` does MinHash and LSH.

```python
from datasketch import MinHash, MinHashLSH

def fingerprint(html):
    m = MinHash(num_perm=128)
    for path in dom_paths(html):        # structural paths, NOT text
        m.update(path.encode())
    return m
```

**Fingerprint the structure, not the words.** The words change every month; the skeleton
does not. Two emails from the same template share nearly all their DOM paths.

MinHash estimates similarity without comparing everything to everything — LSH buckets
candidates so lookup is roughly constant time rather than growing with the corpus.

**Step 2 — extract from a known skeleton.** `parsel` (the selector library from Scrapy):

```python
from parsel import Selector
sel = Selector(html)
amount = sel.css('td.total::text').get()
```

**Step 3 — validate all-or-nothing.**

```python
fields = extract_with_template(html, tpl)
if not all(f in fields for f in tpl.required_fields):
    return None          # fall through to stage 6. Emit nothing.
```

**This guard is the whole safety of the mechanism.** Templates drift when a sender redesigns,
and **drift fails silently** — you keep pulling from a position that now holds something
else. Add: rebuild on a timer, and alarm when match rates fall.

**Coverage, honestly.** Published production work reports **80–90% of transactional mail
matching a known template**, but only about **38–59% producing reliably working rules.** A
big win, not a total one — which is why stage 6 still exists behind it.

**Scope it to transactional senders.** Promotional mail changes layout constantly; the
published work found it the worst case by a wide margin.

---

## 5.3b ⚠️ What happens when a layout changes — and the rule that makes it safe

**Two cases, and they behave completely differently.**

**A big redesign is safe automatically.** We match on the structural fingerprint of the whole
email, not on one field. A redesign produces a different fingerprint, **the template is never
applied**, and the email falls through to stage 6. **Nothing to detect.**

**A small change is the real risk** — one row added, a cell moved. The fingerprint still
matches, so the template fires, **and it may now read the wrong box.** Three defences:

1. **All fields or none.** A missing required field discards the *entire* extraction, not
   just that field — whatever moved may have moved more than one thing.
2. **Value plausibility.** Not "is something there" but "does it look right": is the amount a
   number, positive, **within the range this sender has always used**; is the date in the
   future and within ~90 days. *"K-Electric is never PKR 12345"* catches the account number
   appearing where the amount used to be.
3. **Rebuild every 30 days**, plus an alarm when the match rate for a sender drops. Anything
   that slipped through self-heals within a month.

**The residual risk, stated honestly.** If a bill shows *"amount due"* and *"last month's
amount"* and those two swap positions, **both values are plausible and in range. Nothing
above would flag it.**

### The rule that makes that acceptable

> **A layout extraction never triggers an action. It only ever becomes something we show the
> user.**

The output is a reminder — *"K-Electric, PKR 8,450, due the 15th."* **We never pay, send,
archive or delete on the strength of a template.** So the worst outcome is **a reminder with
a wrong number in it, which the user reads and corrects** — and that correction fixes the
template.

**Compare that to the alternative.** If templates fed an action directly, a silent drift
would become a wrong payment. **They don't, so it can't.**

### And when it fails completely

**The email goes down the normal path** — stage 8 reads it, stage 11 if needed.

> **The worst cost of a broken template is a fraction of a cent. Never a wrong action.**

**That asymmetry is why this design throws extractions away on the slightest doubt.** Being
cautious is nearly free; being confidently wrong is what loses a customer.

## 5.4 `extruct` — the opportunistic path

```python
import extruct
data = extruct.extract(html, syntaxes=['json-ld', 'microdata'])
```

Reads schema.org markup some senders embed. **Under 0.1% of campaigns carry it**, down from
over 1% before 2021 — Microsoft measured 94% of transactional providers still not using it.

**Worth ~30 lines as a fast path. Never a plan.** The clinching evidence: the most mature
open-source travel-email extractor ships **229 hand-written vendor-specific scrapers, and
not one of them filters on markup.**

**One parsing trap:** Microsoft's Actionable Messages use `<script type="application/ld+json">`
too, but with `"@context": "https://schema.org/extensions"` and `"@type": "MessageCard"` —
a private vocabulary sharing the same MIME type. **Branch on `@context`.**

---

# Part 7 — Stage 6: The router

> **In plain terms.** Decides where each email goes next. **One rule matters: it escalates when it is unsure, not when the email is a particular type.** That sounds like a detail and is not — it means the system gets cheaper automatically every time the small models improve, with nobody changing any code.

**What it does.** Decides where each email goes next. **The only component that knows the
others exist.**

**No library, no model.** Roughly 100 lines.

**The one design rule.**

```python
# Escalate on CONFIDENCE, never on CATEGORY.
if result.confidence < THRESHOLD:
    return escalate()
```

**Why this matters more than it looks.** If we escalated on category — *"invoices always go
to the big model"* — our cost is fixed forever. Escalating on confidence means **every
improvement to stage 8 automatically reduces spend, with no code change.**

It also gives us one dial to turn. Raise the threshold and quality rises with cost; lower it
and the reverse. **One number, tunable per user, no redeploy.**

---

# Part 8 — Stage 7: Extract

> **In plain terms.** Finds the dates and the amounts. **Three tools, three jobs:** rules find the date phrases, the expensive model picks which one is the real deadline, and ordinary code does the calendar arithmetic. **That last split is not a preference — AI models are measurably worse than random guessing at date maths**, so they never touch it.

**What it does.** Finds dates and amounts. **Finds them — it does not calculate with them.**

## 8.1 The split that makes this work

**Three different jobs, three different tools:**

| Job | Who does it | Why |
|---|---|---|
| **Find** the date phrases | Rules — HeidelTime, duckling | ~90% F1, free |
| **Pick** which is the deadline | Frontier model | Needs to understand the sentence |
| **Calculate** the actual date | A date library | **Models score below chance here** |

**The measurement behind that last row.** On a temporal-arithmetic benchmark, BERT-base
scored **25.9** and RoBERTa-large **29.1** — against a **random baseline of 35.4.** Both
*worse than guessing.* GPT-4 scored 91.2.

**So: never ask any model what three working days from Thursday is.**

## 8.2 The finders

**HeidelTime** — rule-based, produces TIMEX3 annotations. TempEval-3: **strict F1 81.34,
relaxed 90.30, normalisation 77.61.** Java, so a wrapper or a service. Still competitive
with neural approaches on *normalisation* twenty years on.

**duckling** — Facebook's, in Haskell. Handles dates, amounts, durations, phone numbers.
**Run it as a small HTTP service**; the Python ports lag.

**dateparser** — pure Python, much simpler. Good for well-formed dates in many languages,
weaker on loose phrasing like "the Friday after next".

**TEI2GO** — a spaCy tagger, **122× faster** than HeidelTime at similar identification
accuracy (82.4 strict vs 81.8) — **but it only finds, it does not normalise.** Worth it if
throughput becomes a problem.

**Where to compare them: TempEval-3.** Note that *finding* a date and *normalising* it are
two different scores, and the gap between tools is much larger on normalisation.

## 8.3 The calculators

```python
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
import numpy as np

due = np.busday_offset(np.datetime64('2026-09-03'), 3, roll='forward')
```

- `dateutil` — relative offsets, `rrule` for recurrence
- `zoneinfo` — stdlib since 3.9. **On Windows you must `pip install tzdata`** or it finds
  no zones at all
- `numpy.busday_offset` or the `holidays` package — working days. **Pakistan's calendar
  needs its own holiday list**; Friday half-days and Eid dates matter for deadlines here

## 8.4 The closest published work to our exact problem

**SHERLOCK** — 44,000 labelled emails, extracting only *scheduling-relevant* dates, plus
negation ("not Tuesday"):

| Approach | F1 |
|---|---|
| High-recall rules | 0.54 |
| HeidelTime | 0.75 |
| Trained on in-domain email | **0.94** |

**The determining variable was 44k in-domain labelled emails, not model size.** Third time
that conclusion appears from a different direction — **the training data matters more than
the model.**
---

# Part 9 — Stage 8: The classifier

> **In plain terms.** **The only place in the whole system where anything reads an email to understand it.** A small AI model, running on our own computer, that puts two labels on it: what does this person want from me, and what is this about. **This part also explains what an AI model actually is**, from the beginning — that is the first section to read if the models are the confusing bit.

**What the stage does.** Reads the stripped text and puts two labels on it: *what does the
sender want from me* × *what is this about*, plus a confidence number.

**This is the only place anything reads an email to understand it.**

---

## 9.1 What an encoder model actually is

Worth being able to explain in a minute, because it is the first thing he will ask.

**Step 1 — the text becomes numbers.** A *tokenizer* splits text into pieces called tokens.
Not words — sub-words. `"unsubscribe"` might become `un` + `subscribe`. Each token has an ID
in a fixed vocabulary.

**Step 2 — each token becomes a vector.** An *embedding table* maps every token ID to a list
of numbers (768 of them, for our model). At this point every token's vector depends only on
which token it is — `bank` is identical in "river bank" and "bank account".

**Step 3 — the layers make each vector depend on its neighbours.** This is *attention*. In
each layer, every token looks at every other token and pulls in information from the ones
that matter to it. After the first layer, `bank` in "river bank" has a different vector from
`bank` in "bank account". **After 22 layers, each vector encodes the token in its full
context.**

**Step 4 — one vector represents the whole email.** Pool the token vectors together (or take
the special `[CLS]` token, which exists for this).

**Step 5 — a small layer on top turns that into labels.** A single linear layer maps 768
numbers to however many categories we have. **This is the "head", and it is the only part
that knows about our specific problem.**

**Encoder vs decoder — why this matters.** An *encoder* reads the whole input at once and
produces an understanding of it. A *decoder* (GPT, Claude) generates text one token at a
time.

> **Encoders are for understanding. Decoders are for writing. Stage 8 understands, so it is
> an encoder. Stage 11 writes, so it is a decoder.**

Using a decoder for classification means generating tokens to say what an encoder tells you
directly — **more compute for a worse answer.**

**What "149M parameters" physically means.** 149 million numbers, learned during training.
At 4 bytes each that is ~600MB; at 1 byte (int8) ~150MB. They do not change when we run it —
inference is just arithmetic through fixed numbers.

**What "context length" means.** The maximum number of *tokens* the model can look at. Ours
is 8,192. **Beyond it, text is silently discarded** — no error, no warning. This single fact
disqualified our original 22M choice, which stopped at 256.

---

## 9.2 ModernBERT — what we picked

`answerdotai/ModernBERT-base` · **149M params · 22 layers · 768 hidden · 8,192 context ·
Apache 2.0**

A 2024 rebuild of BERT with everything learned since 2018 folded in.

**What is actually different from BERT:**

| Change | What it buys |
|---|---|
| **RoPE** (rotary position embeddings) | Position encoded by rotating vectors rather than added lookups — **extends to long sequences without retraining** |
| **Alternating attention** | Every third layer looks globally; the rest use a 128-token local window. **Long context without quadratic cost** |
| **Unpadding** | Batched sequences normally pad to the longest. ModernBERT removes padding entirely — **no compute wasted on nothing** |
| **GeGLU activations** | Better than GELU at equal size |
| **2 trillion training tokens, including code** | More and fresher data than BERT's 3.3B |
| **Flash Attention 2** | Memory-efficient attention kernel |

**Measured GLUE:** ModernBERT-base **88.4** vs BERT-base 84.7 vs DeBERTa-v3-base 88.1.
ModernBERT-large **90.4**.

**The number that actually decides it for us:** on an RTX 4090, ModernBERT sustains a
**maximum batch of 1,604 against DeBERTa-v3's 236** — **6.8× the throughput per machine.**
That is the operational argument, not the accuracy one.

**Its weakness, stated honestly.** In a controlled, data-matched comparison on French NER,
**DeBERTa-v3 beat ModernBERT 93.40 vs 92.03.** DeBERTa-v3 is stronger on precision-heavy
*token-level* work. **Our task is sentence-level classification, where ModernBERT's GLUE
advantage applies and its throughput edge is free.**

---

## 9.3 DeBERTa-v3 — the alternative, and why it is a real one

`microsoft/deberta-v3-base` · **183M total (86M backbone + ~98M embeddings) · 12 layers ·
512 context · MIT**

**What makes it strong:**

- **Disentangled attention.** Content and position are kept as separate vectors, and
  attention is computed content-to-content, content-to-position and position-to-content
  separately. Standard BERT adds position into the content vector and loses the
  distinction.
- **ELECTRA-style pretraining.** Instead of masking tokens and predicting them, it learns
  to detect which tokens were *replaced* by a small generator. **Learns from every token,
  not the 15% that were masked** — far more sample-efficient.
- **Gradient-disentangled embedding sharing**, which fixed a training instability in
  ELECTRA.

**Note the parameter breakdown**, because it explains a lot: **98M of its 183M are the
embedding table**, because the vocabulary is 128k. Only 86M do the actual work. This is the
same phenomenon that makes quantisation nearly useless on some small models — **most of
the weights are a lookup table, not computation.**

**Why we did not pick it: 512 context.** That is roughly 400 words. **Plenty of real emails
are longer, and they would be truncated silently** — the exact failure we rejected the 22M
model for.

**When we would switch:** if measured accuracy on our own mail is materially better and our
emails turn out to fit in 512 after stripping. **Worth testing — the strip stage cuts 85%,
so more mail fits than you would expect.**

---

## 9.4 The size evidence

| Comparison | Result | Reading |
|---|---|---|
| MiniLM **22M** → DistilBERT **66M**, same recipe | 82.9 → **91.5 F1** | **+8.7. This is the cliff** |
| DistilBERT **66M** → BERT-base **110M** | 91.5 → 92.8 | +1.2 — diminishing already |
| Controlled ladder, sentence tasks: 32M / 68M / 150M / 400M | 83.5 / 87.2 / **88.9** / 90.8 | **150M is the knee** |
| GLiNER bi-encoder, 32M vs 150M text encoder | 54.0 → 60.3 | **+6.3 for the same jump** |
| PII: 33M / 44M / 184M / 434M | .931 / **.954** / .955 / .961 | **44M→434M buys 0.007** |

**Two independent, differently-constructed ladders put the cliff between 22M and 66M and
the knee around 150M.** That is why 149M, and why not 22M and not 400M.

**And the separate disqualifier for 22M:** `all-MiniLM-L6-v2` truncates at **256 word
pieces** and was trained at 128. Most emails exceed that. **It would have dropped the bottom
of every long email and never told us.**

---

## 9.5 Fine-tuning — what it actually is

**The pretrained model understands English. It does not know our categories.** Fine-tuning
teaches it ours.

**Mechanically:** attach a fresh linear layer (the head) mapping the model's 768-number
output to our category count. Show it labelled examples. Adjust all the weights slightly so
its answers match the labels.

**Typical settings for a model this size:**

```python
learning_rate = 2e-5 to 5e-5     # small — we are nudging, not rebuilding
epochs        = 3 to 5           # more overfits on small data
batch_size    = 16 or 32
optimizer     = AdamW
scheduler     = linear with warmup
max_length    = 512 to start     # raise if strip_ratio says we need it
```

**Why the learning rate is so small.** The model already knows language. **We are adjusting,
not teaching from scratch.** Too high and it forgets what it knew — "catastrophic
forgetting".

**Full fine-tune or freeze?** Full — with 149M parameters and a modern GPU it takes minutes,
and it consistently beats freezing. **Freezing only wins when data is very scarce**, which
brings us to:

**The alternative approach: SetFit.** Rather than fine-tuning end to end, SetFit
contrastively fine-tunes a *sentence encoder* on pairs (same class / different class), then
fits a plain logistic-regression head on the resulting embeddings.

**Why it is worth knowing:** on a 77-class intent benchmark at **10 examples per class**, a
frozen sentence encoder plus a simple head scored **85.19 — beating a fully fine-tuned
BERT-Large at 83.42** — and trained in **65 seconds on a dual-core laptop CPU.**

And on a 11-task few-shot benchmark with **50 labels per task**, SetFit-RoBERTa (355M)
scored **71.3 against GPT-3's 62.7** — a 493× smaller model beating it by 8.6 points.

> **Practical plan: start with SetFit while we have under ~50 examples per class. Move to a
> full ModernBERT fine-tune once we pass a few hundred.**

**One caveat:** SetFit's contrastive pair generation scales badly. On one large corpus it
**failed to finish after 104 hours.** It is a few-shot technique, not a full-data one.

**How much data — the crossover.** Convergent across eight studies:

| Source shape | Crossover |
|---|---|
| 2–6 classes | 8–64 labels per class |
| 11 mixed tasks | 50 per task |
| 2–5 classes | >200 total |
| 20 classes | ~500 ties, 1,000 wins |
| binary | ~1,000 |

**Synthesis: 100–1,000 labelled examples. And more categories makes the crossover arrive
*sooner*, not later.**

**Where the labels come from.** We label them by hand — a few days of one person. There is
no shortcut, and **this is the real bottleneck of the whole project.** Compute is minutes
and pennies; labels are days.

**⚠️ Do not train on Enron.** A model fine-tuned on Enron alone went **F1 0.78 on Enron →
0.66 on mixed real corpora**, and a data audit found **17–22% probable mislabelling** across
the standard public email corpora. Models learn "brittle, non-generalisable heuristics on
stylistic artefacts". **Use it to build the harness. Never to train the shipping model.**

---

## 9.6 Quantisation and ONNX

**Quantisation.** Weights are stored as 32-bit floats. Int8 stores them as 8-bit integers —
**4× smaller, and integer arithmetic is faster.** Accuracy loss on classification is
typically well under a point.

**A trap worth knowing:** quantisation barely helps models whose parameters are mostly the
embedding table. Gemma 3 270M's Q4 file is only **13% smaller than its Q8**, because 170M of
its 270M parameters *are* the 256k vocabulary. **Check the parameter breakdown before
assuming 4×.**

**ONNX.** Open Neural Network Exchange — a portable format plus a runtime, so production
never imports PyTorch.

```python
from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
model = ORTModelForSequenceClassification.from_pretrained(path, export=True)
```

**Measured ~14× speedup** on CPU for a comparable encoder — **a bigger lever than
quantisation.** It also cuts the container image from gigabytes to megabytes.

**Alternatives:** OpenVINO is sometimes faster on Intel CPUs specifically; TensorRT is
fastest but GPU-only, so not for us. **Benchmark on your own machine — these numbers vary
enormously by CPU.**

---

# Part 10 — Stage 9: The reply gate

> **In plain terms.** Decides whether an email needs a reply from you. **The surprise is that the words barely help** — measured, they are worth almost nothing. What predicts it is **who sent it and whether you have replied to them before.** So this stage uses no AI at all: just decision rules learned from your own past behaviour.

**What it does.** Answers *"will this person actually act on this email?"* — **without
reading it.**

## 10.1 Why there is no language model here

Measured on real enterprise mail, each feature group scored alone:

| Group | AUC |
|---|---|
| **Your history with the sender** | **0.692** |
| History with that exact pair | 0.638 |
| **What the email was understood to be** | **0.595** |
| Who they are (department, seniority) | 0.594 |
| Who else is on it | 0.591 |
| Timing | 0.540 |
| Attachments, size | 0.535 |
| **The raw words** | **0.511** |
| Everything combined | **0.721** |

*Chance is 0.500.*

**The raw words are worth 0.011 over a coin flip.** But the *interpreted* content — the
labels stage 8 produced — is worth 0.095. **So this stage does use the content. It uses the
meaning, not the text.**

**Independently replicated:** a second team on the same corpus reached **0.777** with
TF-IDF + gradient boosting, 0.788 ensembled. **Treat ~0.72–0.79 as the real ceiling, not
0.9+.**

**And Google's own production version of this** — Smart Reply's triggering model — is a
**plain feedforward network** over n-grams plus social signals, at **AUC 0.854**, filtering
**89% of messages** before anything expensive runs. Its strongest features are exactly ours:
*is the sender in your address book, have you replied to them before.*

*(Google's 0.854 came from 238 million training messages and Google's social graph. We will
not reach it. 0.72–0.79 is our honest target.)*

## 10.2 What gradient boosting is

**A decision tree** is a flowchart of yes/no questions ending in an answer. *Have you replied
to this sender before? → Are you the only recipient? → 0.87.*

One tree is weak. **Boosting builds many, each trained to fix the previous ones' mistakes**,
and adds their outputs. Typically hundreds of shallow trees.

**Why it beats a neural network on tabular data:** trees split on individual features at
learned thresholds, which is exactly the structure of *"replied more than 40% of the time
AND fewer than 3 recipients"*. **A neural network has to discover that shape; a tree
expresses it natively.**

## 10.3 LightGBM, and the alternatives

```python
import lightgbm as lgb
model = lgb.LGBMClassifier(
    n_estimators=300, num_leaves=31, learning_rate=0.05,
    is_unbalance=True,          # see below
)
```

| Option | Trade-off |
|---|---|
| **LightGBM** | Fastest to train, native categorical handling, leaf-wise growth |
| **XGBoost** | Equivalent accuracy, slower, level-wise growth, more mature tooling |
| **CatBoost** | **Often best with categorical features** — worth testing on our data |
| Logistic regression | Simpler, ~0.70 vs 0.72. A good sanity baseline |

**All four are a one-line swap. Test all four in an afternoon** and keep whichever wins on
our own mail.

## 10.4 ⚠️ Class imbalance — the thing that breaks naive attempts

**92.3% of enterprise email never gets a reply.**

So a model that answers "no" every single time is **92.3% accurate** — and completely
useless.

**Three consequences:**

1. **Never report accuracy.** Report **AUC**, or precision/recall at a chosen threshold.
2. **Weight the classes** — `is_unbalance=True`, or `scale_pos_weight`. Otherwise training
   converges to always-no.
3. **Pick the threshold deliberately.** The model outputs 0–1; *we* choose the cut. **A
   missed reply costs more than a wasted draft**, so we set it low and accept more false
   positives.

## 10.5 The metrics, plainly

| Metric | Question it answers |
|---|---|
| **Precision** | Of the ones I flagged, how many were right? |
| **Recall** | Of the ones that mattered, how many did I catch? |
| **F1** | Harmonic mean of the two |
| **AUC** | If I pick a random positive and a random negative, how often do I rank the positive higher? **Threshold-free** |

**AUC is the right headline here** because it does not depend on where we set the cut, and
it is not fooled by imbalance.

**⚠️ Split by time, not randomly.** A random split lets the model see September mail while
training and be tested on August — **that is cheating**, because senders and topics drift.
**Train on the past, test on the future.** Measured temporal degradation ranges from 0.26 to
7.72 points lost per year depending on task, and — importantly — **continued pretraining on
fresh unlabelled data does not fix it. Only re-annotating current labels does.**

## 10.6 The features

~65, in groups. All computed from headers and prior stages. **None require reading the body
at this stage.**

```
History      replies_to_sender_count, reply_rate, median_reply_hours,
             days_since_last_exchange, ever_initiated_by_me
Pair         thread_length, my_messages_in_thread, is_reply_to_me
From stage 8 intent_label, topic_label, confidence
Recipients   in_to / in_cc, recipient_count, is_internal_domain
Timing       hour_of_day, day_of_week, is_business_hours
Message      has_attachment, subject_length, body_length, has_question_mark
Declared     has_list_unsubscribe, precedence_bulk, auto_submitted
```

**And "no history" is a feature, not a blank.** First-time senders are a category the model
has seen you handle many times. A stranger writing only to you, using your name, asking a
question, not bulk — **that scores high even with zero history.**

---

# Part 11 — Stage 10: The privacy gateway

> **In plain terms.** **The only place anything leaves our building.** Names and ID numbers are stripped out before anything is sent to an outside AI company. This part is also **honest about how well that actually works — which is less well than any marketing anywhere suggests**, and it explains what we can therefore truthfully claim.

**What it does.** Finds names and identifiers so they can be masked before anything crosses
the one door out.

## 11.1 Presidio

Microsoft's PII toolkit, MIT licensed. **Two packages:** `presidio-analyzer` finds spans,
`presidio-anonymizer` replaces them.

```python
from presidio_analyzer import AnalyzerEngine
results = analyzer.analyze(text=text, language='en')
# [type=PERSON, start=44, end=47, score=0.85]
```

**How it is built.** A registry of *recognizers*, each handling one entity type:

- **Pattern recognizers** — regex plus a checksum. Credit cards, IBANs, emails, phone
  numbers. **Near-perfect, because these have verifiable structure.**
- **NER recognizers** — a model that finds people, organisations, locations. **This is where
  we plug in our fine-tuned DeBERTa-v3-small.**
- **Context enhancement** — boosts confidence when nearby words suggest the type.

**We would add Pakistani recognizers**: CNIC (13 digits, `#####-#######-#`), NTN, IBAN
starting `PK`, local mobile formats.

## 11.2 ⚠️ The honest limitation, and it is severe

**Model-card PII scores do not survive real documents.**

| Model | Self-reported | On real documents |
|---|---|---|
| An ai4privacy model | **98.82** | **0.27** |
| Piiranha | **93.12** | **0.34** |
| Best AI system tested | — | 0.71 |
| **Human baseline** | — | **0.77** |

**Nothing tested beats a non-expert human.** And Presidio's own published evaluation is
**precision 0.733 / recall 0.646** — with a separate robustness study finding it detected
**nothing at all in 28% of cases**, and mislabelled 82–92% of the spans it did find.

**What this means for our claims.** We cannot say "names are removed". We can say:

> **"Names and identifiers are stripped, we minimise what crosses, we contract for
> zero-retention, and we measure our own miss rate on our own mail rather than quoting
> anyone's benchmark."**

**The structured identifiers — cards, CNICs, IBANs — are genuinely near-perfect**, because
they are regex-shaped. **It is names and free text where it degrades.** That distinction is
worth making explicitly; it is true and it is defensible.

## 11.3 ⚠️ And do not store embeddings instead

The tempting shortcut — "we don't store the text, only the embedding" — **does not hold.**
Published work recovers **92% of 32-token inputs word-for-word from their embeddings alone**,
independently reproduced.

> **An embedding is not anonymisation. Protect it exactly like raw text.**

We store **typed extracted facts** — a date, an amount, two labels — not vectors of email
bodies. The one exception is the style store, which holds the user's *own outgoing* writing.

---

# Part 12 — Stage 11: The frontier model

> **In plain terms.** The expensive model that writes the actual reply. **About 5 emails in 100 reach it.** This part covers what it costs, the one trick that cuts that cost by ten times, and how to make it answer in a fixed shape instead of free prose.

**What it does.** Writes the reply, and picks which candidate date is the real deadline.

## 12.1 What is different about a decoder

A decoder generates one token at a time, each conditioned on everything before it. That is
why it can write — and why it is slower and costs per token.

**Two prices, and they differ by 5×:**

| | Sonnet 5 |
|---|---|
| Input | **$2.00** / million tokens |
| Input, cached | **$0.20** / million |
| Output | **$10.00** / million |
| Context | 200k tokens |

**Prompt caching is the lever.** Our system prompt and the user's style profile are
identical across every call for that user. Cached, they cost **a tenth**. **Structure the
prompt so the stable part comes first** — caching works on prefixes.

**Batch mode halves it again** if a few hours' delay is acceptable. **Reminders and the
daily brief can absolutely go through batch. Drafts cannot.**

## 12.2 Getting structured output

Two techniques, and the measurements behind them are counter-intuitive.

**Finding 1 — the format tax is a *prompting* tax, not a *decoder* tax.** Asking for JSON at
all costs about **3.9 points** of accuracy. *Enforcing* it with a grammar costs only
**1.6 points more.** **92% of the damage happens before the decoder is involved.**

> **So take the grammar. The constraint is nearly free; the asking is what costs.**

**Finding 2 — reason free, constrain late. Worth +6.8 points**, confirmed by three
independent studies. Let the model think in plain language first, *then* force the answer
into shape. Forcing structure from the first token measurably degrades the thinking.

## 12.3 Whole drafts, not fragments

Evidence favours generating the complete message rather than assembling it from suggested
pieces — **better on speed and on how recipients rated the result.** Fragments cost more
calls for a worse outcome.

## 12.4 The alternatives

| Option | Trade-off |
|---|---|
| **Sonnet 5** ($2/$10) | Our pick |
| **Haiku 4.5** ($1/$5) | **Half price. Genuinely worth testing** — if quality holds on our drafts, that is the single biggest cost lever available |
| Self-hosted 7–8B | Needs a GPU; **break-even at ~24% utilisation.** Not worth it until volume is large and steady |

**How to choose between them: not a public benchmark.** No leaderboard measures "writes a
good email reply in this person's voice". **Generate 20 real drafts with each and have
people compare them blind.**

## 12.5 What we send, and what we do not

**Sent:** the stripped, redacted body; 4–5 of the user's own past replies; a short style
profile; the extracted facts.

**Never sent:** anything from stage 3; other people's mail as style examples; attachments;
the raw thread history.

**Contractually:** zero-retention terms. **This is a term to actually check in the
agreement**, not assume.
---

# Part 13 — Stages 12–14: restore, approve, execute

> **In plain terms.** Putting the real names back, asking you, and then doing the thing. **The most important idea in the entire system is in here:** the rule that nothing sends without your yes lives in our own code, not in the AI's instructions. **An AI can be talked out of asking permission — it has been done to every email agent ever tested. Our code never reads the email, so nothing in an email can reach it.**

## 13.1 Stage 12 — restore names

Swap the placeholders back for the real values, **on our side, before the user sees
anything.** A dictionary lookup against the mapping stage 10 built.

**One rule:** the mapping lives in memory for the life of the request and is never
persisted. If the process dies mid-flight, the draft dies with it. **That is correct** — a
stored mapping is a stored copy of the identifiers we just went to trouble to remove.

**One check:** if any placeholder remains unresolved after the swap, **discard the draft and
do not show it.** An unresolved `[PERSON_3]` in a message the user might send is worse than
no draft.

---

## 13.2 Stage 13 — approval

**What it does.** Presents the decision and waits. **Nothing irreversible happens without a
clear yes.**

### The gate is code, not a prompt

```python
IRREVERSIBLE = {"send", "forward", "unsubscribe", "trash"}

def execute(action: Action, approval: Approval | None) -> Result:
    if action.type in IRREVERSIBLE:
        if approval is None or not approval.is_explicit:
            return Result.blocked("needs approval")
        if approval.draft_hash != action.draft_hash:
            return Result.blocked("approved a different version")
    return dispatch(action)
```

**Read the second check.** The approval is bound to **a hash of the exact draft.** If the
draft changed after the user said yes — because they asked for an edit — **the old approval
no longer applies.** This is what stops "make it shorter and send" from sending a message
the user never saw.

### Why it cannot be a model instruction

| | |
|---|---|
| Measured | **All 1,404 real email agents tested were hijacked**, most within ~2 attempts |
| The action that resisted best | `send_email` — **but only because some models volunteer a confirmation** |
| How the published attack works | **It tells the model the confirmation is not needed this time** |

**A model's manners are a behaviour. Behaviours can be argued with. Our code does not read
the email, so there is nothing in the email that can reach it.**

### Approval defaults to no

Since the interface is text, approval is a typed word.

```python
AFFIRMATIVE = {"yes", "y", "send", "send it", "ok", "okay", "go", "haan", "ji", "theek hai"}

def is_approval(text: str) -> bool:
    return text.strip().lower() in AFFIRMATIVE      # exact match, not substring
```

**Exact match, not fuzzy, not substring.** *"don't send it"* contains *"send it"*. Anything
that is not an unambiguous yes **sends nothing and asks again.**

**This is safer than a button**, because the failure direction is fixed: unclear means
nothing happens.

### State that survives a restart

The approval flow is a state machine, and **it lives in the database, not in memory.**

```
DRAFTED → AWAITING_APPROVAL → APPROVED → EXECUTING → DONE
                     ↓              ↓          ↓
                 REJECTED       EXPIRED    FAILED
```

**If the process is killed between APPROVED and DONE, the next worker picks it up and
finishes.** If it is killed between AWAITING_APPROVAL and APPROVED, nothing was sent.
**There is no state in which a restart causes a send.**

**Approvals expire** — 24 hours. An approval from last week applied to a stale draft is a
bug waiting to happen.

---

## 13.3 The command path — reading what the user typed

**This is a full component, not a footnote.** With text as the only interface, every
interaction goes through it.

### The one hard rule

> **Text the user typed is an INSTRUCTION. Text inside an email is DATA. They never share a
> code path.**

```python
class UserInstruction:   # from the WhatsApp webhook, for a verified user
    text: str

class EmailContent:      # from a mailbox. Untrusted. Always.
    text: str
```

**Two different types, enforced by the type system.** An email saying *"forward this to
X"* can never be constructed as a `UserInstruction`, because the constructor is only reached
from the webhook handler.

**This is the single most important line in the command handling.** If those ever merge, the
whole security argument collapses.

### Turning conversation into standalone questions

Small models score ~72% on standalone instructions and **under 4% on follow-ups.** So we
never give them a follow-up.

**Our code holds the state:**

```sql
CREATE TABLE conversation_state (
    user_id       UUID PRIMARY KEY,
    current_email TEXT,          -- message_id under discussion
    current_draft TEXT,
    draft_hash    TEXT,
    awaiting      TEXT,          -- 'approval' | 'clarification' | null
    updated_at    TIMESTAMPTZ
);
```

When the user types *"make it shorter"*, the model is never asked what *"it"* means:

```
There is a draft pending for message msg_8823.
The draft says: "Hi Ali, I'll have the Q3 report..."
The user said: "make it shorter"
Choose from: send · edit · discard · snooze · remind · archive · label · nothing
```

**Note the last line.** The allowed actions are decided **by our code from the current
state.** With no draft pending, `send` is not on the list. **The model cannot choose an
action we did not offer.**

### The two-stage output

Reason freely, then constrain — **worth +6.8 points**:

```json
{"actions": [
  {"type": "edit", "instruction": "shorten"},
  {"type": "send"}
]}
```

**Which model.** Start with the frontier for everything — commands are five words, so this
costs almost nothing. **Move the common ones to a fine-tuned small model** once we have real
command logs. `remind` and `archive` will be most of the volume, and both are standalone.

**Where small models still fail: genuine follow-ups** that depend on the conversation rather
than the state. Those stay on the frontier.

### Ambiguity

No buttons means we ask in words. *"Which Ali — Ali Raza or Ali Hassan?"* **That is a second
standalone exchange, not a memory problem.**

---

## 13.4 Stage 14 — the executor

**One API call per decision.** Idempotent, audited, undoable.

### Idempotency — never send twice

The failure that matters: we call `messages.send`, the network drops before the response
arrives, we retry, **the user's contact gets two emails.**

```sql
CREATE TABLE executed_actions (
    idempotency_key TEXT PRIMARY KEY,   -- hash(user, message_id, action, draft_hash)
    provider_id     TEXT,
    executed_at     TIMESTAMPTZ NOT NULL
);
```

```python
key = sha256(f"{user_id}:{message_id}:{action}:{draft_hash}")
# INSERT ... ON CONFLICT DO NOTHING. If no row inserted, we already did this.
```

**Write the row before the call, in the same transaction as the state change.** On retry the
insert conflicts and we skip. **Slightly conservative — a crash between insert and call
could lose an action — and that is the correct direction to fail.**

### Audit before, not after

```sql
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL,
    message_id  TEXT,
    action      TEXT NOT NULL,
    reason      JSONB,        -- which stage decided, what confidence
    undo_token  JSONB,        -- exactly what to call to reverse it
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**`reason` is what lets us debug a wrong decision a week later** — which stage decided, at
what confidence, on which features. Without it, "why did it archive that?" is unanswerable.

**`undo_token` holds the literal reversal** — the label to re-add, the folder to move back
to. Not "figure it out later".

### Rate limiting is ours to do

Providers will throttle us. **We throttle ourselves first**, per user, at a rate the
connector declares.

```python
# On 429: exponential backoff with jitter.
# On Graph: honour the Retry-After header exactly — Microsoft escalates against
# clients that ignore it.
```

---

# Part 14 — OAuth and permissions

> **In plain terms.** How a user gives us permission to touch their mailbox **without ever giving us their password.** Also contains the trap that catches every team building this: **while a Google app is still in test mode, every user is silently logged out after 7 days.**

## 14.1 The flow

Authorization Code with PKCE. Same shape everywhere:

1. Redirect the user to the provider's consent page with our client ID, the scopes, a
   redirect URI, `state`, and a PKCE challenge
2. They approve; the provider redirects back with a `code`
3. **Server-side**, exchange `code` + verifier for an **access token** (short-lived) and a
   **refresh token** (long-lived)
4. Store the refresh token encrypted; use it to mint access tokens as needed

**`state` must be checked** — it is the CSRF defence. **PKCE even though we have a secret** —
it costs nothing and closes interception.

## 14.2 Google specifics

**Setup:** Google Cloud Console → enable Gmail API → OAuth consent screen → credentials.

**Scopes we request:**

```
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.send
```

**Never** `https://mail.google.com/` (full mailbox — only needed for permanent delete).

**⚠️ The trap that catches everyone.** While your app is in **Testing** publishing status,
**refresh tokens expire after 7 days.** Everything works for a week, then every user is
silently logged out. **You must move to Production**, which means verification.

**Verification.** `gmail.modify` is a **restricted** scope, so: a verified domain, a privacy
policy, a demo video, and an annual **CASA** security assessment — around **$675/year**
`[verify]`. **Internal / single-organisation apps are exempt entirely** — which is the right
route for the first deployment at the company.

**Asking for less does not help.** Even `gmail.metadata` is restricted, and it blocks
server-side search.

## 14.3 Microsoft specifics

**Setup:** Entra ID → App registrations → redirect URI → API permissions.

**Delegated** permissions: `Mail.ReadWrite`, `Mail.Send`, `offline_access` (this one is what
gets you a refresh token — **it is easy to forget and everything breaks in an hour**),
`User.Read`.

**Never** `Mail.ReadWrite.All` — that is every mailbox in the tenant.

**Admin consent.** Some tenants require an administrator to approve the app for all users.
**Expect this at corporate customers** and build the admin-consent URL flow.

## 14.4 Token storage

```sql
CREATE TABLE mail_accounts (
    id             UUID PRIMARY KEY,
    user_id        UUID NOT NULL,
    provider       TEXT NOT NULL,      -- gmail | graph | jmap | imap
    email          TEXT NOT NULL,
    refresh_token  BYTEA NOT NULL,     -- encrypted
    access_token   BYTEA,              -- encrypted, short-lived
    expires_at     TIMESTAMPTZ,
    sync_token     TEXT,               -- historyId / deltaLink / JMAP state / UIDVALIDITY
    scopes         TEXT[],
    status         TEXT NOT NULL,      -- active | needs_reauth | revoked
    UNIQUE (user_id, provider, email)
);
```

**Encrypt refresh tokens at rest**, with a key from the environment, not the database. A
database dump must not be a mailbox dump.

**Handle revocation.** Users revoke access; tokens get invalidated by password changes.
**On a `401`/`invalid_grant`, mark `needs_reauth` and tell the user** — do not retry forever.

---

# Part 15 — The data model

> **In plain terms.** Every table in the database and why it exists. **The thing to notice is what is missing: there is no column for email bodies.** That is the privacy promise written into the structure of the system rather than into a policy page.

```sql
-- Identity ------------------------------------------------------------
users            (id, whatsapp_number, created_at, timezone)
mail_accounts    (see above)

-- Mail: facts, never bodies -------------------------------------------
messages (
  message_id     TEXT PRIMARY KEY,     -- the RFC header. Provider-independent
  account_id     UUID,
  provider_id    TEXT,                 -- opaque handle for API calls
  thread_key     TEXT,
  sender         TEXT,
  received_at    TIMESTAMPTZ,
  intent_label   TEXT,                 -- stage 8
  topic_label    TEXT,                 -- stage 8
  confidence     REAL,
  act_prob       REAL,                 -- stage 9
  exited_at      TEXT,                 -- which stage. Log this: it IS the funnel
  processed_at   TIMESTAMPTZ
);                                     -- NOTE: no body column. Deliberate.

extracted_facts  (message_id, kind, value, source_span, confidence)

-- The five stores ------------------------------------------------------
sender_history   (account_id, sender, sent_count, replied_count,
                  median_reply_seconds, last_exchange_at)
templates        (sender_pattern, structure_hash, field_selectors JSONB,
                  required_fields TEXT[], built_at, last_matched_at, match_rate)
user_rules       (user_id, kind, pattern, action, created_at)
style_profile    (user_id, greeting, signoff, avg_length, formality, ...)
style_examples   (user_id, text, embedding VECTOR(384), sent_at)
audit_log        (see above)

-- Obligations: from headers alone, no AI -------------------------------
obligations (
  id, user_id, thread_key, direction,   -- 'i_owe' | 'they_owe'
  counterparty, opened_at, closed_at, closing_message_id
);

-- Operations ------------------------------------------------------------
jobs                (see Part 2)
conversation_state  (see 13.3)
executed_actions    (see 13.4)
```

**Two things worth pointing at.**

**`messages` has no body column.** That is the privacy claim expressed in the schema. An
email is read, acted on, and the text is dropped; what persists is typed facts.

**`exited_at` is the funnel.** Log which stage each message left at and the "85% strip / 5%
reach the model" numbers stop being estimates and become a `GROUP BY`.

---

# Part 16 — Running it

> **In plain terms.** Which machine this runs on, what it costs, and what has to be scheduled. **One ordinary server, no graphics card, roughly $100–150 a month for the pilot.** Also the jobs that must run on a timer — **miss them and the whole thing silently stops receiving mail with no error.**

## 16.1 What to deploy on

| Stage | Machine | Cost |
|---|---|---|
| Development | Any laptop, 16 GB RAM, **no GPU** | — |
| Fine-tuning | One rented GPU, **under an hour**. Rent, run, kill | **<$1/run** |
| Pilot | **1 VM: 4 vCPU, 16 GB** + managed Postgres. **No GPU** | ~$100–150/mo |
| Growth | More VMs behind the jobs table | linear |

**Why no GPU.** Break-even on self-hosting: the **classifier** pays off at ~2.4%
utilisation, so we host it and CPU suffices. The **writer** needs ~24%, and would mean a GPU
idle most of the day. **Host the small, rent the big.**

**Capacity.** A comparable encoder converted to ONNX reached **72 docs/sec single-threaded,
233 batched** on a 16-core CPU. Ours is larger, so slower. **Even at 20/sec that is 1.7M
emails/day on one machine** against a heavy user's 200. `[verify — this is arithmetic on
someone else's measurement, not ours. But the margin survives being wrong by 10×.]`

## 16.2 Processes

Three, all from one image:

```
web      FastAPI — OAuth callbacks, provider webhooks, WhatsApp webhook
worker   Claims jobs from the table. Scale this one horizontally
beat     Scheduler: renew watches, refresh tokens, rebuild templates, daily briefs
```

**Renewal jobs are not optional.** Gmail watches expire in **7 days** (renew daily), Graph
subscriptions in **~3 days** (renew daily). **Miss these and push silently stops** — mail
keeps arriving, nothing happens, and no error is raised.

## 16.3 The public HTTPS requirement

Graph webhooks **require a publicly reachable HTTPS endpoint with a valid certificate**, and
respond to a validation handshake within 10 seconds. **No localhost, no self-signed.** For
development use a tunnel; for production this shapes the hosting choice.

## 16.4 Backups and secrets

Nightly Postgres backups, **restore-tested** — an untested backup is a hope.

Secrets in the environment or a manager, **never in the repo**. The token-encryption key
must not live where the database dump lives.

## 16.5 What to log

```python
log.info("message_processed",
         message_id=..., exited_at="stage_9",
         strip_ratio=0.86, intent=..., confidence=0.91,
         act_prob=0.87, latency_ms=34)
```

**Structured, one line per message.** This is the funnel, the strip ratio, and the debugging
trail in one place. **Never log body text.**

**Four alerts worth having:** watch/subscription renewals failing · template match rate
dropping (silent drift) · 429 rate climbing · approvals expiring unanswered.

---

# Part 17 — WhatsApp

> **In plain terms.** How we talk to the user. **The important quirk: we can only send freely within 24 hours of them messaging us.** Outside that window every message costs money and needs pre-approval. **That is the entire reason the daily brief exists** — they reply to it, and the free window reopens.

**WhatsApp Cloud API**, Meta-hosted. Webhook in, REST out.

**⚠️ The 24-hour window.** You may only send free-form messages within **24 hours of the
user's last message.** Outside it you may send only pre-approved **template** messages, and
you pay per conversation.

> **This is why the daily brief exists.** The user replies to it; that reply reopens the
> window; everything for the rest of the day is free-form and free.

**Registration in Pakistan:** a Meta Business account, **business verification** (SECP
registration, FBR NTN, a live website with matching details), a phone number not on WhatsApp
already, and a display name that passes review. **Start this early — it takes weeks, not
days.**

**Templates** need approval per template, in advance. **Write them before you need them.**

**Webhook:** must be public HTTPS, verify Meta's signature on every request. **Reply 200
immediately and queue the work** — Meta retries on slow responses, and you will process the
same message twice.

**Alternative worth knowing:** Telegram's API has none of this friction — no verification, no
window, no per-message cost. **But sir specified WhatsApp**, and he is right on the merits:
in Pakistan WhatsApp is where people already are.

---

# Part 18 — Proving it works

> **In plain terms.** How we know any of this works. **Different parts need different kinds of proof.** The AI parts get scores. The safety gate gets ordinary pass-or-fail tests, **because "99% of the time we ask permission" is not a safety property.**

## 18.1 Build a golden set first

**200 emails from a real mailbox, labelled by hand.** Before writing a model. It is an
afternoon, and every later decision is measured against it.

**Split by time, not randomly** — train on the past, test on the future. A random split lets
the model see September while training and be tested on August. **That is cheating, and it
will make you confident in something that does not work.**

## 18.2 Different things need different measures

| What | Measure | Target |
|---|---|---|
| Stage 4 header rules | Precision | **~1.0** — this is deterministic; anything less is a bug |
| Stage 5 templates | Precision + match rate | High precision; recall can be low |
| Stage 8 classifier | Macro-F1 | Beat the golden set baseline |
| Stage 9 gate | **AUC** | 0.72–0.79 is the honest published ceiling |
| Stage 10 PII | **Recall** on our own mail | Measure it. Do not quote anyone's |
| Stage 11 drafts | **Human pairwise comparison** | See below |
| Stage 13 gate | **Unit tests** | **100%. Not a metric — a test** |

**⚠️ Never judge drafts by an automatic score.** On an email-summarisation benchmark, the
best correlation between ROUGE and human judgement was **0.14**, and *negative* for longer
outputs — judges preferred the model with the *worse* score. **Blind pairwise human
comparison is the only valid method.**

## 18.3 The gate is tested, not measured

Stage 13 is not a model, so it does not get a percentage. **It gets test cases:**

```python
def test_no_send_without_approval(): ...
def test_approval_bound_to_draft_hash(): ...
def test_edited_draft_invalidates_approval(): ...
def test_dont_send_it_is_not_approval(): ...
def test_email_text_cannot_become_an_instruction(): ...
def test_restart_between_approve_and_send_does_not_double_send(): ...
```

**These pass or they fail. There is no probability involved, and that is the point.**

---

# Part 19 — What we do not know

**Genuinely unmeasured. One pilot mailbox answers all of them.**

| Unknown | How to settle it |
|---|---|
| Real strip ratio on our mail | Log `strip_ratio`. One day of data |
| What share exits at each stage | Log `exited_at`. `GROUP BY` |
| Presidio's miss rate on our mail | Hand-label 200 emails, count misses |
| Our cost per user per month | Meter tokens per user for a week |
| Whether 44M is enough for PII | Test 44M vs 184M on our golden set |
| Whether Haiku matches Sonnet on drafts | 20 drafts each, blind comparison |
| Real backfill wall-clock | Run it against live quotas |
| Template match rate on Pakistani senders | Collect 10 bills, build templates, measure |
| Gmail/Graph quota figures | Read the live docs — published numbers change |

**And the honest framing for all of it:**

> **"The percentages are estimates until we run it on a real mailbox. That is an afternoon of
> work, not a research project — and I would rather give you a measured number next week
> than a confident guess today."**

---

# Appendix — what is still thin in this document

Written down so it is not mistaken for complete.

- **Attachment handling** beyond invoice PDFs — images, Office documents, scanned bills
- **Multiple mail accounts** per user, and how the ledger merges across them
- **Non-English mail** — Urdu, Roman Urdu, code-switching. Our models are English-trained;
  this is a real gap for the Pakistani market and is not yet researched
- **The migration story** if a user leaves — export format, deletion guarantees
- **Cost model in detail** — per-user unit economics with the levers laid out
- **Competitive positioning** — who else does this and where the gap actually is
- **Legal** — data protection obligations for a Pakistani company holding foreign users' mail
- **JMAP connector specifics** — deferred until it is actually built
