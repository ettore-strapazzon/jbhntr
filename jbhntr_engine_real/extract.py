"""Job-description extraction heuristics (PRIVATE engine side).

Carved out of ``web/app/services/enrich_service.py`` (R3-16): which URLs can
never yield a JD (redirect trackers, bot-walled boards), and how to pull the JD
out of a posting page (JSON-LD ``JobPosting`` first, then chrome-stripped main
text). The shell keeps the DB queue/persistence and reaches these only through
the ``jbhntr_engine`` façade (``extract_job_body``, ``is_unscrapable_url``,
``is_tracker_url``).
"""

from __future__ import annotations

import json
import re

from jobhunter.sources.base import strip_html

GOOD_CHARS = 500     # a JSON-LD description at least this long wins outright

# URLs a plain HTTP fetch can never turn into a JD (measured 0-5% yield): redirect
# trackers that land on a JavaScript shell, and hosts that 403 every bot. Scraping
# these just burns our IP — skip them and mark the row done, so the enrich queue
# holds only URLs that CAN yield a body. Such jobs get a full JD another way: a
# fuller posting for the same company|title from jsearch/an ATS upgrades the row
# via the upsert dedup path.
_DEAD_URL_BITS = (
    "jobviewtrack.com",   # careerjet redirect tracker -> JS/err (0% measured)
    "/jobs/land/",        # adzuna land redirect (its /details/ pages still work)
    "indeed.com", "linkedin.com", "glassdoor.",  # 403 to bots
)

# Redirect trackers (careerjet/adzuna) that 404 once the underlying job expires —
# unlike the live boards in _DEAD_URL_BITS (indeed/linkedin/glassdoor), which are
# real destinations we simply can't scrape.
_TRACKER_BITS = ("jobviewtrack.com", "/jobs/land/")


def is_unscrapable_url(url: str) -> bool:
    """True for a URL a plain HTTP fetch can never turn into a JD."""
    u = (url or "").lower()
    return any(bit in u for bit in _DEAD_URL_BITS)


def is_tracker_url(url: str) -> bool:
    """True for an aggregator redirect tracker (dies when the job expires)."""
    u = (url or "").lower()
    return any(bit in u for bit in _TRACKER_BITS)


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


def jsonld_description(html: str) -> str:
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


def extract_main(html: str) -> str:
    """Best-effort main-content text: drop chrome tags, strip the rest, collapse
    whitespace. Returns "" for a page that's essentially a JavaScript shell (no
    server-rendered body to read)."""
    html = _COMMENTS.sub(" ", html)
    html = _CHROME.sub(" ", html)
    return re.sub(r"\s+", " ", strip_html(html)).strip()


def extract_job_body(html: str) -> str:
    """Prefer the JSON-LD JobPosting description; fall back to main-content text."""
    jd = jsonld_description(html)
    main = extract_main(html)
    # JSON-LD is the cleanest when it's substantial; otherwise take whichever is longer.
    if len(jd) >= GOOD_CHARS:
        return jd
    return jd if len(jd) >= len(main) else main
