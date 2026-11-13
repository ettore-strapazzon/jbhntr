"""Scheduled-ingestion plan (PRIVATE engine side).

Carved out of ``web/app/services/ingest.py`` (R3-16): which aggregators run in
Lane A (and which are queried per country with localized titles), which keyed
providers run in Lane B and the setting that enables each, their cadence
(fitted to each provider's metered quota), single-country providers, the broad
fallback terms/countries for a cold corpus, and the volume floors/ceilings. The
shell's ingest runner reads it through ``jbhntr_engine.INGEST_PLAN``.
"""

from __future__ import annotations

INGEST_PLAN: dict = {
    # No-key sources that return broadly (Lane A). Boards are added in full.
    "lane_a_aggregators": ("adzuna", "remotive", "remoteok", "arbeitnow"),
    # Aggregators worth querying PER COUNTRY with localized role titles. The others
    # are English-language remote-only boards — one global call is enough.
    "localized_aggregators": frozenset({"adzuna"}),
    # Lane B — keyed/metered providers: name -> the Settings attr that enables it.
    # Each only runs if its key is set. SerpApi sends country + language (gl/hl) and
    # is paid + metered, so it runs weekly and stays tightly capped. Findwork is out:
    # its links are profile-gated, ephemeral pages.
    "keyed_settings": {
        "careerjet": "careerjet_affid",
        "reed": "reed_key",
        "web3career": "web3career_key",
        "usajobs": "usajobs_key",
        "jsearch": "jsearch_key",
        "serpapi": "serpapi_key",
        "francetravail": "france_travail_id",     # gov FR, full JD
        "jobtech": "jobtech_enabled",             # gov SE, keyless, full JD
        "bundesagentur": "bundesagentur_enabled",  # gov DE, keyless, detail-fetched
    },
    # The metered ceilings run weekly; everything else daily.
    "source_cadence": {
        "careerjet": "daily", "reed": "daily",
        "web3career": "daily", "usajobs": "daily",
        # JSearch is the Italy backbone with budget headroom — daily.
        "jsearch": "daily", "serpapi": "weekly",
        "francetravail": "daily", "jobtech": "daily",   # free gov APIs
        "bundesagentur": "weekly",                       # per-job detail calls
    },
    # Single-country providers ignore the active-user country set.
    "source_countries": {
        "reed": ["United Kingdom"],
        "usajobs": ["United States"],
        "francetravail": ["France"],
        "jobtech": ["Sweden"],
        "bundesagentur": ["Germany"],
    },
    # Fallbacks so a cold corpus still ingests something broad; user-derived
    # terms/countries take priority.
    "default_terms": [
        "chief of staff", "business operations", "operations manager",
        "head of operations", "strategy", "project manager", "product manager",
        "program manager", "general manager", "founders associate",
    ],
    "default_countries": ["United States", "United Kingdom", "Italy", "Germany",
                          "France", "Spain", "Canada"],
    # Floors give a cold corpus broad coverage; ceilings bound API-call volume.
    "terms_cap": 25, "terms_max": 40,
    "countries_cap": 7, "countries_max": 10,
    "agency_markets": 7,     # top active markets to scrape agency portals for
    "agency_n": 10,          # top thin-JD companies per market to resolve+scrape
}
