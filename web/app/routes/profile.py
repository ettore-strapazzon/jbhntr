"""Profile page (§11.9) — a strength block over three anchored sections:
Documents, In your words, Targets. Each section saves itself, so a save never
wipes fields it didn't show. Countries are owned by the token field (F-03) and
auto-save independently; everything else round-trips through POST /profile,
branched on a hidden `_section` marker.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Material, Profile, SeedCompany, User
from ..services.profile_service import (
    ABOUT_TARGET, COUNTRIES, DEPTH_LABELS, MIN_TEXT, OBJECTIVE_TARGET,
    WORK_MODES, completeness, rebuild_locations, remote_anywhere_on, split_list,
    strength, text_depth, text_too_short,
)
from ..templating import templates
from .onboarding import COMPANY_TYPES, JOB_TYPES, SENIORITY, VERTICALS

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, user: User = Depends(require_user),
                 db: DbSession = Depends(get_session), saved: str = "", error: str = ""):
    p = user.profile or Profile(user_id=user.id)
    return templates.TemplateResponse(request, "profile.html", {
        "request": request, "user": user, "profile": p,
        "materials": db.query(Material).filter(Material.user_id == user.id).all(),
        "seeds": db.query(SeedCompany).filter(SeedCompany.user_id == user.id).all(),
        "state": completeness(db, user), "strength": strength(db, user),
        "seniority_options": SENIORITY, "company_options": COMPANY_TYPES,
        "vertical_options": VERTICALS, "jobtype_options": JOB_TYPES,
        "work_mode_options": WORK_MODES, "country_options": COUNTRIES,
        "remote_anywhere": remote_anywhere_on(p),
        "objective_target": OBJECTIVE_TARGET, "about_target": ABOUT_TARGET,
        "objective_depth": text_depth(p.objective or "", OBJECTIVE_TARGET),
        "about_depth": text_depth(p.about_me or "", ABOUT_TARGET),
        "depth_labels": DEPTH_LABELS, "min_text": MIN_TEXT,
        "saved": saved, "error": error,
    })


@router.post("/profile")
async def save_profile(request: Request, user: User = Depends(require_user),
                       db: DbSession = Depends(get_session)):
    form = await request.form()
    section = form.get("_section", "you")   # default keeps old callers working

    p = user.profile
    if p is None:
        p = Profile(user_id=user.id)
        db.add(p)
        db.flush()

    if section == "targets":
        p.seniority = [v for v in form.getlist("seniority") if v in SENIORITY]
        p.company_type = [v for v in form.getlist("company_type") if v in COMPANY_TYPES]
        p.verticals = [v for v in form.getlist("verticals") if v in VERTICALS]
        p.job_type = [v for v in form.getlist("job_type") if v in JOB_TYPES]
        p.work_modes = [v for v in form.getlist("work_mode") if v in WORK_MODES]
        rebuild_locations(p)   # countries owned by the token field
        p.search_terms = split_list(form.get("search_terms") or "", limit=15)
        salary = (form.get("salary_floor") or "").strip()
        p.salary_floor_eur = int(salary) if salary.isdigit() else None
        db.query(SeedCompany).filter(SeedCompany.user_id == user.id).delete()
        for value in [v.strip() for v in (form.get("seeds") or "").splitlines() if v.strip()][:100]:
            db.add(SeedCompany(user_id=user.id, value=value[:255]))
        db.commit()
        return RedirectResponse("/profile?saved=1#targets", status_code=303)

    # section == "you": the two authored fields, each with the F-04 floor.
    for field, label, anchor in (("objective", "What you're looking for", "you"),
                                 ("about_me", "A bit about you", "you")):
        if text_too_short(form.get(field) or ""):
            return RedirectResponse(
                f"/profile?error={label}+needs+at+least+{MIN_TEXT}+characters#{anchor}",
                status_code=303)
    p.objective = (form.get("objective") or "").strip()[:10_000]
    p.about_me = (form.get("about_me") or "").strip()[:20_000]
    db.commit()
    return RedirectResponse("/profile?saved=1#you", status_code=303)
