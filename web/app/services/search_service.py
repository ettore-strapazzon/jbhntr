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
        # fair-use ceiling — see docs/ARCHITECTURE.md. An operator reset moves the
        # window start forward (usage_reset_at), so it also clears this daily cap.
        since = utcnow() - timedelta(days=1)
        reset_at = aware(user.usage_reset_at)
        if reset_at and reset_at > since:
            since = reset_at
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


def _trigger_discovery_if_changed(user_id: int) -> None:
    """Fire per-user similar-company discovery (occasions 1-3) in the background.

    Runs when this premium user searches for the first time after setting up their
    profile, after adding 3+ seed companies, or after changing a market signal (a
    new vertical, company type or target country). Owns its own DB session and
    never blocks or fails the search — the companies it finds enrich the shared
    corpus for subsequent searches. The weekly Monday cron still handles the
    periodic refresh (occasion 4) for everyone.
    """
    def _work():
        db = SessionLocal()
        try:
            from .companies_service import (
                discover_for_user, discovery_change_trigger, discovery_signals,
            )
            user = db.get(User, user_id)
            if not user or not user.is_premium:
                return
            if not discovery_change_trigger(user, discovery_signals(db, user)):
                return
            res = discover_for_user(db, user)
            log.info("search-triggered discovery for user %s: %s", user_id, res)
        except Exception:
            log.exception("search-triggered discovery failed for user %s", user_id)
        finally:
            db.close()

    threading.Thread(target=_work, daemon=True).start()


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

        # Premium: if the profile just changed materially (first run, 3+ new seed
        # companies, or a new vertical), kick off similar-company discovery in the
        # background so its finds land in the corpus for the next search.
        _trigger_discovery_if_changed(user_id)

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

        # Persist the derived roles (from objective + CV) so the shared corpus
        # ingest queries them too — not just the titles the user typed. Free: the
        # derive call above already ran. Committed with the search's next _set.
        if user.profile is not None and candidate.target_roles:
            user.profile.derived_roles = list(dict.fromkeys(candidate.target_roles))[:15]

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

        # Hard location gate, now that the LLM has surfaced the real location for
        # postings that reached scoring with a blank location field. Location is a
        # hard requirement, so a job the enriched location places in a country the
        # user didn't choose (with no remote they could take) is dropped outright,
        # not shown as a long shot.
        before = len(scored)
        scored = [(j, m) for (j, m) in scored if _location_ok(j, m, profile)]
        if before != len(scored):
            log.info("Search %s: location gate dropped %d of %d scored",
                     search.id, before - len(scored), before)

        # Tier 1-3 are the real matches; tier 4 are "long shots" shown in a
        # collapsed section so the list has more to offer without diluting the
        # top of it. Tier 5 is never shown.
        by_rank = lambda x: (x[1].tier, -x[1].score)
        ranked = sorted([(j, m) for j, m in scored if m.tier <= 3], key=by_rank)[:MAX_RESULTS_STORED]
        long_shots = sorted([(j, m) for j, m in scored if m.tier == 4], key=by_rank)[:MAX_LONGSHOTS]
        ranked = ranked + long_shots

        # Verify the links the user will actually see are live and ungated, so no
        # one clicks into a 404 or a login wall. Drops the dead ones and purges
        # them from the shared corpus. Fail-soft — never blocks a search.
        _set(db, search, stage="Checking links…")
        ranked = _verify_links(db, ranked)

        _set(db, search, stage="Saving results…")
        for i, (job, match) in enumerate(ranked, start=1):
            good, bad = _reasons_for_card(match)
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
CORPUS_MIN_KEEP = 20      # below this the corpus is too thin -> live fallback
# How many geo-matched, cosine-ranked jobs go to the paid scorer (config.corpus_topk,
# default 60). The per-search cost lever — raise for more matches, at more LLM spend.


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


VERIFY_LIMIT = 30    # top results to link-check before showing (bounds latency)
_VERIFY_UA = "Mozilla/5.0 (compatible; JBHNTR-linkcheck/1.0)"


def _verify_links(db: DbSession, ranked: list) -> list:
    """Link-check the top results; drop the dead/gated ones and purge them from
    the shared corpus, so a user never sees a 404 or a login-wall. Survivors are
    stamped checked so the nightly reaper skips them. Fail-soft: any trouble and
    the unmodified list is returned (a working search beats a perfect one)."""
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    from ..models import Job
    from .reaper import check_url

    from .recover import recover_apply_url

    head = ranked[:VERIFY_LIMIT]
    if not head:
        return ranked
    try:
        with httpx.Client(timeout=12.0, headers={"User-Agent": _VERIFY_UA}) as client:
            def _one(pair):
                job, _m = pair
                return job.dedup_key(), check_url(job.url, client)
            with ThreadPoolExecutor(max_workers=10) as pool:
                verdicts = dict(pool.map(_one, head))
    except Exception as exc:
        log.warning("Link verification skipped: %s", exc)
        return ranked

    # Gated (login-walled) jobs are usually still live — try to recover the real
    # apply link from the company's own ATS before giving up. Recovered jobs keep
    # their place with the new URL; the rest of the gated ones are dropped.
    recovered = 0
    for job, _m in head:
        if verdicts.get(job.dedup_key()) != "gated":
            continue
        new_url = recover_apply_url(job.company, job.title)
        if new_url:
            job.url = new_url
            verdicts[job.dedup_key()] = "active"
            recovered += 1

    dead = {k for k, v in verdicts.items() if v in ("gone", "gated")}
    live = {k for k, v in verdicts.items() if k not in dead}
    by_key = {j.dedup_key(): j for j, _ in head}
    try:
        for k in dead:                       # dead-end links: purge from the corpus
            db.query(Job).filter(Job.dedup_key == k).delete(synchronize_session=False)
        for k in live:                       # keep; stamp checked (+ save any recovered URL)
            vals = {Job.last_checked_at: utcnow()}
            if k in by_key and by_key[k].url:
                vals[Job.url] = by_key[k].url[:1000]
            db.query(Job).filter(Job.dedup_key == k).update(vals, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    if dead or recovered:
        log.info("Search: %d dead/gated links dropped, %d recovered from ATS",
                 len(dead), recovered)
    return [(j, m) for (j, m) in ranked if j.dedup_key() not in dead]


def _location_ok(job, match, profile) -> bool:
    """Final hard location gate, run AFTER scoring on the best location we have.

    Targets one specific leak: a place-BOUND (on-site/hybrid) foreign job that
    reached scoring with a blank location field (adzuna often omits it), so the
    country tag and the cheap prefilter both deferred and the scorer — shown an
    empty location — scored it on role fit. By results time we have
    `match.location`, the location the LLM pulled out of the description
    ("Albany, New York, USA"); re-run the prefilter's geo logic against it so the
    on-site foreign leak is dropped, not shown.

    Deliberately does NOT re-judge remote roles. A remote job is location-
    independent, and if the user accepts remote (any "Remote-*" token) the earlier
    pipeline already governed which remote postings were eligible — second-
    guessing them here on their nominal city ("Remote, Germany") wrongly drops the
    remote work they explicitly asked for. Also keeps the job when the enriched
    location is blank (nothing to judge) or the user set no location constraint.
    """
    locs = profile.locations or []
    if not locs:
        return True
    loc = ((getattr(match, "location", "") or "") or (getattr(job, "location", "") or "")).strip()
    if not loc:
        return True
    # Remote role + user open to remote -> not a location conflict; leave it.
    accepts_remote = any(str(t).lower().startswith("remote") for t in locs)
    if accepts_remote and _is_remote_job(job, match, loc):
        return True
    try:
        probe = job.model_copy(update={"location": loc})
    except Exception:
        return True
    return prefilter(probe, profile)


def _is_remote_job(job, match, loc: str) -> bool:
    """Best-effort: is this posting actually remote? Uses the LLM's read, the
    posting's own signal, and the location text — any one is enough."""
    if "remote" in (loc or "").lower():
        return True
    if "remote" in str(getattr(match, "remote", "") or "").lower():
        return True
    try:
        return bool(job.looks_remote())
    except Exception:
        return False


def _country_allowed(job_countries, remote_mode, target_codes, remote_any) -> bool:
    """Hard geo gate using the corpus country tag (which the nightly backfill now
    fills for the long tail). True = keep.

    Defers to the text prefilter when we can't decide: an untagged job, or a user
    with no country constraint. Otherwise: keep only a job whose settled country
    is one the user chose — or any remote job when the user takes remote-anywhere.
    """
    if not job_countries or not target_codes:
        return True
    if set(job_countries) & set(target_codes):
        return True
    return bool(remote_any and remote_mode == "remote")


def _corpus_candidates(db, profile, candidate, settings, terms):
    """SQL-filter + cosine-rank the corpus into a top-K shortlist to score.

    Returns (jobs, scanned) or (None, scanned) to signal the caller should fall
    back to a live fetch — when embeddings are off, the profile can't be
    embedded, or the corpus is too thin for this user's geography.
    """
    from jobhunter import embeddings, geo
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

    # The user's target countries (from their location tokens) and whether they
    # take remote-from-anywhere — the inputs to the hard country gate below.
    target_codes = {geo.country_of(t) for t in (profile.locations or [])} - {""}
    remote_any = "Remote-Anywhere" in (profile.locations or [])

    # Geography gate: the resolved country tag first (a hard cut for jobs we've
    # confidently placed in another country), then the text prefilter for the
    # rest (remote tokens, cities, still-untagged rows).
    #
    # Split the survivors by CONFIDENCE, not just pass/fail. A job is "confirmed"
    # when it affirmatively matches the user's geography — its country tag is one
    # they chose, or its non-blank location matched a location token. A job that
    # passed only because BOTH its country tag and location were blank slipped
    # through by deferral: we cannot actually place it ("ambiguous"). With
    # thousands of untagged rows in the corpus, the ambiguous set otherwise
    # dominates the cosine shortlist and buries real in-country jobs — e.g. 953
    # Italy jobs pushed out of the top-K by 7k untagged rows, so nothing Italian
    # ever reaches the scorer and the search returns empty. Rank confirmed first;
    # fall back to ambiguous only to reach a workable shortlist size.
    confirmed, ambiguous, vec_by_key = [], [], {}
    for r in rows:
        if not _country_allowed(r.countries, r.remote_mode, target_codes, remote_any):
            continue
        p = _job_to_posting(r)
        if not prefilter(p, profile):
            continue
        vec_by_key[p.dedup_key()] = r.embedding
        placed = (bool(set(r.countries or []) & target_codes)
                  or bool((r.location or "").strip()))
        (confirmed if placed else ambiguous).append(p)

    pool = confirmed if len(confirmed) >= CORPUS_MIN_KEEP else confirmed + ambiguous
    if len(pool) < CORPUS_MIN_KEEP:
        return None, len(rows)

    capped = cap_per_company(pool, terms=terms)
    capped.sort(key=lambda p: -embeddings.cosine(pvec, vec_by_key.get(p.dedup_key(), [])))
    return capped[:config.corpus_topk], len(rows)


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


def _reasons_for_card(match) -> tuple[str, str]:
    """(why_good, why_bad) for the card. Prefer the scorer's separate strengths/
    concerns lists; fall back to splitting the single reasons blob for older
    cached scores that predate those fields."""
    strengths = [s for s in (getattr(match, "strengths", None) or []) if s.strip()]
    concerns = [s for s in (getattr(match, "concerns", None) or []) if s.strip()]
    if strengths or concerns:
        return "\n".join(strengths), "\n".join(concerns)
    return _split_reasons(match.reasons)


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
