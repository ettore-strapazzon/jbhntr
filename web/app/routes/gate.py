"""R3-14 gate prompt endpoints (rendered on /matches; rules in services/gate.py).

  POST /gate           answer=much_better|better|same|worse, csrf=...
                       -> 303 /matches (no-JS form) or the thank-you fragment
                       (HTMX). 400 unknown answer, 409 never asked / already
                       answered, 403 bad CSRF, 303 /login when logged out.
  POST /gate/dismiss   "Not now" -> 303 /matches or an empty fragment (HTMX).

CSRF: the login cookie is SameSite=lax (the app-wide defence) AND these POSTs
carry the per-session HMAC token from security.csrf_token, checked here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session as DbSession

from ..auth import COOKIE, require_user
from ..db import get_session
from ..models import User
from ..security import csrf_ok
from ..services import gate
from ..templating import templates

router = APIRouter()


def _htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _csrf_valid(request: Request, submitted: str) -> bool:
    return csrf_ok(request.cookies.get(COOKIE) or "", submitted or "")


@router.post("/gate")
def gate_answer(request: Request, answer: str = Form(""), csrf: str = Form(""),
                user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    if not _csrf_valid(request, csrf):
        return Response("Your session expired. Reload the page and try again.",
                        status_code=403, media_type="text/plain")
    try:
        gate.answer(db, user.id, answer)
    except gate.GateError as e:
        return Response(str(e), status_code=e.status, media_type="text/plain")
    if _htmx(request):
        return templates.TemplateResponse(
            request, "partials/gate_prompt.html", {"gate_done": True})
    return RedirectResponse("/matches", status_code=303)


@router.post("/gate/dismiss")
def gate_dismiss(request: Request, csrf: str = Form(""),
                 user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    if not _csrf_valid(request, csrf):
        return Response("Your session expired. Reload the page and try again.",
                        status_code=403, media_type="text/plain")
    try:
        gate.dismiss(db, user.id)
    except gate.GateError as e:
        return Response(str(e), status_code=e.status, media_type="text/plain")
    if _htmx(request):
        return HTMLResponse("")
    return RedirectResponse("/matches", status_code=303)
