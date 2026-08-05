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

_UA = "Mozilla/5.0 (compatible; JBHNTR-linkcheck/1.0)"

# A 200 page containing any of these is a genuinely closed/removed posting.
DEAD_MARKERS = (
    "no longer available", "no longer accepting", "no longer open",
    "position has been filled", "has been filled", "this position is closed",
    "posting is closed", "vacancy is closed", "applications are closed",
    "job is no longer", "position is no longer", "job has expired",
    "this job has expired", "job not found", "page not found",
    "the job you are looking for", "not currently accepting",
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
    if r.status_code in (404, 410):
        return "gone"
    if r.status_code != 200:
        return "unknown"
    body = r.text.lower()
    if any(m in body for m in DEAD_MARKERS):
        return "gone"
    if any(m in body for m in WALL_MARKERS):
        return "gated"
    return "active"


def sweep(
    db: DbSession,
    stale_days: int = 45,
    check_limit: int = 5000,  # link-checks per nightly run (chips through the corpus)
    recheck_days: int = 7,
    workers: int = 16,        # concurrency, to keep 5k checks to a sane wall-clock
) -> dict:
    """One reaper pass. Returns counts. Never raises (logs and returns)."""
    try:
        from .corpus_service import GATED_HOSTS

        now = utcnow()

        # 0. Purge any job whose apply URL is a gated/dead-end host — it should
        #    never have been stored, and this cleans out ones ingested earlier.
        gated_deleted = 0
        for host in GATED_HOSTS:
            gated_deleted += (db.query(Job).filter(Job.url.like(f"%{host}%"))
                              .delete(synchronize_session=False))
        db.commit()

        # 1. TTL: gone from every fresh search for too long -> delete, no I/O.
        stale_before = now - timedelta(days=stale_days)
        ttl_deleted = (
            db.query(Job).filter(Job.last_seen_at < stale_before)
            .delete(synchronize_session=False)
        )
        db.commit()

        # 2. Link-check a bounded batch: never-checked or checked long ago,
        #    oldest first, so a daily run chips through the whole corpus.
        recheck_before = now - timedelta(days=recheck_days)
        batch = (
            db.query(Job)
            .filter(or_(Job.last_checked_at.is_(None),
                        Job.last_checked_at < recheck_before))
            .order_by(Job.last_checked_at.is_(None).desc(),
                      Job.last_checked_at.asc())
            .limit(check_limit)
            .all()
        )

        checked = gone = 0
        if batch:
            with httpx.Client(timeout=15.0, headers={"User-Agent": _UA}) as client:
                def _one(job: Job) -> tuple[int, str]:
                    return job.id, check_url(job.url, client)

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    verdicts = dict(pool.map(_one, batch))

            for job in batch:
                verdict = verdicts.get(job.id, "unknown")
                checked += 1
                if verdict == "gone":
                    db.delete(job)
                    gone += 1
                else:
                    job.last_checked_at = now
            db.commit()

        result = {"ttl_deleted": ttl_deleted + gated_deleted, "checked": checked,
                  "gone_deleted": gone, "gated_deleted": gated_deleted,
                  "remaining": db.query(Job).count()}
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
