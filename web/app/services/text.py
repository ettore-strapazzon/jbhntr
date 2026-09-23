"""Copy hygiene for model output (R2).

The prompts already ask the model to avoid machine tells; this is the guarantee
that runs on every generated CV/cover letter (all paths funnel through it), so
the stored text is plain ASCII with none of the typographic fingerprints that
AI detectors and ATS parsers flag. Order matters: spaced dashes first.
"""

from __future__ import annotations

import re

_SUBS = {
    " — ": ", ", " – ": ", ",                        # spaced em/en dash -> comma
    "—": "-", "–": "-", "―": "-", "‒": "-", "−": "-",  # any remaining dash -> hyphen
    "“": '"', "”": '"', "„": '"', "‟": '"',            # curly / low double quotes
    "‘": "'", "’": "'", "‚": "'", "‛": "'",            # curly single quotes + apostrophe
    "…": "...",                                         # ellipsis
    "•": "-", "‣": "-", "◦": "-", "⁃": "-", "·": "-",   # bullet glyphs
    " ": " ", " ": " ", " ": " ",       # nbsp / narrow-nbsp / thin space
    " ": " ", " ": " ", " ": " ",        # figure / punctuation space, line sep
}
# Zero-width + invisible formatting chars — a common hidden watermark; strip them.
_INVISIBLE = dict.fromkeys(
    map(ord, "​‌‍⁠﻿᠎­"), None
)


def humanise(t: str) -> str:
    """Strip machine tells from any model output before it is stored."""
    if not t:
        return ""
    t = t.translate(_INVISIBLE)
    for bad, good in _SUBS.items():
        t = t.replace(bad, good)
    return re.sub(r" {2,}", " ", t).strip()


def as_bullets(text: str, limit: int) -> list[str]:
    """Split a reason field into short bullets (R8.2). Old prose rows render as
    bullets too, so no backfill is needed."""
    if not text:
        return []
    parts = [p.strip(" -•\t") for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    return [p.rstrip(".") for p in parts][:limit]
