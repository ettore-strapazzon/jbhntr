"""Corpus freshness: drop jobs that have gone stale or dead.

Two mechanisms, cheap first:

1. TTL — a posting that hasn't reappeared in any user's fresh search for
   `stale_days` is almost certainly closed; delete it without a network call.
2. Link check — for the rest (oldest-checked first, bounded per run), fetch the
   apply URL and delete the ones that are provably gone (404/410 or a "no longer
   available" page).

Deleting an active job by mistake is self-healing: the next search that fetches
it writes it straight back via the write-through cache. So the check can lean
toward removing the doubtful-dead, but we still keep anything merely
unreachable (timeouts, 403s) rather than guess.

Run from a daily cron (Railway) or manually:
    python -c "from web.app.services.reaper import run; print(run())"

See docs/ARCHITECTURE.md → "Scaling: the shared job corpus" → freshness.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from ..models import Job, utcnow

log = logging.getLogger("jbhntr.reaper")

# Present a normal browser identity. Announcing a bot ("...linkcheck/1.0") makes
# many aggregators/employer sites serve a captcha/bot-wall instead of the posting,
# which we then can't read (verdict 'blocked'). A realistic UA + browser Accept
# headers lets most of those return the real page, so we get a true active/gone
# verdict. This is link-health checking (one GET per posting), not scraping.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BROWSER_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# A 200 page containing any of these is a genuinely closed/removed posting.
DEAD_MARKERS = (
    "no longer available", "no longer accepting", "no longer open",
    "position has been filled", "has been filled", "this position is closed",
    "posting is closed", "vacancy is closed", "applications are closed",
    "job is no longer", "position is no longer", "job has expired",
    "this job has expired", "job not found", "page not found",
    "the job you are looking for", "not currently accepting",
)

# A closed posting often SERVER-SIDE redirects to a URL that flags it, even when
# the landing page is a bot-check/captcha or a generic search page our fetch can't
# read (jooble sends closed jobs to its search page with ?closedJob=True). Match
# the FINAL redirected URL so these are caught regardless of body content.
GONE_URL_MARKERS = (
    "closedjob=true",                       # jooble
    "no-longer-available", "nolongeravailable",
    "job-expired", "jobexpired", "expired-job",
    "position-filled", "positionfilled",
    "joblisting/expired", "jobs/expired",
)

# A bot-check / captcha page returns 200 but is NOT the posting — we cannot read
# whether the job is live. Distinct from 'gone': the job may well still exist, so
# this is 'blocked' (try to recover the real link elsewhere, else flag it).
CAPTCHA_MARKERS = (
    "recaptcha", "hcaptcha", "px-captcha", "captcha-delivery",
    "verify you are human", "are you a human", "please verify you are",
    "cf-browser-verification", "checking your browser before", "just a moment...",
    "unusual traffic from your", "enable javascript and cookies to continue",
    "ddos protection by", "verify you are not a robot",
)

# A login/registration wall hides the real posting. Unlike a 404, the job is
# usually still live — so this is 'gated' (recoverable), not 'gone'.
WALL_MARKERS = (
    "create an account to view", "sign in to view the full",
    "log in to view this job", "register to see the full",
    "sign up to view full", "account to view full job",
    "create an account to see", "sign up to see the full",
)


def check_url(url: str, client: httpx.Client) -> str:
    """Classify a posting URL as 'active', 'gone', 'gated', or 'unknown'.

    Conservative: only 404/410 or an explicit closed-posting page count as gone;
    a registration/login wall is 'gated' (the job likely still exists, so the
    caller can try to recover the real link). Anything ambiguous (timeout, 403,
    redirect) is 'unknown' — kept.
    """
    if not url:
        return "unknown"
    try:
        r = client.get(url, follow_redirects=True)
    except Exception:
        return "unknown"
    # The URL we actually landed on (after redirects) can flag a closed job even
    # when the page body is a captcha/search page we can't parse.
    final_url = str(getattr(r, "url", "") or "").lower()
    if any(m in final_url for m in GONE_URL_MARKERS):
        return "gone"
    if r.status_code in (404, 410):
        return "gone"
    if r.status_code != 200:
        return "unknown"
    body = r.text.lower()
    if any(m in body for m in DEAD_MARKERS):
        return "gone"
    if any(m in body for m in WALL_MARKERS):
        return "gated"
    if any(m in body for m in CAPTCHA_MARKERS):
        return "blocked"        # a bot-wall — we couldn't actually read the posting
    return "active"


def _purge_deprecated_results(db: DbSession, keys: list[str]) -> int:
    """Delete board results (JobResult) for deprecated postings, so a closed job
    stops showing in Matches. Keeps any the user SAVED or APPLIED to — those are
    tracked items the user chose, not just a live listing. Returns rows removed.
    """
    from sqlalchemy import and_, exists

    from ..models import JobResult, JobState

    keys = [k for k in dict.fromkeys(keys) if k]     # dedupe, drop blanks
    if not keys:
        return 0
    # Per-user guard: keep this user's result if they saved/applied to this posting.
    kept = exists().where(and_(
        JobState.user_id == JobResult.user_id,
        JobState.dedup_key == JobResult.dedup_key,
        or_(JobState.saved.is_(True), JobState.applied_at.isnot(None)),
    ))
    removed = 0
    for i in range(0, len(keys), 400):             # SQLite caps IN() at 999 vars
        removed += (db.query(JobResult)
                    .filter(JobResult.dedup_key.in_(keys[i:i + 400]), ~kept)
                    .delete(synchronize_session=False))
    db.commit()
    return removed


def sweep(
    db: DbSession,
    stale_days: int = 45,
    check_limit: int = 5000,  # link-checks per run (chips through the corpus); 0 = all
    recheck_days: int = 7,
    workers: int = 16,        # concurrency, to keep 5k checks to a sane wall-clock
    unverified_stale_days: int = 21,  # tighter TTL for links we can't verify by URL
) -> dict:
    """One reaper pass. Returns counts. Never raises (logs and returns)."""
    try:
        from .corpus_service import GATED_HOSTS

        now = utcnow()
        reaped_keys: list[str] = []   # dedup_keys removed this pass -> purge boards

        # 0. Purge any job whose apply URL is a gated/dead-end host — it should
        #    never have been stored, and this cleans out ones ingested earlier.
        gated_deleted = 0
        for host in GATED_HOSTS:
            gq = db.query(Job).filter(Job.url.like(f"%{host}%"))
            reaped_keys += [k for (k,) in gq.with_entities(Job.dedup_key) if k]
            gated_deleted += gq.delete(synchronize_session=False)
        db.commit()

        # 1. TTL: gone from every fresh search for too long -> delete, no I/O.
        stale_before = now - timedelta(days=stale_days)
        ttl_q = db.query(Job).filter(Job.last_seen_at < stale_before)
        reaped_keys += [k for (k,) in ttl_q.with_entities(Job.dedup_key) if k]
        ttl_deleted = ttl_q.delete(synchronize_session=False)
        db.commit()

        # 1b. Unverifiable (captcha/bot-walled) jobs we can't confirm by URL: trust
        #     the SOURCE instead. If the aggregator stopped surfacing it for a while
        #     it's very likely closed, so prune on a tighter window than the full
        #     TTL — no network, and it stops these lingering as stale results.
        unv_before = now - timedelta(days=unverified_stale_days)
        unv_q = db.query(Job).filter(Job.link_status == "unverified",
                                     Job.last_seen_at < unv_before)
        reaped_keys += [k for (k,) in unv_q.with_entities(Job.dedup_key) if k]
        unverified_pruned = unv_q.delete(synchronize_session=False)
        db.commit()

        # 2. Link-check a bounded batch: never-checked or checked long ago,
        #    oldest first, so a daily run chips through the whole corpus.
        recheck_before = now - timedelta(days=recheck_days)
        q = (
            db.query(Job)
            .filter(or_(Job.last_checked_at.is_(None),
                        Job.last_checked_at < recheck_before))
            .order_by(Job.last_checked_at.is_(None).desc(),
                      Job.last_checked_at.asc())
        )
        if check_limit and check_limit > 0:
            q = q.limit(check_limit)     # 0 = check every due job (one-time deep clean)
        batch = q.all()

        checked = gone = blocked = 0
        if batch:
            with httpx.Client(timeout=15.0, headers=BROWSER_HEADERS) as client:
                def _one(job: Job) -> tuple[int, str]:
                    return job.id, check_url(job.url, client)

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    verdicts = dict(pool.map(_one, batch))

            for job in batch:
                verdict = verdicts.get(job.id, "unknown")
                checked += 1
                if verdict == "gone":
                    if job.dedup_key:
                        reaped_keys.append(job.dedup_key)
                    db.delete(job)
                    gone += 1
                    continue
                job.last_checked_at = now
                if verdict == "blocked":
                    # Couldn't read past a captcha/bot-wall — flag it so the count is
                    # visible and the card can warn. Not deleted: it may still be live.
                    job.link_status = "unverified"
                    blocked += 1
                elif verdict == "active" and job.link_status:
                    job.link_status = ""      # recovered a clean read -> clear the flag
            db.commit()

        # 3. A deprecated posting must also leave users' boards, or they click into
        #    a closed job. Delete the matching results — but keep any the user saved
        #    or applied to (those are tracked items, not just a live listing).
        board_purged = _purge_deprecated_results(db, reaped_keys)

        unverified_total = db.query(Job).filter(Job.link_status == "unverified").count()
        result = {"ttl_deleted": ttl_deleted + gated_deleted, "checked": checked,
                  "gone_deleted": gone, "gated_deleted": gated_deleted,
                  "blocked": blocked, "unverified_pruned": unverified_pruned,
                  "unverified_total": unverified_total,
                  "board_purged": board_purged, "remaining": db.query(Job).count()}
        log.info("Reaper: %s", result)
        return result
    except Exception as exc:
        log.warning("Reaper sweep failed: %s", exc)
        db.rollback()
        return {"error": str(exc)}


def run(**kw) -> dict:
    """Entry point for a cron/manual run — owns its own DB session."""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        return sweep(db, **kw)
    finally:
        db.close()
