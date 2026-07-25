"""Arbeitnow free job-board API (EU-heavy). No key required.

Endpoint: https://www.arbeitnow.com/api/job-board-api  (paginated via ?page=)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.arbeitnow")

MAX_PAGES = 3  # keep it light; newest jobs are on the first pages


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    with http_client() as client:
        for page in range(1, MAX_PAGES + 1):
            try:
                resp = client.get(
                    "https://www.arbeitnow.com/api/job-board-api",
                    params={"page": page},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("Arbeitnow page %d failed: %s", page, exc)
                break
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                jobs.append(_to_posting(item))
    log.info("Arbeitnow: %d postings", len(jobs))
    return jobs


def _to_posting(item: dict) -> JobPosting:
    posted = None
    ts = item.get("created_at")
    if ts:
        try:
            posted = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        except Exception:
            posted = None
    location = item.get("location", "")
    if item.get("remote"):
        location = (location + " (remote)").strip()
    return JobPosting(
        source="arbeitnow",
        title=item.get("title", ""),
        company=item.get("company_name", ""),
        location=location,
        description=strip_html(item.get("description", "")),
        url=item.get("url", ""),
        posted_date=posted,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from ..config import load_profile

    for j in fetch(load_profile(), Settings.from_env())[:5]:
        print(j.title, "|", j.company, "|", j.location)
