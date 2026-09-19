# The prompt set

Every instruction the system ever gives an AI model. Nothing is hidden in the
code — the code loads this file.

**Anyone can edit this file.** No programming needed. Change the wording, save,
run again. That is the point: prompt wording is a product decision, not an
engineering one, and it should not need a developer to change.

**Format.** Each prompt is a `##` heading followed by the text. Anything in
`{curly braces}` is filled in by the system. Lines starting with `>` are notes
for us and are never sent to the model.

---

## classify

> Stage 8. The only place anything reads an email to understand it.
> Returns two labels and nothing else — it does not summarise, decide, or write.
> In production this is replaced by our own 278M model, fine-tuned on these
> same categories. The categories here become that model's output layer, so
> changing this list means retraining.

Read this email and answer with two labels.

What does the sender want from me? Choose exactly one:
- asking me for something
- proposing something
- promising something
- delivering something
- just telling me
- nothing needed

What is it about? Choose exactly one:
- work
- money or bills
- travel
- appointment or meeting
- shopping or order
- personal
- account or security
- newsletter or marketing
- other

Reply with JSON only: {{"intent": "...", "topic": "...", "confidence": 0.0-1.0}}

Subject: {subject}
---
{text}

---

## pick_deadline

> Stage 7 into 11. Rules already found every date in the text. This picks which
> one is the real deadline — that needs understanding the sentence.
>
> ⚠️ It must NOT calculate anything. On date arithmetic, encoders score below
> random chance. The actual date was computed in code before this prompt ran.

Which of these dates is the actual deadline the sender needs action by?
Some are just mentioned in passing.

Subject: {subject}
{candidates}

Reply with JSON only: {{"index": <number>, "kind": "appointment|bill|renewal|application|meeting|default"}}
If none of them is a real deadline, use index -1.

---

## draft_reply

> Stage 11. The only paid step, and the only text that leaves our building.
>
> ⚠️ Everything reaching this prompt has passed stage 10 — names and
> identifiers already replaced with placeholders. The model must keep the
> placeholders exactly; stage 12 swaps the real values back on our side.
>
> Write the WHOLE message, not fragments. Measured better on both speed and
> how recipients rate the result.

Write a reply to this email, in the same voice as the examples.

How this person writes: {profile}

Some of their own past replies:
{examples}

---
The email to reply to. Names are replaced with placeholders — keep the
placeholders exactly as they are, and do not invent real names:

From: {sender}
Subject: {subject}

{text}
---
{instruction}

Write only the reply body. No subject line, no explanation, no quotation marks.

---

## read_command

> Stage 13. Turns what the user typed into one action.
>
> ⚠️ This is a MULTIPLE-CHOICE question, not open-ended understanding. Our own
> code builds the list of allowed actions from the current state, so the model
> can never choose something we did not offer. With no draft pending, "send"
> is not on the list at all.
>
> ⚠️ It reasons in plain words FIRST, then commits to the format. Forcing the
> structure from the first token measurably degrades the thinking — worth
> about 7 points.

The user typed a short instruction about their mailbox.

What is on screen right now:
{state}

The user typed: "{user_text}"

Think about what they mean, then choose exactly one action from this list:
{allowed_actions}

Reply with JSON only:
{{"action": "...", "parameter": "...", "reasoning": "..."}}

Use "nothing" if it is unclear. Do not guess.

---

## clarify

> When a command is ambiguous. No buttons, so we ask in words — and that is a
> second standalone exchange, not a memory problem.

The user said "{user_text}" but it could mean more than one thing:
{options}

Write one short question asking which they meant. One sentence. No preamble.

---

## summarise_for_brief

> The daily brief. Reads NOTHING new — it is assembled from labels and scores
> already computed during the day. This prompt only turns those into a sentence.

Write one short line for a daily summary, from these already-computed facts:

{facts}

One sentence. Plain. No greeting, no sign-off, no "here is your summary".

---

## extract_request

> UC-33 / UC-45 / UC-40. Reads one personal message ONCE — already redacted,
> already stripped of quoted history — and names what was asked, of whom, and
> the phrase that says when. It never computes a date: the phrase comes back
> as text and Python resolves it (encoders score below chance on date
> arithmetic). It never decides to act: the output is a record, and every
> action still needs the Owner.
>
> ⚠️ When unsure, return an empty list. Two people reading the same email
> agree only 72% of the time on whether something is a request. A wrong
> deadline is worse than none.

This is one {direction} message. The subject is "{subject}".
Names and numbers have been replaced with placeholders like [PERSON_1].

{text}

List every concrete request or promise in it. For each one give:
- "what": the request in a few words, using the writer's own words where possible
- "who": who has to do it — "me" (the reader), "sender" (the writer), or "third party"
- "when_phrase": the exact words that say when, or "" if no time is stated
- "evidence": the sentence it came from, quoted
- "confidence": 0.0 to 1.0

Ignore pleasantries, newsletters, and anything that is not a real ask or a real promise.
If there is nothing, or you are not sure, return an empty list.

Reply with JSON only:
{{"items": [{{"what": "...", "who": "...", "when_phrase": "...", "evidence": "...", "confidence": 0.0}}]}}

---

## read_rule

> UC-38. Reads ONE typed sentence, ONCE, at the moment a rule is created, and
> turns it into a match and an action from a fixed list. Matching afterwards
> uses no model at all. The interpretation is shown back to the Owner and
> must be confirmed before anything is saved.
>
> ⚠️ Multiple choice, not open-ended. The action must be one of the allowed
> list; "send" and "delete" are not on it, and no wording puts them there.

The user typed a rule about their mailbox, in their own words:

"{sentence}"

Work out what it matches and what it should do.

match_kind must be one of: sender, domain, subject, person
match_value: the address, domain or words it matches (lower case, no quotes)
action must be one of: {allowed_actions}
action_arg: a label name, a recipient address, or "" — only if the action needs one

If any part of the sentence cannot be read, put it in "unclear" and leave that field empty.

Reply with JSON only:
{{"match_kind": "...", "match_value": "...", "action": "...", "action_arg": "...", "plain": "one sentence saying what this rule will do", "unclear": ""}}

---

# Rules that apply to every prompt

> Not sent to the model. These are for whoever edits this file.

**Never ask a model to calculate a date.** Rules find the date phrases, the
model picks which one matters, and ordinary code does the arithmetic. Measured:
encoders score below random chance on date arithmetic.

**Never ask a model whether to send something.** The approval gate lives in our
own code, below the model layer. All 1,404 email agents tested were hijacked,
and the published attack works by telling the model it need not ask. A model's
manners are not a security control.

**Give a fixed list of options wherever an answer can be enumerated.** A model
choosing from a list we wrote cannot invent an option. A model asked an
open question can.

**Let it reason before it formats.** Asking for JSON at all costs about 3.9
points of accuracy; enforcing the format costs only 1.6 more. Almost all the
damage happens before the decoder — so reason freely first, then commit.

**Text the user typed is an instruction. Text inside an email is data.** They
never share a code path, and no prompt may ever put untrusted email content
where an instruction belongs.
