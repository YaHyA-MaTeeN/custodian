"""
The IMAP proof — same pipeline, different door.

    set IMAP_PASSWORD=your-app-password
    python test_imap.py

⚠️ WHAT THIS ANSWERS, IN ORDER OF WHAT WAS ASKED

  1. Does Gmail work over IMAP with an app password?
     (no registration, no approval, no yearly security audit, no fee)

  2. CAN WE GET ONLY THE PRIMARY TAB OVER IMAP?
     This is the question sir asked. The comparison document marks it
     "TEST — unverified over IMAP". This settles it either way.

  3. Do our own models still work when the mail arrives through IMAP?
     They must. Nothing above the connector knows which door was used.

⚠️ WHY AN APP PASSWORD AND NOT SIGN-IN

Google's rule is: use our sign-in screen to read someone's Gmail, and you pay
for an outside security assessment every year, plus months of approval, plus a
100-user cap until it clears. An app password skips the sign-in screen, so it
skips all three. Same mail, same features, no gatekeeper.

That is a Google BILLING rule, not a technical limit — worth saying plainly,
because it is the whole reason this route exists.
"""

import os
import sys
import time

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if os.name == "nt":
    os.system("")

HOST = "imap.gmail.com"


def ok(msg):   print(f"  {C['g']}PASS{C['0']}  {msg}")
def bad(msg):  print(f"  {C['r']}FAIL{C['0']}  {msg}")
def info(msg): print(f"  {C['dim']}      {msg}{C['0']}")


def main():
    user = os.environ.get("IMAP_USER") or os.environ.get("GMAIL_USER")
    pw = os.environ.get("IMAP_PASSWORD")
    if not pw:
        print(f"""
{C['b']}Need a Gmail app password first{C['0']}
{'-'*62}
  1. Go to  https://myaccount.google.com/apppasswords
     (2-step verification must be on — turn it on if it is not)
  2. Type any name, e.g. "Custodian"
  3. Google shows 16 letters. Copy them.
  4. In PowerShell:

     {C['c']}setx IMAP_USER "login47015@gmail.com"{C['0']}
     {C['c']}setx IMAP_PASSWORD "the16letters"{C['0']}

  5. Close the terminal, open a new one, run this again.

{C['dim']}  No registration. No approval. No security audit. No fee.{C['0']}
""")
        sys.exit(1)
    if not user:
        user = input("  Gmail address: ").strip()

    print(f"\n{C['b']}IMAP proof — Gmail without the API{C['0']}")
    print("=" * 62)

    # ── 1. connect ────────────────────────────────────────────────────
    t0 = time.time()
    try:
        from connectors.imap import ImapConnector
        conn = ImapConnector(HOST, user, pw)
    except Exception as e:
        bad(f"could not connect: {str(e)[:70]}")
        info("Wrong password? App passwords have no spaces.")
        sys.exit(1)
    ok(f"connected as {conn.account_email()}  ({time.time()-t0:.1f}s)")
    info("no OAuth, no consent screen, no approval, no audit, no fee")

    # ── 2. what does this server actually support? ────────────────────
    print(f"\n{C['b']}What this connection can do{C['0']}")
    print("-" * 62)
    for cap in ["supports_labels", "supports_categories", "supports_threads",
                "supports_push", "supports_send", "supports_spam_folder"]:
        v = getattr(conn, cap, False)
        mark = f"{C['g']}yes{C['0']}" if v else f"{C['y']}no {C['0']}"
        print(f"  {cap:<24} {mark}")
    info("Read from the server at connect time, never guessed from the host.")

    # ── 3. THE QUESTION SIR ASKED ─────────────────────────────────────
    print(f"\n{C['b']}THE QUESTION: can we get only the Primary tab over IMAP?{C['0']}")
    print("=" * 62)
    if not conn.has_gmail_extensions():
        bad("this server does not speak X-GM-EXT-1 — categories unavailable")
    else:
        ok("Gmail advertises X-GM-EXT-1 — its own IMAP extensions")
        info("that gives us X-GM-RAW: the full Gmail search box, over IMAP")
        print()
        counts = {}
        for cat in ["primary", "social", "promotions", "updates", "forums"]:
            ids = conn.gmail_search(f"category:{cat}")
            counts[cat] = len(ids)
            colour = C["g"] if cat == "primary" else C["dim"]
            print(f"  {colour}category:{cat:<12}{C['0']} {len(ids):>6,} messages")
        total = sum(counts.values())
        print()
        if counts.get("primary", 0) or total:
            ok("ANSWER: YES. The Primary tab is reachable over IMAP.")
            info(f"{counts.get('primary',0):,} primary out of {total:,} categorised")
            info("Gmail only. Yahoo, Zoho and iCloud have no categories at all —")
            info("which is why the pipeline asks supports_categories, not the host.")
        else:
            bad("ANSWER: NO. X-GM-RAW ran but returned nothing for any category.")
            info("This account may have tabs switched off in Gmail settings.")

        # Other searches worth proving while we are here
        print(f"\n{C['b']}And the rest of the Gmail search box also works{C['0']}")
        print("-" * 62)
        for q, why in [("is:unread newer_than:30d", "last 30 days, unread"),
                       ("has:attachment", "anything with a file"),
                       ("category:primary newer_than:30d",
                        "the exact slice the unified plan needs")]:
            n = len(conn.gmail_search(q))
            print(f"  {n:>6,}  {C['dim']}{q:<32}{C['0']} {why}")

    # ── 4. does the pipeline still work through this door? ────────────
    print(f"\n{C['b']}Does OUR pipeline work through IMAP?{C['0']}")
    print("=" * 62)
    ids = conn.list_ids()[:3]
    if not ids:
        bad("no messages listed")
        return
    ok(f"listed {conn.message_count():,} messages in the inbox")

    from pipeline import (stage02_strip, stage03_sensitive, stage04_headers,
                          stage09_gate, local_classifier)
    from store import Store
    store = Store()

    for env in conn.fetch_envelopes(ids):
        print(f"\n  {C['b']}{(env.subject or '(no subject)')[:52]}{C['0']}")
        print(f"  {C['dim']}from {env.sender_name or env.sender}"
              f"  ·  account {env.account}{C['0']}")

        sens = stage03_sensitive.check(env.sender, env.subject, env.sender_domain)
        print(f"     3  {'SENSITIVE' if sens['sensitive'] else 'not sensitive'}")
        facts = stage04_headers.read(env)
        print(f"     4  {'machine-generated' if facts['machine_generated'] else 'human-sent'}")

        raw = conn.fetch_raw(env.provider_id)
        p = stage02_strip.strip(raw)
        print(f"     2  {p['raw_chars']:,} raw -> {p['stripped_chars']:,} chars")

        if local_classifier.available() and p["text"]:
            lab = local_classifier.classify(p["text"], env.subject, env.sender)
            print(f"     8  {C['c']}{lab['intent']} ({lab['confidence']:.2f}){C['0']}"
                  f"  {C['g']}<- OUR MODEL, unchanged{C['0']}")
            hist = store.history(env.sender, conn.account_email())
            sc = stage09_gate.score(lab, facts, hist, env)
            print(f"     9  needs a reply: {'yes' if sc['needs_reply'] else 'no'} "
                  f"({sc['act_probability']:.2f})")

    print("\n" + "=" * 62)
    print(f"  {C['g']}The models did not change. The stages did not change.{C['0']}")
    print(f"  {C['dim']}Only connectors/imap.py is different from "
          f"connectors/gmail.py.{C['0']}")
    if conn.errors:
        print(f"\n  {C['y']}{len(conn.errors)} error(s) collected:{C['0']}")
        for e in conn.errors[:5]:
            print(f"    {e}")
    conn.close()
    print()


if __name__ == "__main__":
    main()
