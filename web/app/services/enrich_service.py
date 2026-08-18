"""Enrich thin corpus descriptions by fetching the real posting page.

Aggregators (careerjet's snippet, adzuna's blurb) store only a sentence or two,
which caps both work-mode tagging AND match scoring — a job scored with no body
is marked down simply for lacking information. Their URL redirects to the
employer's full posting; HTTP-fetch it and store the body. No LLM, so it's free
bar bandwidth.

Paced, not all-at-once: fetching tens of thousands of pages fast gets our IP
rate-limited/blocked (which also hurts link-checking). Each job is fetched at
most once (Job.desc_enriched), so this is a one-time backlog catch-up plus the
day's new thin jobs, never a nightly full re-scan. When a fuller body is found we
re-tag the row (remote_mode/countries improve with real text) and clear its
embedding so the next embed pass re-embeds it with the JD.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DbSession

from jobhunter.models import JobPosting
from jobhunter.sources.base import http_client, strip_html
from jobhunter.tags import deterministic_tags

from ..config import config
from ..models import Job

log = logging.getLogger("jbhntr.enrich")

_MIN_CHARS = 300      # at/below this a stored description is a snippet, not a JD
_GOOD_CHARS = 400     # only accept a fetched body at least this long
_DESC_CAP = 20_000    # store at most this much
_TIMEOUT = 15.0
_WORKERS = 12


def _fetch_body(url: str) -> tuple[str, bool]:
    """Return (stripped_body, definitive). ``definitive`` is False only on a
    transient error (timeout / connection reset) — those we may retry later; a
    200, 404 or 403 is definitive and the job is marked done so we don't
    re-hammer a page that won't give us more."""
    try:
        with http_client(timeout=_TIMEOUT) as c:
            r = c.get(url, follow_redirects=True)
    except Exception:
        return "", False
    if r.status_code != 200:
        return "", True
    try:
        return strip_html(r.text), True
    except Exception:
        return "", True


def _thin_filter():
    return or_(Job.description.is_(None),
               func.coalesce(func.length(Job.description), 0) < _MIN_CHARS)


def pending_count(db: DbSession) -> int:
    """How many thin, not-yet-enriched jobs remain (for the admin readout)."""
    return (db.query(func.count(Job.id))
            .filter(Job.desc_enriched.is_(False), Job.url.isnot(None), Job.url != "",
                    _thin_filter()).scalar() or 0)


def enrich_thin_descriptions(db: DbSession, limit: int | None = None) -> dict:
    """Fetch and store full descriptions for up to ``limit`` thin jobs, freshest
    first. Returns {enriched, attempted, remaining}."""
    if not config.enrich_enabled:
        return {"enriched": 0, "attempted": 0, "remaining": pending_count(db),
                "skipped": "disabled"}
    limit = config.enrich_nightly_limit if limit is None else limit
    rows = (db.query(Job)
            .filter(Job.desc_enriched.is_(False), Job.url.isnot(None), Job.url != "",
                    _thin_filter())
            .order_by(Job.last_seen_at.desc())
            .limit(limit).all())
    if not rows:
        return {"enriched": 0, "attempted": 0, "remaining": 0}

    # Fetch concurrently (network-bound); apply results on the main thread since a
    # SQLAlchemy session isn't thread-safe.
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda r: (r, *_fetch_body(r.url)), rows))

    enriched = 0
    for r, body, definitive in results:
        if definitive:
            r.desc_enriched = True          # don't re-hammer a page that gave nothing more
        if body and len(body) >= _GOOD_CHARS and len(body) > len(r.description or ""):
            r.description = body[:_DESC_CAP]
            p = JobPosting(source=r.source or "", title=r.title or "",
                           company=r.company or "", location=r.location or "",
                           description=r.description, url=r.url or "")
            tags = deterministic_tags(p)
            r.remote_mode = tags["remote_mode"]
            if tags["countries"]:
                r.countries = tags["countries"]
            r.embedding = None              # re-embedded next pass, now with the real JD
            enriched += 1
    db.commit()
    remaining = pending_count(db)
    log.info("Enrichment: %d filled of %d attempted, %d remaining",
             enriched, len(rows), remaining)
    return {"enriched": enriched, "attempted": len(rows), "remaining": remaining}
