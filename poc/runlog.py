"""
Keep a copy of every test run, exactly as it appeared on screen.

⚠️ WHY THE SCRIPT SAVES IT, NOT A PERSON.

A result that someone copied into a document is a claim about a result. The
file this writes is the output itself — timestamped, untouched, one file per
run. If anyone asks "did you actually run this", the answer is a folder of
files with the time each one happened, not a paragraph saying so.
"""

import sys
from datetime import datetime
from pathlib import Path

RUNS = Path(__file__).parent / "test_runs"


class _Tee:
    """Everything printed goes to the screen AND the file."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def start(name: str) -> Path:
    """Start recording. Returns the path the run is being saved to."""
    RUNS.mkdir(exist_ok=True)
    flags = "_".join(a.lstrip("-") for a in sys.argv[1:] if a.startswith("--"))
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = RUNS / f"{name}{'_' + flags if flags else ''}_{stamp}.txt"
    f = open(path, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, f)
    return path
