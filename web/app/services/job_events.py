"""Timeline entries on a tracked job — interviews, calls, notes, offers, tasks."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session as DbSession

from ..models import JobEvent

EVENT_KINDS = ["note", "interview", "call", "offer", "task"]


def list_for(db: DbSession, user_id: int, dedup_key: str) -> list[JobEvent]:
    return (db.query(JobEvent)
            .filter(JobEvent.user_id == user_id, JobEvent.dedup_key == dedup_key)
            .order_by(JobEvent.occurred_on.desc(), JobEvent.id.desc())
            .all())


def add(db: DbSession, user_id: int, dedup_key: str, kind: str,
        body: str, occurred_on: date | None = None) -> JobEvent:
    ev = JobEvent(
        user_id=user_id, dedup_key=dedup_key,
        kind=kind if kind in EVENT_KINDS else "note",
        body=(body or "")[:500],
        occurred_on=occurred_on or date.today(),
    )
    db.add(ev)
    db.commit()
    return ev


def delete(db: DbSession, user_id: int, event_id: int) -> bool:
    ev = db.get(JobEvent, event_id)
    if not ev or ev.user_id != user_id:
        return False
    db.delete(ev)
    db.commit()
    return True
