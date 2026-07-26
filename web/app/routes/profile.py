"""Profile page — everything the user provided, all editable."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Material, Profile, SeedCompany, User
from ..services.profile_service import (
    COUNTRIES, MIN_TEXT, WORK_MODES, build_location_tokens, completeness,
    split_list, text_too_short,
)
from ..templating import templates
from .onboarding import COMPANY_TYPES, JOB_TYPES, SENIORITY, VERTICALS

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, user: User = Depends(require_user),
                 db: DbSession = Depends(get_session), saved: str = "", error: str = ""):
    return templates.TemplateResponse(request, "profile.html", {
        "request": request, "user": user,
        "profile": user.profile or Profile(user_id=user.id),
        "materials": db.query(Material).filter(Material.user_id == user.id).all(),
        "seeds": db.query(SeedCompany).filter(SeedCompany.user_id == user.id).all(),
        "state": completeness(db, user),
        "seniority_options": SENIORITY, "company_options": COMPANY_TYPES,
        "vertical_options": VERTICALS, "jobtype_options": JOB_TYPES,
        "work_mode_options": WORK_MODES, "country_options": COUNTRIES,
        "min_text": MIN_TEXT, "saved": saved, "error": error,
    })


@router.post("/profile")
async def save_profile(request: Request, user: User = Depends(require_user),
                       db: DbSession = Depends(get_session)):
    form = await request.form()

    # Don't save a too-short long-text answer silently — name the field (F-04).
    for field in ("objective", "about_me"):
        if text_too_short(form.get(field) or ""):
            label = "What you're looking for" if field == "objective" else "About you"
            return RedirectResponse(
                f"/profile?error={label}+needs+at+least+{MIN_TEXT}+characters",
                status_code=303)

    p = user.profile
    if p is None:
        p = Profile(user_id=user.id)
        db.add(p)
        db.flush()

    p.objective = (form.get("objective") or "").strip()[:10_000]
    p.about_me = (form.get("about_me") or "").strip()[:20_000]
    p.seniority = [v for v in form.getlist("seniority") if v in SENIORITY]
    p.company_type = [v for v in form.getlist("company_type") if v in COMPANY_TYPES]
    p.verticals = [v for v in form.getlist("verticals") if v in VERTICALS]
    p.job_type = [v for v in form.getlist("job_type") if v in JOB_TYPES]
    p.work_modes = [v for v in form.getlist("work_mode") if v in WORK_MODES]
    p.countries = [c for c in form.getlist("countries") if c in COUNTRIES]
    p.locations = build_location_tokens(
        p.work_modes, p.countries, remote_anywhere=bool(form.get("remote_anywhere")),
    )
    p.search_terms = split_list(form.get("search_terms") or "", limit=15)

    salary = (form.get("salary_floor") or "").strip()
    p.salary_floor_eur = int(salary) if salary.isdigit() else None

    # Seeds are replaced wholesale — simpler than diffing, and the list is small.
    db.query(SeedCompany).filter(SeedCompany.user_id == user.id).delete()
    for value in [v.strip() for v in (form.get("seeds") or "").splitlines() if v.strip()][:100]:
        db.add(SeedCompany(user_id=user.id, value=value[:255]))

    db.commit()
    return RedirectResponse("/profile?saved=1", status_code=303)
