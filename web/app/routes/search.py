"""The search page: run a search, show results, capture feedback, make docs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
from ..db import get_session
from ..models import Document, Feedback, JobResult, Search, User
from ..services.profile_service import completeness
from ..services.search_service import QuotaError, start_search
from ..templating import templates

log = logging.getLogger("jbhntr.search")
router = APIRouter()


def _latest(db: DbSession, user: User) -> Search | None:
    return (db.query(Search)
              .filter(Search.user_id == user.id)
              .order_by(Search.started_at.desc())
              .first())


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, user: User = Depends(require_user),
                db: DbSession = Depends(get_session), error: str = ""):
    state = completeness(db, user)
    search = _latest(db, user)
    results = []
    if search and search.status == "done":
        results = (db.query(JobResult)
                     .filter(JobResult.search_id == search.id)
                     .order_by(JobResult.position)
                     .all())

    voted = {
        f.job_result_id: f
        for f in db.query(Feedback).filter(Feedback.user_id == user.id)
    }
    docs = {
        (d.job_result_id, d.kind)
        for d in db.query(Document).filter(Document.user_id == user.id)
    }

    return templates.TemplateResponse(request, "search.html", {
        "request": request, "user": user, "state": state,
        "search": search, "results": results, "voted": voted, "docs": docs,
        "searches_left": user.searches_remaining(config.free_searches),
        "docs_left": None if user.is_premium
                     else max(0, config.free_documents - user.documents_used),
        "error": error,
    })


@router.post("/search")
def run_search(request: Request, user: User = Depends(require_user),
               db: DbSession = Depends(get_session)):
    try:
        start_search(db, user)
    except QuotaError as exc:
        return search_page(request, user, db, error=str(exc))
    return RedirectResponse("/search", status_code=303)


@router.get("/search/{search_id}/status", response_class=HTMLResponse)
def status(search_id: int, request: Request, user: User = Depends(require_user),
           db: DbSession = Depends(get_session)):
    """Polled by HTMX while a search runs."""
    search = db.get(Search, search_id)
    if not search or search.user_id != user.id:   # ownership check
        return HTMLResponse("", status_code=404)
    if search.status in ("done", "failed"):
        # Tell HTMX to reload the page so results render.
        return HTMLResponse('<div hx-get="/search" hx-target="body" hx-trigger="load"></div>')
    return templates.TemplateResponse(request, "partials/progress.html", {"request": request, "search": search}
    )


# --------------------------------------------------------------------------- #
@router.post("/feedback/{result_id}")
def feedback(result_id: int, request: Request,
             vote: str = Form(...), note: str = Form(default=""),
             user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    is_htmx = request.headers.get("HX-Request") == "true"
    result = db.get(JobResult, result_id)
    if not result or result.user_id != user.id or vote not in ("up", "down"):
        return HTMLResponse("", status_code=400) if is_htmx \
            else RedirectResponse("/search", status_code=303)

    existing = (db.query(Feedback)
                  .filter(Feedback.user_id == user.id,
                          Feedback.job_result_id == result_id)
                  .first())
    note = (note or "")[: config.max_feedback_chars]
    if existing:
        existing.vote, existing.note = vote, note
        fb = existing
    else:
        fb = Feedback(user_id=user.id, job_result_id=result_id, vote=vote, note=note)
        db.add(fb)
    db.commit()

    # HTMX: swap just this card's vote control in place — no reload, no scroll loss.
    if is_htmx:
        return templates.TemplateResponse(request, "partials/vote.html",
            {"request": request, "r": result, "fb": fb, "config": config})
    return RedirectResponse("/search", status_code=303)


# --------------------------------------------------------------------------- #
@router.post("/generate/{result_id}/{kind}")
def generate(result_id: int, kind: str, request: Request,
             user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """Write a tailored CV or cover letter for one job."""
    if kind not in ("cv", "cl"):
        return RedirectResponse("/search", status_code=303)

    result = db.get(JobResult, result_id)
    if not result or result.user_id != user.id:
        return RedirectResponse("/search", status_code=303)

    # Free allowance is checked server-side; the greyed-out button is only a hint.
    if not user.is_premium and user.documents_used >= config.free_documents:
        return search_page(request, user, db,
                           error="You've used your free documents. Upgrade for unlimited.")

    from jobhunter.config import Settings as EngineSettings
    from jobhunter.generator import Generator
    from jobhunter.models import JobPosting, MatchResult, RankedJob

    from ..services.profile_service import build_engine_materials, build_engine_profile

    settings = EngineSettings.from_env()
    posting = JobPosting(
        source=result.source, title=result.title, company=result.company,
        location=result.location, description=result.description, url=result.apply_url,
    )
    ranked = [RankedJob(job=posting,
                        match=MatchResult(tier=result.tier, score=result.score,
                                          reasons=result.why_good))]
    try:
        Generator(settings, drive=None).tailor_top(
            ranked, build_engine_profile(db, user), build_engine_materials(db, user), limit=1
        )
    except Exception as exc:
        log.exception("Document generation failed")
        return search_page(request, user, db,
                           error=f"Couldn't generate that document: {exc}")

    docs = ranked[0].documents or {}
    content = docs.get("cv" if kind == "cv" else "cover_letter", "")
    if not content:
        return search_page(request, user, db, error="Generation returned nothing. Try again.")

    db.add(Document(user_id=user.id, job_result_id=result.id, kind=kind, content=content))
    if not user.is_premium:
        user.documents_used += 1
    db.commit()
    return RedirectResponse(f"/document/{result.id}/{kind}", status_code=303)


@router.get("/document/{result_id}/{kind}")
def download(result_id: int, kind: str, user: User = Depends(require_user),
             db: DbSession = Depends(get_session)):
    doc = (db.query(Document)
             .filter(Document.job_result_id == result_id,
                     Document.kind == kind,
                     Document.user_id == user.id)      # ownership
             .order_by(Document.created_at.desc())
             .first())
    if not doc:
        return RedirectResponse("/search", status_code=303)

    result = db.get(JobResult, result_id)
    stem = "CV" if kind == "cv" else "CoverLetter"
    safe = "".join(c for c in (result.company or "job") if c.isalnum() or c in " -_")[:40]
    return PlainTextResponse(
        doc.content,
        headers={"Content-Disposition": f'attachment; filename="{stem}-{safe}.txt"'},
    )
