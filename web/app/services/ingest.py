"""Scheduled ingestion — fill the shared corpus for everyone, on a schedule.

Step 1 of the ingestion engine (docs/INGESTION_ENGINE.md): Lanes A + B.
Company ATS discovery (Lane C) and the search rewire come later.

This is WRITE-ONLY: it fetches broadly and upserts into the `jobs` corpus via
the same write-through used by live search. It does not touch the search path,
so it cannot change any user's results — exactly the risk profile of slice 1.

Run from cron:
    python -m web.app.services.ingest --cadence daily    # Lane A + daily Lane-B
    python -m web.app.services.ingest --cadence weekly    # metered (Jooble, JSearch)

Cadence exists to fit metered free quotas (see INGESTION_ENGINE.md §11b): the
two binding sources, Jooble (500/mo) and JSearch (~200/mo), run weekly; the rest
run daily.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter

from jobhunter import geo
from jobhunter.config import Profile, Settings
from jobhunter.sources import AGGREGATORS, boards, keyed

from ..db import SessionLocal
from ..models import Profile as ProfileRow
from .corpus_service import upsert_jobs
from .profile_service import COUNTRIES as PICKER_COUNTRIES

log = logging.getLogger("jbhntr.ingest")

# No-key sources that return broadly (Lane A). Boards are added in full below.
LANE_A_AGGREGATORS = ["adzuna", "remotive", "remoteok", "arbeitnow"]

# Lane B — metered/keyed sources: name -> (settings attr that enables it, fn).
# Each only runs if its key is set, so listing one is harmless when unconfigured.
# SerpApi (Google-for-Jobs) is included again now its query sends the country +
# language (gl/hl) — it previously came back empty for the EU because it defaulted
# to US/English. It is paid + metered, so it runs weekly and stays tightly capped
# (serpapi_max_terms × serpapi_max_locations).
KEYED_SOURCES = {
    "careerjet": ("careerjet_affid", keyed._careerjet),
    "jooble": ("jooble_key", keyed._jooble),
    "reed": ("reed_key", keyed._reed),
    "web3career": ("web3career_key", keyed._web3career),
    "usajobs": ("usajobs_key", keyed._usajobs),
    "jsearch": ("jsearch_key", keyed._jsearch),
    "serpapi": ("serpapi_key", keyed._serpapi),
}
# Findwork removed: its links are its own findwork.dev pages, which are
# profile-gated AND ephemeral (they 404 once the listing rotates), so a user
# clicking through hits a wall or a dead page. findwork.dev is also on
# GATED_HOSTS, so any leftover rows get cleaned out.

# The metered ceilings run weekly; everything else daily (§11b).
SOURCE_CADENCE = {
    "careerjet": "daily", "jooble": "weekly", "reed": "daily",
    "web3career": "daily", "usajobs": "daily",
    "jsearch": "weekly", "serpapi": "weekly",
}

# Single-country sources ignore the active-user country set.
SOURCE_COUNTRIES = {
    "reed": ["United Kingdom"],
    "usajobs": ["United States"],
    "jsearch": ["United States"],
}

# Fallbacks so a cold corpus (or a user who typed no terms) still ingests
# something broad. User-derived terms/countries take priority over these.
DEFAULT_TERMS = [
    "chief of staff", "business operations", "operations manager",
    "head of operations", "strategy", "project manager", "product manager",
    "program manager", "general manager", "founders associate",
]
DEFAULT_COUNTRIES = ["United States", "United Kingdom", "Italy", "Germany", "France"]

# Floors give a cold/small corpus broad coverage; ceilings bound API-call volume
# (countries × terms × pages × sources). Between them, EVERY active user's own
# countries and terms are always included — so a new profile's country/term is
# ingested from the next run, never crowded out by the defaults.
TERMS_CAP = 25          # pad user terms up to this with defaults
TERMS_MAX = 40          # absolute ceiling
COUNTRIES_CAP = 6       # pad user countries up to this with defaults
COUNTRIES_MAX = 10      # absolute ceiling

# code -> display name, built from the picker list so provider locations resolve.
_CODE_TO_NAME: dict[str, str] = {}
for _nm in PICKER_COUNTRIES:
    _c = geo.country_of(_nm)
    if _c:
        _CODE_TO_NAME.setdefault(_c, _nm)


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def corpus_terms(db) -> list[str]:
    """Every active user's terms (by demand) first, padded with broad defaults up
    to the floor. Includes BOTH the titles they typed and the roles the engine
    derived from their objective + CV, so the corpus is built around what people
    actually want. All user terms are kept (up to the ceiling)."""
    counter: Counter[str] = Counter()
    for p in db.query(ProfileRow):
        for t in list(p.search_terms or []) + list(p.derived_roles or []):
            t = (t or "").strip()
            if t:
                counter[t] += 1
    out: list[str] = [t for t, _ in counter.most_common()]   # user terms, prioritised
    for d in DEFAULT_TERMS:
        if d not in out and len(out) < TERMS_CAP:            # pad to the floor only
            out.append(d)
    return out[:TERMS_MAX]


def corpus_countries(db) -> list[str]:
    """Every active user's countries first, padded with broad defaults up to the
    floor. All user countries are kept (up to the ceiling)."""
    out: list[str] = []
    for p in db.query(ProfileRow):
        for loc in (p.locations or []):
            name = _CODE_TO_NAME.get(geo.country_of(loc))
            if name and name not in out:
                out.append(name)
    for d in DEFAULT_COUNTRIES:
        if d not in out and len(out) < COUNTRIES_CAP:        # pad to the floor only
            out.append(d)
    return out[:COUNTRIES_MAX]


def _fetch(label: str, fn, *args) -> list:
    """Call one source, fail soft — a bad source never aborts the cycle."""
    try:
        jobs = fn(*args)
        log.info("ingest %s: %d postings", label, len(jobs))
        return jobs
    except Exception as exc:
        log.warning("ingest %s failed: %s", label, exc)
        return []


def _lane_a(settings: Settings, terms: list[str], countries: list[str]) -> list:
    """Global feeds + broad no-key aggregators."""
    postings: list = []
    prof = Profile(raw={
        "locations": countries,
        "sources": {
            "boards": list(boards.BOARDS),
            "aggregators": LANE_A_AGGREGATORS,
            "search_terms": terms,
        },
    })
    postings += _fetch("boards", boards.fetch, prof, settings)
    for name in LANE_A_AGGREGATORS:
        fn = AGGREGATORS.get(name)
        if fn:
            postings += _fetch(name, fn, prof, settings)
    return postings


def _lane_b(settings: Settings, terms: list[str], countries: list[str], cadence: str) -> list:
    """Metered/keyed sources whose cadence matches this run."""
    postings: list = []
    for name, (attr, fn) in KEYED_SOURCES.items():
        if SOURCE_CADENCE.get(name) != cadence:
            continue
        if not getattr(settings, attr, ""):
            continue  # no key configured
        src_countries = SOURCE_COUNTRIES.get(name, countries)
        for country in src_countries:
            # Providers cap terms at keyed.MAX_TERMS internally, so batch to
            # cover the full corpus term set without exceeding per-call limits.
            for batch in _chunks(terms, keyed.MAX_TERMS):
                prof = Profile(raw={
                    "locations": [country],
                    "sources": {"search_terms": batch},
                })
                postings += _fetch(f"{name}/{country}", fn, prof, settings)
    return postings


def _lane_c(db, settings: Settings) -> list:
    """Company ATS boards from the shared registry (public feeds, unmetered)."""
    from .companies_service import poll_all
    return _fetch("companies", poll_all, db, settings)


def run(cadence: str = "daily") -> dict:
    """One ingestion cycle. Owns its DB session. Never raises."""
    db = SessionLocal()
    try:
        settings = Settings.from_env()
        terms = corpus_terms(db)
        countries = corpus_countries(db)
        log.info("ingest %s: %d terms x %d countries", cadence, len(terms), len(countries))

        # 'discover' is a registry-refresh only (pricey LLM+web-search); it
        # writes companies, not jobs, so daily Lane C then polls them.
        if cadence == "discover":
            from .companies_service import (
                discover_all_active, scrape_custom_companies,
            )
            res = discover_all_active(db)
            # Scrape the careers pages of non-ATS companies discovery registered
            # (premium-sourced, but the jobs land in the shared corpus for all).
            scraped = scrape_custom_companies(db, settings)
            log.info("ingest discover: %s | custom-scrape: %s", res, scraped)
            return {"cadence": "discover", **res, "custom_scrape": scraped}

        postings: list = []
        if cadence == "daily":
            postings += _lane_a(settings, terms, countries)          # Lane A daily only
            postings += _lane_b(settings, terms, countries, "daily")
            postings += _lane_c(db, settings)                        # ATS boards (unmetered)
        elif cadence == "weekly":
            postings += _lane_b(settings, terms, countries, "weekly")
        else:
            raise ValueError(f"unknown cadence {cadence!r}")

        added, updated = upsert_jobs(db, postings)
        # Embed freshly-added corpus jobs (no-op unless embeddings configured).
        from .corpus_service import (
            backfill_countries, correct_ats_locations, embed_new_jobs,
        )
        from ..config import config as web_config
        embedded = embed_new_jobs(db, settings, limit=web_config.embed_limit)
        # Correct aggregator location errors from the source ATS (Ashby/Greenhouse
        # /Lever), then settle any remaining unplaceable country via one LLM lookup.
        corrected = correct_ats_locations(db)
        countried = backfill_countries(db, settings)
        result = {"cadence": cadence, "fetched": len(postings),
                  "added": added, "updated": updated, "embedded": embedded,
                  "ats_corrected": corrected, "countried": countried}
        log.info("ingest done: %s", result)
        return result
    except Exception as exc:
        log.exception("ingest cycle failed")
        return {"error": str(exc)}
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description="JBHNTR scheduled corpus ingestion")
    ap.add_argument("--cadence", choices=["daily", "weekly", "discover"], default="daily")
    args = ap.parse_args()
    print(run(args.cadence))


if __name__ == "__main__":
    main()
