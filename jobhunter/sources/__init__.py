"""Job posting sources and the collector that runs them all fail-soft."""

from __future__ import annotations

import logging

from ..config import Profile, Settings, load_companies
from ..models import JobPosting
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


def collect_all(profile: Profile, settings: Settings) -> list[JobPosting]:
    """Run every enabled source. A failing source never aborts the run."""
    jobs: list[JobPosting] = []

    for name in profile.aggregators:
        fn = AGGREGATORS.get(name)
        if fn is None:
            log.warning("Unknown aggregator %r in profile; skipping.", name)
            continue
        jobs.extend(_safe(name, fn, profile, settings))

    # Niche / vertical boards (crypto, remote-exec, ...) via their public feeds.
    if profile.boards or profile.custom_rss:
        jobs.extend(_safe("boards", boards.fetch, profile, settings))

    # Aggregator APIs that need a key — skipped entirely unless one is set.
    if keyed.configured(settings):
        jobs.extend(_safe("keyed_apis", keyed.fetch, profile, settings))

    # Company career pages (ATS boards) — the long tail, scales to thousands.
    if load_companies():
        jobs.extend(_safe("ats", ats.fetch, profile, settings))

    if profile.linkedin_search_urls:
        jobs.extend(_safe("linkedin", linkedin.fetch, profile, settings))

    if profile.custom_sites:
        jobs.extend(_safe("custom_sites", custom_sites.fetch, profile, settings))

    log.info("Collected %d raw postings across all sources", len(jobs))
    return jobs


def _safe(name, fn, profile, settings) -> list[JobPosting]:
    try:
        return fn(profile, settings) or []
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Source %s crashed and was skipped: %s", name, exc)
        return []
