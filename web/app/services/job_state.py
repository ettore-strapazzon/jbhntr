"""Per-user job state (save / dismiss / applied), keyed by posting identity.

This is the state that turns a one-shot search into a workspace: it outlives
any single run, so the Matches surface can draw a card as saved, hide a
dismissed one, or move an applied one to Applications, no matter which run
re-surfaced the posting.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from ..models import JobState

# Status a user can set on something they applied to (§11.10). "Applied" is set
# automatically the moment they mark it; the rest they pick as things progress.
APPLICATION_STATUSES = ["Applied", "Replied", "Interviewing", "Rejected", "Offer", "Withdrawn"]

# Optional one-tap reason when dismissing (§11.7).
DISMISS_REASONS = ["Wrong level", "Wrong location", "Not the right company", "Not interested"]


def state_map(db: DbSession, user_id: int) -> dict[str, JobState]:
    """Every stored state for a user, keyed by dedup_key for O(1) lookup."""
    return {s.dedup_key: s
            for s in db.query(JobState).filter(JobState.user_id == user_id)}


def get_or_create(db: DbSession, user_id: int, dedup_key: str) -> JobState:
    st = (db.query(JobState)
            .filter(JobState.user_id == user_id, JobState.dedup_key == dedup_key)
            .first())
    if st is None:
        st = JobState(user_id=user_id, dedup_key=dedup_key)
        db.add(st)
        db.flush()
    return st


def set_saved(db: DbSession, user_id: int, dedup_key: str, saved: bool) -> JobState:
    st = get_or_create(db, user_id, dedup_key)
    st.saved = saved
    if saved:
        st.dismissed = False        # saving un-dismisses; the two contradict
    db.commit()
    return st


def set_dismissed(db: DbSession, user_id: int, dedup_key: str,
                  dismissed: bool, reason: str = "") -> JobState:
    st = get_or_create(db, user_id, dedup_key)
    st.dismissed = dismissed
    st.dismiss_reason = reason if dismissed and reason in DISMISS_REASONS else ""
    if dismissed:
        st.saved = False
    db.commit()
    return st


def set_applied(db: DbSession, user_id: int, dedup_key: str, applied: bool) -> JobState:
    from ..models import utcnow
    st = get_or_create(db, user_id, dedup_key)
    if applied:
        if st.applied_at is None:
            st.applied_at = utcnow()
        if not st.application_status:
            st.application_status = "Applied"
        st.dismissed = False
    else:
        st.applied_at = None
        st.application_status = ""
    db.commit()
    return st


def set_application_status(db: DbSession, user_id: int, dedup_key: str,
                           status: str) -> JobState | None:
    if status not in APPLICATION_STATUSES:
        return None
    st = get_or_create(db, user_id, dedup_key)
    from ..models import utcnow
    if st.applied_at is None:
        st.applied_at = utcnow()
    st.application_status = status
    db.commit()
    return st
