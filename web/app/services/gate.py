"""R3-14 gate prompt — "Compared with how you search for jobs today, this
shortlist is: much better / better / about the same / worse".

The Phase-1 gate KPI (KPI_TRACKER: >=60% better, >=30% much-better). Rules:

* **When.** Only after the user has *reviewed* their first scan: a completed
  scan (status 'done', not an "Imported job") with >=1 result, AND a first
  triage action on a result (referral.has_triaged: save / dismiss / applied /
  rating event, or any JobState row). A triage action is the cleanest existing
  signal that they have actually judged the shortlist; merely loading /matches
  (first_shortlist_viewed) fires before they have read a single card.
* **Once.** One GateAnswer row per user (unique user_id). The answer is set
  once and never overwritten; a second submit is rejected.
* **Not now.** Hides it. Re-asked once, no sooner than REASK_AFTER later. A
  second "not now" means never again (MAX_ASKS).
* **Where.** /matches (after the first triage action) and, R3-18, /applications
  (My Jobs, after the first save). Both pages call the ONE eligibility
  function, prompt_for(), over the ONE row, so answering or a second "not now"
  on either page suppresses it on both, and the re-ask is shared. ``surface``
  on the row records which page the answer came from.
* **Events.** gate_prompt_shown (once per ask, n=1|2), gate_prompt_answered
  (answer=...), gate_prompt_dismissed (n=1|2). Never raises from the view path.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from ..config import config
from ..models import GateAnswer, JobResult, Search, aware, utcnow
from . import referral
from .events import record

log = logging.getLogger("jbhntr.gate")

# (stored value, label) — order is the order shown, best first.
ANSWERS = (("much_better", "Much better"), ("better", "Better"),
           ("same", "About the same"), ("worse", "Worse"))
ANSWER_VALUES = frozenset(v for v, _ in ANSWERS)
POSITIVE = ("much_better", "better")
REASK_AFTER = timedelta(days=3)
MAX_ASKS = 2
IMPORTED_STAGE = "Imported job"
# Pages that render the prompt (partials/gate_prompt.html); the first is the
# default for a POST that names none. Also the no-JS redirect target.
SURFACES = ("matches", "applications")
SAVE_EVENTS = ("job_saved", "job_marked_applied")


def surface_of(value: str | None) -> str:
    """A submitted surface, whitelisted; anything else is 'matches'."""
    return value if value in SURFACES else SURFACES[0]


class GateError(Exception):
    """A rejected submit; ``status`` is the HTTP code the route returns."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def reviewed_first_scan(db, user_id: int) -> bool:
    """True once a completed, non-import scan has results AND the user has
    taken a first triage action."""
    return _has_scan_results(db, user_id) and referral.has_triaged(db, user_id)


def _has_scan_results(db, user_id: int) -> bool:
    return bool(db.query(JobResult.id)
                .join(Search, Search.id == JobResult.search_id)
                .filter(Search.user_id == user_id, Search.status == "done",
                        Search.stage != IMPORTED_STAGE)
                .first())


def has_saved(db, user_id: int) -> bool:
    """The user's first save (or mark-applied): an event, or a JobState row
    that is saved / applied (belt and braces if an analytics write was lost)."""
    from sqlalchemy import or_

    from ..models import JobState, ProductEvent
    if (db.query(ProductEvent.id)
            .filter(ProductEvent.user_id == user_id,
                    ProductEvent.name.in_(SAVE_EVENTS)).first()):
        return True
    return db.query(JobState.id).filter(
        JobState.user_id == user_id,
        or_(JobState.saved.is_(True), JobState.applied_at.isnot(None))).first() is not None


def _trigger_met(db, user_id: int, surface: str) -> bool:
    """The per-page moment: /matches after the first triage action, My Jobs
    after the first save. Both need a real (non-import) shortlist, since the
    question is about the shortlist."""
    if surface == "applications":
        return _has_scan_results(db, user_id) and has_saved(db, user_id)
    return reviewed_first_scan(db, user_id)


def _row(db, user_id: int) -> GateAnswer | None:
    return db.query(GateAnswer).filter(GateAnswer.user_id == user_id).one_or_none()


def _due(row: GateAnswer, now) -> bool:
    """Should an existing row be shown now?"""
    if row.answer is not None or row.dismiss_count >= MAX_ASKS:
        return False
    if row.dismiss_count == 0:
        return True                      # still the first ask, not dismissed
    return aware(row.dismissed_at) is not None and now - aware(row.dismissed_at) >= REASK_AFTER


def prompt_for(db, user_id: int, *, surface: str = "matches", now=None) -> bool:
    """THE eligibility check, shared by every surface: should this page show
    the prompt to this user right now? Creates the row (and logs
    gate_prompt_shown) the first time; on the re-ask bumps ``asks`` and logs it
    once more — so the shown/answered/not-now state is one per user, whichever
    page asks. Never raises — a failure just hides the prompt."""
    if not config.gate_prompt or surface not in SURFACES:
        return False
    now = now or utcnow()
    try:
        row = _row(db, user_id)
        if row is not None and not _due(row, now):
            return False                 # answered / not-now'd: one cheap query
        if not _trigger_met(db, user_id, surface):
            return False
        if row is None:
            db.add(GateAnswer(user_id=user_id, asks=1, shown_at=now))
            try:
                db.commit()
            except IntegrityError:       # a parallel request created it first
                db.rollback()
                return False
            record(db, "gate_prompt_shown", user_id, n=1)
            return True
        if row.dismiss_count > 0 and row.asks < MAX_ASKS:
            row.asks = MAX_ASKS
            row.shown_at = now
            db.commit()
            record(db, "gate_prompt_shown", user_id, n=row.asks)
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        log.exception("gate prompt check failed")
        return False


def answer(db, user_id: int, value: str, *, surface: str = "matches",
           now=None) -> GateAnswer:
    """Store the user's one answer (and the page it came from). GateError(400) for an unknown value,
    (409) if never asked or already answered."""
    if value not in ANSWER_VALUES:
        raise GateError(400, "Please pick one of the four options.")
    now = now or utcnow()
    row = _row(db, user_id)
    if row is None:
        raise GateError(409, "We haven't asked you this yet.")
    if row.answer is not None:
        raise GateError(409, "You've already answered — thank you.")
    # Conditional UPDATE so two racing submits cannot both win.
    n = (db.query(GateAnswer)
         .filter(GateAnswer.id == row.id, GateAnswer.answer.is_(None))
         .update({GateAnswer.answer: value, GateAnswer.answered_at: now,
                  GateAnswer.surface: surface_of(surface)},
                 synchronize_session=False))
    db.commit()
    if n != 1:
        raise GateError(409, "You've already answered — thank you.")
    record(db, "gate_prompt_answered", user_id, answer=value)
    db.refresh(row)
    return row


def dismiss(db, user_id: int, *, now=None) -> GateAnswer:
    """'Not now'. GateError(409) if never asked, already answered, or already
    dismissed for this ask."""
    now = now or utcnow()
    row = _row(db, user_id)
    if row is None or row.answer is not None:
        raise GateError(409, "Nothing to dismiss.")
    if row.dismiss_count >= row.asks:      # this ask is already dismissed
        raise GateError(409, "Already dismissed.")
    row.dismiss_count += 1
    row.dismissed_at = now
    db.commit()
    record(db, "gate_prompt_dismissed", user_id, n=row.dismiss_count)
    return row
