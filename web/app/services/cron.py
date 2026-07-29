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


def nightly(today: datetime.date | None = None) -> dict:
    """Run the scheduled maintenance. Weekly work only on WEEKLY_DAY.

    Order matters: reap first, then (weekly) grow the company registry and pull
    the metered sources, then the daily ingest, which polls the registry
    (including anything just discovered) and embeds new jobs.
    """
    day = today or datetime.datetime.utcnow().date()
    is_weekly = day.weekday() == WEEKLY_DAY
    out: dict = {"weekly": is_weekly}

    out["reaper"] = reaper_run()
    if is_weekly:
        out["discover"] = ingest_run("discover")
        out["ingest_weekly"] = ingest_run("weekly")
    out["ingest_daily"] = ingest_run("daily")

    # Premium daily/weekly digest (R13.4). No-op unless SMTP is configured.
    from ..db import SessionLocal
    from .digest import run_digests
    db = SessionLocal()
    try:
        out["digests"] = run_digests(db, is_weekly_day=is_weekly)
        out["pageview_pruned"] = _prune_pageviews(db)
    finally:
        db.close()

    log.info("nightly done (weekly=%s): %s", is_weekly, out)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(nightly())


if __name__ == "__main__":
    main()
