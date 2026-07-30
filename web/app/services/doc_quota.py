"""Per-type tailored-document allowance (PLAN-02).

Counted per *distinct job*, so regenerating the same document for the same job
never costs another allowance. Free is a lifetime allowance; Premium resets each
calendar month at 00:00 UTC on the 1st. Neither plan is unlimited.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from ..config import config
from ..models import Document, User, aware, utcnow


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
