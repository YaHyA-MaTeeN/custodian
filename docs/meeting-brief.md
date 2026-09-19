# Meeting brief — Inbox Custodian
*For you, not for sir. Everything here you should be able to say without notes.*

---

## The 60-second open

> "I took the recording and turned it into a scoped product. Three things I want to walk you through: what we build first and why, the two platform constraints that change the plan, and the cost architecture — because I think we can run this at about a dollar or two per user per month instead of fifty."

Then hand over / share the doc. Don't read it aloud — let him skim while you talk.

---

## The five points that carry the meeting

**1. The product is the approval loop, not the inbox.**
Everyone else puts AI inside the mail client. We put it in the channel the user already checks. That inversion is the positioning, and it's what makes "no app needed" true in V0.

**2. The highest-value features need no LLM at all.**
Cleanup, unsubscribe, the sensitive vault, scope control — all header-level rules. So V0 ships in two weeks, is fully demoable, and costs zero per user. This directly answers his "don't build something ambitious that never finishes."

**3. CASA is the real obstacle, and we route around it.**
Gmail read access is a *restricted scope*: public launch needs Google verification plus an annual security assessment ($500–$4,500+/yr, recurring). But — Testing mode allows 100 users with no verification, and a Workspace admin can install internally for one domain. **His own ORIC/@uet example is the deployment that dodges it.** Say that; it lands.
Corollary: we don't put `delete` in the tool surface, because full-mailbox access triggers the heavier assessment tier. A safety decision that's also a compliance decision.

**4. WhatsApp — he was right to worry, and here's the shape of it.**
Needs Meta business verification, a dedicated number, and proactive messages must be pre-approved templates billed per message. **But** once the user replies, a 24-hour window opens where everything is free. So: one template a day opens the window, all approvals ride free inside it. And we build channel-agnostic and ship Telegram first, so the demo is never stuck in Meta's queue.

**5. The cost number.**
Naive (every email → frontier model) ≈ **$54/user/month**. Cascade (headers → local small model → redacted frontier for drafts only) ≈ **$1–3**. 20–50×. And the punchline: *the biggest lever isn't which model we pick, it's not calling a model at all.*

---

## The privacy angle he asked for

Same design as the cost architecture — that's the insight. Every byte we don't send is a byte we don't pay for *and* don't expose.

- Sensitive/OTP mail detected from **headers alone**, body never read by any model. (This is the direct answer to his OTP question.)
- PII tokenized locally before egress — `<PERSON_1>`, `<AMOUNT_1>` — de-tokenized after. Provider never sees an identity.
- **We store derived structure, never content.** Vectors and metadata, not mail. If the DB leaks, nobody's email leaks.
- Data Passport: a per-email receipt of what left, redacted how, to which model. Competitors can't copy a receipt with a prompt.
- Bonus: Google's Workspace policy *already forbids* training on this data. Our privacy story is also our compliance obligation.

---

## Answers to the questions he'll ask

**"Can we use RAG / a vector DB?"**
Not over the whole mailbox — it's the most expensive option, it stores exactly what we promised not to store, and email is thread-scoped not corpus-scoped. Instead: thread-local context, a small sender-memory record, and a local vector index over **the user's own Sent mail** for style exemplars. That last one *is* the tone-learning feature — retrieval instead of fine-tuning, so it's per-user, instant, and improves with every edit.

**"App, extension, Windows, Mac, or SDK?"**
One backend, thin clients. Mail arrives while the phone is asleep, so the agent is server-side no matter what. Once that's true, the chat channel is a free zero-install client covering every OS. Mobile app at V3, web dashboard for settings, extension deferred, SDK not now.

**"What about the small model on mobile?"**
Be honest here — it's a point in your favour, not a problem. An on-device model **can't** run the ingestion path (background limits, battery). The small model's home in V1 is our own CPU box. On-device is a real V3 feature as an opt-in local-only mode.

**"Can we build the 10–100M parameter model?"**
At that size you don't get a *generative* model — but you don't need one. 30–110M is exactly right for an encoder + classification head (category/urgency/junk), NER for redaction, and embeddings. Anything that has to *write* needs 0.5–1.7B (Qwen3-0.6B, Gemma 3, Llama 3.2 1B), quantized, on CPU.
**The sequencing is the answer:** don't train first, collect first. Every frontier call is a labeled example, and the user's edit is a free preference signal. After 4–6 weeks of usage we have a distillation set from our exact task distribution. Frontier as teacher, small model as student, Send-or-Edit as the reward. It arrives as a *byproduct of running the product*, which is why the agent is never blocked on it — exactly what he asked for.
One thing we own today: S1 behind a stable interface from commit one, and every frontier call logged in distillation-ready form. Skip that and the training set doesn't exist when we want it.

**"What if it sends a wrong email?"**
Nothing sends without approval in V0–V2. No confidence threshold, no exceptions. Plus: never delete — archive to a reviewable label with 30-day undo, and the first run is dry-run only.

---

## What to ask him for

1. **UET internal deployment or public beta?** — recommend internal, it sidesteps CASA and gets real users in week three.
2. **Telegram OK for the demo?** — one day of work, removes an external dependency from the critical path.
3. **Do we have a box for the local model?** — 16GB CPU is enough to start. Determines whether V1 slips.
4. **Cost ceiling per user per month?** — $2 buys Sonnet-quality drafts; $1 means Haiku with escalation. The router needs the number.
5. **Is 8 weeks to V2 the commitment?** — V0 alone is demoable in two.

---

## Tone notes

- He gave an abstract and asked you to think. So lead with **decisions you made**, not questions you have. The five questions come at the end, framed as "these change what I build; everything else I can proceed on."
- Two places to explicitly credit his framing: the ORIC/@uet scoping example (it turned out to be the compliance workaround) and his instinct that WhatsApp would be hectic (it is, and here's the shape).
- Don't oversell. The cost numbers are estimates from stated assumptions — say so before he asks. "To be re-measured against a real 1,000-message corpus in week one."
- If he pushes on scope, the answer is ready: V0 is two weeks and standalone. We can always add; we can't un-ship a half-finished V2.
