"""Terms, Privacy and Cookies pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..templating import templates

router = APIRouter()


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse(request, "legal/terms.html", {"request": request})


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse(request, "legal/privacy.html", {"request": request})


@router.get("/cookies", response_class=HTMLResponse)
def cookies(request: Request):
    return templates.TemplateResponse(request, "legal/cookies.html", {"request": request})
