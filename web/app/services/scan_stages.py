"""Scan stage text -> progress rail step (R3-31).

The worker (`search_service._run_search`) writes free-text stages, plus the
heartbeat's "LABEL done/total" form. The rail in `partials/progress.html` has
four steps: 0 Collecting, 1 Filtering by location, 2 Ranking by meaning,
3 Scoring the shortlist. Every stage the worker writes has an explicit rule
here; tests/test_progress_rail.py reads the worker's source and fails on any
stage text without one, so a new message can't silently fall back to step 0.
"""

from __future__ import annotations

import logging

log = logging.getLogger("jbhntr.search")

# (lower-case prefix, rail step). Order matters only if prefixes overlap.
STAGE_STEPS: tuple[tuple[str, int], ...] = (
    ("starting", 0),
    ("understanding your profile", 0),
    ("searching the job corpus", 1),
    ("collecting job postings", 1),
    ("filtering", 1),
    ("shortlisting", 2),
    ("scoring", 3),            # "Scoring N jobs…", "Scoring: reading…", "Scoring d/t"
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
