"""
The findings.

Every one of these is a database query over envelope data. No model runs here,
nothing is sent anywhere, and nothing in the mailbox is touched.

The design rule this file follows: we never decide what is important. We
measure what this person actually engages with. "Never once opened" is a fact
about their behaviour; "promotional" would be a guess about the sender.
"""

from collections import defaultdict


def scan(store) -> dict:
    f = {}

    # --- the shape of the mailbox ----------------------------------------
    f["total"] = store.one("SELECT COUNT(*) FROM messages")
    f["unread"] = store.one("SELECT COUNT(*) FROM messages WHERE unread=1")
    f["inbox"] = store.one("SELECT COUNT(*) FROM messages WHERE in_inbox=1")
    f["senders"] = store.one("SELECT COUNT(DISTINCT sender) FROM messages")
    f["gb"] = (store.one("SELECT SUM(size) FROM messages") or 0) / 1e9

    # --- bulk mail, as declared by the sender itself ----------------------
    # Not a guess: List-Unsubscribe has been required on bulk mail since
    # February 2024, so the sender told us.
    f["bulk_total"] = store.one("SELECT COUNT(*) FROM messages WHERE bulk=1")
    f["bulk_senders"] = store.one(
        "SELECT COUNT(DISTINCT sender) FROM messages WHERE bulk=1")
    f["one_click_senders"] = store.one(
        "SELECT COUNT(DISTINCT sender) FROM messages WHERE one_click=1")

    f["pile"] = store.q("""
        SELECT sender, sender_name, COUNT(*), SUM(unread),
               SUM(size)/1e6, MAX(one_click)
          FROM messages WHERE bulk=1
         GROUP BY sender ORDER BY COUNT(*) DESC LIMIT 25""")

    # --- engagement, not category ----------------------------------------
    # Eight or more messages and every single one still unread.
    f["dormant"] = store.q("""
        SELECT sender, sender_name, COUNT(*), SUM(size)/1e6
          FROM messages
         GROUP BY sender
        HAVING COUNT(*) >= 8 AND SUM(unread) = COUNT(*)
         ORDER BY COUNT(*) DESC LIMIT 25""")
    f["dormant_senders"] = store.one("""
        SELECT COUNT(*) FROM (
            SELECT sender FROM messages GROUP BY sender
             HAVING COUNT(*) >= 8 AND SUM(unread) = COUNT(*))""")
    f["dormant_messages"] = store.one("""
        SELECT COALESCE(SUM(c),0) FROM (
            SELECT COUNT(*) c FROM messages GROUP BY sender
             HAVING COUNT(*) >= 8 AND SUM(unread) = COUNT(*))""")

    # --- storage ----------------------------------------------------------
    # Size comes back free with every listing. No attachment was downloaded.
    f["big"] = store.q("""
        SELECT sender, sender_name, subject, size/1e6
          FROM messages ORDER BY size DESC LIMIT 15""")
    f["by_domain"] = store.q("""
        SELECT sender_domain, COUNT(*), SUM(size)/1e6
          FROM messages WHERE sender_domain != ''
         GROUP BY sender_domain ORDER BY SUM(size) DESC LIMIT 15""")

    # --- machines vs people ----------------------------------------------
    f["human"] = store.q("""
        SELECT sender, sender_name, COUNT(*), SUM(unread)
          FROM messages WHERE bulk=0
         GROUP BY sender ORDER BY COUNT(*) DESC LIMIT 20""")

    # --- Gmail's own split, free with every message -----------------------
    cats = defaultdict(int)
    for (c,) in store.q("SELECT categories FROM messages"):
        for k in (c or "").split(","):
            cats[k or "Primary"] += 1
    f["categories"] = sorted(cats.items(), key=lambda x: -x[1])

    # --- threads ----------------------------------------------------------
    # Conversations rebuilt from Message-ID / In-Reply-To. This is what the
    # obligation ledger runs on. It needs sent mail to be useful, so on a
    # mailbox with no replies it will report nothing — correctly.
    f["threads"] = store.one("SELECT COUNT(DISTINCT thread_id) FROM messages")
    f["in_threads"] = store.one(
        "SELECT COUNT(*) FROM messages WHERE in_reply_to != ''")

    # --- machine replies (out-of-office and friends) ----------------------
    f["auto"] = store.one("SELECT COUNT(*) FROM messages WHERE auto_sub != ''")

    return f
