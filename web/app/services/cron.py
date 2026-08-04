"""One scheduled entrypoint, so production needs a single Railway cron service.

Run it nightly (e.g. `0 3 * * *`). Every night it prunes dead jobs and runs the
daily ingest. Once a week (Monday, UTC) it also refreshes company discovery and
runs the weekly metered sources (Jooble/JSearch/Findwork). This keeps ops to one
cron service with one set of environment variables instead of four.

    python -m web.app.services.cron

See docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import datetime
import logging

from .ingest import run as ingest_run
from .reaper import run as reaper_run

log = logging.getLogger("jbhntr.cron")

WEEKLY_DAY = 0   # Monday, in UTC
PAGEVIEW_RETENTION_DAYS = 730   # 24 months — matches the Privacy Policy


def _prune_pageviews(db, days: int = PAGEVIEW_RETENTION_DAYS) -> int:
    """Delete raw page-view rows past the retention window (privacy promise)."""
    from ..models import PageView, utcnow
    cutoff = utcnow() - datetime.timedelta(days=days)
    n = db.query(PageView).filter(PageView.created_at < cutoff).delete(
        synchronize_session=False)
    db.commit()
    return n


def _stage(out: dict, name: str, fn):
    """Run one maintenance stage; never let its failure abort the others.

    A Python exception here is logged and recorded, so the cron process still
    exits 0. (An OS-level OOM kill cannot be caught by this — see the embedding
    note in docs/DEPLOYMENT.md.)
    """
    try:
        out[name] = fn()
    except Exception as exc:
        log.exception("nightly stage %s failed", name)
        out[name] = {"error": f"{type(exc).__name__}: {exc}"}


def nightly(today: datetime.date | None = None) -> dict:
    """Run the scheduled maintenance. Weekly work only on WEEKLY_DAY.

    Order matters: reap first, then (weekly) grow the company registry and pull
    the metered sources, then the daily ingest, which polls the registry
    (including anything just discovered) and embeds new jobs. Each stage is
    isolated so one failure cannot crash the whole nightly run.
    """
    day = today or datetime.datetime.utcnow().date()
    is_weekly = day.weekday() == WEEKLY_DAY
    out: dict = {"weekly": is_weekly}

    _stage(out, "reaper", reaper_run)
    if is_weekly:
        _stage(out, "discover", lambda: ingest_run("discover"))
        _stage(out, "ingest_weekly", lambda: ingest_run("weekly"))
    _stage(out, "ingest_daily", lambda: ingest_run("daily"))

    # Premium daily/weekly digest (R13.4). No-op unless SMTP is configured.
    from ..db import SessionLocal
    from .digest import run_digests
    db = SessionLocal()
    try:
        _stage(out, "digests", lambda: run_digests(db, is_weekly_day=is_weekly))
        _stage(out, "pageview_pruned", lambda: _prune_pageviews(db))
        _stage(out, "corpus_stat", lambda: _record_corpus_stat(db, out))
    finally:
        db.close()

    log.info("nightly done (weekly=%s): %s", is_weekly, out)
    return out


def _record_corpus_stat(db, out: dict) -> int:
    """Persist the night's corpus size + churn so daily trends are visible in
    /admin. Reads counts from the stage results already gathered in `out`."""
    from ..models import CorpusStat, Job

    def g(stage: str, key: str) -> int:
        v = out.get(stage)
        return int(v.get(key, 0)) if isinstance(v, dict) else 0

    row = CorpusStat(
        total=db.query(Job).count(),
        added=g("ingest_daily", "added") + g("ingest_weekly", "added"),
        updated=g("ingest_daily", "updated") + g("ingest_weekly", "updated"),
        ttl_deleted=g("reaper", "ttl_deleted"),
        gone_deleted=g("reaper", "gone_deleted"),
        checked=g("reaper", "checked"),
        embedded=g("ingest_daily", "embedded") + g("ingest_weekly", "embedded"),
    )
    db.add(row)
    db.commit()
    return row.total


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(nightly())


if __name__ == "__main__":
    main()
