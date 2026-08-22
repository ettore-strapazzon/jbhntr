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
# Result pages per query. Careerjet is free + generous (our top source), so page
# deep; Jooble is metered (~500 calls/month), so stay shallow.
CAREERJET_PAGES = 3
JOOBLE_PAGES = 2


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
            for page in range(1, CAREERJET_PAGES + 1):
                r = c.get(
                    "http://public.api.careerjet.net/search",
                    params={
                        "keywords": term, "location": location,
                        "affid": s.careerjet_affid, "user_ip": "127.0.0.1",
                        "user_agent": "Mozilla/5.0", "url": s.careerjet_referer,
                        "locale_code": locale, "pagesize": 50, "page": page,
                    },
                    # Careerjet rejects calls without a Referer.
                    headers={"Referer": s.careerjet_referer},
                )
                if r.status_code != 200:
                    log.warning("Careerjet %s p%d: HTTP %s", term, page, r.status_code)
                    break
                page_jobs = r.json().get("jobs", []) or []
                for j in page_jobs:
                    out.append(JobPosting(
                        source="api:careerjet",
                        title=j.get("title", ""),
                        company=j.get("company", ""),
                        location=j.get("locations", ""),
                        description=strip_html(j.get("description", "")),
                        url=j.get("url", ""),
                        salary_text=j.get("salary", "") or "",
                    ))
                if len(page_jobs) < 50:
                    break                       # last page for this term
    return out


def _jooble(profile: Profile, s: Settings) -> list[JobPosting]:
    out: list[JobPosting] = []
    location = (_cities(profile) or [""])[0]
    with http_client() as c:
        for term in _terms(profile):
            for page in range(1, JOOBLE_PAGES + 1):
                r = c.post(
                    f"https://jooble.org/api/{s.jooble_key}",
                    json={"keywords": term, "location": location, "page": page},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code != 200:
                    log.warning("Jooble %s p%d: HTTP %s", term, page, r.status_code)
                    break
                page_jobs = r.json().get("jobs", []) or []
                for j in page_jobs:
                    out.append(JobPosting(
                        source="api:jooble",
                        title=j.get("title", ""),
                        company=j.get("company", ""),
                        location=j.get("location", ""),
                        description=strip_html(j.get("snippet", "")),
                        url=j.get("link", ""),
                        salary_text=j.get("salary", "") or "",
                    ))
                if not page_jobs:
                    break                       # no more results for this term
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
    """JSearch (Google-for-Jobs via RapidAPI). Uses the current /search-v2 endpoint
    (the old /search 404s) whose payload is data.jobs[] with a full job_description.
    num_pages multiplies results per query (RapidAPI bills ~x pages) — deeper pull
    for the Italy/EU backbone via JSEARCH_PAGES; country is the ISO code."""
    out: list[JobPosting] = []
    location = (_cities(profile) or [""])[0]
    country = geo.country_of(location) or ""
    pages = max(1, min(int(getattr(s, "jsearch_pages", 3) or 3), 10))
    with http_client(timeout=30.0) as c:
        for term in _terms(profile):
            params = {"query": (f"{term} in {location}".strip() if location else term),
                      "num_pages": pages, "date_posted": "all"}
            if country:
                params["country"] = country
            r = c.get("https://jsearch.p.rapidapi.com/search-v2", params=params,
                      headers={"X-RapidAPI-Key": s.jsearch_key,
                               "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
            if r.status_code != 200:
                log.warning("JSearch %s: HTTP %s — %s", term, r.status_code,
                            (r.text or "")[:200])
                continue
            for j in ((r.json().get("data") or {}).get("jobs") or []):
                loc = (", ".join(x for x in [j.get("job_city"), j.get("job_country")] if x)
                       or (j.get("job_location", "") or "").split("•")[0].strip())
                out.append(JobPosting(
                    source="api:jsearch",
                    title=j.get("job_title", ""),
                    company=j.get("employer_name", ""),
                    location=loc,
                    description=strip_html(j.get("job_description", "") or ""),
                    url=j.get("job_apply_link", ""),
                    is_remote=bool(j.get("job_is_remote")),
                ))
    return out


_FT_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
_FT_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"


def _francetravail(profile: Profile, s: Settings) -> list[JobPosting]:
    """France Travail (ex-Pôle Emploi) — the French government job API. Millions of
    FR listings with full descriptions. OAuth2 client-credentials, then search.
    Free after a one-time app registration at francetravail.io."""
    out: list[JobPosting] = []
    with http_client(timeout=30.0) as c:
        try:
            # The scope MUST include application_{client_id} — without it France
            # Travail's token endpoint 400s. This is the usual "it returns nothing".
            tok = c.post(_FT_TOKEN_URL, params={"realm": "/partenaire"},
                         data={"grant_type": "client_credentials",
                               "client_id": s.france_travail_id,
                               "client_secret": s.france_travail_secret,
                               "scope": (f"application_{s.france_travail_id} "
                                         "api_offresdemploiv2 o2dsoffre")})
        except Exception as exc:
            log.warning("France Travail token failed: %s", exc)
            return out
        if tok.status_code != 200:
            log.warning("France Travail token: HTTP %s — %s",
                        tok.status_code, (tok.text or "")[:200])
            return out
        access = (tok.json() or {}).get("access_token", "")
        if not access:
            return out
        auth = {"Authorization": f"Bearer {access}"}
        for term in _terms(profile):
            r = c.get(_FT_SEARCH_URL, params={"motsCles": term, "range": "0-49"},
                      headers=auth)
            if r.status_code not in (200, 206):
                log.warning("France Travail %s: HTTP %s", term, r.status_code)
                continue
            for j in (r.json().get("resultats") or []):
                out.append(JobPosting(
                    source="api:francetravail",
                    title=j.get("intitule", ""),
                    company=(j.get("entreprise") or {}).get("nom", ""),
                    location=(j.get("lieuTravail") or {}).get("libelle", ""),
                    description=strip_html(j.get("description", "") or ""),
                    url=(j.get("origineOffre") or {}).get("urlOrigine", ""),
                ))
    return out


_BA_KEY = "jobboerse-jobsuche"     # documented public client-id (bund.dev), no signup
_BA_SEARCH = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
_BA_DETAIL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v2/jobdetails/"
_BA_DETAIL_CAP = 30                # detail fetches per term (bound the extra calls)


def _ba_description(c, refnr: str) -> str:
    """Fetch the full JD for one Bundesagentur listing (search has titles only)."""
    from urllib.parse import quote
    try:
        r = c.get(_BA_DETAIL + quote(refnr, safe=""), headers={"X-API-Key": _BA_KEY})
        if r.status_code != 200:
            return ""
        return strip_html((r.json() or {}).get("stellenbeschreibung", "") or "")
    except Exception:
        return ""


def _bundesagentur(profile: Profile, s: Settings) -> list[JobPosting]:
    """Germany's Bundesagentur für Arbeit — the federal job API (huge). The search
    returns listings without a body, so we fetch each one's detail for the full JD
    and ONLY emit jobs where we got a real description (never add German snippets)."""
    from urllib.parse import quote
    out: list[JobPosting] = []
    hdr = {"X-API-Key": _BA_KEY}
    with http_client(timeout=30.0) as c:
        for term in _terms(profile):
            try:
                r = c.get(_BA_SEARCH, params={"was": term, "size": 50, "page": 1}, headers=hdr)
            except Exception as exc:
                log.warning("Bundesagentur %s: %s", term, exc)
                continue
            if r.status_code != 200:
                log.warning("Bundesagentur %s: HTTP %s", term, r.status_code)
                continue
            for j in (r.json().get("stellenangebote") or [])[:_BA_DETAIL_CAP]:
                refnr = j.get("refnr", "")
                desc = _ba_description(c, refnr) if refnr else ""
                if len(desc) < 200:          # no real JD -> skip (don't add a snippet)
                    continue
                ort = j.get("arbeitsort") or {}
                loc = ", ".join(x for x in [ort.get("ort"), ort.get("region"),
                                            ort.get("land")] if x)
                out.append(JobPosting(
                    source="api:bundesagentur",
                    title=j.get("titel", "") or j.get("beruf", ""),
                    company=j.get("arbeitgeber", ""),
                    location=loc or "Deutschland",
                    description=desc,
                    url=j.get("externeUrl", "")
                        or (f"https://www.arbeitsagentur.de/jobsuche/jobdetail/"
                            f"{quote(refnr, safe='')}" if refnr else ""),
                ))
    return out


def _jobtech(profile: Profile, s: Settings) -> list[JobPosting]:
    """Sweden's Arbetsförmedlingen JobTech — fully open (no key), full descriptions
    in the search response. All Swedish public listings."""
    out: list[JobPosting] = []
    with http_client(timeout=30.0) as c:
        for term in _terms(profile):
            r = c.get("https://jobsearch.api.jobtechdev.se/search",
                      params={"q": term, "limit": 100})
            if r.status_code != 200:
                log.warning("JobTech %s: HTTP %s", term, r.status_code)
                continue
            for j in (r.json().get("hits") or []):
                addr = j.get("workplace_address") or {}
                loc = ", ".join(x for x in [addr.get("municipality"),
                                            addr.get("region"), addr.get("country")] if x)
                out.append(JobPosting(
                    source="api:jobtech",
                    title=j.get("headline", ""),
                    company=(j.get("employer") or {}).get("name", ""),
                    location=loc or "Sweden",
                    description=strip_html((j.get("description") or {}).get("text", "") or ""),
                    url=j.get("webpage_url", "")
                        or (j.get("application_details") or {}).get("url", ""),
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
    ("france_travail_id", _francetravail),
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
