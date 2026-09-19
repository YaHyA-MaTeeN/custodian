"""
Learn how this person writes, from their Sent folder.

    python learn_voice.py

Reads their own outgoing mail — never the inbox — builds a profile of how they
write, and stores each reply as a vector so we can later find the ones closest
to whatever situation comes up.

⚠️ This is the ONLY place we hold the user's email text, and it is only ever
their own outgoing writing.
"""

import sys

from connectors.gmail import GmailConnector
from pipeline import stage02_strip
from pipeline.stage19_voice import StyleStore, describe

HOW_MANY = 200          # a couple of hundred is plenty


def main():
    print("\nLearning your writing voice")
    print("─" * 52)

    conn = GmailConnector()
    me = conn.account_email()
    print(f"  {me}")

    # Sent folder only. The inbox is not touched.
    print(f"\n  reading your last {HOW_MANY} sent messages…")
    try:
        r = conn.svc.users().messages().list(
            userId="me", labelIds=["SENT"], maxResults=HOW_MANY).execute()
        ids = [m["id"] for m in r.get("messages", [])]
    except Exception as e:
        print(f"  could not read the Sent folder: {e}\n")
        sys.exit(1)

    if not ids:
        print("\n  ⚠️  No sent mail in this account.")
        print("     Voice learning needs messages you have written yourself.")
        print("     Everything else in the pipeline still works — the drafting")
        print("     step will just have no examples to imitate.\n")
        sys.exit(0)

    sent = []
    for i, mid in enumerate(ids, 1):
        try:
            parsed = stage02_strip.strip(conn.fetch_raw(mid))
            if len(parsed["text"]) > 40:
                sent.append({"text": parsed["text"], "subject": ""})
        except Exception:
            pass
        print(f"\r  {i}/{len(ids)}", end="", flush=True)
    print(f"\r  {len(sent)} usable replies from {len(ids)} sent messages")

    if len(sent) < 3:
        print("\n  ⚠️  Too few to learn a style from. Needs a handful at least.\n")
        sys.exit(0)

    store = StyleStore()
    profile = store.learn(sent)

    print("\n" + "─" * 52)
    print("  What we learned about how you write:\n")
    for k, v in profile.items():
        print(f"    {k:<18} {v}")

    print(f"\n  in one line:  {describe(profile)}")
    print(f"\n  {store.count()} replies stored as vectors, for matching later.")

    # Show the matching actually working.
    demo = "Can you send me the report by Friday please?"
    close = store.find_similar(demo, k=3)
    if close:
        print(f"\n  Test — for a situation like:")
        print(f'    "{demo}"')
        print(f"\n  the closest things you have written before:\n")
        for i, t in enumerate(close, 1):
            print(f"    {i}. {t[:88].replace(chr(10), ' ')}…")

    print("\n  ⚠️ Nothing here is baked into a model. It is a profile and a few")
    print("     of your own past replies, handed to the writer as examples at")
    print("     the moment it writes. Delete the account and it is gone.\n")


if __name__ == "__main__":
    main()
