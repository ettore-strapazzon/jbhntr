"""Aggregator APIs that need an API key.

Each one activates only when its key is present in `.env`, so this module is a
no-op until you add credentials. Nothing here is required.

Free (key by signup/request):
  * Careerjet   — ~90 countries incl. Italy   CAREERJET_AFFID
  * Jooble      — ~70 countries incl. Italy   JOOBLE_API_KEY
  * Reed        — UK                          REED_API_KEY
  * Findwork    — tech/developer              FINDWORK_API_KEY
  * Web3.career — crypto/web3 (freemium)      WEB3CAREER_API_KEY

Paid (metered per search):
  * SerpApi     — Google for Jobs, which indexes Indeed / LinkedIn / Glassdoor
                  in a single call. 250 free searches/month.   SERPAPI_KEY
  * JSearch     — a cheaper Google-Jobs wrapper via RapidAPI.  JSEARCH_API_KEY

⚠️ The request/response shapes below follow each provider's published API docs
but are **not runtime-verified** — we have no keys to test with. If one returns
nothing after you add a key, run with `-v` and check the logged response; the
mapping is the likely culprit, and each fetcher fails soft.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .. import geo
from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.keyed")

MAX_TERMS = 5          # queries per API per run, to bound cost
RESULTS_PER_QUERY = 50


# "Remote-EU"/"Remote-Anywhere" name no country a jobs API can search.
_GENERIC_REGIONS = {"eu", "europe", "emea", "anywhere", "worldwide", "global", "us"}


def _cities(profile: Profile) -> list[str]:
    """Place names these APIs can actually search.

    'Remote-XX' is not a valid query, but the country inside it is — and a
    country subsumes its cities, so 'Remote-Italy' is worth more than 'Milan'
    when the caller only gets two searches. Countries therefore come first.
    """
    countries, cities = [], []
    for loc in profile.locations:
        token = loc.strip()
        if not token:
            continue
        if token.lower().startswith("remote"):
            region = token.split("-", 1)[1].strip() if "-" in token else ""
            if region and region.lower() not in _GENERIC_REGIONS:
                countries.append(region)
        else:
            cities.append(token)
    return list(dict.fromkeys(countries + cities))


def _terms(profile: Profile) -> list[str]:
    return (profile.search_terms or ["chief of staff"])[:MAX_TERMS]


# --------------------------------------------------------------------------- #
def _careerjet(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    # Locale follows the user's country, not a global default, so a US user
    # gets en_US rather than the operator's home locale.
    locale = geo.careerjet_locale(profile, default=s.careerjet_locale or "en_GB")
    location = (_cities(profile) or [""])[0]
    with http_client() as c:
        for term in _terms(profile):
            r = c.get(
                "http://public.api.careerjet.net/search",
                params={
                    "keywords": term, "location": location,
                    "affid": s.careerjet_affid, "user_ip": "127.0.0.1",
                    "user_agent": "Mozilla/5.0", "url": s.careerjet_referer,
                    "locale_code": locale, "pagesize": 50,
                },
                # Careerjet rejects calls without a Referer.
                headers={"Referer": s.careerjet_referer},
            )
            if r.status_code != 200:
                log.warning("Careerjet %s: HTTP %s", term, r.status_code)
                continue
            for j in r.json().get("jobs", []) or []:
                out.append(JobPosting(
                    source="api:careerjet",
                    title=j.get("title", ""),
                    company=j.get("company", ""),
                    location=j.get("locations", ""),
                    description=strip_html(j.get("description", "")),
                    url=j.get("url", ""),
                    salary_text=j.get("salary", "") or "",
                ))
    return out


def _jooble(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    location = (_cities(profile) or [""])[0]
    with http_client() as c:
        for term in _terms(profile):
            r = c.post(
                f"https://jooble.org/api/{s.jooble_key}",
                json={"keywords": term, "location": location},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code != 200:
                log.warning("Jooble %s: HTTP %s", term, r.status_code)
                continue
            for j in r.json().get("jobs", []) or []:
                out.append(JobPosting(
                    source="api:jooble",
                    title=j.get("title", ""),
                    company=j.get("company", ""),
                    location=j.get("location", ""),
                    description=strip_html(j.get("snippet", "")),
                    url=j.get("link", ""),
                    salary_text=j.get("salary", "") or "",
                ))
    return out


def _reed(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    with http_client() as c:
        for term in _terms(profile):
            r = c.get(
                "https://www.reed.co.uk/api/1.0/search",
                params={"keywords": term, "resultsToTake": RESULTS_PER_QUERY},
                auth=(s.reed_key, ""),  # key as username, blank password
            )
            if r.status_code != 200:
                log.warning("Reed %s: HTTP %s", term, r.status_code)
                continue
            for j in r.json().get("results", []) or []:
                out.append(JobPosting(
                    source="api:reed",
                    title=j.get("jobTitle", ""),
                    company=j.get("employerName", ""),
                    location=j.get("locationName", ""),
                    description=strip_html(j.get("jobDescription", "")),
                    url=j.get("jobUrl", ""),
                ))
    return out


def _findwork(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    with http_client() as c:
        for term in _terms(profile):
            r = c.get(
                "https://findwork.dev/api/jobs/",
                params={"search": term},
                headers={"Authorization": f"Token {s.findwork_key}"},
            )
            if r.status_code != 200:
                log.warning("Findwork %s: HTTP %s", term, r.status_code)
                continue
            for j in r.json().get("results", []) or []:
                out.append(JobPosting(
                    source="api:findwork",
                    title=j.get("role", ""),
                    company=j.get("company_name", ""),
                    location=j.get("location", "") or ("Remote" if j.get("remote") else ""),
                    description=strip_html(j.get("text", "")),
                    url=j.get("url", ""),
                ))
    return out


def _web3career(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    with http_client() as c:
        r = c.get(
            "https://web3.career/api/v1",
            params={"token": s.web3career_key, "limit": 100},
        )
        if r.status_code != 200:
            log.warning("Web3.career: HTTP %s", r.status_code)
            return out
        data: Any = r.json()
        # Documented response is [count, "jobs", [ ...jobs... ]].
        items = data
        if isinstance(data, list):
            items = next((x for x in data if isinstance(x, list)), [])
        elif isinstance(data, dict):
            items = data.get("jobs", [])
        for j in items or []:
            if not isinstance(j, dict):
                continue
            out.append(JobPosting(
                source="api:web3career",
                title=j.get("title", ""),
                company=j.get("company", ""),
                location=j.get("location", ""),
                description=strip_html(j.get("description", "") or ""),
                url=j.get("apply_url") or j.get("url", ""),
            ))
    return out


def _serpapi(profile: Profile, s: Settings) -> list[JobPosting]:
    """Google for Jobs — indexes Indeed, LinkedIn, Glassdoor and company sites.

    Each call is one billed 'search'. Terms x locations is the cost driver, so
    both are capped.
    """
    out: list[JobPosting] = []
    locations = (_cities(profile) or [""])[: s.serpapi_max_locations]
    with http_client(timeout=30.0) as c:
        for term in _terms(profile)[: s.serpapi_max_terms]:
            for loc in locations:
                # Country + language for the location, so a non-English market
                # (Italy → gl=it, hl=it) isn't served US/English results (empty).
                gl, hl = geo.google_locale(loc)
                params = {"engine": "google_jobs", "q": term, "location": loc,
                          "api_key": s.serpapi_key, "hl": hl}
                if gl:
                    params["gl"] = gl
                r = c.get("https://serpapi.com/search", params=params)
                if r.status_code != 200:
                    log.warning("SerpApi %s/%s: HTTP %s", term, loc, r.status_code)
                    continue
                for j in r.json().get("jobs_results", []) or []:
                    apply_opts = j.get("apply_options") or []
                    url = apply_opts[0].get("link", "") if apply_opts else j.get("share_link", "")
                    out.append(JobPosting(
                        source="api:serpapi",
                        title=j.get("title", ""),
                        company=j.get("company_name", ""),
                        location=j.get("location", ""),
                        description=strip_html(j.get("description", "")),
                        url=url,
                    ))
    return out


def _usajobs(profile: Profile, s: Settings) -> list[JobPosting]:
    """US federal jobs — every function, government-wide. Free, authoritative.

    Auth is a free API key plus your registered email in the User-Agent header
    (https://developer.usajobs.gov/apirequest/). Only meaningful for US-based
    or US-remote searches, so we skip it when the profile implies no US intent.
    """
    from .. import geo

    if "us" not in geo.countries(profile, limit=5):
        return []
    out: list[JobPosting] = []
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": s.usajobs_email or "jobhunter@example.com",
        "Authorization-Key": s.usajobs_key,
    }
    with http_client(timeout=30.0) as c:
        for term in _terms(profile):
            r = c.get(
                "https://data.usajobs.gov/api/search",
                params={"Keyword": term, "ResultsPerPage": 50},
                headers=headers,
            )
            if r.status_code != 200:
                log.warning("USAJOBS %s: HTTP %s", term, r.status_code)
                continue
            items = (r.json().get("SearchResult", {}) or {}).get("SearchResultItems", []) or []
            for it in items:
                d = it.get("MatchedObjectDescriptor", {}) or {}
                details = (d.get("UserArea", {}) or {}).get("Details", {}) or {}
                out.append(JobPosting(
                    source="api:usajobs",
                    title=d.get("PositionTitle", ""),
                    company=d.get("OrganizationName", ""),
                    location=d.get("PositionLocationDisplay", ""),
                    description=strip_html(details.get("JobSummary", "") or ""),
                    url=d.get("PositionURI", ""),
                ))
    return out


def _jsearch(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    location = (_cities(profile) or [""])[0]
    with http_client(timeout=30.0) as c:
        for term in _terms(profile):
            r = c.get(
                "https://jsearch.p.rapidapi.com/search",
                params={"query": f"{term} {location}".strip(), "page": 1, "num_pages": 1},
                headers={
                    "X-RapidAPI-Key": s.jsearch_key,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                },
            )
            if r.status_code != 200:
                log.warning("JSearch %s: HTTP %s", term, r.status_code)
                continue
            for j in r.json().get("data", []) or []:
                loc = ", ".join(
                    x for x in [j.get("job_city"), j.get("job_country")] if x
                )
                out.append(JobPosting(
                    source="api:jsearch",
                    title=j.get("job_title", ""),
                    company=j.get("employer_name", ""),
                    location=loc,
                    description=strip_html(j.get("job_description", "") or ""),
                    url=j.get("job_apply_link", ""),
                ))
    return out


# --------------------------------------------------------------------------- #
# (setting attribute that enables it, fetcher)
PROVIDERS: list[tuple[str, Callable[[Profile, Settings], list[JobPosting]]]] = [
    ("careerjet_affid", _careerjet),
    ("jooble_key", _jooble),
    ("reed_key", _reed),
    ("findwork_key", _findwork),
    ("web3career_key", _web3career),
    ("usajobs_key", _usajobs),
    ("serpapi_key", _serpapi),
    ("jsearch_key", _jsearch),
]


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for attr, fn in PROVIDERS:
        if not getattr(settings, attr, ""):
            continue  # no key configured — silently skip
        name = fn.__name__.lstrip("_")
        try:
            found = fn(profile, settings)
            jobs.extend(found)
            log.info("API %s: %d postings", name, len(found))
        except Exception as exc:
            log.warning("API %s failed: %s", name, exc)
    return jobs


def configured(settings: Settings) -> list[str]:
    """Names of the keyed APIs that are currently switched on."""
    return [
        fn.__name__.lstrip("_")
        for attr, fn in PROVIDERS
        if getattr(settings, attr, "")
    ]
