"""RemoteOK free JSON API (remote roles). No key required.

Endpoint: https://remoteok.com/api  (first array element is a legal notice)
Not keyword-filtered server-side; we return everything and let the matcher
plus keyword pre-filter do the screening.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.remoteok")


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    with http_client() as client:
        try:
            resp = client.get("https://remoteok.com/api")
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("RemoteOK failed: %s", exc)
            return []

    for item in data:
        # Skip the leading legal/disclaimer object which lacks a position.
        if not isinstance(item, dict) or not item.get("position"):
            continue
        jobs.append(_to_posting(item))
    log.info("RemoteOK: %d postings", len(jobs))
    return jobs


def _to_posting(item: dict) -> JobPosting:
    posted = None
    date_str = item.get("date")
    if date_str:
        try:
            posted = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except Exception:
            posted = None
    tags = item.get("tags") or []
    return JobPosting(
        source="remoteok",
        is_remote=True,  # remote-only board
        title=item.get("position", ""),
        company=item.get("company", ""),
        location=item.get("location") or "Remote",
        description=strip_html(item.get("description", ""))
        + (" | tags: " + ", ".join(tags) if tags else ""),
        url=item.get("url", ""),
        posted_date=posted,
        salary_text=_salary(item),
    )


def _salary(item: dict) -> str:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo or hi:
        return f"{int(lo or 0)}-{int(hi or 0)}"
    return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from ..config import load_profile

    for j in fetch(load_profile(), Settings.from_env())[:5]:
        print(j.title, "|", j.company, "|", j.location)
