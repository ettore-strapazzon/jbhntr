"""Step-by-step onboarding. Every step is skippable; the search gate isn't."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
from ..db import get_session
from ..models import Material, Profile, SeedCompany, User
from ..security import UploadError, encrypt_bytes, extract_text, validate_upload
from ..services.profile_service import (
    COUNTRIES, WORK_MODES, build_location_tokens, completeness, split_list,
)
from ..templating import templates

router = APIRouter(prefix="/onboarding")

# Order matters: required steps first, so a user who quits early still has the
# minimum needed to search.
STEPS = [
    ("cv",           "Your CV",              True),
    ("about",        "About you",            True),
    ("objective",    "What you want",        True),
    ("role",         "Role & seniority",     True),
    ("company",      "Company & sectors",    True),
    ("location",     "Location & job type",  True),
    ("extras",       "Extra documents",      False),
    ("seeds",        "Companies you admire", False),
    ("terms",        "Job titles to search", False),
]
STEP_IDS = [s[0] for s in STEPS]

SENIORITY = ["junior", "mid", "senior", "lead", "head", "director", "chief", "vp"]
COMPANY_TYPES = ["startup", "scaleup", "enterprise", "agency", "non-profit", "public sector"]
VERTICALS = ["AI", "fintech", "crypto", "SaaS", "e-commerce", "healthtech", "deeptech",
             "banking", "consultancy", "gaming", "climate", "marketplace", "media"]
JOB_TYPES = ["full-time", "part-time", "contract", "freelance"]


def _profile(db: DbSession, user: User) -> Profile:
    p = user.profile
    if p is None:
        p = Profile(user_id=user.id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _next_step(current: str) -> str:
    i = STEP_IDS.index(current)
    return STEP_IDS[i + 1] if i + 1 < len(STEP_IDS) else ""


def _render(request: Request, step: str, db: DbSession, user: User, **extra):
    idx = STEP_IDS.index(step)
    return templates.TemplateResponse(request, f"onboarding/{step}.html",
        {
            "request": request, "user": user, "profile": _profile(db, user),
            "step": step, "step_no": idx + 1, "step_total": len(STEPS),
            "step_title": STEPS[idx][1], "required": STEPS[idx][2],
            "next_step": _next_step(step),
            "seniority_options": SENIORITY, "company_options": COMPANY_TYPES,
            "vertical_options": VERTICALS, "jobtype_options": JOB_TYPES,
            "work_mode_options": WORK_MODES, "country_options": COUNTRIES,
            "materials": db.query(Material).filter(Material.user_id == user.id).all(),
            "seeds": db.query(SeedCompany).filter(SeedCompany.user_id == user.id).all(),
            "state": completeness(db, user),
            **extra,
        },
    )


@router.get("", response_class=HTMLResponse)
def start(request: Request, user: User = Depends(require_user),
          db: DbSession = Depends(get_session)):
    return RedirectResponse("/onboarding/cv", status_code=303)


@router.get("/{step}", response_class=HTMLResponse)
def show_step(step: str, request: Request, user: User = Depends(require_user),
              db: DbSession = Depends(get_session)):
    if step not in STEP_IDS:
        return RedirectResponse("/onboarding/cv", status_code=303)
    return _render(request, step, db, user)


# --------------------------------------------------------------------------- #
@router.post("/upload")
async def upload(
    request: Request,
    kind: str = Form(...),
    step: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: DbSession = Depends(get_session),
):
    if kind not in ("cv", "cover_letter", "linkedin"):
        return RedirectResponse(f"/onboarding/{step}", status_code=303)

    raw = await file.read()
    try:
        ext, mime = validate_upload(file.filename or "", raw)
    except UploadError as exc:
        return _render(request, step, db, user, error=str(exc))

    text = extract_text(ext, raw)
    if not text.strip():
        return _render(request, step, db, user,
                       error="We couldn't read any text from that file. "
                             "If it's a scanned PDF, please upload a text-based one.")

    db.add(Material(
        user_id=user.id, kind=kind, filename=(file.filename or "upload")[:255],
        mime=mime, size_bytes=len(raw),
        ciphertext=encrypt_bytes(raw),   # never stored in plaintext
        text=text[:200_000],
    ))
    db.commit()
    return RedirectResponse(f"/onboarding/{step}", status_code=303)


@router.post("/material/{material_id}/delete")
def delete_material(material_id: int, step: str = Form(default="cv"),
                    user: User = Depends(require_user),
                    db: DbSession = Depends(get_session)):
    (db.query(Material)
       .filter(Material.id == material_id, Material.user_id == user.id)  # ownership
       .delete())
    db.commit()
    return RedirectResponse(f"/onboarding/{step}", status_code=303)


# --------------------------------------------------------------------------- #
@router.post("/save/{step}")
def save_step(
    step: str,
    request: Request,
    user: User = Depends(require_user),
    db: DbSession = Depends(get_session),
    about_me: str = Form(default=""),
    objective: str = Form(default=""),
    salary_floor: str = Form(default=""),
    seed_values: str = Form(default=""),
    search_terms: str = Form(default=""),
):
    p = _profile(db, user)

    if step == "about":
        p.about_me = about_me.strip()[:20_000]
    elif step == "objective":
        p.objective = objective.strip()[:10_000]
    elif step == "terms":
        p.search_terms = [t.strip() for t in search_terms.splitlines() if t.strip()][:15]
    elif step == "seeds":
        db.query(SeedCompany).filter(SeedCompany.user_id == user.id).delete()
        for value in [v.strip() for v in seed_values.splitlines() if v.strip()][:100]:
            db.add(SeedCompany(user_id=user.id, value=value[:255]))
    if salary_floor.strip().isdigit():
        p.salary_floor_eur = int(salary_floor.strip())

    db.commit()
    nxt = _next_step(step)
    return RedirectResponse(f"/onboarding/{nxt}" if nxt else "/search", status_code=303)


@router.post("/save-lists/{step}")
async def save_lists(step: str, request: Request,
                     user: User = Depends(require_user),
                     db: DbSession = Depends(get_session)):
    """Steps whose fields are multi-select checkboxes."""
    form = await request.form()
    p = _profile(db, user)

    if step == "role":
        p.seniority = [v for v in form.getlist("seniority") if v in SENIORITY]
    elif step == "company":
        p.company_type = [v for v in form.getlist("company_type") if v in COMPANY_TYPES]
        p.verticals = [v for v in form.getlist("verticals") if v in VERTICALS]
    elif step == "location":
        p.work_modes = [v for v in form.getlist("work_mode") if v in WORK_MODES]
        p.countries = [c for c in form.getlist("countries") if c in COUNTRIES]
        p.locations = build_location_tokens(
            p.work_modes, p.countries,
            remote_anywhere=bool(form.get("remote_anywhere")),
        )
        p.job_type = [v for v in form.getlist("job_type") if v in JOB_TYPES]

    db.commit()
    nxt = _next_step(step)
    return RedirectResponse(f"/onboarding/{nxt}" if nxt else "/search", status_code=303)
