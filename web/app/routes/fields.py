"""Small HTMX endpoints for auto-saving form widgets.

Currently just the country token field (F-03), used by both onboarding step 2
and Profile > Targets. Each endpoint mutates the profile, keeps the engine
location tokens in step, and returns the re-rendered field partial — no inline
script, so it holds under the strict CSP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Profile, User
from ..services.profile_service import (
    ABOUT_TARGET, COUNTRIES, COUNTRY_PRESETS, DEPTH_LABELS, OBJECTIVE_TARGET,
    remote_anywhere_on, set_countries, text_depth,
)
from ..templating import templates

router = APIRouter(prefix="/fields")


def _profile(db: DbSession, user: User) -> Profile:
    p = user.profile
    if p is None:
        p = Profile(user_id=user.id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _render(request: Request, db: DbSession, user: User) -> HTMLResponse:
    p = _profile(db, user)
    return templates.TemplateResponse(request, "partials/country_field.html", {
        "request": request, "profile": p, "country_options": COUNTRIES,
        "remote_anywhere": remote_anywhere_on(p),
    })


@router.post("/countries/add", response_class=HTMLResponse)
def add_country(request: Request, country: str = Form(default=""),
                user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    p = _profile(db, user)
    typed = country.strip().lower()
    match = next((c for c in COUNTRIES if c.lower() == typed), None)
    if match and match not in (p.countries or []):
        set_countries(p, list(p.countries or []) + [match])
        db.commit()
    return _render(request, db, user)


@router.post("/countries/remove", response_class=HTMLResponse)
def remove_country(request: Request, country: str = Form(default=""),
                   user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    p = _profile(db, user)
    set_countries(p, [c for c in (p.countries or []) if c != country])
    db.commit()
    return _render(request, db, user)


@router.post("/countries/preset", response_class=HTMLResponse)
def preset(request: Request, preset: str = Form(default=""),
           user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    p = _profile(db, user)
    if preset == "remote":
        set_countries(p, list(p.countries or []), remote_anywhere=True)
    elif preset == "remote-off":
        set_countries(p, list(p.countries or []), remote_anywhere=False)
    elif preset in COUNTRY_PRESETS:
        set_countries(p, list(p.countries or []) + COUNTRY_PRESETS[preset])
    db.commit()
    return _render(request, db, user)


@router.post("/depth", response_class=HTMLResponse)
async def depth(request: Request, field: str = Form(default="objective"),
                user: User = Depends(require_user)):
    """Live depth meter for a long-text field — no save, just reflects length
    against the field's STRONG target as the user types (§5.5)."""
    form = await request.form()
    value = form.get(field) or ""
    target = ABOUT_TARGET if field == "about_me" else OBJECTIVE_TARGET
    level = text_depth(value, target)
    return templates.TemplateResponse(request, "partials/depth_meter.html", {
        "request": request, "level": level, "label": DEPTH_LABELS[level],
    })
