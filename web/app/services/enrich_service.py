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

import json
import logging
import re
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
_GOOD_CHARS = 500     # only accept a fetched body at least this long
_DESC_CAP = 20_000    # store at most this much
_TIMEOUT = 15.0
_WORKERS = 12

# Page chrome to drop BEFORE extracting text, so we store the JD rather than the
# nav/footer/cookie banner (whole-page strip_html was polluting descriptions).
_CHROME = re.compile(
    r"(?is)<(script|style|noscript|nav|header|footer|aside|form|svg|template|"
    r"select|button)\b[^>]*>.*?</\1\s*>")
_COMMENTS = re.compile(r"(?is)<!--.*?-->")


_JSONLD = re.compile(
    r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>')


def _iter_nodes(data):
    """Walk a JSON-LD document, yielding every dict (through lists and @graph)."""
    if isinstance(data, list):
        for x in data:
            yield from _iter_nodes(x)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])


def _jsonld_description(html: str) -> str:
    """The `description` of a JobPosting in the page's JSON-LD, if present. This is
    the reliable path: Google for Jobs makes most postings (ATS + company sites)
    embed the FULL JD as structured data in the server HTML, so it works even when
    the visible page is JavaScript-rendered and plain scraping gets nothing."""
    for m in _JSONLD.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for node in _iter_nodes(data):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "jobposting" for x in types) and node.get("description"):
                return re.sub(r"\s+", " ", strip_html(str(node["description"]))).strip()
    return ""


def _extract_main(html: str) -> str:
    """Best-effort main-content text: drop chrome tags, strip the rest, collapse
    whitespace. Returns "" for a page that's essentially a JavaScript shell (no
    server-rendered body to read)."""
    html = _COMMENTS.sub(" ", html)
    html = _CHROME.sub(" ", html)
    text = re.sub(r"\s+", " ", strip_html(html)).strip()
    return text


def _best_body(html: str) -> str:
    """Prefer the JSON-LD JobPosting description; fall back to main-content text."""
    jd = _jsonld_description(html)
    main = _extract_main(html)
    # JSON-LD is the cleanest when it's substantial; otherwise take whichever is longer.
    if len(jd) >= _GOOD_CHARS:
        return jd
    return jd if len(jd) >= len(main) else main


def _fetch_body(url: str, timeout: float = _TIMEOUT) -> tuple[str, bool]:
    """Return (main_text, definitive). ``definitive`` is False only on a transient
    error (timeout / connection reset) — those we may retry later; a 200, 404 or
    403 is definitive and the job is marked done so we don't re-hammer a page that
    won't give us more."""
    try:
        with http_client(timeout=timeout) as c:
            r = c.get(url, follow_redirects=True)
    except Exception:
        return "", False
    if r.status_code != 200:
        return "", True
    try:
        return _best_body(r.text), True
    except Exception:
        return "", True


def fetch_description(url: str, timeout: float = 10.0) -> str:
    """Public: the full description for one posting URL, or "" if we couldn't get a
    substantial body. Used by the search path to fill a shortlisted job before it
    is scored, so the matcher never judges fit from a snippet."""
    if not url:
        return ""
    body, _ = _fetch_body(url, timeout=timeout)
    return body[:_DESC_CAP] if len(body) >= _GOOD_CHARS else ""


def persist_description(db: DbSession, posting) -> bool:
    """Store a freshly-fetched description on the matching corpus row, re-tag it and
    clear its embedding — so a search that enriched a shortlisted job also fixes
    the corpus for everyone and it isn't re-fetched. Does NOT commit (caller
    batches). Returns True if it updated a row."""
    desc = posting.description or ""
    if len(desc) < _GOOD_CHARS:
        return False
    row = db.query(Job).filter(Job.dedup_key == posting.dedup_key()).first()
    if not row or len(desc) <= len(row.description or ""):
        return False
    row.description = desc[:_DESC_CAP]
    tags = deterministic_tags(posting)
    row.remote_mode = tags["remote_mode"]
    if tags["countries"]:
        row.countries = tags["countries"]
    row.embedding = None
    row.desc_enriched = True
    return True


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
        # Accept only a real gain over the snippet (>= _GOOD_CHARS AND clearly
        # longer), so page-chrome or a truncated shell never overwrites the row.
        existing = len(r.description or "")
        if body and len(body) >= _GOOD_CHARS and len(body) >= existing + 300:
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
