"""Per-card actions on a result: save, dismiss, applied (§11.7).

Each is an HTMX POST that mutates the per-user JobState (keyed by the posting's
dedup_key, so it sticks across runs) and swaps just that one card back in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
from ..db import get_session
from ..models import Document, Feedback, JobResult, JobState, User
from ..services import job_state
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
        "docs_left": None if user.is_premium
                     else max(0, config.free_documents - user.documents_used),
        "dismiss_reasons": job_state.DISMISS_REASONS,
    })


def _act(request: Request, db: DbSession, user: User, result_id: int, mutate):
    r = _result(db, user, result_id)
    is_htmx = request.headers.get("HX-Request") == "true"
    if not r:
        return HTMLResponse("", status_code=404) if is_htmx \
            else RedirectResponse("/matches", status_code=303)
    mutate(r)
    if is_htmx:
        return _render_card(request, db, user, r)
    return RedirectResponse("/matches", status_code=303)


@router.post("/{result_id}/save")
def save(result_id: int, request: Request, user: User = Depends(require_user),
         db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_saved(db, user.id, r.dedup_key, True))


@router.post("/{result_id}/unsave")
def unsave(result_id: int, request: Request, user: User = Depends(require_user),
           db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_saved(db, user.id, r.dedup_key, False))


@router.post("/{result_id}/dismiss")
def dismiss(result_id: int, request: Request, reason: str = Form(default=""),
            user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_dismissed(db, user.id, r.dedup_key, True, reason))


@router.post("/{result_id}/undismiss")
def undismiss(result_id: int, request: Request, user: User = Depends(require_user),
              db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_dismissed(db, user.id, r.dedup_key, False))


@router.post("/{result_id}/applied")
def applied(result_id: int, request: Request, user: User = Depends(require_user),
            db: DbSession = Depends(get_session)):
    return _act(request, db, user, result_id,
                lambda r: job_state.set_applied(db, user.id, r.dedup_key, True))


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
