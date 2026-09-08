"""Find the age at which an aggregator's links go dead, then purge the dead tail.

careerjet/jooble hand out redirect trackers (jobviewtrack.com etc.) that 404 once
the underlying job expires. The tracker refuses our datacenter IP (the reaper reads
it as 'unknown'), so a plain HTTP check can't tell a live recent job from a dead old
one. But age predicts liveness: careerjet re-lists a job daily while it's open — so
`last_seen_at` stays fresh — and drops it when it dies, freezing `last_seen_at`.

So: bucket jobs by days-since-last-seen, sample a few per bucket through the Bright
Data Scraping Browser (a residential IP that gets past the bot-wall), find the age
where the 404 rate crosses a threshold, and delete jobs whose last_seen is older than
that. No fixed-guess TTL; recent live jobs are kept; there's no whack-a-mole because
a stale-last_seen job is one careerjet already stopped serving.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

from ..models import DeadLink, Job, aware, utcnow

log = logging.getLogger("jbhntr.calibrate")

_CDP_HOST = "brd.superproxy.io:9222"
AGG_SOURCES = ("api:careerjet", "api:jooble")
_DEAD_STATUSES = (404, 410)
_DEAD_MIN = 2            # a bucket is "dead" at >= this many dead hits in its sample (>=2/5)

# A dead careerjet/jooble tracker doesn't 404 through a real browser — it bounces the
# viewer to a "similar jobs" search on one of the aggregator's OWN domains. So landing
# back on any of these (rather than a real employer/ATS site) means the job is gone.
_AGG_HOSTS = ("jobviewtrack.com", "careerjet.", "optioncarriere.", "opcionempleo.",
              "jobrapido.", "jooble.", "whatjobs.", "trovit.", "jobisjob.")


def _is_dead(status, final_url: str) -> bool:
    if status in _DEAD_STATUSES:
        return True
    if status is None:
        return False                    # couldn't load — unknown, not counted dead
    host = urlparse(final_url or "").netloc.lower()
    return any(h in host for h in _AGG_HOSTS)


def _auth() -> str:
    from jobhunter.config import Settings
    return getattr(Settings.from_env(), "brightdata_browser_auth", "") or ""


async def _statuses(urls: list[str], auth: str, concurrency: int = 5) -> dict[str, tuple]:
    """{url: (final_status, final_url)} via one Scraping Browser session, a few pages at
    a time. We keep the final URL because a dead tracker bounces to a 200 aggregator
    page rather than 404ing. Images/media/CSS blocked to keep Browser bandwidth low."""
    from playwright.async_api import async_playwright

    out: dict[str, tuple] = {}
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"wss://{auth}@{_CDP_HOST}")

        async def _block(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                await route.abort()
            else:
                await route.continue_()

        async def _one(u: str):
            async with sem:
                page = await browser.new_page()
                page.set_default_navigation_timeout(45000)
                try:
                    try:
                        await page.route("**/*", _block)
                    except Exception:
                        pass
                    resp = await page.goto(u, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1200)          # let JS/meta redirects settle
                    out[u] = ((resp.status if resp else None), page.url)
                except Exception:
                    out[u] = (None, "")
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

        try:
            await asyncio.gather(*[_one(u) for u in urls])
        finally:
            await browser.close()
    return out


def _check(urls: list[str]) -> dict[str, tuple]:
    """Sync wrapper -> {url: (status, final_url)}. Returns {} if no creds or it fails."""
    auth = _auth()
    if not auth or not urls:
        return {}
    try:
        return asyncio.run(_statuses(urls, auth))
    except Exception as exc:
        log.warning("calibrate: browser check failed: %s", str(exc)[:200])
        return {}


def calibrate(db, sources: tuple[str, ...] = AGG_SOURCES,
              sample: int = 5, max_age: int = 60) -> dict:
    """Sample `sample` links per days-since-last-seen bucket, check them, and return
    the per-bucket dead counts plus the proposed cutoff (youngest age whose bucket AND
    the next-older one are both dead — a two-bucket guard against a fluke). Deletes
    nothing. Returns {error:...} when the browser isn't configured."""
    if not _auth():
        return {"error": "no brightdata_browser_auth configured"}
    now = utcnow()
    rows = (db.query(Job.url, Job.last_seen_at)
            .filter(Job.source.in_(sources), Job.url != "").all())
    buckets: dict[int, list[str]] = {}
    for url, ls in rows:
        age = (now - (aware(ls) or now)).days
        if 0 <= age <= max_age:
            buckets.setdefault(age, []).append(url)
    if not buckets:
        return {"error": "no aggregator jobs in range", "total": len(rows)}

    per_bucket: dict[int, dict] = {}
    to_check: list[str] = []
    for age, urls in buckets.items():
        picks = random.sample(urls, min(sample, len(urls)))
        per_bucket[age] = {"n": len(urls), "sampled": len(picks), "dead": 0, "_urls": picks}
        to_check += picks

    statuses = _check(to_check)      # {url: (status, final_url)}
    if not statuses:
        return {"error": "browser check returned nothing (creds/blocked?)",
                "sampled": len(to_check)}

    status_dist: Counter = Counter()
    final_hosts: Counter = Counter()
    for st, final in statuses.values():
        status_dist[str(st)] += 1
        final_hosts[urlparse(final or "").netloc.lower() or "(none)"] += 1
    for age, d in per_bucket.items():
        d["dead"] = sum(1 for u in d["_urls"] if _is_dead(*statuses.get(u, (None, ""))))
        del d["_urls"]

    ages = sorted(per_bucket)
    cutoff = None
    for i, a in enumerate(ages):
        if per_bucket[a]["dead"] >= _DEAD_MIN:
            nxt = ages[i + 1] if i + 1 < len(ages) else None
            if nxt is None or per_bucket[nxt]["dead"] >= _DEAD_MIN:
                cutoff = a
                break
    would_purge = sum(v["n"] for a, v in per_bucket.items()
                      if cutoff is not None and a >= cutoff)
    curve = {a: f"{per_bucket[a]['dead']}/{per_bucket[a]['sampled']} (n={per_bucket[a]['n']})"
             for a in ages}
    # Key diagnostics FIRST so they survive any log truncation; the long curve last.
    res = {"cutoff_days": cutoff, "would_purge": would_purge, "checked": len(statuses),
           "status_dist": dict(status_dist), "final_hosts": dict(final_hosts.most_common(12)),
           "sources": list(sources), "curve": curve}
    log.info("calibrate: %s", res)
    return res


def purge(db, cutoff_days: int, sources: tuple[str, ...] = AGG_SOURCES) -> dict:
    """Delete aggregator jobs whose last_seen_at is older than cutoff_days, tombstone
    them (so a straggler re-list can't resurrect one), and purge their board rows."""
    from .reaper import _purge_deprecated_results
    now = utcnow()
    before = now - timedelta(days=cutoff_days)
    q = db.query(Job).filter(Job.source.in_(sources), Job.last_seen_at < before)
    keys = [k for (k,) in q.with_entities(Job.dedup_key) if k]
    for k in keys:
        db.merge(DeadLink(dedup_key=k, url="", reason="aggregator_aged_out", created_at=now))
    deleted = q.delete(synchronize_session=False)
    db.commit()
    board = _purge_deprecated_results(db, keys)
    res = {"deleted": deleted, "board_purged": board, "cutoff_days": cutoff_days}
    log.info("aggregator purge: %s", res)
    return res
