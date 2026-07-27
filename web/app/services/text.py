"""Copy hygiene for model output (R2).

The prompts already ask the model to avoid machine tells; this strips the one
that survives most often, dashes, before anything is stored or shown.
"""

from __future__ import annotations

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
