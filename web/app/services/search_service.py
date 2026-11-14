"""Run the jobhunter engine for one user and persist the results.

This is the only place the web app drives the engine. It runs in a background
thread (or an RQ worker in production) because a search takes minutes.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from jbhntr_engine import Matcher, cap_per_company, collect_all_sources
from jbhntr_engine import Settings as EngineSettings
from jbhntr_engine import (
    derive_candidate, derive_company_profile, derive_criteria, prefilter, resolve_seeds,
)

from ..config import config
from ..db import SessionLocal
from ..models import Feedback, JobResult, Search, User, aware, utcnow
from .profile_service import (
    build_engine_materials, build_engine_profile, completeness, seed_values,
)

log = logging.getLogger("jbhntr.search")

# A real scan takes a few minutes; a 'running' search with no progress write
# (heartbeat) for this long is treated as a hung/killed worker and recovered by
# the status poller and the boot/nightly sweep.
STUCK_SEARCH_MINUTES = 15


def _silent_since(minutes: int):
    """SQL filter: no worker progress write for `minutes`. Measured from the
    heartbeat (`last_progress_at`), falling back to `started_at` while it is NULL
    — a queued scan the worker never touched, or a row from before R3-28."""
    return (func.coalesce(Search.last_progress_at, Search.started_at)
            < utcnow() - timedelta(minutes=minutes))

MAX_RESULTS_STORED = 60   # tier 1-3 shown; scoring already filters hard
MAX_LONGSHOTS = 15        # tier-4 "long shots", shown in a collapsed section


class QuotaError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
def _profile_hash(user: User) -> str:
    """Stable hash of the profile fields the engine reads, for the free-rerun check."""
    import hashlib
    import json
    p = user.profile
    if not p:
        return ""
    payload = json.dumps({
        "objective": p.objective, "seniority": sorted(p.seniority or []),
        "company_type": sorted(p.company_type or []), "verticals": sorted(p.verticals or []),
        "locations": sorted(p.locations or []), "work_modes": sorted(p.work_modes or []),
        "search_terms": sorted(p.search_terms or []), "salary_floor_eur": p.salary_floor_eur,
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _free_rerun(db: DbSession, user: User, phash: str) -> bool:
    """An identical-profile re-run within 24h of a completed scan is free (PRICE-04)."""
    if not phash:
        return False
    since = utcnow() - timedelta(days=1)
    return db.query(Search).filter(
        Search.user_id == user.id, Search.status == "done",
        Search.profile_hash == phash,
        Search.finished_at >= aware(since)).count() > 0


def start_search(db: DbSession, user: User, free: bool = False) -> Search:
    """Validate, create the row, charge credits (or run free), and kick off the
    work. Raises QuotaError (profile incomplete) or credits.InsufficientCredits
    (which the route renders as the zero state). Debit BEFORE compute — the worker
    refunds on failure (`_run_search`)."""
    from . import credits
    state = completeness(db, user)
    if not state.can_search:
        from . import events
        from .activation import assign_variant
        events.record(db, "scan_blocked_incomplete", user_id=user.id,
                      count=len(state.missing_required),
                      variant=assign_variant(user.id))
        raise QuotaError("Finalise your profile first: " + ", ".join(state.missing_required))

    phash = _profile_hash(user)
    free_kind = "first" if free else ("rerun" if _free_rerun(db, user, phash) else "paid")
    if free_kind == "paid" and not credits.can_afford(db, user, config.cost_search):
        raise credits.InsufficientCredits(config.cost_search, credits.balance(db, user))

    search = Search(user_id=user.id, status="queued", stage="Starting…", profile_hash=phash)
    db.add(search)
    db.commit()
    db.refresh(search)

    if free_kind == "first":
        user.first_scan_used_at = utcnow()
        credits.record(db, user, "first_scan_free", ref_type="search", ref_id=str(search.id))
    elif free_kind == "rerun":
        credits.record(db, user, "search", ref_type="search", ref_id=str(search.id),
                       note="Repeat scan within 24 hours")
    else:
        credits.debit(db, user, config.cost_search, "search", ref_type="search",
                      ref_id=str(search.id), idempotency_key=f"search:{search.id}")
    db.commit()

    from .activation import assign_variant
    from .events import record
    # R3-04: the arm rides on the KPI numerator so first-scan rate reads per cohort.
    record(db, "scan_started", user_id=user.id, variant=assign_variant(user.id))

    threading.Thread(target=_run_search, args=(search.id, user.id, free_kind), daemon=True).start()
    return search


# --------------------------------------------------------------------------- #
def fail_stuck_searches(db: DbSession, older_than_minutes: int | None = None) -> int:
    """Global sweep: recover EVERY user's scans left 'running'/'queued' by an
    interrupted worker.

    A scan runs in a daemon thread inside the web process, so a deploy or restart
    kills it mid-run with no exception — stranding the Search row forever and the
    progress poller with it. Boot (app lifespan) and the nightly cron both call it
    with the STUCK_SEARCH_MINUTES floor, measured from the last progress write
    (R3-28): boot can't tell its own orphans from a live scan on another instance (R3-26), and the cron also catches a thread that
    hung without the process dying. `older_than_minutes=None` (no floor) is only
    safe with a single instance and no live workers. A user's status poll does
    NOT call this — it reaps only its own row via `reap_stuck_search` (R3-24). Returns the number of rows reaped."""
    q = db.query(Search.id).filter(Search.status.in_(("running", "queued")))
    if older_than_minutes is not None:
        q = q.filter(_silent_since(older_than_minutes))
    n = sum(reap_stuck_search(db, sid, older_than_minutes=older_than_minutes)
            for (sid,) in q.all())
    if n:
        log.info("Recovered %d interrupted search(es)", n)
    return n


def reap_stuck_search(db: DbSession, search_id: int, *, user_id: int | None = None,
                      older_than_minutes: int | None = None) -> bool:
    """Fail ONE stuck scan and undo its charge (refund a paid scan, or free the
    first-scan slot). `user_id` scopes it to the caller's own row (status poll).

    The status flip is a conditional UPDATE (… WHERE status IN running/queued), so
    when the per-search reap, the global sweep or two workers race on the same row
    exactly one claims it and only that one undoes the charge. The refund is also
    idempotency-keyed (`refund:{debit id}`) as a second line. Returns True iff this
    call claimed the row."""
    from . import credits
    from ..models import CreditLedger

    q = db.query(Search).filter(Search.id == search_id,
                                Search.status.in_(("running", "queued")))
    if user_id is not None:
        q = q.filter(Search.user_id == user_id)
    if older_than_minutes is not None:
        q = q.filter(_silent_since(older_than_minutes))
    claimed = q.update({Search.status: "failed", Search.stage: "",
                        Search.error: "Interrupted — please run the scan again.",
                        Search.finished_at: utcnow()}, synchronize_session=False)
    db.commit()
    if not claimed:
        return False
    s = db.get(Search, search_id)
    db.refresh(s)
    debit = (db.query(CreditLedger)
             .filter(CreditLedger.idempotency_key == f"search:{s.id}").first())
    if debit is not None:
        credits.refund(db, debit)        # idempotent; no-op if it wasn't a debit
    else:
        first = (db.query(CreditLedger)
                 .filter(CreditLedger.reason == "first_scan_free",
                         CreditLedger.ref_id == str(s.id)).first())
        if first is not None:
            u = db.get(User, s.user_id)
            if u is not None and u.first_scan_used_at is not None:
                u.first_scan_used_at = None      # let them retry the free scan
                db.commit()
    return True


# --------------------------------------------------------------------------- #
class _ScanReaped(Exception):
    """The worker's row is no longer running/queued: a reaper failed (and refunded)
    it under us. The worker stops and writes nothing more (R3-25)."""


def _claim(db: DbSession, search_id: int, **fields) -> bool:
    """Write `fields` to the scan only while it is still running/queued, with the
    same conditional UPDATE the reaper uses, then commit. On a lost claim roll back
    instead, so nothing staged with this write (e.g. the JobResult rows) lands.
    Every write also stamps the heartbeat the stuck floor is measured from (R3-28)."""
    fields = {"last_progress_at": utcnow(), **fields}
    n = (db.query(Search)
         .filter(Search.id == search_id, Search.status.in_(("running", "queued")))
         .update(fields, synchronize_session=False))
    if not n:
        db.rollback()
        return False
    db.commit()
    return True


def _set(db: DbSession, search: Search, **fields) -> None:
    """Worker progress/status write. Raises `_ScanReaped` if the row was reaped, so
    a still-alive thread can't resurrect a 'failed' scan or keep spending compute."""
    if not _claim(db, search.id, **fields):
        raise _ScanReaped(search.id)


# In-stage heartbeat (R3-29): at most one progress write per this many seconds.
# Far below STUCK_SEARCH_MINUTES, far above "a DB write per scored job".
HEARTBEAT_SECONDS = 30


class _Heartbeat:
    """The throttled ``progress(done, total)`` callback handed to the engine's long
    stages (scoring, live fetch; R3-30/31: enrichment, link checks, triage, and
    between the opening AI calls), so a stage running past STUCK_SEARCH_MINUTES
    keeps stamping `last_progress_at` and isn't reaped mid-flight (R3-29).

    It writes through `_claim`, so a reaped row is never written (never revived).
    On a lost claim it does NOT raise into the engine: the engine treats progress
    as an observer (`report_progress` swallows errors, and `collect_all` runs each
    source under a catch-all), and an exception out of the scoring loop would
    still wait for the in-flight pool anyway — so a raise would be eaten or buy
    nothing. Instead it sets `reaped`, goes quiet, and the worker calls `check()`
    right after the stage, which raises `_ScanReaped` into the normal reaped path.
    Any other failure (DB hiccup) is logged and swallowed: a missed beat must
    never kill a healthy scan. Beats from a non-owner thread are dropped — the
    worker's session is not thread-safe (the engine contract says caller's thread).

    `should_stop` (R3-30) is the same flag as the engine's cancellation hook: once
    a beat has lost its claim the engine stops at its next job/source and returns
    early; the worker's `check()` then discards the partial output.
    """

    def __init__(self, db: DbSession, search_id: int, label: str, *,
                 every: float | None = None, clock=time.monotonic):
        self.db, self.search_id, self.label = db, search_id, label
        self.every = HEARTBEAT_SECONDS if every is None else every
        self.clock = clock
        self.reaped = False
        self._owner = threading.get_ident()
        self._last = clock()          # the stage itself was just written by `_set`

    def __call__(self, done: int, total: int) -> None:
        if self.reaped or threading.get_ident() != self._owner:
            return
        now = self.clock()
        if now - self._last < self.every:
            return
        self._last = now
        try:
            if not _claim(self.db, self.search_id, stage=f"{self.label} {done}/{total}"):
                self.reaped = True
                log.warning("Search %s reaped mid-stage; stopping after this stage",
                            self.search_id)
        except Exception as exc:
            log.warning("Search %s heartbeat write failed (scan continues): %s",
                        self.search_id, exc)
            try:
                self.db.rollback()
            except Exception:
                pass

    def should_stop(self) -> bool:
        """The engine's `should_stop` hook: True once this scan has been reaped."""
        return self.reaped

    def check(self) -> None:
        """Call after the stage: stop the worker if the scan was reaped during it."""
        if self.reaped:
            raise _ScanReaped(self.search_id)


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
            if not user:
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


def _run_search(search_id: int, user_id: int, free_kind: str = "paid") -> None:
    """Background worker. Owns its own DB session. `free_kind` (paid|first|rerun)
    decides the credit correction if the scan fails."""
    db = SessionLocal()
    try:
        search = db.get(Search, search_id)
        user = db.get(User, user_id)
        if not search or not user:
            return

        settings = EngineSettings.from_env()
        settings.scoring_model = config.scoring_model   # one quality level (D-2)

        # Premium: if the profile just changed materially (first run, 3+ new seed
        # companies, or a new vertical), kick off similar-company discovery in the
        # background so its finds land in the corpus for the next search.
        _trigger_discovery_if_changed(user_id)

        profile = build_engine_profile(db, user)
        materials = build_engine_materials(db, user)
        labels = [s.label() for s in resolve_seeds(seed_values(db, user),
                                                   guess_domains=True)]

        # Derive the candidate profile FIRST: keyword-based sources need real
        # job titles to query. Users who skip the optional "job titles" step
        # would otherwise get no keyword results at all.
        _set(db, search, status="running", stage="Understanding your profile…")
        # Three serial AI calls follow (candidate, company profile, criteria), each
        # up to ~90 s (45 s timeout + 1 retry), ~185 s on the OpenAI-compatible
        # client (strict + loose JSON attempts): ~9 min with no write. Beat between
        # them (R3-31); a reaped scan stops before the next paid call.
        opening = _Heartbeat(db, search.id, "Understanding your profile…")
        candidate = derive_candidate(profile, materials, settings)
        opening(1, 3)
        opening.check()
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
        opening(2, 3)
        opening.check()
        criteria = derive_criteria(profile, labels, settings)
        opening(3, 3)
        opening.check()
        matcher = Matcher(settings)

        # Step 4: read the shared corpus (fast — no live fetch). Cosine ranking
        # replaces the AI triage stage. Falls back to a live fetch when the
        # corpus is cold/thin for this user or embeddings are off, so a search
        # never returns empty during rollout.
        _set(db, search, stage="Searching the job corpus…")
        jobs, scanned, matched = _corpus_candidates(db, profile, candidate, settings, terms)

        if jobs is None:
            _set(db, search, stage="Collecting job postings…")
            beat = _Heartbeat(db, search.id, "Collecting job postings…")
            raw = collect_all_sources(profile, settings, progress=beat,
                                      should_stop=beat.should_stop)
            beat.check()
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
                # ceil(N/25) SERIAL AI batches — minutes on a big fetch (R3-31).
                beat = _Heartbeat(db, search.id, "Shortlisting")
                jobs = matcher.triage(jobs, profile, candidate, company_profile,
                                      progress=beat, should_stop=beat.should_stop)
                beat.check()
        else:
            # `matched` is the full set of jobs in the user's geography; `jobs` is
            # the cosine-ranked top-K sent to scoring. Show the true located count.
            located = matched
            log.info("Search %s: corpus mode (%d scanned, %d located -> %d to score)",
                     search.id, scanned, matched, len(jobs))

        _set(db, search, raw_count=scanned, located_count=located, ranked_count=len(jobs))

        _set(db, search, stage=f"Scoring {len(jobs)} jobs in detail…")
        # Enrichment and the link check fetch pages for minutes too (R3-30): beat.
        # The label keeps "scor" so the progress rail stays on the scoring step.
        beat = _Heartbeat(db, search.id, "Scoring: reading job descriptions")
        _enrich(jobs, db, beat=beat)
        beat.check()
        feedback = _feedback_examples(db, user)
        beat = _Heartbeat(db, search.id, "Scoring")
        scored = _score_cached(db, matcher, jobs, profile, materials, feedback,
                               company_profile, criteria, settings, progress=beat,
                               should_stop=beat.should_stop)
        beat.check()

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
        beat = _Heartbeat(db, search.id, "Checking links…")
        ranked, unverified = _verify_links(db, ranked, beat=beat)
        beat.check()

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
                link_status=("unverified" if job.dedup_key() in unverified else ""),
            ))
        # Not committed here: the results land in the same transaction as the
        # claim to 'done' below, so a reaped scan's results are rolled back (R3-25).

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
        # A completed scan is the referred friend's activation — pay the inviter once
        # (idempotent; no-op for a non-referred user). REFERRAL-02.
        from . import referral
        u = db.get(User, user_id)
        if u is not None:
            referral.reward_inviter_if_activated(db, u)

    except _ScanReaped:
        # A reaper already failed + refunded this scan (it looked hung). Its results
        # were rolled back; the reaper's 'failed' and refund stand. Charge nothing,
        # refund nothing — the user re-runs from the "Interrupted" message.
        log.warning("Search %s was reaped while still running; results discarded",
                    search_id)
    except Exception as exc:  # never leave a search stuck in 'running'
        log.exception("Search %s failed", search_id)
        try:
            db.rollback()
            # Only the writer that flips the row to 'failed' undoes the charge: if a
            # reaper got there first it already refunded / freed the slot (R3-25).
            if not _claim(db, search_id, status="failed", stage="",
                          error=str(exc)[:500], finished_at=utcnow()):
                log.warning("Search %s already reaped; skipping credit correction",
                            search_id)
                return
            # Never charge for a failure: refund a paid scan, or free the first-scan
            # slot so the user can retry for free (PRICE-04 / ONBOARD-02).
            from . import credits
            from ..models import CreditLedger
            if free_kind == "paid":
                row = (db.query(CreditLedger)
                       .filter(CreditLedger.idempotency_key == f"search:{search_id}").first())
                if row is not None:
                    credits.refund(db, row)
            elif free_kind == "first":
                u = db.get(User, user_id)
                if u is not None and u.first_scan_used_at is not None:
                    u.first_scan_used_at = None
                    db.commit()
        except Exception:
            log.exception("credit correction after failed search %s", search_id)
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
    from jbhntr_engine import JobPosting
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


def _verify_links(db: DbSession, ranked: list, beat=None) -> tuple[list, set]:
    """Link-check the top results; drop the dead/gated ones and purge them from
    the shared corpus, so a user never sees a 404 or a login-wall. Survivors are
    stamped checked so the nightly reaper skips them. Fail-soft: any trouble and
    the unmodified list is returned (a working search beats a perfect one).

    `beat` (a `_Heartbeat`, R3-30) is called on this thread per checked link and
    per recovery attempt (recovery is serial, up to 3 ATS boards per link). If it
    says stop, the unmodified list is returned and the corpus is not touched."""
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    from jbhntr_engine import recover_apply_url

    from ..models import Job
    from .reaper import BROWSER_HEADERS, check_url

    head = ranked[:VERIFY_LIMIT]
    if not head:
        return ranked, set()
    try:
        with httpx.Client(timeout=12.0, headers=BROWSER_HEADERS) as client:
            def _one(pair):
                job, _m = pair
                return job.dedup_key(), check_url(job.url, client)
            with ThreadPoolExecutor(max_workers=10) as pool:
                verdicts = {}
                for i, (k, v) in enumerate(pool.map(_one, head), 1):
                    verdicts[k] = v
                    if beat is not None:
                        beat(i, len(head))
    except Exception as exc:
        log.warning("Link verification skipped: %s", exc)
        return ranked, set()

    # Gated (login wall) and blocked (captcha/bot-wall) jobs may still be live —
    # try to recover the real apply link from the company's own ATS. Recovered
    # jobs keep their place with the new URL. Unrecovered GATED jobs are dropped
    # (the wall really does hide the posting); unrecovered BLOCKED jobs are KEPT
    # but flagged 'unverified' (we couldn't confirm live OR gone — don't discard a
    # possibly-live job, but warn on the card).
    if beat is not None and beat.should_stop():
        return ranked, set()
    suspects = sum(1 for v in verdicts.values() if v in ("gated", "blocked"))
    tried = recovered = 0
    unverified: set[str] = set()
    for job, _m in head:
        v = verdicts.get(job.dedup_key())
        if v not in ("gated", "blocked"):
            continue
        # ATS / scraped jobs are verified live by their source API (only lists open
        # roles); their pages are just Cloudflare-walled. Treat as active, not
        # unverified — don't badge the good ones (OpenAI/Ashby, Okta/Greenhouse…).
        src = getattr(job, "source", "") or ""
        if v == "blocked" and (src.startswith("ats:") or src.startswith("scrape:")):
            verdicts[job.dedup_key()] = "active"
            continue
        if beat is not None and beat.should_stop():
            return ranked, set()
        new_url = recover_apply_url(job.company, job.title)
        tried += 1
        if beat is not None:
            beat(tried, suspects)
        if new_url:
            job.url = new_url
            verdicts[job.dedup_key()] = "active"
            recovered += 1
        elif v == "blocked":
            verdicts[job.dedup_key()] = "unverified"
            unverified.add(job.dedup_key())

    dead = {k for k, v in verdicts.items() if v in ("gone", "gated")}
    live = {k for k, v in verdicts.items() if k not in dead}
    by_key = {j.dedup_key(): j for j, _ in head}
    try:
        for k in dead:                       # dead-end links: purge from the corpus
            db.query(Job).filter(Job.dedup_key == k).delete(synchronize_session=False)
        for k in live:                       # keep; stamp checked (+ save any recovered URL)
            vals = {Job.last_checked_at: utcnow(),
                    Job.link_status: ("unverified" if k in unverified else "")}
            if k in by_key and by_key[k].url:
                vals[Job.url] = by_key[k].url[:1000]
            db.query(Job).filter(Job.dedup_key == k).update(vals, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    if dead or recovered or unverified:
        log.info("Search: %d dropped, %d recovered from ATS, %d unverified (captcha)",
                 len(dead), recovered, len(unverified))
    kept = [(j, m) for (j, m) in ranked if j.dedup_key() not in dead]
    return kept, unverified


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


_GENERIC_REMOTE_LOCS = {"remote", "fully remote", "anywhere", "worldwide", "global"}


def _is_remote_job(job, match, loc: str) -> bool:
    """Genuinely remote — NOT a place-based foreign job that merely mentions
    'remote' in its description. Trust the scorer's structured `remote` field
    (it read the whole posting and classified it) first; else a location whose
    PRIMARY token is remote ("Remote", "Remote - EU"). Deliberately does NOT use
    the crude description keyword scan (`looks_remote`), which kept on-site foreign
    jobs — e.g. a Boston role whose text says 'remote-friendly'."""
    if str(getattr(match, "remote", "") or "").strip().lower() == "remote":
        return True
    l = (loc or "").lower().strip()
    return l.startswith("remote") or l in _GENERIC_REMOTE_LOCS


def _country_allowed(job_countries, remote_mode, target_codes, remote_any) -> bool:
    """Hard geo gate using the corpus country tag (which the nightly backfill now
    fills for the long tail). True = keep.

    Defers to the text prefilter when we can't decide: an untagged job, or a user
    with no country constraint. A job confidently placed in a country the user did
    NOT choose is dropped — including a remote role tied to a specific foreign
    country ("Remote in United States"), which is NOT remote-from-anywhere, so it
    stays out even for remote-anywhere users. Genuinely global remote roles carry
    no country tag and are kept by the untagged branch above (then the prefilter's
    generic-remote check decides).
    """
    if not job_countries or not target_codes:
        return True
    return bool(set(job_countries) & set(target_codes))


def _corpus_candidates(db, profile, candidate, settings, terms):
    """SQL-filter + cosine-rank the corpus into a top-K shortlist to score.

    Returns (jobs, scanned) or (None, scanned) to signal the caller should fall
    back to a live fetch — when embeddings are off, the profile can't be
    embedded, or the corpus is too thin for this user's geography.
    """
    from jbhntr_engine import embeddings, geo
    from ..models import Job

    if not embeddings.is_configured(settings):
        return None, 0, 0
    pvec = embeddings.embed_one(_candidate_query_text(profile, candidate), settings)
    if not pvec:
        return None, 0, 0

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
        return None, len(rows), 0

    capped = cap_per_company(pool, terms=terms)
    capped.sort(key=lambda p: -embeddings.cosine(pvec, vec_by_key.get(p.dedup_key(), [])))
    # Third value: how many jobs actually matched the user's geography (the full
    # located set), NOT the capped shortlist — so the progress UI can show the true
    # "in your countries" count rather than the top-K sent to scoring.
    return capped[:config.corpus_topk], len(rows), len(pool)


def _score_cached(db, matcher, jobs, profile, materials, feedback,
                  company_profile, criteria, settings, progress=None, should_stop=None):
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
        return matcher.score(jobs, profile, materials, feedback, company_profile, criteria,
                             progress=progress, should_stop=should_stop)

    hits, misses = [], []
    for j in jobs:
        m = cached.get(by_hash[j.dedup_key()])
        (hits.append((j, m)) if m is not None else misses.append(j))

    fresh = (matcher.score(misses, profile, materials, feedback, company_profile, criteria,
                           progress=progress, should_stop=should_stop)
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


def _enrich(jobs, db=None, beat=None) -> None:
    """Fill full JDs for the shortlist BEFORE scoring — the matcher can't judge fit
    from a snippet. First the structured ATS/LinkedIn path (empty bodies), then a
    generic fetch (JSON-LD JobPosting / main content) for anything still thin. What
    we fetch is persisted back to the corpus row, so it's fixed for everyone and
    not re-fetched.

    `beat` (a `_Heartbeat`, R3-30) is called on this thread per finished job; if
    it says stop, the queued fetches are cancelled and nothing is persisted."""
    from concurrent.futures import ThreadPoolExecutor

    from jbhntr_engine import enrich_description

    from . import enrich_service

    targets = [j for j in jobs if j.url and len(j.description or "") < 300][:120]
    if not targets:
        return

    def _one(j):
        try:
            enrich_description(j)                    # ATS/LinkedIn structured fill
        except Exception:
            pass
        if len(j.description or "") < 300:
            body = enrich_service.fetch_description(j.url)
            if body and len(body) > len(j.description or ""):
                j.description = body
        return j

    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, _j in enumerate(pool.map(_one, targets), 1):
            if beat is None:
                continue
            beat(i, len(targets))
            if i < len(targets) and beat.should_stop():
                pool.shutdown(wait=False, cancel_futures=True)
                return

    # Persist the fuller descriptions to the corpus (best-effort, one commit).
    # Force-evaluate ALL (list, not a short-circuiting any()) so every row is saved.
    if db is not None:
        try:
            changed = [enrich_service.persist_description(db, j) for j in targets]
            if any(changed):
                db.commit()
        except Exception:
            db.rollback()
            log.exception("persist enriched descriptions failed")


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
            "why": fb.note or "",            # matcher reads "why" (was silently dropped)
            "user_score": fb.user_score,     # the candidate's own 0-100, when given
            "our_score": jr.score,           # what we scored it — the disagreement
        }
        for fb, jr in rows
    ]
    examples.sort(key=lambda e: -e["weight"])   # strongest signals first
    return examples
