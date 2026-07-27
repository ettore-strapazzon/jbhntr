"""Per-type free document allowance.

A free user gets a small number of tailored CVs and cover letters, counted per
*distinct job* — so regenerating the same one costs nothing, but tailoring a new
role does. Premium is unlimited (returns None).
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from ..config import config
from ..models import Document, User


def used(db: DbSession, user_id: int, kind: str) -> int:
    return (db.query(Document.job_result_id)
              .filter(Document.user_id == user_id, Document.kind == kind)
              .distinct().count())


def left(db: DbSession, user: User, kind: str) -> int | None:
    """Remaining docs of this kind, or None for unlimited (premium)."""
    if user.is_premium:
        return None
    limit = config.free_cvs if kind == "cv" else config.free_cover_letters
    return max(0, limit - used(db, user.id, kind))


def allowance(db: DbSession, user: User) -> dict:
    return {"cv": left(db, user, "cv"), "cl": left(db, user, "cl")}
