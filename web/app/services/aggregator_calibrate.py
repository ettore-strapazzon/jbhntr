"""Find the age at which an aggregator's links go dead, then purge the dead tail.

Some aggregators hand out redirect trackers that die once the underlying job
expires, and a plain HTTP check can't tell a live recent job from a dead old one.
Age predicts liveness: an open job keeps being re-listed (fresh `last_seen_at`),
a dead one stops. So bucket jobs by days-since-last-seen, sample a few per bucket
through the engine's tracker check, find the age where the dead rate crosses a
threshold (two buckets in a row), and delete jobs older than that.

The DB side (buckets, cutoff, purge) is the shell's; which sources, the browser
check and the dead-landing rule are engine-side (R3-16, ``jbhntr_engine``).
"""

from __future__ import annotations

import logging
import random
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

from jbhntr_engine import (
    AGGREGATOR_SOURCES, aggregator_check_configured, aggregator_link_dead,
    aggregator_link_statuses,
)

from ..models import Job, aware, utcnow

log = logging.getLogger("jbhntr.calibrate")

# Which sources hand out trackers, the browser check that reads a tracker's real
# fate and the "bounced back to the aggregator" rule are engine-side (R3-16).
AGG_SOURCES = AGGREGATOR_SOURCES
_DEAD_MIN = 2            # a bucket is "dead" at >= this many dead hits in its sample (>=2/5)


def _is_dead(status, final_url: str) -> bool:
    return aggregator_link_dead(status, final_url)


def _auth() -> bool:
    return aggregator_check_configured()


def _check(urls: list[str]) -> dict[str, tuple]:
    """{url: (status, final_url)} via the engine's browser check; {} without creds."""
    return aggregator_link_statuses(urls)


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
    """Delete aggregator jobs whose last_seen_at is older than cutoff_days and purge
    their board rows. NOT tombstoned: an age-out isn't a confirmed-dead job — if the
    feed lists it again with a fresh (working) token we want it back."""
    from .reaper import _purge_deprecated_results
    now = utcnow()
    before = now - timedelta(days=cutoff_days)
    q = db.query(Job).filter(Job.source.in_(sources), Job.last_seen_at < before)
    keys = [k for (k,) in q.with_entities(Job.dedup_key) if k]
    deleted = q.delete(synchronize_session=False)
    db.commit()
    board = _purge_deprecated_results(db, keys)
    res = {"deleted": deleted, "board_purged": board, "cutoff_days": cutoff_days}
    log.info("aggregator purge: %s", res)
    return res
