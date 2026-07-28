"""Copy hygiene for model output (R2).

The prompts already ask the model to avoid machine tells; this strips the one
that survives most often, dashes, before anything is stored or shown.
"""

from __future__ import annotations

import re

# Order matters: spaced dashes first, so " word — word " becomes "word, word".
DASHES = {
    " — ": ", ",   # spaced em dash
    " – ": ", ",   # spaced en dash
    "—": ", ",     # bare em dash
    "–": "-",       # bare en dash -> hyphen
}


def humanise(t: str) -> str:
    """Strip machine tells from any model output before it is stored."""
    if not t:
        return ""
    for bad, good in DASHES.items():
        t = t.replace(bad, good)
    return t.replace("  ", " ").strip()


def as_bullets(text: str, limit: int) -> list[str]:
    """Split a reason field into short bullets (R8.2). Old prose rows render as
    bullets too, so no backfill is needed."""
    if not text:
        return []
    parts = [p.strip(" -•\t") for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    return [p.rstrip(".") for p in parts][:limit]
