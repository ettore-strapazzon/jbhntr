"""Per-country scraping hints for the top staffing agencies.

A truly zero-config scraper for arbitrary agency SPAs isn't realistic — each has a
different jobs URL, API and detail endpoint. But a country's tail is dominated by
~15-20 stable agencies, so we configure those once here and let the general
pipeline (render + capture + LLM) handle everyone else.

Each hint (keyed by country code -> normalized company name):
  listing     : the URL to RENDER (where the SPA loads its jobs). Required.
  detail_api  : OPTIONAL template to fetch one job's FULL JD, when the listing API
                is summary-only. Placeholders are job-object fields; "{field:lower}"
                lowercases. e.g. Adecco's summarized list has jobId + brandName, and
                the full JD is at /job-description-details/{jobId}/{brand}/it/it-IT/job.

To add an agency: run /admin/test-browser?name=X&debug=1, read `rendered`,
`json_response_urls` and `sample_job`, and encode the listing + detail template here.
"""

from __future__ import annotations

import re

AGENCY_HINTS: dict[str, dict[str, dict]] = {
    "it": {
        "adecco": {
            "listing": "https://www.adecco.it/offerte-lavoro",
            "detail_api": ("https://www.adecco.com/api/data/jobs/"
                           "job-description-details/{jobId}/{brandName:lower}/it/it-IT/job"),
        },
        # Listing-only hints: the general extractor (captured API / JSON-LD / LLM +
        # detail-follow) fills the jobs; a detail_api is added later if the list is
        # summary-only. The value here is the CORRECT jobs URL (Manpower's jobs are at
        # /it/trova-lavoro, not the /offerte-lavoro that 404s).
        "manpower": {"listing": "https://www.manpower.it/it/trova-lavoro"},
        "etjca": {"listing": "https://career.etjca.it/jobs.php?lan=it"},
        "synergie": {"listing": "https://www.synergie-italia.it/candidato/offerte-di-lavoro"},
        # ADHR: adhr.it/offerte-di-lavoro loads candidati.adhr.it/api/it/announcements
        # (jobs carry a relative href we now follow for the JD).
        "adhr": {"listing": "https://www.adhr.it/offerte-di-lavoro"},
        # Sitemap agencies (Randstad, Gi Group, Areajob) need no hint — Rung 0 reads
        # their sitemaps for free. Add the remaining JS-only ones (Openjobmetis,
        # Orienta, Umana…) here as each is decoded.
    },
}

# Correct employer domain when Clearbit mis-resolves an ambiguous agency name to a
# wrong (often foreign) site. Checked BEFORE Clearbit/guessing in _resolve_domain.
# Keyed by country -> normalized name. (Orienta -> a Malaysian paper, Ali -> Alight,
# Synergie's real site is synergie-italia.it not synergie.it.)
DOMAIN_OVERRIDES: dict[str, dict[str, str]] = {
    "it": {
        "synergie": "synergie-italia.it",
        "ali": "alispa.it",
        "orienta": "orienta.it",
        "during": "during.it",
    },
}


# Companies that dominate the thin tail but are NOT a single scrapable employer —
# job-board aggregators (their "jobs" come from many companies, like careerjet) or
# obvious non-agencies. Skipped by the agency scrape and flagged in the monitor so
# they stop showing as "needs scrape". Global (a board is a board everywhere).
NOT_SCRAPABLE = {
    "impiegando", "jobcamere", "jobrapido", "jooble", "indeed", "linkedin",
    "glassdoor", "monster", "infojobs", "subito", "bakeca", "trovit",
}


def is_ignored(company: str) -> bool:
    """True if `company` is an aggregator/board we shouldn't try to scrape."""
    norm = _norm(company)
    return bool(norm) and any(norm == k or k in norm for k in NOT_SCRAPABLE)


def domain_for(company: str, country: str) -> str:
    """A pinned correct domain for a mis-resolving agency, or "" if none."""
    market = DOMAIN_OVERRIDES.get((country or "").lower(), {})
    norm = _norm(company)
    if not norm:
        return ""
    for key, dom in market.items():
        if norm == key or norm.startswith(key) or key in norm:
            return dom
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def hint_for(company: str, country: str) -> dict | None:
    """The hint for a company in a market, matched on the normalized name."""
    market = AGENCY_HINTS.get((country or "").lower(), {})
    norm = _norm(company)
    if not norm:
        return None
    for key, hint in market.items():
        if norm == key or norm.startswith(key) or key in norm:
            return hint
    return None
