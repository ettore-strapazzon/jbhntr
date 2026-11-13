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

from jbhntr_engine import (
    AGGREGATORS, BOARD_NAMES, INGEST_PLAN, KEYED_MAX_TERMS, KEYED_PROVIDERS, Profile,
    Settings, fetch_boards, geo,
)

from ..db import SessionLocal
from ..models import Profile as ProfileRow
from .corpus_service import upsert_jobs
from .profile_service import COUNTRIES as PICKER_COUNTRIES

log = logging.getLogger("jbhntr.ingest")

# The ingestion plan — Lane A/B source lists, enabling settings, cadence per
# metered quota, single-country providers, cold-corpus fallbacks and volume caps —
# is engine-side (R3-16): jbhntr_engine.INGEST_PLAN. Same module names as before.
LANE_A_AGGREGATORS = list(INGEST_PLAN["lane_a_aggregators"])
_LOCALIZED_AGGREGATORS = set(INGEST_PLAN["localized_aggregators"])
# Lane B: name -> (settings attr that enables it, provider fn).
KEYED_SOURCES = {name: (attr, KEYED_PROVIDERS[name])
                 for name, attr in INGEST_PLAN["keyed_settings"].items()}
SOURCE_CADENCE = dict(INGEST_PLAN["source_cadence"])
SOURCE_COUNTRIES = dict(INGEST_PLAN["source_countries"])
DEFAULT_TERMS = list(INGEST_PLAN["default_terms"])
DEFAULT_COUNTRIES = list(INGEST_PLAN["default_countries"])
TERMS_CAP = INGEST_PLAN["terms_cap"]              # pad user terms up to this with defaults
TERMS_MAX = INGEST_PLAN["terms_max"]              # absolute ceiling
COUNTRIES_CAP = INGEST_PLAN["countries_cap"]      # pad user countries up to this
COUNTRIES_MAX = INGEST_PLAN["countries_max"]      # absolute ceiling
_AGENCY_MARKETS = INGEST_PLAN["agency_markets"]   # top markets for agency portals (nightly)
_AGENCY_N = INGEST_PLAN["agency_n"]               # top thin-JD companies per market

# code -> display name, built from the picker list so provider locations resolve.
_CODE_TO_NAME: dict[str, str] = {}
for _nm in PICKER_COUNTRIES:
    _c = geo.country_of(_nm)
    if _c:
        _CODE_TO_NAME.setdefault(_c, _nm)


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _as_list(v) -> list[str]:
    """Coerce a stored value to a list of strings. A term/location field that got
    saved as a plain STRING must be treated as one item — never iterated, or
    `for c in "milan"` explodes it into single characters and every source gets
    queried with junk like 'm','i','l'…"""
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


def corpus_terms(db) -> list[str]:
    """Every active user's terms (by demand) first, padded with broad defaults up
    to the floor. Includes BOTH the titles they typed and the roles the engine
    derived from their objective + CV, so the corpus is built around what people
    actually want. All user terms are kept (up to the ceiling)."""
    counter: Counter[str] = Counter()
    for p in db.query(ProfileRow):
        for t in _as_list(p.search_terms) + _as_list(p.derived_roles):
            t = (t or "").strip()
            # Skip junk like "[]"/"null" (a field saved as a serialized-empty
            # string) — a real search term must contain a letter.
            if t and any(ch.isalpha() for ch in t):
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
        for loc in _as_list(p.locations):
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


def _lane_a(db, settings: Settings, terms: list[str], countries: list[str],
           light: bool = False) -> list:
    """Global feeds + broad no-key aggregators. Keyword aggregators (adzuna) are
    queried per country with localized role titles; remote-only boards stay one
    global English call. `light` skips the (LLM) term localization so an operator
    run can't stall on OpenRouter latency."""
    from . import term_localize

    postings: list = []
    base = Profile(raw={
        "locations": countries,
        "sources": {"boards": list(BOARD_NAMES), "search_terms": terms},
    })
    postings += _fetch("boards", fetch_boards, base, settings)
    local_cache: dict[str, list[str]] = {}
    for name in LANE_A_AGGREGATORS:
        fn = AGGREGATORS.get(name)
        if not fn:
            continue
        if name in _LOCALIZED_AGGREGATORS:
            for country in countries:
                if country not in local_cache:
                    code = geo.country_of(country)
                    local_cache[country] = (
                        term_localize.localized_terms(db, settings, terms, code)
                        if code and not light else [])
                cterms = (terms + [t for t in local_cache[country] if t not in terms])[:TERMS_MAX]
                prof = Profile(raw={"locations": [country],
                                    "sources": {"aggregators": [name], "search_terms": cterms}})
                postings += _fetch(f"{name}/{country}", fn, prof, settings)
        else:
            prof = Profile(raw={"locations": countries,
                                "sources": {"aggregators": [name], "search_terms": terms}})
            postings += _fetch(name, fn, prof, settings)
    return postings


def _lane_b(db, settings: Settings, terms: list[str], countries: list[str],
           cadence: str, light: bool = False) -> list:
    """Metered/keyed sources whose cadence matches this run. For non-English
    markets each country's query set is extended with localized role titles
    (e.g. 'Direttore Operativo' for Italy) so we don't miss postings written in
    the local language. `light` skips the (LLM) localization for a fast operator run."""
    from . import term_localize

    postings: list = []
    local_cache: dict[str, list[str]] = {}

    def _localized(country: str) -> list[str]:
        if country not in local_cache:
            code = geo.country_of(country)
            local_cache[country] = (
                term_localize.localized_terms(db, settings, terms, code)
                if code and not light else [])
        return (terms + [t for t in local_cache[country] if t not in terms])[:TERMS_MAX]

    for name, (attr, fn) in KEYED_SOURCES.items():
        if SOURCE_CADENCE.get(name) != cadence:
            continue
        if not getattr(settings, attr, ""):
            continue  # no key configured
        src_countries = SOURCE_COUNTRIES.get(name, countries)

        # JSearch is metered (~10k requests/mo) and makes ONE API call per term, so
        # querying every term x every country drains the quota in days. Spread a
        # fixed daily query budget evenly across markets instead, so the paid
        # full-JD source runs all month rather than dying mid-month.
        if name == "jsearch":
            try:
                budget = max(1, int(getattr(settings, "jsearch_daily_queries", 120) or 120))
            except (TypeError, ValueError):
                budget = 120
            # Demand-weighted: src_countries is ordered by user demand (their
            # markets first), and jsearch is the ONLY reliable full-JD source for
            # markets with no ATS/gov feed (e.g. Italy). Spreading the quota evenly
            # starved the markets users actually search; instead give the front of
            # the list the lion's share (weight ~1/rank), the long tail a trickle.
            weights = [1.0 / (i + 1) for i in range(len(src_countries))]
            total_w = sum(weights) or 1.0
            for country, w in zip(src_countries, weights):
                n = max(1, round(budget * w / total_w))
                cterms = _localized(country)[:n]
                if not cterms:
                    continue
                prof = Profile(raw={"locations": [country],
                                    "sources": {"search_terms": cterms}})
                postings += _fetch(f"{name}/{country}", fn, prof, settings)
            continue

        for country in src_countries:
            country_terms = _localized(country)
            # Providers cap terms at keyed.MAX_TERMS internally, so batch to
            # cover the full corpus term set without exceeding per-call limits.
            for batch in _chunks(country_terms, KEYED_MAX_TERMS):
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


def run(cadence: str = "daily", light: bool = False) -> dict:
    """One ingestion cycle. Owns its DB session. Never raises.

    `light=True` caps the heavy post-fetch tail (local embedding, geo/remote
    backfill) to small batches so an operator "run now" finishes in a few minutes
    instead of grinding ~20k CPU embeddings. Coverage/tags still update from the
    fetch+upsert; the embedding backlog just clears over the nightly (full) runs."""
    db = SessionLocal()
    try:
        # engine_settings (not raw from_env) so the country-tag LLM lookup has a
        # model on OpenRouter — otherwise it raises and every unresolvable place
        # stays untagged.
        from .profile_service import engine_settings
        settings = engine_settings(premium=True)
        terms = corpus_terms(db)
        countries = corpus_countries(db)
        log.info("ingest %s: %d terms x %d countries", cadence, len(terms), len(countries))

        # 'discover' is a registry-refresh only (pricey LLM+web-search); it
        # writes companies, not jobs, so daily Lane C then polls them.
        if cadence == "discover":
            from .companies_service import (
                discover_all_active, resolve_corpus_companies,
                scrape_market_agencies, scrape_custom_companies,
            )
            res = discover_all_active(db)
            # Resolve the most common corpus companies to their ATS board (HTTP
            # probe, no LLM) so daily Lane C ingests their full-JD openings, which
            # upgrade the thin aggregator snippets via dedup.
            resolved = resolve_corpus_companies(db)
            # Scrape the careers pages of non-ATS companies discovery registered
            # (premium-sourced, but the jobs land in the shared corpus for all).
            scraped = scrape_custom_companies(db, settings)
            # Staffing-agency portals per active market (their full JDs dedup-upgrade
            # the thin careerjet snippets). Nightly only — skipped on a light operator
            # run, which stays fast (use /admin/run-agencies for a manual pull). Heavy
            # but bounded; each market fail-soft.
            agencies: dict = {}
            if not light:
                for cname in countries[:_AGENCY_MARKETS]:
                    code = geo.country_of(cname)
                    if not code:
                        continue
                    try:
                        agencies[code] = scrape_market_agencies(
                            db, country=code, n=_AGENCY_N, settings=settings)
                    except Exception as exc:
                        log.warning("agency scrape %s failed: %s", code, exc)
            log.info("ingest discover: %s | resolve: %s | custom-scrape: %s | agencies: %s",
                     res, resolved, scraped, {k: v.get("added") for k, v in agencies.items()})
            return {"cadence": "discover", **res, "resolve": resolved,
                    "custom_scrape": scraped}

        postings: list = []
        lanes: dict[str, int] = {}
        if cadence == "daily":
            la = _lane_a(db, settings, terms, countries, light=light)    # Lane A daily only
            lb = _lane_b(db, settings, terms, countries, "daily", light=light)
            lc = _lane_c(db, settings)                               # ATS boards (unmetered)
            lanes = {"a": len(la), "b": len(lb), "c": len(lc)}
            postings += la + lb + lc
        elif cadence == "weekly":
            postings += _lane_b(db, settings, terms, countries, "weekly", light=light)
        else:
            raise ValueError(f"unknown cadence {cadence!r}")

        added, updated = upsert_jobs(db, postings)
        # Embed freshly-added corpus jobs (no-op unless embeddings configured).
        from .corpus_service import (
            backfill_countries, backfill_remote_modes, correct_ats_locations,
            embed_new_jobs,
        )
        from ..config import config as web_config
        # A "run now" caps the tail so it returns quickly; the nightly cron uses the
        # full limits to keep the whole corpus embedded/tagged.
        emb_lim = 1500 if light else web_config.embed_limit
        ats_lim = 800 if light else web_config.ats_correct_limit
        geo_lim = 800 if light else web_config.geo_backfill_limit
        rem_lim = 3000 if light else web_config.remote_backfill_limit
        embedded = embed_new_jobs(db, settings, limit=emb_lim)
        # Correct aggregator location errors from the source ATS (Ashby/Greenhouse
        # /Lever), then settle any remaining unplaceable country via one LLM lookup.
        corrected = correct_ats_locations(db, limit=ats_lim)
        # Geo backfill's residue uses (batched) LLM lookups — skip on a light
        # operator run so it can't stall on OpenRouter; deterministic_tags already
        # placed most rows at upsert, and the nightly cron does the full backfill.
        countried = 0 if light else backfill_countries(db, settings, limit=geo_lim)
        # Re-tag work mode for jobs stuck at 'unknown' now that geo/descriptions grew.
        remoded = backfill_remote_modes(db, limit=rem_lim)
        result = {"cadence": cadence, "fetched": len(postings), "lanes": lanes,
                  "added": added, "updated": updated, "embedded": embedded,
                  "ats_corrected": corrected, "countried": countried,
                  "remoded": remoded}
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
