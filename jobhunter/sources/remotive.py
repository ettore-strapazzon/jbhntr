"""Remotive free JSON API (remote roles). No key required.

Docs: https://remotive.com/api/remote-jobs
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.remotive")


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    terms = profile.search_terms
    if not terms:
        log.warning("Remotive: no search terms configured, skipping.")
        return []
    with http_client() as client:
        for term in terms:
            try:
                resp = client.get(
                    "https://remotive.com/api/remote-jobs",
                    params={"search": term, "limit": 100},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("Remotive term %r failed: %s", term, exc)
                continue
            for item in data.get("jobs", []):
                jobs.append(_to_posting(item))
    log.info("Remotive: %d postings", len(jobs))
    return jobs


def _to_posting(item: dict) -> JobPosting:
    posted = None
    pub = item.get("publication_date")
    if pub:
        try:
            posted = datetime.fromisoformat(pub.replace("Z", "+00:00")).date()
        except Exception:
            posted = None
    return JobPosting(
        source="remotive",
        is_remote=True,  # remote-only board
        title=item.get("title", ""),
        company=item.get("company_name", ""),
        location=item.get("candidate_required_location", "Remote"),
        description=strip_html(item.get("description", "")),
        url=item.get("url", ""),
        posted_date=posted,
        salary_text=item.get("salary", "") or "",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from ..config import load_profile

    for j in fetch(load_profile(), Settings.from_env())[:5]:
        print(j.title, "|", j.company, "|", j.location)
