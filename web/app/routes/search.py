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


from urllib.parse import quote


@router.get("/search")
def search_redirect():
    """The page moved to /matches; keep the old URL working."""
    return RedirectResponse("/matches", status_code=307)


@router.post("/search")
def run_search(request: Request, user: User = Depends(require_user),
               db: DbSession = Depends(get_session)):
    try:
        start_search(db, user)
    except QuotaError as exc:
        return RedirectResponse(f"/matches?error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/matches", status_code=303)


@router.post("/search/{search_id}/notify", response_class=HTMLResponse)
def notify_when_ready(search_id: int, request: Request,
                      user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """'Email me when it's ready' (§11.6). Sets the flag the worker checks."""
    search = db.get(Search, search_id)
    if search and search.user_id == user.id and search.status in ("queued", "running"):
        search.notify_email = True
        db.commit()
    return HTMLResponse('<span class="small muted">We\'ll email you when it\'s ready.</span>')


@router.get("/search/{search_id}/status", response_class=HTMLResponse)
def status(search_id: int, request: Request, user: User = Depends(require_user),
           db: DbSession = Depends(get_session)):
    """Polled by HTMX while a search runs."""
    search = db.get(Search, search_id)
    if not search or search.user_id != user.id:   # ownership check
        return HTMLResponse("", status_code=404)
    if search.status in ("done", "failed"):
        # Tell HTMX to reload the page so results render.
        return HTMLResponse('<div hx-get="/matches" hx-target="body" hx-trigger="load"></div>')
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
            else RedirectResponse("/matches", status_code=303)

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
        return RedirectResponse("/matches", status_code=303)

    result = db.get(JobResult, result_id)
    if not result or result.user_id != user.id:
        return RedirectResponse("/matches", status_code=303)

    # Per-type free allowance, checked server-side (the greyed button is a hint).
    # Regenerating a doc this job already has is always free.
    from ..services import doc_quota
    already = (db.query(Document)
                 .filter(Document.job_result_id == result.id,
                         Document.kind == kind, Document.user_id == user.id).first())
    if not user.is_premium and not already and doc_quota.left(db, user, kind) == 0:
        label = "tailored CVs" if kind == "cv" else "cover letters"
        return RedirectResponse(
            "/matches?error=" + quote(f"You've used your free {label}. Premium is unlimited."),
            status_code=303)

    from jobhunter.config import Settings as EngineSettings
    from jobhunter.generator import Generator
    from jobhunter.models import JobPosting, MatchResult, RankedJob

    from ..services.profile_service import build_engine_materials, build_engine_profile

    settings = EngineSettings.from_env()
    # Search overrides only the scoring model; generation uses its own tier and
    # was left unconfigured, so tailoring raised "no generation model" and got
    # swallowed to "returned nothing". Point generation at the same model search
    # uses, which we know works with the configured key.
    model = config.premium_scoring_model if user.is_premium else config.free_scoring_model
    settings.scoring_model = model
    settings.generation_model = model
    posting = JobPosting(
        source=result.source, title=result.title, company=result.company,
        location=result.location, description=result.description, url=result.apply_url,
    )
    gen = Generator(settings, drive=None)
    eng_profile = build_engine_profile(db, user)
    eng_materials = build_engine_materials(db, user)
    note = ""
    try:
        if kind == "cl":
            # Cover letters get a company-tone read plus a short note explaining it.
            out = gen.cover_letter(eng_profile, eng_materials, posting)
            content = (out or {}).get("cover_letter", "")
            note = (out or {}).get("tone_note", "")
        else:
            ranked = [RankedJob(job=posting,
                                match=MatchResult(tier=result.tier, score=result.score,
                                                  reasons=result.why_good))]
            gen.tailor_top(ranked, eng_profile, eng_materials, limit=1)
            content = (ranked[0].documents or {}).get("cv", "")
    except Exception as exc:
        log.exception("Document generation failed")
        return RedirectResponse(
            "/matches?error=" + quote(f"Couldn't generate that document: {exc}"),
            status_code=303)

    if not content:
        return RedirectResponse(
            "/matches?error=" + quote("Generation returned nothing. Try again."),
            status_code=303)

    # Belt-and-suspenders on the "no em dashes" rule — strip any the model slips
    # through, so the draft never reads as machine-written.
    dedash = lambda t: (t or "").replace(" — ", ", ").replace("—", ", ").replace("–", "-")
    db.add(Document(user_id=user.id, job_result_id=result.id, kind=kind,
                    content=dedash(content), note=dedash(note)))
    if not user.is_premium:
        user.documents_used += 1
    db.commit()
    # The document view (routes/documents.py) renders it, editable, with exports.
    return RedirectResponse(f"/document/{result.id}/{kind}", status_code=303)
