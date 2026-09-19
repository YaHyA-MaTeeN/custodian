"""
Voice learning — how this person actually writes.

Learned from their SENT folder. Never their inbox. The only email text that
ever leaves our building is the user's own outgoing writing — never anybody
else's incoming mail.

⚠️ THIS IS NOT A MODEL TRAINED ON THE USER.

Nothing about them is baked into any model's weights. Two things are stored:

  A PROFILE   how they open, how they sign off, how long they write, how
              formal they are. Plain counting. No AI.

  EXAMPLES    four or five of their own past replies, chosen because they
              match the situation at hand, handed to the writing model as
              samples at the moment it writes.

That distinction matters. Because nothing is baked in, deleting the account
removes it completely — there is no model to unlearn.

⚠️ AND THE VECTOR STORE

Finding "the four replies most like this situation" is the one job in the whole
system that genuinely needs vector search. Thousands of vectors per user, a few
searches a day.

  POC         vectors stored as blobs in SQLite, compared in numpy
  Production  the same vectors in Postgres with pgvector

That is why the design says "no separate vector database" — not "no vectors".
Postgres already does this; adding Pinecone or Qdrant would mean a second
system to run for a job the first one handles.
"""

import re
import sqlite3
import numpy as np

VECTOR_DIM = 384

GREETINGS = ["hi", "hello", "hey", "dear", "good morning", "good afternoon",
             "salam", "assalam", "morning", "afternoon"]
SIGNOFFS = ["thanks", "thank you", "best", "best regards", "regards", "cheers",
            "kind regards", "sincerely", "many thanks", "br", "warm regards"]

CONTRACTIONS = re.compile(r"\b(I'm|I'll|don't|can't|won't|it's|that's|we'll|you're)\b", re.I)
EXCLAIM = re.compile(r"!")


# ══════════════════ the profile — plain counting, no AI ══════════════════

def build_profile(sent_texts: list[str]) -> dict:
    """
    How this person writes. Every line below is counting, not intelligence.
    """
    if not sent_texts:
        return {}

    greet, sign, lengths, contractions, exclaims, bullets = {}, {}, [], 0, 0, 0

    for text in sent_texts:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if not lines:
            continue

        first = lines[0].lower()
        for g in GREETINGS:
            if first.startswith(g):
                greet[g] = greet.get(g, 0) + 1
                break

        for l in reversed(lines[-4:]):
            low = l.lower().rstrip(",.!")
            if low in SIGNOFFS:
                sign[low] = sign.get(low, 0) + 1
                break

        words = len(text.split())
        lengths.append(words)
        contractions += len(CONTRACTIONS.findall(text))
        exclaims += len(EXCLAIM.findall(text))
        bullets += sum(1 for l in lines if l.startswith(("-", "*", "•")))

    n = len(sent_texts)
    avg = int(np.mean(lengths)) if lengths else 0

    return {
        "greeting": max(greet, key=greet.get).title() if greet else "none",
        "sign_off": max(sign, key=sign.get).title() if sign else "none",
        "average_words": avg,
        "length": "short" if avg < 60 else "medium" if avg < 140 else "long",
        "formality": "casual" if contractions / max(n, 1) > 1.5 else "formal",
        "uses_bullets": bullets / max(n, 1) > 0.4,
        "exclamation_marks": round(exclaims / max(n, 1), 2),
        "samples": n,
    }


def describe(profile: dict) -> str:
    """The profile as a sentence, for the writing prompt."""
    if not profile:
        return "unknown"
    bits = [
        f"opens with '{profile['greeting']}'" if profile["greeting"] != "none"
        else "no greeting",
        f"signs off '{profile['sign_off']}'" if profile["sign_off"] != "none"
        else "no sign-off",
        f"{profile['length']} replies (~{profile['average_words']} words)",
        profile["formality"],
    ]
    if profile.get("uses_bullets"):
        bits.append("often uses bullet points")
    return ", ".join(bits)


# ══════════════════ the vectors ══════════════════

class Vectoriser:
    """
    Turns a piece of writing into numbers, so we can find similar ones.

    POC uses TF-IDF — a well-understood method that needs no model download and
    works the moment you run it. Production swaps in sentence embeddings from a
    small encoder; the interface below is the same either way, so it is a
    one-line change.
    """

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.model = TfidfVectorizer(
            max_features=VECTOR_DIM, stop_words="english",
            ngram_range=(1, 2), sublinear_tf=True)
        self.fitted = False

    def fit(self, texts: list[str]):
        if len(texts) < 2:
            return False
        self.model.fit(texts)
        self.fitted = True
        return True

    def encode(self, text: str) -> np.ndarray:
        v = self.model.transform([text]).toarray()[0].astype(np.float32)
        out = np.zeros(VECTOR_DIM, dtype=np.float32)
        out[:len(v)] = v[:VECTOR_DIM]
        n = np.linalg.norm(out)
        return out / n if n else out


# ══════════════════ the store ══════════════════

SCHEMA = """
CREATE TABLE IF NOT EXISTS style_examples (
    id        INTEGER PRIMARY KEY,
    text      TEXT,
    subject   TEXT,
    embedding BLOB          -- in production this is a pgvector column
);
CREATE TABLE IF NOT EXISTS style_profile (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class StyleStore:
    """
    ⚠️ The one place we hold the user's own email text, and it is only ever
    their OUTGOING writing. Never anybody else's incoming mail.
    """

    def __init__(self, path="mailbox.db"):
        import os
        if os.environ.get("DATABASE_URL") and os.environ.get("CUSTODIAN_STORE", "pg") != "sqlite":
            # Same database as everything else: the account's own schema on
            # Postgres. The tables are created there by PgStore from this
            # file's SCHEMA, and the proxy translates the SQL below.
            from pg_store import PgStore
            self.db = PgStore().db
        else:
            self.db = sqlite3.connect(path)
            self.db.executescript(SCHEMA)
            self.db.commit()
        self.vec = Vectoriser()

    def learn(self, sent: list[dict]) -> dict:
        """
        `sent` is [{"text": ..., "subject": ...}] from the Sent folder.
        Builds the profile, embeds each reply, stores both.
        """
        texts = [s["text"] for s in sent if len(s.get("text", "")) > 40]
        if not texts:
            return {}

        profile = build_profile(texts)
        self.db.execute("DELETE FROM style_profile")
        self.db.executemany("INSERT INTO style_profile VALUES (?,?)",
                            [(k, str(v)) for k, v in profile.items()])

        if self.vec.fit(texts):
            self.db.execute("DELETE FROM style_examples")
            rows = [(s.get("text"), s.get("subject", ""),
                     self.vec.encode(s["text"]).tobytes())
                    for s in sent if len(s.get("text", "")) > 40]
            self.db.executemany(
                "INSERT INTO style_examples (text, subject, embedding) VALUES (?,?,?)",
                rows)
        self.db.commit()
        return profile

    def profile(self, domain: str = "") -> dict:
        """
        The recipe, with the Owner's own settings on top (UC-42).

        ⚠️ AN EXPLICIT SETTING ALWAYS WINS OVER WHAT WE LEARNED (BR-163).
        Learning carries on and rewrites the base keys; a key the Owner set
        is stored as "set:<field>" and overrides it every time. A voice for
        one group of people — "group:<domain>:<field>" — overrides both,
        only for mail to that domain (BR-164). Changing one never changes
        another.
        """
        rows = {k: v for k, v in self.db.execute("SELECT key, value FROM style_profile")}
        base = {k: v for k, v in rows.items() if ":" not in k}
        for k, v in rows.items():
            if k.startswith("set:"):
                base[k[4:]] = v
        if domain:
            pre = f"group:{domain.lower()}:"
            for k, v in rows.items():
                if k.startswith(pre):
                    base[k[len(pre):]] = v
        return base

    def set_field(self, field: str, value: str, domain: str = "") -> None:
        key = f"group:{domain.lower()}:{field}" if domain else f"set:{field}"
        self.db.execute("INSERT OR REPLACE INTO style_profile VALUES (?,?)", (key, value))
        self.db.commit()

    def reset(self, domain: str = "") -> int:
        pre = f"group:{domain.lower()}:" if domain else "set:"
        n = self.db.execute("DELETE FROM style_profile WHERE key LIKE ?", (pre + "%",)).rowcount
        self.db.commit()
        return n

    def groups(self) -> list:
        return sorted({k.split(":")[1] for (k,) in
                       self.db.execute("SELECT key FROM style_profile WHERE key LIKE 'group:%'")})

    def find_similar(self, situation: str, k: int = 5) -> list[str]:
        """
        The four or five of THIS PERSON'S past replies that best match the
        situation now. Not random ones — the closest ones.

        "They are replying to a colleague about a deadline — here are four
        times they did exactly that."
        """
        rows = self.db.execute(
            "SELECT text, embedding FROM style_examples").fetchall()
        if not rows:
            return []
        if not self.vec.fitted:
            self.vec.fit([r[0] for r in rows])
        if not self.vec.fitted:
            return [r[0] for r in rows[:k]]

        query = self.vec.encode(situation)
        scored = []
        for text, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            if v.shape[0] != VECTOR_DIM:
                continue
            scored.append((float(np.dot(query, v)), text))

        scored.sort(reverse=True)
        return [t for _, t in scored[:k]]

    def close(self):
        self.db.close()

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM style_examples").fetchone()[0]
