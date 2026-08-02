"""Alpha-testing feedback: a top-of-page banner CTA leads here, to a short
whole-product survey (four 1-5 ratings + open comments). Works logged-in or not,
so a friend can leave feedback without signing up. Stored as SiteFeedback and
read back on the operator dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import current_user
from ..db import get_session
from ..models import SITE_FEEDBACK_QUESTIONS, SiteFeedback, User
from ..templating import templates

router = APIRouter()

_MAX = 4000  # generous cap per open box


def _clamp(value: str) -> int | None:
    """A 1-5 rating, or None when the tester left the question blank."""
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return None


@router.get("/feedback", response_class=HTMLResponse)
def feedback_form(request: Request, sent: str = "", from_: str = "",
                  user: User | None = Depends(current_user)):
    # `from` is a reserved word; read it off the query params directly.
    origin = request.query_params.get("from", "")
    return templates.TemplateResponse(request, "alpha_feedback.html", {
        "request": request, "user": user, "sent": bool(sent),
        "questions": SITE_FEEDBACK_QUESTIONS, "origin": origin,
    })


@router.post("/feedback")
def feedback_submit(
    request: Request,
    q_useful: str = Form(""), q_easy: str = Form(""),
    q_look: str = Form(""), q_pay: str = Form(""),
    likes: str = Form(""), dislikes: str = Form(""),
    broken: str = Form(""), other: str = Form(""),
    path: str = Form(""),
    user: User | None = Depends(current_user),
    db: DbSession = Depends(get_session),
):
    fb = SiteFeedback(
        user_id=user.id if user else None,
        q_useful=_clamp(q_useful), q_easy=_clamp(q_easy),
        q_look=_clamp(q_look), q_pay=_clamp(q_pay),
        likes=likes[:_MAX], dislikes=dislikes[:_MAX],
        broken=broken[:_MAX], other=other[:_MAX],
        path=(path or "")[:255],
    )
    db.add(fb)
    db.commit()
    return RedirectResponse("/feedback?sent=1", status_code=303)
