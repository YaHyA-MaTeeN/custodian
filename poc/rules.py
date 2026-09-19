"""
UC-38 — A rule, typed in plain English. Read once, confirmed, then no AI.

    python rules.py                                  # your rules
    python rules.py "never touch mail from ahmed@acc.com"
    python rules.py "label everything from @supplier.com as Invoices"
    python rules.py "clear everything from promo@shop.com"   # becomes an approval item
    python rules.py --apply 3                        # also apply rule 3 to existing mail (asks)
    python rules.py --delete 3

⚠️ TWO THINGS THIS MUST NEVER DO.

Never save without showing the interpretation back (BR-141). A sentence read
wrong and stored silently mishandles mail for weeks, and the customer blames
the product. So: what we understood, in plain words, plus how many existing
messages it would match — and only a typed yes saves it.

Never let a typed rule unlock a forbidden action (BR-142). "Send" and
"delete" are not on the list the model chooses from, and no wording puts them
there. "Clear everything from X" becomes an APPROVAL ITEM — "14 ready to
clear — review" — and nothing moves until the Owner clicks in pile.py.
"Forward invoices to finance" becomes drafts prepared by forward_batch.py.

⚠️ THE AI READS THE SENTENCE ONCE (BR-143). Matching afterwards is
store.rules_for(): a string comparison, no model, about a penny and a half
for the customer's whole lifetime. Existing rules keep working with the
model switched off.

⚠️ AN UNCLEAR SENTENCE IS REFUSED, NOT GUESSED (BR-144). The part that could
not be read is named and asked for.
"""

import os
import sys

from store import Store

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

# The whole vocabulary the model may choose from. Nothing here sends or
# deletes. The two that touch mail in bulk produce approval items, not actions.
ALLOWED = ["protect", "top", "label", "clear_approval", "forward_drafts", "never_reply"]

PLAIN = {
    "protect":        "never put mail from {m} in the pile, never unsubscribe from it, never sweep it",
    "top":            "always rank mail from {m} at the top",
    "label":          "label mail from {m} as “{a}”",
    "clear_approval": "gather mail from {m} for clearing — you review and click; nothing moves on its own",
    "forward_drafts": "prepare forwards of mail from {m} to {a} as DRAFTS — you send them from your mail app",
    "never_reply":    "never suggest a reply to mail from {m}",
}


def interpret(sentence: str) -> dict:
    """One model call, at creation. Returns the fields, or {'unclear': ...}."""
    from pipeline import model, prompts
    prompt = prompts.get("read_rule", sentence=sentence, allowed_actions=", ".join(ALLOWED))
    try:
        out = model._json_from(model._generate(prompt))
    except Exception as e:
        return {"unclear": f"the rule box is temporarily unavailable ({str(e)[:40]})"}
    action = str(out.get("action", "")).lower()
    # ⚠️ BR-142 in code: anything outside the list, and anything that smells
    # of send / delete, is mapped to its allowed form or refused.
    if action in ("send", "reply", "auto_reply"):
        return {"unclear": "we never send. Did you mean a draft, or a label?"}
    if action in ("delete", "trash", "clear", "remove"):
        action = "clear_approval"
    if action in ("forward",):
        action = "forward_drafts"
    if action not in ALLOWED:
        return {"unclear": out.get("unclear") or f"what to do (we can: {', '.join(ALLOWED)})"}
    kind = str(out.get("match_kind", "")).lower()
    value = str(out.get("match_value", "")).lower().strip().lstrip("@")
    if kind not in ("sender", "domain", "subject", "person") or not value:
        return {"unclear": out.get("unclear") or "what it should match — an address, a domain, or words in the subject"}
    return {"match_kind": kind, "match_value": value, "action": action,
            "action_arg": str(out.get("action_arg", "")).strip(),
            "plain": PLAIN[action].format(m=value, a=out.get("action_arg", "") or "…")}


def count_matches(store, kind, value) -> int:
    v = value.lower()
    if kind in ("sender", "person"):
        return store.one("SELECT COUNT(*) FROM messages WHERE sender=?", v)
    if kind == "domain":
        return store.one("SELECT COUNT(*) FROM messages WHERE sender_domain=? OR sender_domain LIKE ?",
                         v, f"%.{v}")
    return store.one("SELECT COUNT(*) FROM messages WHERE LOWER(subject) LIKE ?", f"%{v}%")


def create(store, sentence: str):
    print(f"\n{C['b']}“{sentence}”{C['0']}")
    print("─" * 70)
    r = interpret(sentence)
    if "unclear" in r:
        print(f"  {C['y']}We could not read part of that: {r['unclear']}{C['0']}")
        print(f"  {C['dim']}Rewrite the sentence and try again. Nothing was saved.{C['0']}\n")
        return
    n = count_matches(store, r["match_kind"], r["match_value"])
    print(f"  We understood: {C['c']}{r['plain']}{C['0']}")
    print(f"  This would have matched {C['b']}{n:,}{C['0']} of your messages so far.")
    if n > 2000:
        print(f"  {C['y']}That is very broad. Is that what you meant?{C['0']}")
    if r["action"] == "clear_approval":
        print(f"  {C['dim']}Note: we never clear on our own. This gathers them; you click in pile.py.{C['0']}")
    if r["action"] == "forward_drafts":
        print(f"  {C['dim']}Note: we never send. forward_batch.py prepares drafts you send yourself.{C['0']}")
    # Conflict check (BR-145): show, do not silently override.
    existing = [x for x in store.rules() if x[2] == r["match_kind"] and x[3] == r["match_value"]]
    for x in existing:
        print(f"  {C['y']}A rule already exists for this: “{x[1]}” → {x[6]}{C['0']}")
    try:
        typed = input("  Correct? type yes: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    if typed != "yes":
        print("  nothing saved.\n"); return
    rid = store.add_rule(sentence, r["match_kind"], r["match_value"], r["action"],
                         r["action_arg"], r["plain"])
    store.record_action("", "", "correction", f"rule {rid}: {r['plain'][:60]}")
    print(f"\n  {C['g']}saved as rule {rid}.{C['0']} It applies to mail arriving from now on.")
    if n and r["action"] == "label":
        print(f"  {C['dim']}python rules.py --apply {rid}   applies it to the {n:,} already there.{C['0']}")
    print()


def show(store):
    print(f"\n{C['b']}Your rules{C['0']}")
    print("─" * 70)
    rows = store.rules()
    if not rows:
        print("  none yet.  python rules.py \"never touch mail from x@y.com\"\n"); return
    for rid, sentence, kind, value, action, arg, plain, gid, at in rows:
        src = f"{C['dim']}(marked important){C['0']}" if gid else f"{C['dim']}“{sentence[:44]}”{C['0']}"
        print(f"  {rid:>3}. {plain[:64]:64} {src}")
    print(f"\n  {C['dim']}--delete N · --apply N{C['0']}\n")


def apply_existing(store, rid: int):
    """BR-146: existing mail is a separate, explicit action with its own count."""
    r = next((x for x in store.rules() if x[0] == rid), None)
    if not r:
        print("\n  no such rule.\n"); return
    _, sentence, kind, value, action, arg, plain, gid, at = r
    if action != "label":
        print(f"\n  Only label rules can be applied backwards here. "
              f"Clearing goes through pile.py, forwards through forward_batch.py.\n"); return
    import connect
    conn = connect.open_mailbox(quiet=True)
    if kind in ("sender", "person"):
        rows = store.q("SELECT provider_id, message_id, subject FROM messages WHERE sender=? AND in_inbox=1", value)
    elif kind == "domain":
        rows = store.q("SELECT provider_id, message_id, subject FROM messages WHERE (sender_domain=? OR sender_domain LIKE ?) AND in_inbox=1", value, f"%.{value}")
    else:
        rows = store.q("SELECT provider_id, message_id, subject FROM messages WHERE LOWER(subject) LIKE ? AND in_inbox=1", f"%{value}%")
    print(f"\n  {len(rows):,} existing message(s) would be labelled “{arg}”.")
    try:
        typed = input("  Apply to those too? type yes: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    if typed != "yes":
        print("  nothing changed.\n"); return
    handle = conn.ensure_label(arg)
    done = 0
    for pid, mid, subject in rows:
        try:
            live = connect.live_id(conn, pid, mid) or pid
            conn.apply_label(live, handle)
            store.record_action(mid, pid, "label", arg, before=handle); done += 1
        except Exception:
            pass
    print(f"\n  {C['g']}{done} labelled.{C['0']}  python history.py --undo reverses any.\n")


def main():
    store = Store()
    args = sys.argv[1:]
    if "--delete" in args:
        store.remove_rule(int(args[args.index("--delete") + 1]))
        print("\n  removed.\n"); return
    if "--apply" in args:
        return apply_existing(store, int(args[args.index("--apply") + 1]))
    sentence = " ".join(a for a in args if not a.startswith("--")).strip()
    if sentence:
        return create(store, sentence)
    show(store)


if __name__ == "__main__":
    main()
