"""
Loads prompts.md.

Why prompts live in a text file rather than inside the code:

  - Wording is a product decision, not an engineering one. Sir should be able
    to change how the system speaks without a developer.
  - They can be reviewed. A prompt buried in an f-string never gets read;
    one in a document does.
  - They can be versioned and compared. When drafts get worse, you want to see
    exactly what changed.
  - Nothing is hidden. Every instruction the system gives any model is in one
    file, which is the honest answer to "what are you telling the AI?"
"""

import re
from pathlib import Path

PROMPTS_FILE = Path(__file__).parent.parent / "prompts.md"

_cache = None


def _load() -> dict:
    """Parse prompts.md into {name: template}. Note lines are dropped."""
    global _cache
    if _cache is not None:
        return _cache

    if not PROMPTS_FILE.exists():
        raise FileNotFoundError(f"{PROMPTS_FILE} is missing")

    text = PROMPTS_FILE.read_text(encoding="utf-8")
    out, name, body = {}, None, []

    for line in text.splitlines():
        heading = re.match(r"^##\s+(\w+)\s*$", line)
        if heading:
            if name:
                out[name] = "\n".join(body).strip().strip("-").strip()
            name, body = heading.group(1), []
            continue
        if line.startswith("# "):          # a top-level heading ends a prompt
            if name:
                out[name] = "\n".join(body).strip().strip("-").strip()
                name, body = None, []
            continue
        if line.startswith(">"):           # a note for us, never sent
            continue
        if name is not None:
            body.append(line)

    if name:
        out[name] = "\n".join(body).strip().strip("-").strip()

    _cache = out
    return out


def get(name: str, **fields) -> str:
    """
    Fetch a prompt and fill in its {placeholders}.

    Raises if a placeholder is missing, rather than sending a half-filled
    prompt to a model and getting a confusing answer back.
    """
    template = _load().get(name)
    if template is None:
        raise KeyError(f"no prompt called '{name}' in prompts.md. "
                       f"Available: {', '.join(sorted(_load()))}")
    try:
        return template.format(**fields)
    except KeyError as e:
        raise KeyError(f"prompt '{name}' needs a value for {e}") from None


def names() -> list[str]:
    return sorted(_load())


def reload():
    """Pick up edits to prompts.md without restarting."""
    global _cache
    _cache = None
    return _load()


if __name__ == "__main__":
    ps = _load()
    print(f"\n{len(ps)} prompts in prompts.md\n")
    for k, v in ps.items():
        fields = sorted(set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", v)))
        print(f"  {k:<22} {len(v):>5} chars   fills in: {', '.join(fields) or 'nothing'}")
    print()
