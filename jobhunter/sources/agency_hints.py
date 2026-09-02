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
        # Sitemap agencies (Randstad, Gi Group, Areajob) need no hint — Rung 0 reads
        # their sitemaps for free. Add the JS-only ones (Manpower, Synergie,
        # Openjobmetis, ADHR, Etjca, Orienta, Umana…) here as each is decoded.
    },
}


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
