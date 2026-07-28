"""Onboarding in three steps (§5.1 / §11.2-11.4).

The nine linear steps collapsed to the smallest set of things only the user can
give: a CV, where and how they want to work, and what they're after in their own
words. Everything else (extra documents, seed companies, search terms) moved out
of the funnel and became post-first-search refinements on Profile. Required
steps still come first so a user who stops early keeps the minimum to search;
the search gate is the real guard, not the step order.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Material, Profile, User
from ..security import UploadError, encrypt_bytes, extract_text, validate_upload
from ..services.profile_service import (
    ABOUT_TARGET, COUNTRIES, DEPTH_LABELS, MIN_TEXT, OBJECTIVE_TARGET,
    WORK_MODES, completeness, rebuild_locations, remote_anywhere_on,
    text_depth, text_too_short,
)
from ..templating import templates

router = APIRouter(prefix="/onboarding")

# Three steps, all required before the first search. Labels drive the rail.
STEPS = [
    ("upload", "Start with your CV",          True),
    ("aim",    "Where and how you'll work",   True),
    ("words",  "Now the part only you can write", True),
]
STEP_IDS = [s[0] for s in STEPS]
STEP_LABELS = ["Your CV", "Where and how", "In your words"]

# Four seniority bands (R5.3). The old eight-token vocabulary is kept as an
# internal expansion so the matching engine still sees what it was tuned on.
SENIORITY = ["junior", "mid", "senior", "executive"]
SENIORITY_LABELS = {
    "junior":    ("Junior",    "0 to 2 years, or a first role in this field"),
    "mid":       ("Mid",       "3 to 6 years, owns their own work"),
    "senior":    ("Senior",    "Senior, staff, principal, lead"),
    "executive": ("Executive", "Head, director, VP, chief"),
}
SENIORITY_EXPANSION = {
    "junior":    ["junior", "graduate", "associate", "entry"],
    "mid":       ["mid", "intermediate"],
    "senior":    ["senior", "staff", "principal", "lead"],
    "executive": ["head", "director", "chief", "vp", "svp", "c-level"],
}
# Old stored token -> new band, for the one-off profile migration.
SENIORITY_MIGRATE = {"lead": "senior", "head": "executive", "director": "executive",
                     "chief": "executive", "vp": "executive"}

VERTICALS = [
    "AI and machine learning", "Software and SaaS", "Developer tools and cloud",
    "Cybersecurity", "Data and analytics", "Fintech and payments",
    "Banking and capital markets", "Insurance", "Crypto and web3",
    "E-commerce and retail", "Marketplaces", "Consumer apps and social",
    "Media, gaming and entertainment", "Healthcare and healthtech",
    "Pharma, biotech and medtech", "Climate, energy and utilities",
    "Mobility, transport and logistics", "Manufacturing and industrial",
    "Deeptech, space and robotics", "Construction and real estate",
    "Travel and hospitality", "Food, drink and agriculture",
    "Education and edtech", "HR, recruiting and future of work",
    "Legal and regtech", "Professional services and consulting",
    "Telecoms", "Public sector and government", "Defence and aerospace",
    "Non-profit and NGO", "Sport and fitness", "Fashion and beauty",
]
COMPANY_TYPES = [
    "Pre-seed or seed startup", "Series A or B startup",
    "Scaleup, Series C and beyond", "Listed company", "Large private company",
    "Family owned business", "Small or medium business",
    "Agency or studio", "Consultancy", "Non-profit or NGO",
    "Public sector or government", "University or research institute",
    "Investor, PE or VC", "Fully remote company",
    "Bootstrapped and profitable",
]
# Old slug -> new label, for the one-off profile migration (R5.4).
VERTICAL_MIGRATE = {"AI": "AI and machine learning", "SaaS": "Software and SaaS",
                    "fintech": "Fintech and payments", "banking": "Banking and capital markets"}
COMPANY_MIGRATE = {"startup": "Series A or B startup",
                   "scaleup": "Scaleup, Series C and beyond", "enterprise": "Listed company"}

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
    p = _profile(db, user)
    ctx = {
        "request": request, "user": user, "profile": p,
        "step": step, "step_no": idx + 1, "step_total": len(STEPS),
        "step_title": STEPS[idx][1], "step_labels": STEP_LABELS,
        "required": STEPS[idx][2], "next_step": _next_step(step),
        "seniority_options": SENIORITY, "seniority_labels": SENIORITY_LABELS,
        "company_options": COMPANY_TYPES,
        "vertical_options": VERTICALS, "jobtype_options": JOB_TYPES,
        "work_mode_options": WORK_MODES, "country_options": COUNTRIES,
        "remote_anywhere": remote_anywhere_on(p),
        "materials": db.query(Material).filter(Material.user_id == user.id).all(),
        "state": completeness(db, user),
        "objective_target": OBJECTIVE_TARGET, "about_target": ABOUT_TARGET,
        "objective_depth": text_depth(p.objective or "", OBJECTIVE_TARGET),
        "about_depth": text_depth(p.about_me or "", ABOUT_TARGET),
        "depth_labels": DEPTH_LABELS,
        "values": {},
    }
    ctx.update(extra)
    return templates.TemplateResponse(request, f"onboarding/{step}.html", ctx)


@router.get("", response_class=HTMLResponse)
def start(request: Request, user: User = Depends(require_user),
          db: DbSession = Depends(get_session)):
    return RedirectResponse("/onboarding/upload", status_code=303)


@router.get("/{step}", response_class=HTMLResponse)
def show_step(step: str, request: Request, user: User = Depends(require_user),
              db: DbSession = Depends(get_session)):
    if step not in STEP_IDS:
        return RedirectResponse("/onboarding/upload", status_code=303)
    return _render(request, step, db, user)


# Where an upload/delete returns to. An allow-list, so `return_to` from a form
# can never become an open redirect. Fixes the bug where uploading from Profile
# dumped the user back into onboarding step one (R6).
RETURN_TO = {"upload": "/onboarding/upload", "profile": "/profile#documents"}


def _return_error(request, db, user, step, return_to, error):
    if return_to == "profile":
        from .profile import profile_page   # lazy: profile imports from us
        return profile_page(request, user=user, db=db, error=error)
    return _render(request, step, db, user, error=error)


# ----------------------------- uploads (step 1) ---------------------------- #
@router.post("/upload")
async def upload(
    request: Request,
    kind: str = Form(...),
    step: str = Form(default="upload"),
    return_to: str = Form(default="upload"),
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: DbSession = Depends(get_session),
):
    dest = RETURN_TO.get(return_to, "/onboarding/upload")
    if kind not in ("cv", "cover_letter", "linkedin"):
        return RedirectResponse(dest, status_code=303)

    raw = await file.read()
    try:
        ext, mime = validate_upload(file.filename or "", raw)
    except UploadError as exc:
        return _return_error(request, db, user, step, return_to, str(exc))

    text = extract_text(ext, raw)
    if not text.strip():
        return _return_error(request, db, user, step, return_to,
                             "We couldn't read any text in that file. "
                             "If it's a scan, upload a text-based version.")

    db.add(Material(
        user_id=user.id, kind=kind, filename=(file.filename or "upload")[:255],
        mime=mime, size_bytes=len(raw),
        ciphertext=encrypt_bytes(raw),   # never stored in plaintext
        text=text[:200_000],
    ))
    db.commit()
    return RedirectResponse(dest, status_code=303)


@router.post("/material/{material_id}/delete")
def delete_material(material_id: int, request: Request,
                    step: str = Form(default="upload"),
                    return_to: str = Form(default="upload"),
                    user: User = Depends(require_user),
                    db: DbSession = Depends(get_session)):
    (db.query(Material)
       .filter(Material.id == material_id, Material.user_id == user.id)  # ownership
       .delete())
    db.commit()
    # The delete control swaps just its own row out (R5.2); reply empty for HTMX.
    if request.headers.get("HX-Request") == "true":
        return HTMLResponse("")
    return RedirectResponse(RETURN_TO.get(return_to, "/onboarding/upload"), status_code=303)


# --------------------------- where & how (step 2) -------------------------- #
@router.post("/save/aim")
async def save_aim(request: Request, user: User = Depends(require_user),
                   db: DbSession = Depends(get_session)):
    """Work mode, seniority, sectors, company type, job type. Countries are
    owned by the token field and already saved; we just rebuild the engine
    location tokens from the (possibly new) work modes."""
    form = await request.form()
    p = _profile(db, user)
    p.work_modes = [v for v in form.getlist("work_mode") if v in WORK_MODES]
    p.seniority = [v for v in form.getlist("seniority") if v in SENIORITY]
    p.company_type = [v for v in form.getlist("company_type") if v in COMPANY_TYPES]
    p.verticals = [v for v in form.getlist("verticals") if v in VERTICALS]
    p.job_type = [v for v in form.getlist("job_type") if v in JOB_TYPES]
    rebuild_locations(p)
    db.commit()
    return RedirectResponse("/onboarding/words", status_code=303)


# --------------------------- in your words (step 3) ------------------------ #
@router.post("/save/words")
async def save_words(
    request: Request,
    user: User = Depends(require_user),
    db: DbSession = Depends(get_session),
    objective: str = Form(default=""),
    about_me: str = Form(default=""),
):
    p = _profile(db, user)
    values = {"objective": objective, "about_me": about_me}
    if text_too_short(objective):
        return _render(request, "words", db, user, values=values,
                       error=f"What you're looking for needs at least {MIN_TEXT} characters.")
    if text_too_short(about_me):
        return _render(request, "words", db, user, values=values,
                       error=f"A bit about you needs at least {MIN_TEXT} characters.")
    p.objective = objective.strip()[:10_000]
    p.about_me = about_me.strip()[:20_000]
    db.commit()
    return RedirectResponse("/matches", status_code=303)
