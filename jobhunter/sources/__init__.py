"""Job posting sources and the collector that runs them all fail-soft."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..config import Profile, Settings, load_companies
from ..models import JobPosting, ProgressFn, report_progress
from . import (
    adzuna, arbeitnow, ats, boards, custom_sites, keyed, linkedin, remoteok,
    remotive,
)

log = logging.getLogger("jobhunter.sources")

# Aggregators selectable by name in profile.sources.aggregators.
AGGREGATORS = {
    "adzuna": adzuna.fetch,
    "remotive": remotive.fetch,
    "remoteok": remoteok.fetch,
    "arbeitnow": arbeitnow.fetch,
}


def collect_all(profile: Profile, settings: Settings,
                progress: Optional[ProgressFn] = None) -> list[JobPosting]:
    """Run every enabled source. A failing source never aborts the run.

    ``progress(done, total)`` (R3-29) reports finished sources out of the enabled
    ones, and keeps beating at that count while a long source (the ATS long tail)
    is still running, so the caller's heartbeat never goes silent for a whole stage.
    """
    steps: list[tuple[str, Callable, bool]] = []   # (name, fetch, beats inside)
    for name in profile.aggregators:
        fn = AGGREGATORS.get(name)
        if fn is None:
            log.warning("Unknown aggregator %r in profile; skipping.", name)
            continue
        steps.append((name, fn, False))

    # Niche / vertical boards (crypto, remote-exec, ...) via their public feeds.
    if profile.boards or profile.custom_rss:
        steps.append(("boards", boards.fetch, False))

    # Aggregator APIs that need a key — skipped entirely unless one is set.
    if keyed.configured(settings):
        steps.append(("keyed_apis", keyed.fetch, False))

    # Company career pages (ATS boards) — the long tail, scales to thousands.
    if load_companies():
        steps.append(("ats", ats.fetch, True))

    if profile.linkedin_search_urls:
        steps.append(("linkedin", linkedin.fetch, False))

    if profile.custom_sites:
        steps.append(("custom_sites", custom_sites.fetch, False))

    jobs: list[JobPosting] = []
    total = len(steps)
    for done, (name, fn, beats_inside) in enumerate(steps):
        kw = ({"progress": lambda _d, _t, done=done: report_progress(progress, done, total)}
              if beats_inside else {})
        jobs.extend(_safe(name, fn, profile, settings, **kw))
        report_progress(progress, done + 1, total)

    log.info("Collected %d raw postings across all sources", len(jobs))
    return jobs


def _safe(name, fn, profile, settings, **kw) -> list[JobPosting]:
    try:
        return fn(profile, settings, **kw) or []
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Source %s crashed and was skipped: %s", name, exc)
        return []
