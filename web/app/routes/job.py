"""Per-card actions on a result: save, dismiss, applied (§11.7).

Each is an HTMX POST that mutates the per-user JobState (keyed by the posting's
dedup_key, so it sticks across runs) and swaps just that one card back in.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
from ..db import get_session
from ..models import Document, Feedback, JobResult, JobState, User
from ..services import doc_quota, job_events, job_state
from ..templating import templates

router = APIRouter(prefix="/job")


def _result(db: DbSession, user: User, result_id: int) -> JobResult | None:
    r = db.get(JobResult, result_id)
    return r if r and r.user_id == user.id else None


def _render_card(request: Request, db: DbSession, user: User, r: JobResult) -> HTMLResponse:
    st = (db.query(JobState)
            .filter(JobState.user_id == user.id, JobState.dedup_key == r.dedup_key)
            .first())
    fb = (db.query(Feedback)
            .filter(Feedback.user_id == user.id, Feedback.job_result_id == r.id)
            .first())
    docs = {(d.job_result_id, d.kind)
            for d in db.query(Document).filter(Document.user_id == user.id,
                                               Document.job_result_id == r.id)}
    return templates.TemplateResponse(request, "partials/job_card.html", {
        "request": request, "user": user, "config": config,
        "r": r, "st": st, "fb": fb, "docs": docs,
        "allow": doc_quota.allowance(db, user),
        "dismiss_reasons": job_state.DISMISS_REASONS,
    })


def _act(request: Request, db: DbSession, user: User, result_id: int, mutate,
         event: str | None = None):
    r = _result(db, user, result_id)
    is_htmx = request.headers.get("HX-Request") == "true"
    if not r:
        return HTMLResponse("", status_code=404) if is_htmx \
            else RedirectResponse("/matches", status_code=303)
    mutate(r)
    if event:
        from ..services.events import record
        record(db, event, user_id=user.id)
    if is_htmx:
        return _render_card(request, db, user, r)
    return RedirectResponse("/matches", status_code=303)


@router.post("/{result_id}/save")
def save(result_id: int, request: Request, user: User = Depends(require_user),
         db: DbSession = Depends(get_session)):
    resp = _act(request, db, user, result_id,
                lambda r: job_state.set_saved(db, user.id, r.dedup_key, True),
                event="job_saved")
    # Tell the client to toast + highlight the My Jobs tab (htmx response only).
    if request.headers.get("HX-Request") == "true":
        resp.headers["HX-Trigger-After-Settle"] = "jobSavedToMyJobs"
    return resp


@router.post("/{result_id}/unsave")
def unsave(result_id: int, request: Request, user: User = Depends(require_user),
           db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_saved(db, user.id, r.dedup_key, False))


@router.post("/{result_id}/dismiss")
def dismiss(result_id: int, request: Request, reason: str = Form(default=""),
            user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_dismissed(db, user.id, r.dedup_key, True, reason),
                event="job_dismissed")


@router.post("/{result_id}/undismiss")
def undismiss(result_id: int, request: Request, user: User = Depends(require_user),
              db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_dismissed(db, user.id, r.dedup_key, False))


@router.post("/{result_id}/applied")
def applied(result_id: int, request: Request, user: User = Depends(require_user),
            db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_applied(db, user.id, r.dedup_key, True),
                event="job_marked_applied")


@router.post("/{result_id}/unapplied")
def unapplied(result_id: int, request: Request, user: User = Depends(require_user),
              db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_applied(db, user.id, r.dedup_key, False))


@router.post("/{result_id}/status")
def set_status(result_id: int, status: str = Form(...),
               user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """Update the application status from the Applications table (§11.10)."""
    r = _result(db, user, result_id)
    if r:
        job_state.set_application_status(db, user.id, r.dedup_key, status)
    return RedirectResponse("/applications", status_code=303)


# --------------------------- My Jobs tracker ------------------------------- #
def _render_track_card(request: Request, db: DbSession, user: User,
                       r: JobResult) -> HTMLResponse:
    st = (db.query(JobState)
            .filter(JobState.user_id == user.id, JobState.dedup_key == r.dedup_key)
            .first())
    docs = {(d.job_result_id, d.kind)
            for d in db.query(Document).filter(Document.user_id == user.id,
                                               Document.job_result_id == r.id)}
    return templates.TemplateResponse(request, "partials/track_card.html", {
        "request": request, "user": user, "config": config, "r": r, "st": st,
        "stage": job_state.stage_of(st) if st else "Saved",
        "docs": docs, "allow": doc_quota.allowance(db, user),
        "events": job_events.list_for(db, user.id, r.dedup_key),
        "pipeline_stages": job_state.PIPELINE_STAGES,
        "close_outcomes": job_state.CLOSE_OUTCOMES,
        "event_kinds": job_events.EVENT_KINDS,
    })


def _track_act(request: Request, db: DbSession, user: User, result_id: int, mutate,
               event: str | None = None):
    r = _result(db, user, result_id)
    is_htmx = request.headers.get("HX-Request") == "true"
    if not r:
        return HTMLResponse("", status_code=404) if is_htmx \
            else RedirectResponse("/applications", status_code=303)
    mutate(r)
    if event:
        from ..services.events import record
        record(db, event, user_id=user.id)
    if is_htmx:
        return _render_track_card(request, db, user, r)
    return RedirectResponse("/applications", status_code=303)


@router.post("/{result_id}/stage")
def stage(result_id: int, request: Request, stage: str = Form(...),
          user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    return _track_act(request, db, user, result_id,
                      lambda r: job_state.set_stage(db, user.id, r.dedup_key, stage),
                      event="job_stage_changed")


@router.post("/{result_id}/close")
def close(result_id: int, request: Request, outcome: str = Form(...),
          user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    return _track_act(request, db, user, result_id,
                      lambda r: job_state.close_application(db, user.id, r.dedup_key, outcome),
                      event="job_closed")


@router.post("/{result_id}/reopen")
def reopen(result_id: int, request: Request,
           user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    return _track_act(request, db, user, result_id,
                      lambda r: job_state.reopen_application(db, user.id, r.dedup_key))


@router.post("/{result_id}/next-step")
def next_step(result_id: int, request: Request,
              text: str = Form(default=""), on: str = Form(default=""),
              user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    d = None
    if on:
        try:
            d = date.fromisoformat(on)
        except ValueError:
            d = None
    return _track_act(request, db, user, result_id,
                      lambda r: job_state.set_next_step(db, user.id, r.dedup_key, text, d))


@router.post("/{result_id}/event")
def add_event(result_id: int, request: Request, kind: str = Form(default="note"),
              body: str = Form(default=""), occurred_on: str = Form(default=""),
              user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    d = None
    if occurred_on:
        try:
            d = date.fromisoformat(occurred_on)
        except ValueError:
            d = None
    return _track_act(request, db, user, result_id,
                      lambda r: job_events.add(db, user.id, r.dedup_key, kind, body, d))


@router.post("/{result_id}/event/{event_id}/delete")
def del_event(result_id: int, event_id: int, request: Request,
              user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    return _track_act(request, db, user, result_id,
                      lambda r: job_events.delete(db, user.id, event_id))
