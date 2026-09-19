"""
Custodian — the full pipeline, end to end.

Takes the newest messages in a mailbox and walks each one through all fourteen
stages, printing what happens at every step and why.

    python agent.py            # 5 newest messages
    python agent.py 20         # 20 of them
    python agent.py 10 --draft # also write a draft for anything needing a reply
    python agent.py 10 --draft --drafts   # put it in Gmail Drafts, never send

Stages 8 and 11 need a free Gemini key:
    https://aistudio.google.com/apikey
    setx GEMINI_API_KEY "your-key"      (then reopen the terminal)

Without a key, stages 1-7, 9, 10, 13 and 14 still run. The pipeline degrades
rather than stopping, which is the point.
"""

import os
import sys
from datetime import datetime

import connect
from store import Store
from pipeline import (stage02_strip, stage03_sensitive, stage04_headers,
                      stage05_forms, stage07_dates, stage09_gate,
                      stage10_redact, stage13_approval,
                      stage16_commitments)

HAS_KEY = bool(os.environ.get("GEMINI_API_KEY"))

# Our own trained classifier, if we have one. Stage 8 uses it in preference to
# anything hosted: free, ~110ms, and the text never leaves this machine.
from pipeline import local_classifier
HAS_OWN_MODEL = local_classifier.available()

if HAS_KEY:
    from pipeline import model

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")


def line(char="─", n=74):
    print(C["dim"] + char * n + C["0"])


def stage(n, name, detail="", flag=""):
    colour = {"exit": C["y"], "stop": C["r"], "ai": C["c"], "": ""}[flag]
    print(f"  {C['dim']}{n:>2}{C['0']} {colour}{name:<22}{C['0']} {detail}")


def sender_history(store, address, me=""):
    """One place, so the gate sees the same history everywhere."""
    return store.history(address, me)


def known_names(store, limit=400):
    rows = store.q("""SELECT DISTINCT sender_name FROM messages
                       WHERE sender_name != '' LIMIT ?""", limit)
    names = set()
    for (full,) in rows:
        for part in full.replace(",", " ").split():
            if len(part) > 2 and part[0].isupper():
                names.add(part)
    return list(names)


def voice(situation: str, domain: str = ""):
    """
    Stage 19 — the user's own writing.

    A profile of how they write, plus the four or five of THEIR OWN past
    replies closest to this situation, found by vector search. Not random
    examples — the ones that actually match.

    `domain` picks a per-group voice if the Owner set one (UC-42, BR-164):
    a different sign-off for clients than for colleagues. An explicit
    setting always beats what was learned (BR-163).

    Run  python learn_voice.py  first to populate it.
    """
    try:
        from pipeline.stage19_voice import StyleStore, describe
        st = StyleStore()
        prof = st.profile(domain)
        if st.count() == 0 and not prof:
            return [], {}, "none yet — run learn_voice.py"
        examples = st.find_similar(situation, k=5) if st.count() else []
        return examples, prof, describe(prof) if prof else "neutral professional voice"
    except Exception as e:
        return [], {}, f"unavailable: {e}"


# ══════════════════════════ the pipeline ══════════════════════════

def run_one(conn, store, env, names, want_draft, audit):
    print()
    line("═")
    print(f"  {C['b']}{(env.subject or '(no subject)')[:66]}{C['0']}")
    print(f"  {C['dim']}from {env.sender_name or env.sender}{C['0']}")
    line()

    # ── 1 ──────────────────────────────────────────────────────────
    stage(1, "CONNECTOR", f"{conn.name} · push={conn.supports_push} "
                          f"labels={conn.supports_labels}")

    # ── 3 ── runs BEFORE anything opens the message ─────────────────
    sens = stage03_sensitive.check(env.sender, env.subject, env.sender_domain)
    if sens["sensitive"]:
        stage(3, "SENSITIVE GATE", C["r"] + "STOP — " + sens["reasons"][0] + C["0"], "stop")
        print(f"\n     {C['y']}→ {sens['notice']}{C['0']}")
        print(f"     {C['dim']}The body was never fetched. Nothing read it.{C['0']}")
        return {"exit": "stage 3 — sensitive"}
    stage(3, "SENSITIVE GATE", "not sensitive · headers only")

    # ── 4 ──────────────────────────────────────────────────────────
    facts = stage04_headers.read(env, env.auth_results)
    hist = sender_history(store, env.sender, conn.account_email())
    bits = []
    bits.append("machine-generated" if facts["machine_generated"] else "human-sent")
    if facts["one_click_unsubscribe"]:
        bits.append("1-click unsub")
    if facts["auto_reply"]:
        bits.append("auto-reply")
    stage(4, "HEADER RULES", " · ".join(bits))

    ex = stage04_headers.engagement_exit(hist["sent"], hist["opened"])
    if ex["exit"]:
        stage(4, "  → engagement", C["y"] + "EXIT — " + ex["reason"] + C["0"], "exit")
        print(f"\n     {C['dim']}Not a category. Measured behaviour: this person, "
              f"this sender.{C['0']}")
        return {"exit": "stage 4 — never engaged"}

    # ── 2 ── now we fetch the body ─────────────────────────────────
    raw = conn.fetch_raw(env.provider_id)
    parsed = stage02_strip.strip(raw)
    stage(2, "PARSE & STRIP",
          f"{parsed['raw_chars']:,} raw → {parsed['stripped_chars']:,} chars "
          f"({C['g']}−{parsed['total_reduction']*100:.0f}%{C['0']}"
          f"{C['dim']}, of which −{parsed['reduction']*100:.0f}% was quoted reply{C['0']})")

    # Show what they actually wrote.
    #
    # Not decoration: this is the exact text stage 8 classifies and stage 11
    # answers. Printing the decision without the message it was made about
    # makes the whole trace unjudgeable — you cannot tell a good reply from a
    # bad one without seeing what it is replying to.
    body_text = parsed["text"].strip()
    if body_text:
        print(f"\n     {C['dim']}what they wrote:{C['0']}")
        for l in body_text[:600].splitlines()[:8]:
            if l.strip():
                print(f"     {C['dim']}▏{C['0']} {l.strip()[:88]}")
        if len(body_text) > 600:
            print(f"     {C['dim']}▏ … {len(body_text) - 600:,} more characters{C['0']}")
        print()

    # ── 5 ──────────────────────────────────────────────────────────
    atts = parsed["attachments"]
    for a in atts:
        a["bytes"] = conn.fetch_attachment(env.provider_id, a.get("name"))
    forms = stage05_forms.extract(atts, "")
    if forms["hit"]:
        what = []
        for m in forms["meetings"]:
            what.append(f"meeting: {m['summary']} at {(m['start'] or '')[:16]}")
        for p in forms["passes"]:
            what.append(f"{p['type']}: {p['description']}")
        for i in forms["invoices"]:
            what.append(f"invoice data in {i['filename']}")
        stage(5, "FORMS & LAYOUTS", C["g"] + "; ".join(what)[:52] + C["0"], "exit")
        print(f"\n     {C['dim']}The sender attached the answer. No model was used.{C['0']}")
    else:
        stage(5, "FORMS & LAYOUTS", f"nothing attached · shape "
                                    f"{forms['fingerprint'] or 'n/a'}")

    # ── 7 ──────────────────────────────────────────────────────────
    cands = stage07_dates.find_candidates(parsed["text"])
    stage(7, "FIND DATES", f"{len(cands)} candidate(s)" +
          (f" · {cands[0]['phrase']!r}" if cands else " · rules, no model"))

    # ── 16 ── a date is a commitment, whether or not it needs a reply ──
    #
    # ⚠️ This runs BEFORE stage 9, deliberately. "Your meeting is tomorrow"
    # needs no reply — and it is exactly the message a person most needs
    # remembered. Reply and remember are different jobs.
    commitment = stage16_commitments.from_email(env, cands, forms, facts)
    if commitment:
        stage16_commitments.record(store, env, commitment)
        stage(16, "COMMITMENT",
              f"{C['g']}{commitment['kind']}{C['0']} due "
              f"{commitment['due']:%a %d %b %H:%M} · remind "
              f"{commitment['remind_at']:%a %d %b %H:%M}")
        print(f"     {C['dim']}{commitment['source']} — "
              f"{commitment['why']}. Reversible, so no approval needed.{C['0']}")

    # ── 8 ── the first model ───────────────────────────────────────
    # OUR OWN model if we have trained one. It needs no key, no network, and
    # nothing leaves this machine. Gemini only if we have not trained yet.
    if HAS_OWN_MODEL or HAS_KEY:
        from pipeline import model as model_layer
        labels = model_layer.classify(parsed["text"], env.subject, env.sender)
        ours = labels.get("by") == "our model"
        who = (C["g"] + "OUR MODEL, on this laptop" + C["0"]) if ours else \
              (C["y"] + "Gemini" + C["0"])
        stage(8, "READ IT",
              f"{C['c']}{labels['intent']}{C['0']} × {labels['topic']} "
              f"({labels['confidence']:.2f}) · {who}", "ai")
    else:
        labels = {"intent": "just telling me", "topic": "other", "confidence": 0.0}
        stage(8, "READ IT", C["dim"] + "no model and no key" + C["0"])

    # ── 6 ── the router actually reports what it did ────────────────
    if labels.get("escalated_from") is not None:
        stage(6, "ROUTER", f"{C['y']}ESCALATED{C['0']} — our model was unsure "
                           f"({labels['escalated_from']:.2f} < 0.65), asked a bigger one",
              "ai")
    elif labels.get("note"):
        stage(6, "ROUTER", C["dim"] + labels["note"] + C["0"])
    else:
        stage(6, "ROUTER", f"kept our model's answer "
                           f"({labels.get('confidence', 0):.2f} ≥ 0.65) — no escalation")

    # ── 9 ── uses stage 8's MEANING, never re-reads the text ───────
    sc = stage09_gate.score(labels, facts, hist, env)
    # UC-44 / UC-38 — an explicit rule always beats the model (BR-145).
    # Checked after scoring so the score is still recorded honestly; the
    # verdict is what the rule says.
    if store.is_protected(env.sender, env.sender_domain):
        sc["needs_reply"] = True
        sc["why"] = "you marked this person important, " + sc["why"]
    # ⚠️ BR-105 — the reason is written now, in the same breath as the
    # decision. Reconstructed later it would be a guess wearing a record's
    # clothes, and "why did it do that" would have no honest answer.
    store.record_decision(env.message_id, "9",
                          "needs a reply" if sc["needs_reply"] else "no reply needed",
                          sc["why"], sc["act_probability"])
    stage(9, "NEEDS A REPLY?",
          f"{sc['act_probability']:.2f} — {C['g'] if sc['needs_reply'] else C['y']}"
          f"{'yes' if sc['needs_reply'] else 'no'}{C['0']}")
    print(f"     {C['dim']}why: {sc['why']}{C['0']}")
    if sc["first_contact"]:
        print(f"     {C['dim']}first contact — no history, but the other "
              f"signals still work{C['0']}")

    if not sc["needs_reply"]:
        print(f"\n     {C['y']}→ filed. Appears in the daily brief. "
              f"No paid model was called.{C['0']}")
        return {"exit": "stage 9 — no reply needed", "labels": labels}

    if not want_draft:
        print(f"\n     {C['dim']}→ would draft a reply. Run with --draft.{C['0']}")
        return {"exit": "stage 9 — draft not requested", "labels": labels}

    # ⚠️ Already answered? Then stop here.
    #
    # Without this, running the script twice offers to reply to the same mail
    # again — and a second yes puts a duplicate in someone else's inbox. The
    # approval gate cannot catch that: the user really did approve, twice, and
    # both times meant it. Only a record of what was already done can.
    when = store.already_replied(env.message_id)
    if when:
        print(f"\n     {C['y']}→ already replied to this on {when[:16]}. "
              f"Not asking again.{C['0']}")
        return {"exit": "already answered", "labels": labels}

    # ── 10 ── THE ONLY DOOR OUT ────────────────────────────────────
    redacted, mapping = stage10_redact.redact(
        stage10_redact.minimise(parsed["text"]), names)
    sender_tok, _ = stage10_redact.redact(env.sender_name or env.sender, names)
    stage(10, "HIDE NAMES", f"{len(mapping)} identifier(s) replaced — "
                            f"{C['b']}the only door out{C['0']}", "ai")

    # ── 11 ─────────────────────────────────────────────────────────
    if not HAS_KEY:
        stage(11, "WRITE IT", C["dim"] + "skipped — no key" + C["0"])
        return {"exit": "stage 11 — no key"}

    deadline = model.pick_deadline(cands, env.subject) if cands else None
    if deadline:
        when = stage07_dates.reminder_time(
            datetime.fromisoformat(deadline["resolved"]),
            deadline.get("kind", "default"))
        print(f"     {C['dim']}deadline picked by the model: "
              f"{deadline['phrase']!r} → remind {when:%d %b %H:%M} "
              f"(computed in code){C['0']}")

    # ── 19 ── the user's own voice ─────────────────────────────────
    examples, profile, summary = voice(parsed["text"][:400], env.sender_domain)
    stage(19, "YOUR VOICE",
          f"{len(examples)} matching past replies · {summary[:42]}")

    draft = model.draft_reply(redacted, env.subject, sender_tok,
                              examples, profile)
    stage(11, "WRITE IT", f"{len(draft)} chars · {C['y']}the only paid step{C['0']}", "ai")

    # ── 12 ─────────────────────────────────────────────────────────
    final, leftover = stage10_redact.restore(draft, mapping)
    if leftover:
        stage(12, "NAMES BACK", C["r"] + f"unresolved {leftover} — draft discarded" + C["0"])
        return {"exit": "stage 12 — unresolved placeholder"}
    stage(12, "NAMES BACK", "restored locally, before anyone sees it")

    print()
    line("┄")
    for l in final.splitlines():
        print(f"  {C['c']}│{C['0']} {l}")
    line("┄")

    # ── UC-25 · BR-95 — write it into Drafts instead of sending ─────
    #
    # ⚠️ SAFER THAN ASKING. A draft in the Owner's own Drafts folder cannot
    # leave without them pressing send in their own mail app — so the approval
    # stops being a promise our code makes and becomes a fact about where the
    # message lives. There is no code path of ours that can dispatch it.
    if "--drafts" in sys.argv:
        r = stage13_approval.execute(
            conn, "draft", env.provider_id, final, None, audit,
            to=env.sender,
            subject=(env.subject if env.subject.lower().startswith("re:")
                     else f"Re: {env.subject}"),
            in_reply_to=env.message_id, references=env.references or env.message_id,
            thread_id=env.thread_id)
        stage(13, "TO DRAFTS", f"{C['g']}written to your Drafts folder{C['0']} — "
                               f"no approval needed, it cannot send itself", "ai")
        if r["done"]:
            store.record_action(env.message_id, env.provider_id, "draft",
                                r.get("draft_id", ""), before="no draft")
            print(f"     {C['dim']}Open Gmail → Drafts. It is threaded into the "
                  f"conversation.{C['0']}")
        return {"exit": "completed — draft written", "labels": labels, "draft": final}

    # ── 13 ─────────────────────────────────────────────────────────
    ap = stage13_approval.Approval("send", final)
    stage(13, "ASK YOU", "waiting for an explicit yes")

    print(f"\n  {C['dim']}Type: yes / no / anything else{C['0']}")
    try:
        answer = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = "no"

    ok, why = ap.grant(answer)
    print(f"     {C['g'] if ok else C['y']}{why}{C['0']}")

    # ── 14 ─────────────────────────────────────────────────────────
    # ⚠️ The reply needs to know WHO it goes to and WHAT it answers.
    # Without in_reply_to it arrives as a brand new conversation, which is the
    # most visible way an assistant looks broken.
    result = stage13_approval.execute(
        conn, "send", env.provider_id, final, ap if ok else None, audit,
        to=env.sender, subject=(env.subject if env.subject.lower().startswith("re:")
                                else f"Re: {env.subject}"),
        in_reply_to=env.message_id, references=env.references or env.message_id,
        thread_id=env.thread_id)
    stage(14, "DO IT", f"{'done' if result['done'] else 'blocked'} — {result['reason']}")
    if result["done"]:
        store.mark_replied(env.message_id, result.get("sent_id", ""))
    return {"exit": "completed", "labels": labels, "draft": final}


# ══════════════════════════ main ══════════════════════════

def main():
    n = 5
    want_draft = "--draft" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)

    print(f"\n{C['b']}Custodian — full pipeline{C['0']}")
    line("═")

    conn = connect.open_mailbox()
    store = Store()
    print(f"  {conn.account_email()} · {conn.message_count():,} messages")
    own = (C["g"] + "OUR OWN trained model, on this CPU" + C["0"]) if HAS_OWN_MODEL \
        else (C["y"] + "not trained yet — falling back to Gemini" + C["0"])
    key = (C["g"] + "Gemini" + C["0"]) if HAS_KEY else (C["y"] + "no key" + C["0"])
    print(f"  stage 8  · reads the email  : {own}")
    print(f"  stage 11 · writes the reply : {key}")
    if store.have():
        print(f"  {len(store.have()):,} envelopes already scanned (run.py)")

    ids = conn.list_ids()[:n]
    envs = list(conn.fetch_envelopes(ids))
    store.save(envs)

    names = known_names(store)
    audit = []
    tally = {}

    for env in envs:
        r = run_one(conn, store, env, names, want_draft, audit)
        tally[r["exit"]] = tally.get(r["exit"], 0) + 1

    print()
    line("═")
    print(f"  {C['b']}Where {len(envs)} messages left the pipeline{C['0']}\n")
    for where, count in sorted(tally.items(), key=lambda x: -x[1]):
        print(f"    {count:>3}  {where}")
    print(f"\n  {len(audit)} action(s) logged, each with how to reverse it.")
    print()


if __name__ == "__main__":
    main()
