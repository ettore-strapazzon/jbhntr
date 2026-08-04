"""Adzuna free API — the reliable keyword-based backbone.

Docs: https://developer.adzuna.com/  (free tier: app_id + app_key)
One request per search term. Fails soft (returns []) if keys are missing.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from .. import geo
from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.adzuna")

RESULTS_PER_PAGE = 50
_PACE = 0.25       # polite gap between calls; the free tier limits ~25/min
_MAX_429 = 4       # retries when rate-limited, with exponential backoff


def _get_page(client, url: str, params: dict) -> dict | None:
    """One Adzuna page, backing off on 429 (the free tier's rate limit). Returns
    the JSON, or None on a non-recoverable error."""
    for attempt in range(_MAX_429):
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429:          # rate limited — wait and retry
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt == _MAX_429 - 1:
                log.warning("Adzuna %s failed: %s", url, exc)
                return None
            time.sleep(2 ** attempt)
    return None

# The endpoint is already scoped to one country, so "where=Italy" on the /it/
# endpoint matches nothing and silently returns zero results. Only a city or
# region is a useful narrowing; anything country-level we drop.
COUNTRY_WORDS = {
    "italy", "italia", "united kingdom", "uk", "great britain", "england",
    "united states", "usa", "us", "germany", "deutschland", "france",
    "spain", "españa", "netherlands", "poland", "austria", "switzerland",
    "belgium", "ireland", "portugal", "canada", "australia", "europe", "eu",
}


def _where(profile: Profile, country: str) -> str:
    """The city to narrow to, or "" to search the whole country.

    `where` only ever narrows, and Adzuna can't express what our own prefilter
    can: a country name returns nothing on a country-scoped endpoint, and
    pinning to one city silently drops the Remote-<region> jobs the candidate
    also asked for. So we narrow only in the unambiguous case — a single city,
    no remote tokens — and otherwise pull the country and filter ourselves.
    """
    cities = []
    for loc in profile.locations:
        token = loc.strip()
        if not token:
            continue
        if token.lower().startswith("remote"):
            return ""                       # wants remote too: don't pin a city
        if token.lower() in COUNTRY_WORDS:
            continue
        cities.append(token)
    return cities[0] if len(cities) == 1 else ""


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    if not (settings.adzuna_app_id and settings.adzuna_app_key):
        log.info("Adzuna: no credentials set, skipping.")
        return []

    # Query the countries the USER'S profile implies, not one global default.
    # The endpoint is per-country, so a hardcoded code served (e.g.) US users
    # Italian jobs. Fall back to the configured default only when nothing in
    # the profile resolves to a supported country.
    country_list = geo.countries(profile) or [settings.adzuna_country or "gb"]

    jobs: list[JobPosting] = []
    with http_client() as client:
        # No hardcoded fallback query: a wrong default (it used to be
        # "backend engineer") floods the run with irrelevant jobs. The pipeline
        # fills search_terms from the candidate's derived target roles instead.
        if not profile.search_terms:
            log.warning("Adzuna: no search terms configured, skipping.")
            return []
        pages = max(1, settings.adzuna_pages)
        for country in country_list:
            location = _where(profile, country)
            for term in profile.search_terms:
                # Page through results (was: only page 1 = 50 jobs/term), so we
                # capture far more of Adzuna's inventory per query. Stop early on
                # the last page. Paced + 429-backed-off to respect the free tier.
                for page in range(1, pages + 1):
                    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
                    params = {
                        "app_id": settings.adzuna_app_id,
                        "app_key": settings.adzuna_app_key,
                        "results_per_page": RESULTS_PER_PAGE,
                        "what": term,
                        "content-type": "application/json",
                    }
                    if location:
                        params["where"] = location
                    data = _get_page(client, url, params)
                    if data is None:
                        break
                    results = data.get("results", [])
                    for item in results:
                        jobs.append(_to_posting(item))
                    if len(results) < RESULTS_PER_PAGE:
                        break               # no more pages for this query
                    time.sleep(_PACE)

    log.info("Adzuna: %d postings across %s (%d pages/query)",
             len(jobs), ", ".join(country_list), pages)
    return jobs


def _to_posting(item: dict) -> JobPosting:
    posted = None
    created = item.get("created")
    if created:
        try:
            posted = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
        except Exception:
            posted = None

    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    salary_text = ""
    if salary_min or salary_max:
        salary_text = f"{int(salary_min or 0)}-{int(salary_max or 0)}"

    return JobPosting(
        source="adzuna",
        title=item.get("title", ""),
        company=(item.get("company") or {}).get("display_name", ""),
        location=(item.get("location") or {}).get("display_name", ""),
        description=strip_html(item.get("description", "")),
        url=item.get("redirect_url", ""),
        posted_date=posted,
        salary_text=salary_text,
    )


if __name__ == "__main__":  # manual smoke test
    logging.basicConfig(level=logging.INFO)
    from ..config import load_profile

    for j in fetch(load_profile(), Settings.from_env())[:5]:
        print(j.title, "|", j.company, "|", j.location)
