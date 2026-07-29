"""Terms, Privacy and Cookies pages — public and indexable (SEO-007)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import seo
from ..templating import templates

router = APIRouter()


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    ctx = {"request": request, **seo.public_seo(
        title="Terms of Service | JBHNTR",
        description=("Read the terms for using JBHNTR, including account, "
                     "free-use, AI-output and job-listing limitations."),
        path="/terms", og_title="Terms of Service")}
    return templates.TemplateResponse(request, "legal/terms.html", ctx)


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    ctx = {"request": request, **seo.public_seo(
        title="Privacy Policy | JBHNTR",
        description=("Read how JBHNTR processes CVs, profile data, job-search "
                     "activity, analytics and international AI-provider transfers."),
        path="/privacy", og_title="Privacy Policy")}
    return templates.TemplateResponse(request, "legal/privacy.html", ctx)


@router.get("/cookies", response_class=HTMLResponse)
def cookies(request: Request):
    ctx = {"request": request, **seo.public_seo(
        title="Cookie Notice | JBHNTR",
        description=("JBHNTR uses one essential session cookie and cookieless "
                     "analytics. See what is stored and why."),
        path="/cookies", og_title="Cookie Notice")}
    return templates.TemplateResponse(request, "legal/cookies.html", ctx)
