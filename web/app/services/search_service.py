"""Run the jobhunter engine for one user and persist the results.

This is the only place the web app drives the engine. It runs in a background
thread (or an RQ worker in production) because a search takes minutes.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from jobhunter import seeds as seeds_mod
from jobhunter import sources
from jobhunter.candidate import derive as derive_candidate
from jobhunter.candidate import derive_company_profile
from jobhunter.config import Settings as EngineSettings
from jobhunter.criteria import derive as derive_criteria
from jobhunter.dedup import cap_per_company, prefilter
from jobhunter.matcher import Matcher

from ..config import config
from ..db import SessionLocal
from ..models import Feedback, JobResult, Search, User, aware, utcnow
from .profile_service import (
    build_engine_materials, build_engine_profile, completeness, seed_values,
)

log = logging.getLogger("jbhntr.search")

MAX_RESULTS_STORED = 60   # tier 1-3 shown; scoring already filters hard
MAX_LONGSHOTS = 15        # tier-4 "long shots", shown in a collapsed section


class QuotaError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
def check_quota(db: DbSession, user: User) -> None:
    """Raise QuotaError if this user may not start another search."""
    if user.is_premium:
        # Premium runs a daily automatic search plus manual runs under a
        # fair-use ceiling — see docs/ARCHITECTURE.md.
        since = utcnow() - timedelta(days=1)
        today = (
            db.query(Search)
            .filter(Search.user_id == user.id, Search.started_at >= since)
            .count()
        )
        if today >= config.premium_searches_per_day:
            raise QuotaError(
                f"You've run {today} searches in the last 24 hours. "
                "Fair-use limit reached — try again tomorrow."
            )
        return

    remaining = user.searches_remaining(config.free_searches)
    if remaining is not None and remaining <= 0:
        raise QuotaError(
            f"You've used all {config.free_searches} free searches. "
            "Premium searches for you every day."
        )


def start_search(db: DbSession, user: User) -> Search:
    """Validate, create the row, and kick off the work in the background."""
    state = completeness(db, user)
    if not state.can_search:
        raise QuotaError("Finalise your profile first: " + ", ".join(state.missing_required))
    check_quota(db, user)

    search = Search(user_id=user.id, status="queued", stage="Starting…")
    db.add(search)
    user.searches_used += 1          # count on start, so retries can't farm it
    db.commit()
    db.refresh(search)

    from .events import record
    record(db, "scan_started", user_id=user.id)

    threading.Thread(target=_run_search, args=(search.id, user.id), daemon=True).start()
    return search


# --------------------------------------------------------------------------- #
def _set(db: DbSession, search: Search, **fields) -> None:
    for k, v in fields.items():
        setattr(search, k, v)
    db.commit()


def _run_search(search_id: int, user_id: int) -> None:
    """Background worker. Owns its own DB session."""
    db = SessionLocal()
    try:
        search = db.get(Search, search_id)
        user = db.get(User, user_id)
        if not search or not user:
            return

        settings = EngineSettings.from_env()
        # Free users are scored with the cheap model; premium gets the better one.
        settings.scoring_model = (
            config.premium_scoring_model if user.is_premium else config.free_scoring_model
        )

        profile = build_engine_profile(db, user)
        materials = build_engine_materials(db, user)
        labels = [s.label() for s in seeds_mod.resolve(seed_values(db, user),
                                                       guess_domains=True)]

        # Derive the candidate profile FIRST: keyword-based sources need real
        # job titles to query. Users who skip the optional "job titles" step
        # would otherwise get no keyword results at all.
        _set(db, search, status="running", stage="Understanding your profile…")
        candidate = derive_candidate(profile, materials, settings)
        # Always widen coverage with adjacent titles the CV implies — the user's
        # own terms lead (they win the per-source query slots and rank ties),
        # then the derived roles fill in to catch jobs worded differently.
        # Previously the derived terms were used ONLY when the user typed none,
        # so a user who entered "Chief of Staff" never saw "Business Operations".
        merged = _merge_terms(list(profile.search_terms), candidate.target_roles)
        if merged:
            profile.raw.setdefault("sources", {})["search_terms"] = merged
            log.info("Search terms for user %s: %s", user.id, merged)

        terms = list(profile.search_terms) + list(candidate.target_roles or [])
        company_profile = derive_company_profile(labels, settings)
        criteria = derive_criteria(profile, labels, settings)
        matcher = Matcher(settings)

        # Step 4: read the shared corpus (fast — no live fetch). Cosine ranking
        # replaces the AI triage stage. Falls back to a live fetch when the
        # corpus is cold/thin for this user or embeddings are off, so a search
        # never returns empty during rollout.
        _set(db, search, stage="Searching the job corpus…")
        jobs, scanned = _corpus_candidates(db, profile, candidate, settings, terms)

        if jobs is None:
            _set(db, search, stage="Collecting job postings…")
            raw = sources.collect_all(profile, settings)
            scanned = len(raw)
            # Write-through so this fetch also enriches the shared corpus.
            _cache_to_corpus(raw)
            unique: dict[str, object] = {}
            for job in raw:
                if prefilter(job, profile):
                    unique.setdefault(job.dedup_key(), job)
            located = len(unique)
            _set(db, search, raw_count=scanned, located_count=located,
                 stage=f"Filtering {located} jobs to your locations…")
            jobs = cap_per_company(list(unique.values()), terms=terms)
            if len(jobs) > 40:
                _set(db, search, stage=f"Shortlisting {len(jobs)} jobs…")
                jobs = matcher.triage(jobs, profile, candidate, company_profile)
        else:
            located = len(jobs)   # the corpus already filtered by location
            log.info("Search %s: corpus mode (%d scanned -> %d to score)",
                     search.id, scanned, len(jobs))

        _set(db, search, raw_count=scanned, located_count=located, ranked_count=len(jobs))

        _set(db, search, stage=f"Scoring {len(jobs)} jobs in detail…")
        _enrich(jobs)
        feedback = _feedback_examples(db, user)
        scored = _score_cached(db, matcher, jobs, profile, materials, feedback,
                               company_profile, criteria, settings)

        # Tier 1-3 are the real matches; tier 4 are "long shots" shown in a
        # collapsed section so the list has more to offer without diluting the
        # top of it. Tier 5 is never shown.
        by_rank = lambda x: (x[1].tier, -x[1].score)
        ranked = sorted([(j, m) for j, m in scored if m.tier <= 3], key=by_rank)[:MAX_RESULTS_STORED]
        long_shots = sorted([(j, m) for j, m in scored if m.tier == 4], key=by_rank)[:MAX_LONGSHOTS]
        ranked = ranked + long_shots

        _set(db, search, stage="Saving results…")
        for i, (job, match) in enumerate(ranked, start=1):
            good, bad = _split_reasons(match.reasons)
            db.add(JobResult(
                search_id=search.id, user_id=user.id, position=i,
                short_id=job.short_id(), dedup_key=job.dedup_key(), tier=match.tier,
                tier_label=match.tier_label, score=match.score,
                fit_role=match.fit_role, fit_candidate=match.fit_candidate,
                title=match.role or job.title,
                company=match.company or job.company,
                company_url=_company_url(job),
                company_blurb="",
                location=match.location or job.location,
                description=(job.description or "")[:4000],
                apply_url=job.url, source=job.source,
                tags=list(match.tags), why_good=good, why_bad=bad,
            ))
        db.commit()

        # A run that couldn't score most of its shortlist is not a run that
        # "found nothing" — say which it was, or the next hour goes into
        # debugging filters that were working fine.
        note = ""
        if matcher.failures and jobs:
            share = matcher.failures / len(jobs)
            if share >= 0.2:
                note = (
                    f"Only {len(jobs) - matcher.failures} of {len(jobs)} "
                    "shortlisted jobs could be scored — these results are "
                    "incomplete. This is usually an exhausted AI API balance."
                )
                log.error("Search %s: %s", search.id, note)

        _set(db, search, status="done", stage="Done", error=note,
             scored_count=len(ranked), finished_at=utcnow())
        log.info("Search %s finished: %d results", search.id, len(ranked))
        from .events import record
        record(db, "scan_completed", user_id=user_id, count=len(ranked))

    except Exception as exc:  # never leave a search stuck in 'running'
        log.exception("Search %s failed", search_id)
        try:
            search = db.get(Search, search_id)
            if search:
                _set(db, search, status="failed", stage="",
                     error=str(exc)[:500], finished_at=utcnow())
        except Exception:
            pass
    finally:
        db.close()


# --------------------------------------------------------------------------- #
def _merge_terms(user_terms: list[str], derived: list[str], cap: int = 10) -> list[str]:
    """User terms first (higher priority), then adjacent derived roles.

    Case-insensitive de-dupe. The order matters downstream: keyword sources
    take the first N per their own cap, and title-relevance ranking favours
    earlier terms — so the user's stated terms carry more weight, the derived
    ones widen the net.
    """
    out: list[str] = []
    seen: set[str] = set()
    for term in list(user_terms) + list(derived):
        t = (term or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:cap]


CORPUS_FRESH_DAYS = 30    # ignore corpus jobs not seen in a fresh ingest since
CORPUS_TOPK = 60          # generous — cosine ranks, the LLM scorer decides
CORPUS_MIN_KEEP = 20      # below this the corpus is too thin -> live fallback


def _job_to_posting(row) -> object:
    from jobhunter.models import JobPosting
    return JobPosting(
        source=row.source, title=row.title, company=row.company,
        location=row.location, description=row.description, url=row.url,
        is_remote=(row.remote_mode == "remote"),
    )


def _candidate_query_text(profile, candidate) -> str:
    """The text we embed to represent what this candidate wants.

    Includes the user's own search terms (their favourite job titles) as well as
    the roles derived from the CV, so titles they add explicitly genuinely
    influence the semantic match, not only which postings get fetched.
    """
    parts = [
        profile.objective or "",
        getattr(candidate, "headline", "") or "",
        " ".join(profile.search_terms or []),        # user's stated titles
        " ".join(candidate.target_roles or []),      # titles derived from the CV
        " ".join(candidate.skills or []),
    ]
    return ". ".join(p for p in parts if p) or "job"


def _corpus_candidates(db, profile, candidate, settings, terms):
    """SQL-filter + cosine-rank the corpus into a top-K shortlist to score.

    Returns (jobs, scanned) or (None, scanned) to signal the caller should fall
    back to a live fetch — when embeddings are off, the profile can't be
    embedded, or the corpus is too thin for this user's geography.
    """
    from jobhunter import embeddings
    from ..models import Job

    if not embeddings.is_configured(settings):
        return None, 0
    pvec = embeddings.embed_one(_candidate_query_text(profile, candidate), settings)
    if not pvec:
        return None, 0

    cutoff = utcnow() - timedelta(days=CORPUS_FRESH_DAYS)
    rows = (db.query(Job)
              .filter(Job.embedding.isnot(None), Job.last_seen_at >= aware(cutoff))
              .all())

    # Same geography gate as live search, on the corpus rows.
    cands, vec_by_key = [], {}
    for r in rows:
        p = _job_to_posting(r)
        if prefilter(p, profile):
            cands.append(p)
            vec_by_key[p.dedup_key()] = r.embedding
    if len(cands) < CORPUS_MIN_KEEP:
        return None, len(rows)

    capped = cap_per_company(cands, terms=terms)
    capped.sort(key=lambda p: -embeddings.cosine(pvec, vec_by_key.get(p.dedup_key(), [])))
    return capped[:CORPUS_TOPK], len(rows)


def _score_cached(db, matcher, jobs, profile, materials, feedback,
                  company_profile, criteria, settings):
    """Score only the jobs not already cached under an identical context.

    Cuts the dominant per-search cost on repeat/overlapping searches. A cache
    hit is reused as-is; misses are scored once and stored. Fails open: any
    cache trouble falls back to scoring everything.
    """
    from . import score_cache
    try:
        ctx = score_cache.context_key(profile, materials, feedback,
                                      company_profile, criteria, settings.scoring_model)
        by_hash = {j.dedup_key(): score_cache.job_hash(ctx, j) for j in jobs}
        cached = score_cache.get_many(db, list(by_hash.values()))
    except Exception as exc:
        log.warning("Score cache unavailable, scoring all: %s", exc)
        return matcher.score(jobs, profile, materials, feedback, company_profile, criteria)

    hits, misses = [], []
    for j in jobs:
        m = cached.get(by_hash[j.dedup_key()])
        (hits.append((j, m)) if m is not None else misses.append(j))

    fresh = (matcher.score(misses, profile, materials, feedback, company_profile, criteria)
             if misses else [])
    if fresh:
        score_cache.put_many(
            db, [(by_hash[j.dedup_key()], j, m, settings.scoring_model) for j, m in fresh])
    log.info("Search %s: %d cached + %d scored", getattr(matcher, "_sid", "?"),
             len(hits), len(fresh))
    return hits + fresh


def _cache_to_corpus(postings) -> None:
    """Upsert fetched postings into the shared corpus, in an isolated session."""
    from .corpus_service import upsert_jobs

    cdb = SessionLocal()
    try:
        upsert_jobs(cdb, postings)
    finally:
        cdb.close()


def _enrich(jobs) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from jobhunter.sources.ats import enrich_description

    missing = [j for j in jobs if not j.description][:200]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(enrich_description, missing))


def _split_reasons(reasons: str) -> tuple[str, str]:
    """The matcher writes one paragraph; the UI wants 'why good' vs 'why bad'.

    Split on the first contrast marker. Anything unsplittable is treated as the
    positive case, since a tier<=3 job is being shown for a reason.
    """
    text = (reasons or "").strip()
    for marker in (" However,", " But ", " however,", " Gaps:", " Concerns:",
                   " Misalignment", " but ", " although ", " Although "):
        if marker in text:
            head, _, tail = text.partition(marker)
            return head.strip(), tail.strip().lstrip(",. ").capitalize()
    return text, ""


def _company_url(job) -> str:
    """Best-effort link to the company, not the advert."""
    src = job.source or ""
    if src.startswith("ats:"):
        parts = src.split(":")
        if len(parts) >= 3:
            return f"https://www.google.com/search?q={parts[2]}+careers"
    return ""


def _feedback_examples(db: DbSession, user: User) -> list[dict]:
    """Past 1-5 ratings, fed back into scoring so it learns (R9.2). Heaviest
    signals first; the borderline threes are the hard cases."""
    from ..models import RATING_VERDICT, RATING_WEIGHT
    rows = (
        db.query(Feedback, JobResult)
        .join(JobResult, Feedback.job_result_id == JobResult.id)
        .filter(Feedback.user_id == user.id)
        .order_by(Feedback.created_at.desc())
        .limit(20)
        .all()
    )
    examples = [
        {
            "title": jr.title,
            "company": jr.company,
            "url": jr.apply_url,
            "verdict": RATING_VERDICT.get(fb.rating or 3, "borderline"),
            "weight": RATING_WEIGHT.get(fb.rating or 3, 0.0),
            "reason": fb.note or "",
        }
        for fb, jr in rows
    ]
    examples.sort(key=lambda e: -e["weight"])   # strongest signals first
    return examples
