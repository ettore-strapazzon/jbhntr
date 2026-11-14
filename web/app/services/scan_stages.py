"""Scan stage text -> progress rail step (R3-31, labels R3-32b).

The worker (`search_service._run_search`) writes free-text stages, plus the
heartbeat's "LABEL done/total" form. The rail in `partials/progress.html` shows
the four RAIL_STEPS below; each step is named for the activity of every stage
mapped to it, so the bold step never contradicts the stage line above it, and
every run path (corpus or live fetch) lights all four in order. Every stage the
worker writes has an explicit rule here; tests/test_progress_rail.py reads the
worker's source and fails on any stage text without one, on a stage filed under
a label for a different activity, and on a step that goes backwards.
"""

from __future__ import annotations

import logging

log = logging.getLogger("jbhntr.search")

# The rail's step labels, in run order. progress.html renders these.
RAIL_STEPS: tuple[str, ...] = (
    "Reading your profile",
    "Finding jobs for you",
    "Scoring each job",
    "Checking links and saving",
)

# (lower-case prefix, rail step). Order matters only if prefixes overlap.
STAGE_STEPS: tuple[tuple[str, int], ...] = (
    ("starting", 0),
    ("understanding your profile", 0),
    ("searching the job corpus", 1),   # corpus mode: read + location + rank in one go
    ("collecting job postings", 1),    # live-fetch fallback ...
    ("filtering", 1),
    ("shortlisting", 1),               # ... AI shortlist of the fetched jobs
    ("scoring", 2),            # "Scoring N jobs…", "Scoring: reading…", "Scoring d/t"
    ("checking links", 3),     # after scoring: verifying the shortlist's links
    ("saving results", 3),
    ("done", 3),
)

_warned: set[str] = set()


def stage_step(stage: str | None) -> int | None:
    """The rail step for a stage text, or None if no rule matches (or it's empty)."""
    s = (stage or "").strip().lower()
    if not s:
        return None
    for prefix, step in STAGE_STEPS:
        if s.startswith(prefix):
            return step
    if s not in _warned:                   # polled every 3 s: say it once per text
        _warned.add(s)
        log.warning("progress rail: no step for scan stage %r", stage)
    return None
