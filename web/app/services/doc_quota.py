"""Per-type tailored-document allowance (PLAN-02).

Counted per *distinct job*, so regenerating the same document for the same job
never costs another allowance. Free is a lifetime allowance; Premium resets each
calendar month at 00:00 UTC on the 1st. Neither plan is unlimited.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from ..config import config
from ..models import Document, JobResult, User, aware, utcnow


def kinds_by_key(db: DbSession, user_id: int, dedup_keys=None) -> dict[str, set[str]]:
    """Map each job's ``dedup_key`` -> the set of document kinds ('cv'/'cl') drafted
    for it, resolved across *every* JobResult that shares the key.

    Documents attach to a specific ``JobResult.id``, but the same job re-ingested on
    a later run gets a fresh row (same dedup_key). Looking a draft up by the newest
    row's id alone would orphan it — the card would offer "Draft" again as if none
    existed. Joining on dedup_key keeps a draft attached to its job for good.
    """
    q = (db.query(JobResult.dedup_key, Document.kind)
           .join(Document, Document.job_result_id == JobResult.id)
           .filter(Document.user_id == user_id))
    if dedup_keys is not None:
        q = q.filter(JobResult.dedup_key.in_(list(dedup_keys)))
    out: dict[str, set[str]] = {}
    for dk, kind in q:
        out.setdefault(dk, set()).add(kind)
    return out


def month_start(now: datetime | None = None) -> datetime:
    """00:00 UTC on the first of the current month."""
    now = aware(now or utcnow())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def used(db: DbSession, user_id: int, kind: str, *, since: datetime | None = None) -> int:
    """Distinct jobs this user has generated `kind` for (optionally since a date)."""
    q = (db.query(Document.job_result_id)
           .filter(Document.user_id == user_id, Document.kind == kind))
    if since is not None:
        q = q.filter(Document.created_at >= since)
    return q.distinct().count()


def limit_for(user: User, kind: str) -> int:
    if user.is_premium:
        return (config.premium_cvs_monthly if kind == "cv"
                else config.premium_cover_letters_monthly)
    return config.free_cvs if kind == "cv" else config.free_cover_letters


def left(db: DbSession, user: User, kind: str) -> int:
    """Remaining docs of this kind. Premium counts within the current month;
    free counts lifetime. Never None — no plan is unlimited."""
    since = month_start() if user.is_premium else None
    return max(0, limit_for(user, kind) - used(db, user.id, kind, since=since))


def allowance(db: DbSession, user: User) -> dict:
    return {"cv": left(db, user, "cv"), "cl": left(db, user, "cl")}
