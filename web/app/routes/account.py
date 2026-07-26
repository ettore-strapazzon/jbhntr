"""Account: premium page, GDPR data export, account deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import clear_cookie, require_user
from ..config import config
from ..db import get_session
from ..models import (
    Document, Feedback, JobResult, Material, Profile, Search, SeedCompany,
    Session, User,
)
from ..templating import templates

router = APIRouter()


@router.get("/premium", response_class=HTMLResponse)
def premium(request: Request, user: User = Depends(require_user), requested: str = ""):
    return templates.TemplateResponse(request, "premium.html",
        {"request": request, "user": user, "requested": requested})


@router.post("/premium/notify")
def premium_notify(user: User = Depends(require_user),
                   db: DbSession = Depends(get_session)):
    """Capture premium intent while checkout is 'coming soon' (F-13). Records a
    flag the operator can upgrade from manually, instead of a dead-end button."""
    from ..models import utcnow
    if not user.premium_requested_at:
        user.premium_requested_at = utcnow()
        db.commit()
    return RedirectResponse("/premium?requested=1", status_code=303)


# --------------------------------------------------------------------------- #
@router.get("/account", response_class=HTMLResponse)
def account(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "account.html", {"request": request, "user": user})


@router.get("/account/export")
def export_data(user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """GDPR Art. 15 — everything we hold, as JSON.

    File *contents* are included as extracted text rather than the encrypted
    original, which is what the user actually gave us.
    """
    p = user.profile
    data = {
        "account": {
            "email": user.email,
            "plan": user.plan,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "searches_used": user.searches_used,
            "documents_used": user.documents_used,
            "marketing_opt_in": user.marketing_opt_in,
        },
        "profile": {
            "objective": p.objective if p else "",
            "about_me": p.about_me if p else "",
            "seniority": p.seniority if p else [],
            "company_type": p.company_type if p else [],
            "verticals": p.verticals if p else [],
            "locations": p.locations if p else [],
            "job_type": p.job_type if p else [],
            "search_terms": p.search_terms if p else [],
            "salary_floor_eur": p.salary_floor_eur if p else None,
        },
        "documents_uploaded": [
            {"kind": m.kind, "filename": m.filename, "size_bytes": m.size_bytes,
             "extracted_text": m.text}
            for m in db.query(Material).filter(Material.user_id == user.id)
        ],
        "seed_companies": [s.value for s in
                           db.query(SeedCompany).filter(SeedCompany.user_id == user.id)],
        "searches": [
            {"id": s.id, "status": s.status, "started_at": s.started_at.isoformat(),
             "results": s.scored_count}
            for s in db.query(Search).filter(Search.user_id == user.id)
        ],
        "job_results": [
            {"title": r.title, "company": r.company, "tier": r.tier, "score": r.score,
             "tags": r.tags, "why_good": r.why_good, "why_bad": r.why_bad}
            for r in db.query(JobResult).filter(JobResult.user_id == user.id)
        ],
        "feedback": [
            {"vote": f.vote, "note": f.note, "at": f.created_at.isoformat()}
            for f in db.query(Feedback).filter(Feedback.user_id == user.id)
        ],
        "generated_documents": [
            {"kind": d.kind, "created_at": d.created_at.isoformat(), "content": d.content}
            for d in db.query(Document).filter(Document.user_id == user.id)
        ],
    }
    return JSONResponse(
        data,
        headers={"Content-Disposition": 'attachment; filename="jbhntr-my-data.json"'},
    )


@router.post("/account/delete")
def delete_account(request: Request, confirm: str = Form(default=""),
                   user: User = Depends(require_user),
                   db: DbSession = Depends(get_session)):
    """GDPR Art. 17 — a real hard delete, not a soft flag.

    Rows are removed in dependency order; the encrypted file bytes go with the
    `materials` rows, so nothing recoverable is left behind.
    """
    if confirm.strip().upper() != "DELETE":
        return templates.TemplateResponse(request, "account.html", {
            "request": request, "user": user,
            "error": 'Type DELETE exactly to confirm.',
        })

    uid = user.id
    db.query(Document).filter(Document.user_id == uid).delete()
    db.query(Feedback).filter(Feedback.user_id == uid).delete()
    db.query(JobResult).filter(JobResult.user_id == uid).delete()
    db.query(Search).filter(Search.user_id == uid).delete()
    db.query(Material).filter(Material.user_id == uid).delete()
    db.query(SeedCompany).filter(SeedCompany.user_id == uid).delete()
    db.query(Profile).filter(Profile.user_id == uid).delete()
    db.query(Session).filter(Session.user_id == uid).delete()
    db.query(User).filter(User.id == uid).delete()
    db.commit()

    response = RedirectResponse("/?deleted=1", status_code=303)
    clear_cookie(response)
    return response
