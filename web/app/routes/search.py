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
    from ..services.credits import InsufficientCredits
    try:
        start_search(db, user)
    except InsufficientCredits:
        return RedirectResponse("/credits?from=scan", status_code=303)
    except QuotaError as exc:
        return RedirectResponse(f"/matches?error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/matches", status_code=303)


@router.post("/matches/import")
def import_from_url(request: Request, url: str = Form(...),
                    user: User = Depends(require_user),
                    db: DbSession = Depends(get_session)):
    """Paste a job URL, score it against you, and show it as a card (IMPORT-01).
    Costs config.cost_external_import; free actions stay free."""
    import hashlib

    from ..services import credits
    from ..services.import_service import JobImportError, import_job
    key = f"import:{hashlib.sha1((url or '').encode()).hexdigest()[:16]}:{user.id}"
    try:
        row = credits.debit(db, user, config.cost_external_import, "external_import",
                            ref_type="import", ref_id=url[:120], idempotency_key=key)
    except credits.InsufficientCredits:
        return RedirectResponse("/credits?from=import", status_code=303)
    try:
        _, search_id = import_job(db, user, url)
    except JobImportError as exc:
        credits.refund(db, row, reason="search_refund")
        return RedirectResponse("/matches?error=" + quote(str(exc)), status_code=303)
    except Exception:
        credits.refund(db, row, reason="search_refund")
        log.exception("Job import failed")
        return RedirectResponse(
            "/matches?error=" + quote("Import failed — please try again."), status_code=303)
    # Show the board filtered to this one-off run so the imported card is front and centre.
    return RedirectResponse(f"/matches?run={search_id}", status_code=303)


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
             rating: int = Form(...), note: str = Form(default=""),
             user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    from ..models import RATING_TO_VOTE
    is_htmx = request.headers.get("HX-Request") == "true"
    result = db.get(JobResult, result_id)
    if not result or result.user_id != user.id or not 1 <= rating <= 5:
        return HTMLResponse("", status_code=400) if is_htmx \
            else RedirectResponse("/matches", status_code=303)

    fb = (db.query(Feedback)
            .filter(Feedback.user_id == user.id, Feedback.job_result_id == result_id)
            .first())
    if fb is None:
        fb = Feedback(user_id=user.id, job_result_id=result_id)
        db.add(fb)
    fb.rating = rating
    fb.vote = RATING_TO_VOTE[rating]                      # derived, kept for downstream
    fb.note = (note or "")[: config.max_feedback_chars]
    db.commit()
    from ..services.events import record
    record(db, "match_rated", user_id=user.id, rating=rating)

    # HTMX: swap just this card's rating control in place, no reload, no scroll loss.
    if is_htmx:
        return templates.TemplateResponse(request, "partials/vote.html",
            {"request": request, "r": result, "fb": fb, "config": config})
    return RedirectResponse("/matches", status_code=303)


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

    # Priced in credits (PLAN-02/PRICE-05): first CV/CL at its price, any later
    # version of the same (job, kind) at the cheaper regenerate price. Debit before
    # compute; refund on failure. Editing/exporting an existing doc stays free.
    from ..services import credits
    versions = (db.query(Document)
                .filter(Document.job_result_id == result.id,
                        Document.kind == kind, Document.user_id == user.id).all())
    if versions:
        price, reason = config.cost_regenerate, "doc_regen"
        idem = f"doc:{kind}:{result.id}:v{len(versions) + 1}"
    else:
        price = config.cost_cv if kind == "cv" else config.cost_cover_letter
        reason = "doc_cv" if kind == "cv" else "doc_cl"
        idem = f"doc:{kind}:{result.id}"
    try:
        charge = credits.debit(db, user, price, reason, ref_type="document",
                               ref_id=str(result.id), idempotency_key=idem)
    except credits.InsufficientCredits:
        return RedirectResponse("/credits?from=doc", status_code=303)

    def _fail(msg: str):
        credits.refund(db, charge, reason="search_refund")
        return RedirectResponse("/applications?error=" + quote(msg), status_code=303)

    from jobhunter.models import MatchResult, RankedJob

    from ..services.profile_service import build_generation_context

    # Generation config (models, posting, drive-less Generator) — shared with the
    # refine loop so both behave identically.
    gen, eng_profile, eng_materials, posting = build_generation_context(
        db, user, result, config)
    settings = gen.settings
    note = ""
    content = ""

    # CV: structured generation — the model fills explicit fields (honest headline,
    # every employer/position/bullet, kept sections) which we serialise to the
    # canonical layout the renderer parses exactly. This keeps roles and metrics
    # from being lost in a prose rewrite. Falls back to the paths below on failure.
    if kind == "cv":
        from ..services import cv_build
        built = cv_build.build_cv(eng_materials, posting, settings, config)
        if built:
            content = built
            note = "Tailored from your CV's structure — sections, roles and metrics kept."

    # A multi-model panel for a stronger result than a single model can give — for
    # everyone now (one quality level, D-2). Runs for cover letters, and for a CV
    # only if the structured build above failed; any panel failure falls back.
    if not content:
        try:
            from ..services import panel
            pr = panel.deliberate(kind, eng_materials, posting, settings, config)
            if pr and pr.get("content"):
                content = pr["content"]
                note = (f"Refined by a {pr['models']}-model panel "
                        f"({int(pr['agreement'] * 100)}% agreement).")
        except Exception:
            log.exception("Panel generation failed; using single model")

    try:
        if content:
            pass
        elif kind == "cl":
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
        return _fail(f"Couldn't generate that document: {exc}")

    if not content:
        return _fail("Generation returned nothing. Try again.")

    # Strip any dashes the model slips through, so the draft never reads as
    # machine-written (R2).
    from ..services.text import humanise
    db.add(Document(user_id=user.id, job_result_id=result.id, kind=kind,
                    content=humanise(content), note=humanise(note)))
    db.commit()
    from ..services.events import record
    record(db, "document_generated", user_id=user.id, kind=kind)
    # The document view (routes/documents.py) renders it, editable, with exports.
    return RedirectResponse(f"/document/{result.id}/{kind}", status_code=303)
