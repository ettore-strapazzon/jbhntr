"""Per-user job state (save / dismiss / applied), keyed by posting identity.

This is the state that turns a one-shot search into a workspace: it outlives
any single run, so the Matches surface can draw a card as saved, hide a
dismissed one, or move an applied one to Applications, no matter which run
re-surfaced the posting.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session as DbSession

from ..models import JobState

# Statuses a user can set on an applied job (stored on JobState.application_status).
# "Saved" is derived (saved & not applied) and never stored; "Applied" is set on apply.
APPLICATION_STATUSES = ["Applied", "Interviewing", "Offer", "Accepted", "Rejected", "Withdrawn"]

# Forward pipeline the stage control exposes, in order.
PIPELINE_STAGES = ["Applied", "Interviewing", "Offer", "Accepted"]

# Terminal outcomes -> a job in one of these renders in the "Closed" group.
CLOSED_STATUSES = {"Accepted", "Rejected", "Withdrawn"}

# Reachable from the "close it" action at any active stage.
CLOSE_OUTCOMES = ["Rejected", "Withdrawn"]

# Board groups, in display order.
STAGE_ORDER = ["Saved", "Applied", "Interviewing", "Offer", "Closed"]

# Reopen maps a closed-from stage back to a live status.
_REOPEN_TO = {"Interviewing": "Interviewing", "Offer": "Offer"}

# Optional one-tap reason when dismissing (§11.7).
DISMISS_REASONS = ["Wrong level", "Wrong location", "Not the right company", "Not interested"]


def stage_of(st: "JobState") -> str:
    """The board group a tracked job belongs to (see tracker spec §1)."""
    if st.application_status in CLOSED_STATUSES:
        return "Closed"
    if st.applied_at is None:
        return "Saved"
    if st.application_status in ("Interviewing", "Offer"):
        return st.application_status
    return "Applied"


def _active_stage(st: "JobState") -> str:
    """Pipeline stage ignoring closure — recorded as closed_from_stage on close.
    Only called while the job is not already closed."""
    if st.applied_at is None:
        return "Saved"
    if st.application_status in ("Interviewing", "Offer"):
        return st.application_status
    return "Applied"


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


def set_stage(db: DbSession, user_id: int, dedup_key: str, stage: str) -> JobState | None:
    """Move an applied job to a forward pipeline stage (also used for 'I applied')."""
    if stage not in PIPELINE_STAGES:
        return None
    from ..models import utcnow
    st = get_or_create(db, user_id, dedup_key)
    if st.applied_at is None:
        st.applied_at = utcnow()
    st.application_status = stage
    st.closed_from_stage = ""        # re-entering the pipeline clears any prior closure
    st.dismissed = False
    db.commit()
    return st


def to_saved(db: DbSession, user_id: int, dedup_key: str) -> JobState:
    """Move a job back to the Saved column — undo an 'I applied' (or a later
    stage), clearing the application but keeping it saved."""
    st = get_or_create(db, user_id, dedup_key)
    st.saved = True
    st.applied_at = None
    st.application_status = ""
    st.closed_from_stage = ""
    st.dismissed = False
    db.commit()
    return st


def close_application(db: DbSession, user_id: int, dedup_key: str,
                      outcome: str) -> JobState | None:
    """Reject or Withdraw from any active stage, remembering the stage."""
    if outcome not in CLOSE_OUTCOMES:
        return None
    from ..models import utcnow
    st = get_or_create(db, user_id, dedup_key)
    if st.applied_at is None:
        st.applied_at = utcnow()     # closing implies it's past "Saved"
    if st.application_status not in CLOSED_STATUSES:
        st.closed_from_stage = _active_stage(st)
    st.application_status = outcome
    db.commit()
    return st


def reopen_application(db: DbSession, user_id: int, dedup_key: str) -> JobState:
    st = get_or_create(db, user_id, dedup_key)
    st.application_status = _REOPEN_TO.get(st.closed_from_stage, "Applied")
    st.closed_from_stage = ""
    db.commit()
    return st


def set_next_step(db: DbSession, user_id: int, dedup_key: str,
                  text: str, on: "date | None") -> JobState:
    st = get_or_create(db, user_id, dedup_key)
    st.next_step = (text or "")[:80]
    st.next_step_on = on
    db.commit()
    return st
