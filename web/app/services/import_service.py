"""Premium: import a single job from a URL and score it like a corpus match.

Fetch the page, have the LLM structure it into a posting, score it with the same
Matcher the corpus search uses, and persist it as a JobResult so it renders as a
normal match card (score, fits / you-fit, reasons, tags). One-off Search row of
its own so it shows under the run selector and never mixes into a real scan.
"""

from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy.orm import Session as DbSession

from jobhunter.candidate import derive_company_profile
from jobhunter.criteria import derive as derive_criteria
from jobhunter.matcher import Matcher
from jobhunter.models import JobPosting
from jobhunter.tags import deterministic_tags

from ..models import JobResult, Search, User, utcnow
from .profile_service import (
    build_engine_materials, build_engine_profile, engine_settings, seed_values,
)

log = logging.getLogger("jbhntr.import")

_UA = "Mozilla/5.0 (compatible; JBHNTR-import/1.0)"

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_job": {"type": "boolean",
                   "description": "true only if the page is a single job posting"},
        "title": {"type": "string"},
        "company": {"type": "string"},
        "location": {"type": "string",
                     "description": "city/country, or 'Remote', as stated"},
        "description": {"type": "string",
                        "description": "the full role description text"},
    },
    "required": ["is_job", "title", "company", "location", "description"],
    "additionalProperties": False,
}


class JobImportError(Exception):
    """A user-facing reason the import could not complete."""


def _fetch_text(url: str) -> str:
    """Fetch a page and reduce it to visible text (no external HTML parser)."""
    r = httpx.get(url, headers={"User-Agent": _UA}, follow_redirects=True, timeout=20.0)
    r.raise_for_status()
    html = r.text
    html = re.sub(r"(?is)<(script|style|noscript|nav|footer|header|svg)[^>]*>.*?</\1>",
                  " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:20000]


def _extract_posting(url: str, settings) -> JobPosting:
    """Fetch + structure a single posting. Raises ImportError with a clear reason."""
    from jobhunter import llm

    try:
        text = _fetch_text(url)
    except Exception as exc:
        raise JobImportError(f"Couldn't open that link ({exc}).") from exc
    if len(text) < 200:
        raise JobImportError("That page had almost no readable text — it may need a login "
                          "or render with JavaScript. Try the direct posting URL.")
    try:
        data = llm.get_client(settings).json(
            system="You extract a single job posting's fields from raw page text. "
                   "If the page is not a job posting, set is_job=false.",
            user=f"Page URL: {url}\n\nPage text:\n{text}",
            schema=_EXTRACT_SCHEMA, tier=llm.SCORING, max_tokens=2000, cache_system=False)
    except Exception as exc:
        raise JobImportError(f"Couldn't read the posting ({exc}).") from exc

    if not data.get("is_job") or not (data.get("title") or "").strip():
        raise JobImportError("That didn't look like a single job posting.")
    loc = (data.get("location") or "").strip()
    return JobPosting(
        source="import", title=(data.get("title") or "").strip()[:300],
        company=(data.get("company") or "").strip()[:200], location=loc[:200],
        description=(data.get("description") or "").strip(), url=url,
        is_remote="remote" in loc.lower(),
    )


def import_job(db: DbSession, user: User, url: str) -> tuple[JobResult, int]:
    """Import, score, and store one job. Returns (JobResult, search_id), any tier."""
    from .search_service import _company_url, _split_reasons

    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise JobImportError("Please paste a full http(s) job URL.")

    settings = engine_settings(premium=user.is_premium)
    posting = _extract_posting(url, settings)
    deterministic_tags(posting)   # geo/remote/salary (no-op fields the matcher reads)

    profile = build_engine_profile(db, user)
    materials = build_engine_materials(db, user)
    try:
        from jobhunter import seeds as seeds_mod
        labels = [s.label() for s in seeds_mod.resolve(seed_values(db, user), guess_domains=True)]
        company_profile = derive_company_profile(labels, settings)
        criteria = derive_criteria(profile, labels, settings)
        scored = Matcher(settings).score([posting], profile, materials, [],
                                         company_profile, criteria)
    except Exception as exc:
        log.exception("Import scoring failed")
        raise JobImportError(f"Couldn't score that job ({exc}).") from exc
    if not scored:
        raise JobImportError("Couldn't score that job — try again.")

    job, match = scored[0]
    good, bad = _split_reasons(match.reasons)
    search = Search(user_id=user.id, status="done", stage="Imported job",
                    raw_count=1, located_count=1, ranked_count=1, scored_count=1,
                    finished_at=utcnow())
    db.add(search)
    db.flush()
    jr = JobResult(
        search_id=search.id, user_id=user.id, position=1,
        short_id=job.short_id(), dedup_key=job.dedup_key(), tier=match.tier,
        tier_label=match.tier_label, score=match.score,
        fit_role=match.fit_role, fit_candidate=match.fit_candidate,
        title=match.role or job.title, company=match.company or job.company,
        company_url=_company_url(job), company_blurb="",
        location=match.location or job.location,
        description=(job.description or "")[:4000], apply_url=job.url, source="import",
        tags=list(match.tags), why_good=good, why_bad=bad,
    )
    db.add(jr)
    db.commit()
    log.info("Imported job for user %s: tier %s score %s (%s)",
             user.id, match.tier, match.score, url)
    return jr, search.id
