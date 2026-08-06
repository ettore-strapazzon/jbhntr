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


def discovery_change_trigger(user: User, seeds: list[str],
                             verticals: list[str]) -> bool:
    """Per-user profile changes that should run discovery on this user's NEXT
    search (occasions 1-3), independent of the weekly cadence:

      1. first run — the profile was just set up (discovery has never run),
      2. at least N new seed companies added since the last run, or
      3. any new vertical added since the last run.

    Premium only. Excludes the weekly refresh (occasion 4), which the Monday cron
    applies to everyone via `due_for_discovery`.
    """
    if not user.is_premium:
        return False
    if aware(user.last_discovery_at) is None:
        return True
    new_seeds = set(seeds) - set(user.discovery_seeds or [])
    new_verticals = set(verticals) - set(user.discovery_verticals or [])
    return len(new_seeds) >= config.discovery_new_seeds_trigger or bool(new_verticals)


def due_for_discovery(user: User, seeds: list[str], verticals: list[str],
                      now=None) -> bool:
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
    return discovery_change_trigger(user, seeds, verticals)


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
    from .profile_service import build_engine_profile, seed_values

    target = target or config.discover_target
    try:
        if not user.is_premium:
            return {"discovered": 0, "added": 0, "reason": "not premium"}
        seeds = seed_values(db, user)
        if not seeds:
            return {"discovered": 0, "added": 0, "reason": "no seeds"}
        verticals = list(user.profile.verticals or []) if user.profile else []
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
        # whether the profile has since changed materially.
        user.last_discovery_at = utcnow()
        user.discovery_seeds = list(seeds)
        user.discovery_verticals = list(verticals)
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
    from .profile_service import seed_values

    totals = {"users": 0, "skipped": 0, "added": 0, "premium": 0, "per_user": []}
    for user in db.query(User).all():
        if not user.profile or not user.is_premium:
            totals["skipped"] += 1
            continue
        totals["premium"] += 1
        seeds = seed_values(db, user)
        verticals = list(user.profile.verticals or [])
        if not force and not due_for_discovery(user, seeds, verticals):
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
                            limit: int = 30) -> dict:
    """Scrape the careers pages of registered non-ATS companies into the corpus.

    Runs on the slow (weekly) cadence — each company is one LLM extraction — and
    rotates oldest-polled-first so all custom companies get refreshed over time.
    Jobs are written through with `deterministic_tags`, so they are tagged and
    matched exactly like any other corpus posting, for every user. No-op without
    an LLM. Never raises.
    """
    from jobhunter import llm
    from jobhunter.sources.careers_scrape import scrape_careers
    from .profile_service import engine_settings

    settings = settings or engine_settings(premium=True)
    if not llm.is_configured(settings):
        return {"companies": 0, "jobs": 0, "reason": "no llm"}
    companies = (db.query(Company).filter(Company.ats == CUSTOM_ATS)
                 .order_by(Company.last_polled_at.is_(None).desc(),
                           Company.last_polled_at.asc())
                 .limit(limit).all())
    if not companies:
        return {"companies": 0, "jobs": 0}

    postings: list[JobPosting] = []
    now = utcnow()
    for c in companies:
        try:
            jobs = scrape_careers(c.ats_token, c.name, settings)
        except Exception as exc:
            log.debug("Custom scrape %s failed: %s", c.ats_token, exc)
            jobs = []
        c.jobs_count = len(jobs)
        c.last_polled_at = now
        postings.extend(jobs)
    db.commit()

    if postings:
        from .corpus_service import upsert_jobs
        upsert_jobs(db, postings)
    log.info("Custom scrape: %d companies -> %d postings", len(companies), len(postings))
    return {"companies": len(companies), "jobs": len(postings)}


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
