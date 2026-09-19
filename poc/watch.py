"""
Custodian, live. Leave this running and it reacts to mail as it arrives.

    python watch.py                 # watch, decide, label
    python watch.py --draft         # also draft a reply and ask before sending
    python watch.py --quiet         # decide and label, one line per message
    python watch.py --every 5       # poll every 5 seconds (default 15)

Ctrl+C stops it. Everything it did is in applied_labels.json, and
    python sort_mailbox.py --undo
removes every label it applied — including the ones added while watching.

⚠️ POLLING, NOT PUSH — AND THAT IS THE RIGHT CHOICE ON A LAPTOP.

Gmail can push, and the connector says so (supports_push = True). But a push
needs a public HTTPS endpoint for Google to call, plus a Pub/Sub topic. A
laptop behind a home router has neither.

So we poll history.list, which is NOT a re-scan: we ask Gmail "what changed
since bookmark X" and it answers with just the changes. One quota unit per
poll against roughly 1,500 for a full re-list of this mailbox. At 15 seconds
that is about 5,760 units a day out of a 1,000,000,000 daily allowance.

The pipeline above it does not know or care which trigger woke it. Moving to
real push later changes this one file and nothing else — which is the whole
point of the connector boundary.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import connect
from store import Store
from pipeline import (stage02_strip, stage03_sensitive, stage04_headers,
                      stage09_gate, stage10_redact, stage13_approval)
from sort_mailbox import LABELS, ensure_labels, decide

AUDIT = Path("applied_labels.json")

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")


def arg_int(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            return int(sys.argv[i + 1])
    return default


def load_audit() -> list:
    """⚠️ Append to what sort_mailbox wrote, never replace it — otherwise
    --undo would forget the labels applied before the watcher started."""
    if AUDIT.exists():
        try:
            return json.loads(AUDIT.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def handle(conn, store, env, label_ids, applied, want_draft, quiet, names):
    """One newly arrived message, through the same stages as everything else."""
    when = datetime.now().strftime("%H:%M:%S")
    who = env.sender_name or env.sender
    print(f"\n{C['b']}  {when}  {(env.subject or '(no subject)')[:58]}{C['0']}")
    print(f"  {C['dim']}         from {who}{C['0']}")

    # ── 3 ── before anything opens it ─────────────────────────────────
    sens = stage03_sensitive.check(env.sender, env.subject, env.sender_domain)
    if sens["sensitive"]:
        print(f"  {C['r']}         3 SENSITIVE — {sens['reasons'][0]}{C['0']}")
        print(f"  {C['dim']}         body never fetched{C['0']}")
        key = "private"
    else:
        facts = stage04_headers.read(env)
        hist = store.history(env.sender, conn.account_email())

        labels = None
        if not facts["machine_generated"]:
            try:
                from pipeline import local_classifier
                if local_classifier.available():
                    text = stage02_strip.strip(conn.fetch_raw(env.provider_id))["text"]
                    labels = local_classifier.classify(text, env.subject, env.sender)
            except Exception:
                pass

        if not quiet:
            kind = "machine-generated" if facts["machine_generated"] else "human-sent"
            print(f"  {C['dim']}         4 {kind}{C['0']}")
            # What they actually wrote — the text every decision below is about.
            if not facts["machine_generated"]:
                try:
                    said = stage02_strip.strip(conn.fetch_raw(env.provider_id))["text"]
                    for l in said.strip()[:300].splitlines()[:4]:
                        if l.strip():
                            print(f"  {C['dim']}           ▏ {l.strip()[:80]}{C['0']}")
                except Exception:
                    pass
            if labels:
                print(f"  {C['c']}         8 {labels['intent']} "
                      f"({labels['confidence']:.2f}) · our model{C['0']}")
            sc = stage09_gate.score(labels or {"intent": "no response needed",
                                               "topic": "other", "confidence": 0.0},
                                    facts, hist, env)
            print(f"  {C['dim']}         9 needs a reply: "
                  f"{'yes' if sc['needs_reply'] else 'no'} ({sc['act_probability']:.2f}) "
                  f"— {sc['why']}{C['0']}")
            # ⚠️ WRITE IT DOWN. This line was missing, and its absence was
            # invisible from the terminal — the watcher printed a verdict,
            # looked completely correct, and recorded nothing. Every message
            # it had ever processed still read "not run through the pipeline
            # yet" everywhere else in the system. A decision that is not
            # written down did not happen.
            store.record_decision(env.message_id, "9",
                                  "needs a reply" if sc["needs_reply"]
                                  else "no reply needed",
                                  sc["why"], sc["act_probability"])

        key = decide(env, facts, hist, labels, store)

    # ── label it — reversible, so no approval needed ──────────────────
    if key:
        try:
            conn.apply_label(env.provider_id, label_ids[key])
            store.record_action(env.message_id, env.provider_id, "label",
                                LABELS[key], before=label_ids[key])
            applied.append({"id": env.provider_id,
                            # which door applied it — the file serves both,
                            # and their ids mean different things
                            "door": getattr(conn, "name", ""),
                            "label_id": label_ids[key],
                            "label": LABELS[key], "subject": (env.subject or "")[:70],
                            "at": datetime.now().isoformat()})
            AUDIT.write_text(json.dumps(applied, indent=2), encoding="utf-8")
            print(f"  {C['g']}         → {LABELS[key]}{C['0']}")
        except Exception as e:
            print(f"  {C['y']}         could not label: {str(e)[:50]}{C['0']}")
    else:
        print(f"  {C['dim']}         → no label — left exactly as it is{C['0']}")

    # ── 10-14 ── only on request, and only ever with your yes ─────────
    if want_draft and key == "reply":
        draft_and_ask(conn, store, env, names, applied)


def draft_and_ask(conn, store, env, names, applied):
    """The full path. Stops dead at stage 13 every time."""
    # Already answered — say so and stop. A watcher restarted twice in a day
    # must not offer the same reply twice.
    when = store.already_replied(env.message_id)
    if when:
        print(f"  {C['y']}         already replied on {when[:16]} — not asking again{C['0']}")
        return
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"  {C['dim']}         11 no key — cannot draft{C['0']}")
        return
    try:
        text = stage02_strip.strip(conn.fetch_raw(env.provider_id))["text"]
        redacted, mapping = stage10_redact.redact(
            stage10_redact.minimise(text), names)
        sender_tok, _ = stage10_redact.redact(env.sender_name or env.sender, names)
        print(f"  {C['dim']}         10 {len(mapping)} identifier(s) hidden "
              f"— the only door out{C['0']}")

        from pipeline import model
        from pipeline.stage19_voice import StyleStore, describe
        st = StyleStore()
        examples = st.find_similar(text[:400], k=5) if st.count() else []
        profile = st.profile() if st.count() else {}

        draft = model.draft_reply(redacted, env.subject, sender_tok,
                                  examples, profile)
        final, leftover = stage10_redact.restore(draft, mapping)
        if leftover:
            print(f"  {C['r']}         12 unresolved {leftover} — draft discarded{C['0']}")
            return

        print()
        for l in final.splitlines():
            print(f"  {C['c']}│{C['0']} {l}")

        ap = stage13_approval.Approval("send", final)
        print(f"\n  {C['y']}  13 send this reply? yes sends it. "
              f"Anything else does not.{C['0']}")
        try:
            answer = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = "no"
        ok, why = ap.grant(answer)
        print(f"     {C['g'] if ok else C['y']}{why}{C['0']}")

        r = stage13_approval.execute(
            conn, "send", env.provider_id, final, ap if ok else None, applied,
            to=env.sender, subject=f"Re: {env.subject}",
            in_reply_to=env.message_id, references=env.message_id,
            thread_id=getattr(env, "thread_id", ""))
        print(f"  {C['dim']}         14 "
              f"{'SENT' if r['done'] else 'not sent'} — {r['reason']}{C['0']}")
        if r["done"]:
            store.mark_replied(env.message_id, r.get("sent_id", ""))
    except Exception as e:
        print(f"  {C['y']}         drafting failed: {str(e)[:60]}{C['0']}")


def main():
    want_draft = "--draft" in sys.argv
    quiet = "--quiet" in sys.argv
    every = arg_int("--every", 15)

    print(f"\n{C['b']}Custodian — live{C['0']}")
    print("─" * 62)

    conn = connect.open_mailbox()
    store = Store()
    print(f"  {conn.account_email()}")

    from pipeline import local_classifier
    print(f"  classifier : {C['g']+'our own model' if local_classifier.available() else C['y']+'not trained'}{C['0']}")
    print(f"  drafting   : {(C['g']+'on — will ask before sending') if want_draft else (C['dim']+'off (--draft to enable)')}{C['0']}")
    print(f"  polling    : every {every}s via history.list")

    label_ids = ensure_labels(conn)
    applied = load_audit()
    names = [n for (n,) in store.q(
        "SELECT DISTINCT sender_name FROM messages WHERE sender_name != '' LIMIT 400")]
    names = [p for full in names for p in full.replace(",", " ").split()
             if len(p) > 2 and p[0].isupper()]

    bookmark = conn.current_history_id()
    print(f"\n  {C['g']}watching from now. Send yourself a mail to see it work.{C['0']}")
    print(f"  {C['dim']}Ctrl+C to stop. Nothing is sent without your typed yes.{C['0']}")
    print("─" * 62)

    seen, ticks = set(), 0
    try:
        while True:
            time.sleep(every)
            ticks += 1
            try:
                ids, bookmark = conn.new_since(bookmark)
            except Exception as e:
                print(f"  {C['y']}poll failed: {str(e)[:60]} — retrying{C['0']}")
                continue

            fresh = [i for i in ids if i not in seen]
            if not fresh:
                # A quiet heartbeat, so an idle watcher never looks frozen.
                print(f"  {C['dim']}{datetime.now():%H:%M:%S}  nothing new{C['0']}",
                      end="\r" if ticks % 4 else "\n")
                continue

            seen.update(fresh)
            for env in conn.fetch_envelopes(fresh):
                store.save([env])
                handle(conn, store, env, label_ids, applied,
                       want_draft, quiet, names)

    except KeyboardInterrupt:
        print(f"\n\n  stopped. {len(applied)} label(s) recorded in {AUDIT}")
        print(f"  {C['dim']}python sort_mailbox.py --undo   removes them all.{C['0']}\n")


if __name__ == "__main__":
    main()
