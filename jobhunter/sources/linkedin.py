"""LinkedIn — BEST-EFFORT, ISOLATED guest scraper.

Uses LinkedIn's unauthenticated guest job-search endpoint
(`/jobs-guest/jobs/api/seeMoreJobPostings/search`) which returns HTML job
cards without login. This WILL get rate-limited or blocked periodically — it is
deliberately fail-soft (returns whatever it got, or []) so the rest of the
pipeline never depends on it. Treated as a bonus source, not the foundation.

There is no viable official LinkedIn jobs API for an individual (see the plan).
If this proves too flaky, the documented paid fallback is a low-cost
third-party scraper for LinkedIn only.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client

log = logging.getLogger("jobhunter.sources.linkedin")

GUEST_ENDPOINT = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)

# Rotate UA per request to look less scripted.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

PAGES_PER_SEARCH = 2          # each page = 25 cards
# Descriptions are NOT fetched here. Card listings have no body, and fetching
# them upfront meant paying for jobs we'd never score while still leaving most
# listings body-less (which quietly buried real matches). The pipeline now
# fetches descriptions lazily, only for the jobs about to be scored — see
# jobhunter.sources.ats.enrich_description.
FETCH_DESCRIPTIONS = False
MAX_DESCRIPTIONS = 15          # only used if FETCH_DESCRIPTIONS is re-enabled
POLITE_DELAY_S = 1.2           # between requests


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    urls = profile.linkedin_search_urls
    if not urls:
        return []

    jobs: list[JobPosting] = []
    desc_budget = MAX_DESCRIPTIONS
    req = 0
    for search_url in urls:
        keywords, location = _params_from_url(search_url)
        for page in range(PAGES_PER_SEARCH):
            ua = USER_AGENTS[req % len(USER_AGENTS)]
            req += 1
            cards = _fetch_cards(keywords, location, page * 25, ua)
            if not cards:
                break  # blocked or exhausted for this search
            for card in cards:
                jobs.append(card)
            time.sleep(POLITE_DELAY_S)

    if FETCH_DESCRIPTIONS:
        for job in jobs:
            if desc_budget <= 0:
                break
            if job.url:
                desc = _fetch_description(job.url, USER_AGENTS[desc_budget % 3])
                if desc:
                    job.description = desc
                desc_budget -= 1
                time.sleep(POLITE_DELAY_S)

    log.info("LinkedIn: %d postings (best-effort)", len(jobs))
    return jobs


def _params_from_url(search_url: str) -> tuple[str, str]:
    q = parse_qs(urlparse(search_url).query)
    keywords = (q.get("keywords") or [""])[0]
    location = (q.get("location") or [""])[0]
    return keywords, location


def _fetch_cards(keywords: str, location: str, start: int, ua: str) -> list[JobPosting]:
    params = {"keywords": keywords, "location": location, "start": start}
    try:
        with http_client(ua=ua) as client:
            resp = client.get(GUEST_ENDPOINT, params=params)
            if resp.status_code != 200:
                log.warning("LinkedIn returned %s (likely rate-limited)", resp.status_code)
                return []
            html = resp.text
    except Exception as exc:
        log.warning("LinkedIn card fetch failed: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    out: list[JobPosting] = []
    for li in soup.select("li"):
        title_el = li.select_one("h3")
        company_el = li.select_one("h4")
        loc_el = li.select_one(".job-search-card__location")
        link_el = li.select_one("a")
        if not title_el or not link_el:
            continue
        out.append(
            JobPosting(
                source="linkedin",
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=loc_el.get_text(strip=True) if loc_el else location,
                url=(link_el.get("href") or "").split("?")[0],
            )
        )
    return out


def _fetch_description(job_url: str, ua: str) -> str:
    try:
        with http_client(ua=ua) as client:
            resp = client.get(job_url)
            if resp.status_code != 200:
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")
            el = soup.select_one(".show-more-less-html__markup") or soup.select_one(
                ".description__text"
            )
            return el.get_text(" ", strip=True) if el else ""
    except Exception:
        return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from ..config import load_profile

    for j in fetch(load_profile(), Settings.from_env())[:5]:
        print(j.title, "|", j.company, "|", j.location, "|", j.url)
