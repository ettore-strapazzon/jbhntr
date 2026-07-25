"""Adzuna free API — the reliable keyword-based backbone.

Docs: https://developer.adzuna.com/  (free tier: app_id + app_key)
One request per search term. Fails soft (returns []) if keys are missing.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .. import geo
from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.adzuna")

RESULTS_PER_PAGE = 50

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
        for country in country_list:
            location = _where(profile, country)
            for term in profile.search_terms:
                url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
                params = {
                    "app_id": settings.adzuna_app_id,
                    "app_key": settings.adzuna_app_key,
                    "results_per_page": RESULTS_PER_PAGE,
                    "what": term,
                    "content-type": "application/json",
                }
                if location:
                    params["where"] = location
                try:
                    resp = client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    log.warning("Adzuna %s/%r failed: %s", country, term, exc)
                    continue

                for item in data.get("results", []):
                    jobs.append(_to_posting(item))

    log.info("Adzuna: %d postings across %s", len(jobs), ", ".join(country_list))
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
