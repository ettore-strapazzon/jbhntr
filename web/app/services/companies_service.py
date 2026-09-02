"""The shared company registry and Lane C polling (Phase 2, step 2).

- `seed_registry` puts the config seed companies into the DB (idempotent).
- `discover_for_user` runs seeds -> ~100 similar companies (discover.py) and
  upserts the readable ones, shared across all users.
- `poll_all` fetches every registry company's public ATS board into the corpus.

All ATS feeds are public JSON/XML APIs — no scraping, no keys, no ToS friction.
See docs/INGESTION_ENGINE.md → Lane C / §4.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from jobhunter.config import Settings, load_companies
from jobhunter.models import JobPosting
from jobhunter.sources.ats import FETCHERS

from ..config import config
from ..models import Company, User, aware, utcnow

log = logging.getLogger("jbhntr.companies")

DISCOVER_TARGET = 100     # similar companies to accumulate per user, over time
DISCOVER_MAX_ROUNDS = 2   # per call — keep a scheduled run short; accumulate across runs
POLL_WORKERS = 12
RESOLVE_WORKERS = 16      # concurrent ATS-board probes in resolve_corpus_companies


def discovery_signals(db: DbSession, user: User) -> dict:
    """The profile inputs discovery keys off: seed companies plus the market
    signals (verticals, company types, countries). Used both to decide whether a
    fresh run is due and to record what a run was based on."""
    from .profile_service import seed_values
    p = user.profile
    return {
        "seeds": seed_values(db, user),
        "verticals": list(p.verticals or []) if p else [],
        "company_types": list(p.company_type or []) if p else [],
        "countries": list(p.countries or []) if p else [],
    }


def discovery_change_trigger(user: User, signals: dict) -> bool:
    """Per-user profile changes that should run discovery on this user's NEXT
    search (occasions 1-3), independent of the weekly cadence:

      1. first run — the profile was just set up (discovery has never run),
      2. any new market signal since the last run — a new vertical, company type
         or target country, or
      3. at least N new seed companies added since the last run.

    Premium only. Excludes the weekly refresh (occasion 4), which the Monday cron
    applies to everyone via `due_for_discovery`.
    """
    if not user.is_premium:
        return False
    if aware(user.last_discovery_at) is None:
        return True
    new_seeds = set(signals["seeds"]) - set(user.discovery_seeds or [])
    new_verticals = set(signals["verticals"]) - set(user.discovery_verticals or [])
    new_types = set(signals["company_types"]) - set(user.discovery_company_types or [])
    new_countries = set(signals["countries"]) - set(user.discovery_countries or [])
    return (len(new_seeds) >= config.discovery_new_seeds_trigger
            or bool(new_verticals or new_types or new_countries))


def due_for_discovery(user: User, signals: dict, now=None) -> bool:
    """Should premium discovery run for this user on the scheduled (Monday) sweep?

    Premium only. Due when it has never run, when the weekly cadence window has
    elapsed (occasion 4), or when the profile changed materially since the last
    run (occasions 1-3, `discovery_change_trigger`).
    """
    from datetime import timedelta
    if not user.is_premium:
        return False
    now = now or utcnow()
    last = aware(user.last_discovery_at)
    if last is None:
        return True
    if now - last >= timedelta(days=config.discovery_interval_days):
        return True
    return discovery_change_trigger(user, signals)


# --------------------------------------------------------------------------- #
def _insert_company_safe(db: DbSession, *, ats: str, token: str, name: str,
                         source: str, user_id: int | None) -> bool:
    """Insert one Company, returning True only if a new row was created.

    A single discovery run proposes many companies and commits once at the end.
    Two of them can resolve to the SAME (ats, token) — verify() guesses board
    handles, so distinct names can land on one token — and with autoflush off the
    in-run existence check below doesn't see the first, still-pending insert. Both
    then get added and the final commit trips uq_company_ats, which in Postgres
    aborts the WHOLE transaction ("rolled back due to a previous exception"),
    losing every company in the run. Guard each insert with a SAVEPOINT and flush
    inside it, so a duplicate rolls back just that one row and the run continues.
    """
    row = (db.query(Company)
             .filter(Company.ats == ats, Company.ats_token == token).first())
    if row:
        if not row.name and name:
            row.name = name[:200]
        return False
    try:
        with db.begin_nested():          # savepoint
            db.add(Company(ats=ats, ats_token=token, name=(name or token)[:200],
                           source=source, discovered_for=user_id))
            db.flush()                   # surface a duplicate now, inside the savepoint
        return True
    except IntegrityError:
        return False                     # raced/duplicate (ats, token) — skip, keep going


def upsert_company(db: DbSession, ats: str, token: str, name: str,
                   source: str = "discovered", user_id: int | None = None) -> bool:
    """Insert a company if new. Returns True if inserted. Deduped on (ats, token)."""
    ats = (ats or "").strip().lower()
    token = (token or "").strip()
    if not (ats and token and ats in FETCHERS):
        return False
    return _insert_company_safe(db, ats=ats, token=token, name=name,
                                source=source, user_id=user_id)


CUSTOM_ATS = "custom"          # a company scraped from its own careers page
MAX_CUSTOM_PER_RUN = 20        # cap new custom companies registered per discovery run


def upsert_custom_company(db: DbSession, name: str, domain: str,
                          user_id: int | None = None) -> bool:
    """Register a non-ATS company (scraped from its careers page) keyed by domain.

    Separate from `upsert_company`, which only accepts known ATS platforms.
    """
    domain = (domain or "").strip().lower()
    for pre in ("https://", "http://", "www."):
        if domain.startswith(pre):
            domain = domain[len(pre):]
    domain = domain.strip("/").split("/")[0]
    if not domain or "." not in domain:
        return False
    return _insert_company_safe(db, ats=CUSTOM_ATS, token=domain[:120], name=name,
                                source="scraped", user_id=user_id)


# Hosts that are NOT an employer's own site — aggregators and their redirect
# trackers. A corpus URL on one of these gives us no employer domain, so we must
# fall through to Clearbit resolution instead of mistaking the tracker for the
# company's website (jobviewtrack.com is careerjet's redirect — the #1 offender).
_AGGREGATOR_HOSTS = (
    "careerjet", "jobviewtrack", "adzuna", "jooble", "indeed", "linkedin",
    "glassdoor", "monster", "totaljobs", "jobrapido", "neuvoo", "talent.com",
    "ziprecruiter", "simplyhired", "whatjobs", "jobisjob", "trovit", "jobsora",
    "stepstone", "infojobs", "lever.co", "greenhouse.io", "myworkdayjobs",
    "bebee", "joblift", "jobtome", "learn4good", "kariera",
)


def _corpus_domain(db: DbSession, company: str) -> str:
    """A best-effort employer domain from a non-aggregator job URL of this company
    (helps the careers-page fallback in verify). Aggregator URLs give no employer
    domain, so this is usually empty for the thin long tail."""
    return _corpus_hints(db, company)[0]


def _corpus_hints(db: DbSession, company: str) -> tuple[str, str]:
    """(employer_domain, country_code) for a company from its corpus rows. The
    domain comes from a non-aggregator job URL (usually empty for the careerjet
    long tail); the country code (from a job's tags) picks the right TLD to GUESS
    a domain for those — an Italian company is far likelier to be foo.it than
    foo.com. Both best-effort."""
    from urllib.parse import urlparse

    from ..models import Job
    domain = code = ""
    for url, countries in (db.query(Job.url, Job.countries)
                           .filter(Job.company == company).limit(20)):
        if not domain and url:
            host = urlparse(url or "").netloc.lower().replace("www.", "")
            if host and not any(a in host for a in _AGGREGATOR_HOSTS):
                domain = host
        if not code and countries:
            code = str(countries[0] or "").lower()
        if domain and code:
            break
    return domain, code


# ISO country code -> the TLD that market's companies most often use, for domain
# guessing when the corpus gives us no employer domain (careerjet's thin tail).
_COUNTRY_TLD = {
    "it": "it", "fr": "fr", "de": "de", "es": "es", "nl": "nl", "se": "se",
    "pl": "pl", "pt": "pt", "dk": "dk", "no": "no", "fi": "fi", "at": "at",
    "ch": "ch", "be": "be", "ie": "ie", "uk": "co.uk", "gb": "co.uk",
    "br": "com.br", "mx": "com.mx", "ca": "ca",
}


def _guess_domains(name: str, code: str) -> list[str]:
    """Candidate website domains for a company we have no domain for: the
    squished name across common TLDs, market TLD first. Best-effort — wrong
    guesses simply don't resolve or yield no ATS board (verify only accepts a
    board that actually returns jobs), so there's no false-positive risk."""
    base = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if len(base) < 2:
        return []
    tlds = ["com", "io", "co", "ai"]
    t = _COUNTRY_TLD.get((code or "").lower())
    if t and t not in tlds:
        tlds.insert(0, t)          # a local company is likelier foo.it than foo.com
    return [f"{base}.{tld}" for tld in tlds]


def _live_domain(guesses: list[str]) -> str:
    """First candidate domain that answers an HTTP request — the company's real
    site, so verify() can probe its careers page. Short timeout; stops at first."""
    from jobhunter.sources.base import http_client
    for d in guesses:
        try:
            with http_client(timeout=6.0) as c:
                r = c.get(f"https://{d}", follow_redirects=True)
            if r.status_code < 400:
                return d
        except Exception:
            continue
    return ""


def _clearbit_domains(name: str) -> list[str]:
    """Free, keyless company-name -> domain suggestions (Clearbit autocomplete),
    best-match first. This is the real fix for the long tail whose domain doesn't
    resemble its name (Satispay->satispay.com, not the .it a guess would try).
    Fail-soft: [] on any error / rate-limit, so we fall back to TLD guessing."""
    from jobhunter.sources.base import http_client
    try:
        with http_client(timeout=8.0) as c:
            r = c.get("https://autocomplete.clearbit.com/v1/companies/suggest",
                      params={"query": name})
        if r.status_code != 200:
            return []
        return [d["domain"] for d in r.json()
                if isinstance(d, dict) and d.get("domain")]
    except Exception:
        return []


def _resolve_domain(name: str, code: str) -> str:
    """Best-effort employer domain for a company we have none for. Ask Clearbit
    (real, name-matched domains), rank them, append TLD guesses as a fallback, and
    return the first candidate that actually answers HTTP. '' if none resolve."""
    norm = re.sub(r"[^a-z0-9]+", "", (name or "").lower())

    def _score(dom: str) -> int:
        base = re.sub(r"[^a-z0-9]+", "", dom.split(".")[0].lower())
        s = 50 if base == norm else (20 if norm and norm in base else 0)
        t = _COUNTRY_TLD.get((code or "").lower())
        if t and dom.endswith("." + t):
            s += 5
        return -s

    cands = sorted(_clearbit_domains(name), key=_score) + _guess_domains(name, code)
    # For an in-country company, try the market-TLD of the COMPANY NAME first
    # (Orienta -> orienta.it), ahead of Clearbit — whose top hit for an ambiguous
    # name can be a wrong foreign site (Orienta -> orientaldaily.com.my). A staffing
    # agency's localised portal (randstad.it) also carries THIS country's jobs.
    t = _COUNTRY_TLD.get((code or "").lower())
    if t:
        name_slug = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
        if len(name_slug) >= 2:
            cands = [f"{name_slug}.{t}"] + cands
    seen: set[str] = set()
    ordered: list[str] = []
    for d in cands:
        if d and d not in seen:
            seen.add(d)
            ordered.append(d)
    return _live_domain(ordered[:6])


def resolve_corpus_companies(db: DbSession, limit: int | None = None) -> dict:
    """Resolve the most common corpus companies to their public ATS board so we
    ingest their FULL-JD openings — which then upgrade the thin aggregator snippets
    via the company|title dedup. HTTP-only ATS probing (no LLM). A company with no
    discoverable board is recorded (ats='none') so we never re-probe it. The daily
    Lane C poll then fetches the boards we just registered. Returns {probed, resolved}."""
    if not config.corpus_resolve_enabled:
        return {"probed": 0, "resolved": 0, "skipped": "disabled"}
    from sqlalchemy import func

    from jobhunter.discover import _slugify, verify

    from ..models import Job

    cap = config.corpus_resolve_limit if limit is None else limit
    known = {(name or "").strip().lower()
             for (name,) in db.query(Company.name).all()}
    rows = (db.query(Job.company, func.count(Job.id))
            .filter(Job.company.isnot(None), Job.company != "")
            .group_by(Job.company)
            .order_by(func.count(Job.id).desc())
            .limit(cap * 5).all())
    picked = [name for name, _ in rows
              if name and name.strip().lower() not in known][:cap]
    if not picked:
        return {"probed": 0, "resolved": 0}

    # Pre-compute employer-domain + country hints on the main thread (DB read),
    # THEN probe every company's ATS board concurrently — verify() is HTTP-only and
    # was the slow, sequential bottleneck (~8 probes/company). Insert on the main
    # thread after, since the SQLAlchemy session isn't thread-safe.
    hints = {name: _corpus_hints(db, name) for name in picked}

    def _probe(name: str):
        slug = _slugify(name)
        if not slug:
            return (name, "", None, "")
        domain, code = hints.get(name, ("", ""))
        # No employer domain (the careerjet tail)? Resolve one — Clearbit
        # autocomplete first (real domains), then TLD guessing — so verify() can
        # reach the company's own careers page / embedded ATS board.
        if not domain:
            domain = _resolve_domain(name, code)
        try:
            return (name, slug, verify(name, slug, domain or ""), domain or "")
        except Exception:
            return (name, slug, None, domain or "")

    with ThreadPoolExecutor(max_workers=RESOLVE_WORKERS) as pool:
        results = list(pool.map(_probe, picked))

    resolved = custom = 0
    for name, slug, res, domain in results:
        if res:
            ats, token, _ = res
            if upsert_company(db, ats, token, name, source="corpus"):
                resolved += 1
        elif domain:
            # No supported ATS, but Clearbit/guessing found the company's real
            # website — keep it as a custom company so the (JSON-LD-first, mostly
            # free) careers scraper can read its openings. Beats discarding the
            # domain we just worked to find.
            if upsert_custom_company(db, name, domain, user_id=None):
                custom += 1
        elif slug:
            # No board and no website at all — mark attempted (ats='none', polled by
            # nothing) so we don't keep re-probing a genuine dead end.
            _insert_company_safe(db, ats="none", token=slug, name=name,
                                 source="corpus", user_id=None)
    db.commit()
    log.info("Corpus company resolution: %d/%d to an ATS board, %d to custom careers",
             resolved, len(picked), custom)
    return {"probed": len(picked), "resolved": resolved, "custom": custom}


def seed_registry(db: DbSession) -> int:
    """Ensure the config seed companies are in the registry. Idempotent."""
    added = 0
    for entry in load_companies():
        ats = (entry.get("ats") or "").lower()
        token = entry.get("token") or ""
        if upsert_company(db, ats, token, entry.get("name", ""), source="seed"):
            added += 1
    if added:
        db.commit()
    return added


# --------------------------------------------------------------------------- #
def discover_for_user(db: DbSession, user: User, target: int | None = None) -> dict:
    """Find companies similar to a user's seeds and add readable ones to the
    registry. Pricey (LLM + web search), so call on a slow cadence, not per
    search. Returns counts. Never raises.
    """
    from jobhunter import discover as discover_mod
    from .profile_service import build_engine_profile

    target = target or config.discover_target
    try:
        if not user.is_premium:
            return {"discovered": 0, "added": 0, "reason": "not premium"}
        # Seeds are the strongest signal but NOT required: discovery can run from
        # the market profile alone (objective, verticals, company types, countries).
        # Only bail when there is no usable signal at all.
        signals = discovery_signals(db, user)
        seeds = signals["seeds"]
        p = user.profile
        has_signal = bool(seeds or (p and (p.objective or p.verticals or p.company_type)))
        if not has_signal:
            return {"discovered": 0, "added": 0,
                    "reason": "no seeds or market profile to search from"}
        profile = build_engine_profile(db, user)
        from .profile_service import engine_settings
        settings = engine_settings(premium=True)   # from_env() leaves the model empty on OpenRouter
        # Exclude companies already in the shared registry so each short run
        # finds NEW ones; results accumulate toward `target` across scheduled
        # runs rather than blocking for minutes in one pass.
        already = [c.name for c in db.query(Company).all() if c.name]
        have = db.query(Company).filter(Company.discovered_for == user.id).count()
        remaining = max(0, target - have)
        if remaining == 0:
            return {"discovered": 0, "added": 0, "seeds": len(seeds),
                    "reason": f"target reached ({have}/{target} discovered)"}
        verified, rejected = discover_mod.discover(
            profile, settings, target=remaining, seeds=seeds,
            max_rounds=DISCOVER_MAX_ROUNDS, exclude=already)

        # Dedupe within the run BEFORE inserting: distinct proposed names can
        # resolve to the same (ats, token), and inserting the same key twice is
        # what tripped uq_company_ats. (upsert_* also savepoint-guards each insert;
        # this just avoids the wasted attempt.)
        added = custom = 0
        seen_ats: set[tuple[str, str]] = set()
        for c in verified:
            key = ((c.get("ats") or "").strip().lower(), (c.get("token") or "").strip())
            if key in seen_ats:
                continue
            seen_ats.add(key)
            if upsert_company(db, c.get("ats", ""), c.get("token", ""),
                              c.get("name", ""), source="discovered", user_id=user.id):
                added += 1
        # Companies with no readable ATS but a known domain: register them for a
        # careers-page scrape (bounded per run so one user can't flood the table).
        seen_dom: set[str] = set()
        for c in rejected:
            if custom >= MAX_CUSTOM_PER_RUN:
                break
            dom = (c.get("domain") or "").strip().lower()
            if dom and dom in seen_dom:
                continue
            seen_dom.add(dom)
            if upsert_custom_company(db, c.get("name", ""), c.get("domain", ""),
                                     user_id=user.id):
                custom += 1
        # Record what this run was based on, so the next cadence check can tell
        # whether the profile has since changed materially (seeds, verticals,
        # company types or markets).
        user.last_discovery_at = utcnow()
        user.discovery_seeds = list(signals["seeds"])
        user.discovery_verticals = list(signals["verticals"])
        user.discovery_company_types = list(signals["company_types"])
        user.discovery_countries = list(signals["countries"])
        db.commit()
        # verified_n/rejected_n expose WHERE a run produced nothing: both 0 means
        # the LLM/web-search suggested nothing; verified 0 + rejected >0 means
        # companies were found but none had a readable public ATS; added 0 with
        # verified >0 means they were all already in the registry.
        result = {"seeds": len(seeds), "verified_n": len(verified),
                  "rejected_n": len(rejected), "added": added, "custom": custom}
        log.info("Discovery for user %s: %s", user.id, result)
        return result
    except Exception as exc:
        log.warning("Discovery for user %s failed: %s", user.id, exc)
        db.rollback()
        return {"error": str(exc)[:200]}


def discover_all_active(db: DbSession, force: bool = False) -> dict:
    """Scheduled refresh: run discovery for every PREMIUM user who is due (cadence
    elapsed or profile changed materially). Free users are skipped — this is a
    premium feature — but the companies it finds feed everyone's corpus.

    `force=True` (operator "run now") ignores the cadence so a premium user with
    seeds is processed immediately instead of waiting for the weekly window.
    """
    totals = {"users": 0, "skipped": 0, "added": 0, "premium": 0, "per_user": []}
    for user in db.query(User).all():
        if not user.profile or not user.is_premium:
            totals["skipped"] += 1
            continue
        totals["premium"] += 1
        signals = discovery_signals(db, user)
        if not force and not due_for_discovery(user, signals):
            totals["skipped"] += 1
            totals["per_user"].append(f"{user.email}: not due")
            continue
        res = discover_for_user(db, user)
        totals["users"] += 1
        totals["added"] += res.get("added", 0)
        # A compact per-user trace so the operator can see exactly what happened.
        if "error" in res:
            totals["per_user"].append(f"{user.email}: error {res['error']}")
        elif res.get("reason"):                       # not premium / no seeds / target reached
            totals["per_user"].append(f"{user.email}: {res['reason']}")
        elif res.get("seeds"):
            totals["per_user"].append(
                f"{user.email}: seeds {res['seeds']} -> suggested "
                f"{res['verified_n'] + res['rejected_n']} (ATS-readable "
                f"{res['verified_n']}, +{res['added']} new, +{res['custom']} to scrape)")
        else:
            totals["per_user"].append(f"{user.email}: no companies suggested")
    return totals


# --------------------------------------------------------------------------- #
def scrape_custom_companies(db: DbSession, settings: Settings | None = None,
                            limit: int = 120) -> dict:
    """Scrape the careers pages of registered non-ATS companies into the corpus.

    The big lever for the aggregator long tail (Italian SMBs etc.): a careerjet
    company with no ATS but a real website, whose openings we read straight off its
    careers page. FREE where the page embeds JobPosting JSON-LD (most do, for
    Google-for-Jobs); an LLM extractor is the fallback for JS-only pages with no
    structured data. Rotates oldest-polled-first so all custom companies refresh
    over time. Scrapes concurrently (each page is HTTP + at most one LLM call).
    Jobs go through `deterministic_tags`, matched like any corpus posting. Never
    raises.
    """
    from jobhunter.sources.careers_scrape import scrape_careers
    from .profile_service import engine_settings

    settings = settings or engine_settings(premium=True)
    companies = (db.query(Company).filter(Company.ats == CUSTOM_ATS)
                 .order_by(Company.last_polled_at.is_(None).desc(),
                           Company.last_polled_at.asc())
                 .limit(limit).all())
    if not companies:
        return {"companies": 0, "jobs": 0}

    def _one(c: Company):
        try:
            return c.id, scrape_careers(c.ats_token, c.name, settings)
        except Exception as exc:
            log.debug("Custom scrape %s failed: %s", c.ats_token, exc)
            return c.id, []

    postings: list[JobPosting] = []
    now = utcnow()
    by_id = {c.id: c for c in companies}
    with ThreadPoolExecutor(max_workers=6) as pool:   # HTTP/LLM-bound; polite to sites
        for cid, jobs in pool.map(_one, companies):
            by_id[cid].jobs_count = len(jobs)
            by_id[cid].last_polled_at = now
            postings.extend(jobs)
    db.commit()

    if postings:
        from .corpus_service import upsert_jobs
        upsert_jobs(db, postings)
    filled = sum(1 for p in postings if len(p.description or "") >= 300)
    log.info("Custom scrape: %d companies -> %d postings (%d with full JD)",
             len(companies), len(postings), filled)
    return {"companies": len(companies), "jobs": len(postings), "full_jd": filled}


def scrape_market_agencies(db: DbSession, country: str = "it", n: int = 25,
                           settings: Settings | None = None) -> dict:
    """Resolve the top-N THIN-JD companies in a specific market to their LOCAL-market
    portal and scrape it. The fix for global agencies: Randstad's thin Italian jobs
    need randstad.IT (its Italian portal), not the randstad.com the generic resolver
    picks — so we force the country code, register the .it domain as custom, and
    scrape it now (sitemap JSON-LD). Returns counts + a per-company trace."""
    from sqlalchemy import String, func

    from jobhunter.sources.careers_scrape import scrape_careers

    from .corpus_service import upsert_jobs
    from .profile_service import engine_settings

    settings = settings or engine_settings(premium=True)
    from ..models import Job
    thin = func.coalesce(func.length(Job.description), 0) < 300
    cfilt = func.cast(Job.countries, String).ilike(f'%"{country.lower()}"%')
    rows = (db.query(Job.company, func.count(Job.id))
            .filter(thin, cfilt, Job.company.isnot(None), Job.company != "")
            .group_by(Job.company).order_by(func.count(Job.id).desc())
            .limit(max(1, min(n, 60))).all())
    picked = [c for c, _ in rows if c]

    postings: list[JobPosting] = []
    trace: list[str] = []
    for name in picked:
        dom = _resolve_domain(name, country)          # country -> .it portal
        if not dom:
            trace.append(f"{name[:26]}: no domain")
            continue
        upsert_custom_company(db, name, dom)          # register so nightly re-scrapes
        try:
            # Agencies have huge sitemaps — pull a deep page (600) of full JDs per run.
            jobs = scrape_careers(dom, name, settings, sitemap_cap=600, country=country)
        except Exception as exc:
            trace.append(f"{name[:26]} ({dom}): error {type(exc).__name__}")
            continue
        full = sum(1 for j in jobs if len(j.description or "") >= 300)
        trace.append(f"{name[:26]} ({dom}): {len(jobs)}j {full}full")
        postings.extend(jobs)
    db.commit()
    added = updated = 0
    if postings:
        added, updated = upsert_jobs(db, postings)
    log.info("Market agencies %s: %d companies -> %d jobs (+%d/%d)",
             country, len(picked), len(postings), added, updated)
    return {"country": country, "companies": len(picked), "jobs": len(postings),
            "added": added, "updated": updated, "trace": trace}


def poll_all(db: DbSession, settings: Settings | None = None) -> list[JobPosting]:
    """Lane C: fetch every registry company's public ATS board, concurrently.

    Updates jobs_count / last_polled_at as a side effect. Returns all postings
    for the caller to write through to the corpus.
    """
    seed_registry(db)
    # Only companies on a known ATS are polled here (public JSON/XML feeds).
    # Custom (careers-page) companies are scraped separately on the weekly cadence.
    companies = db.query(Company).filter(Company.ats.in_(list(FETCHERS))).all()
    if not companies:
        return []

    def _one(c: Company):
        fn = FETCHERS.get(c.ats)
        if not fn:
            return c.id, []
        try:
            return c.id, fn(c.name, c.ats_token)
        except Exception as exc:
            log.debug("Poll %s:%s failed: %s", c.ats, c.ats_token, exc)
            return c.id, []

    postings: list[JobPosting] = []
    now = utcnow()
    by_id = {c.id: c for c in companies}
    with ThreadPoolExecutor(max_workers=POLL_WORKERS) as pool:
        for cid, jobs in pool.map(_one, companies):
            by_id[cid].jobs_count = len(jobs)
            by_id[cid].last_polled_at = now
            postings.extend(jobs)
    db.commit()
    log.info("Lane C: polled %d companies -> %d postings", len(companies), len(postings))
    return postings
