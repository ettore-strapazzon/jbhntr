"""Persist the feedback the user leaves in the sheet.

feedback.jsonl accumulates one example per line: {title, company, url, verdict,
why}. On each run we merge any newly-filled sheet feedback into it, then feed
the whole set to the matcher as few-shot examples.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import DATA_DIR

log = logging.getLogger("jobhunter.feedback")

FEEDBACK_PATH = DATA_DIR / "feedback.jsonl"


def _key(ex: dict) -> tuple:
    return (
        (ex.get("url") or "").split("?")[0].rstrip("/"),
        (ex.get("title") or "").strip().lower(),
        (ex.get("company") or "").strip().lower(),
    )


def load(path: Path = FEEDBACK_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def merge(new_examples: list[dict], path: Path = FEEDBACK_PATH) -> list[dict]:
    """Add new examples that aren't already stored; return the full set."""
    existing = load(path)
    seen = {_key(e) for e in existing}
    added = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for ex in new_examples:
            k = _key(ex)
            if k in seen:
                continue
            seen.add(k)
            fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
            existing.append(ex)
            added += 1
    if added:
        log.info("Stored %d new feedback examples (total %d)", added, len(existing))
    return existing
