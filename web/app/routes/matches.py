"""The Matches surface (§11.5) — home for a logged-in user. Accumulates results
across runs, lets them be filtered and triaged, and hosts the run button."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
from ..db import get_session
from ..models import Document, Feedback, JobResult, Search, User
from ..services import doc_quota, matches_service
from ..services.job_state import DISMISS_REASONS
from ..services.profile_service import completeness, strength
from ..templating import templates

router = APIRouter()


def _latest_any(db: DbSession, user: User) -> Search | None:
    return (db.query(Search).filter(Search.user_id == user.id)
              .order_by(Search.started_at.desc()).first())


def _matches_context(request: Request, user: User, db: DbSession, *,
                     error="", run=0, source="", sort="best", saved="",
                     tier=None) -> dict:
    """Shared context for the page and the results partial, so they never drift."""
    tier = tier or []
    m = matches_service.build(
        db, user, run_id=run or None, tiers=set(tier) or None,
        source=source, sort=sort, saved_only=bool(saved))
    latest_any = _latest_any(db, user)
    running = latest_any if (latest_any and latest_any.status in ("queued", "running")) else None
    voted = {f.job_result_id: f for f in db.query(Feedback).filter(Feedback.user_id == user.id)}
    docs = {(d.job_result_id, d.kind) for d in db.query(Document).filter(Document.user_id == user.id)}
    return {
        "request": request, "user": user, "config": config,
        "m": m, "state": completeness(db, user), "strength": strength(db, user),
        "running": running,
        "last_failed": latest_any if (latest_any and latest_any.status == "failed") else None,
        "voted": voted, "docs": docs, "dismiss_reasons": DISMISS_REASONS,
        "searches_left": user.searches_remaining(config.free_searches),
        "allow": doc_quota.allowance(db, user),
        "f_tier": set(tier), "f_source": source, "f_sort": sort,
        "f_saved": bool(saved), "f_run": run, "error": error,
    }


@router.get("/matches", response_class=HTMLResponse)
def matches_page(request: Request, user: User = Depends(require_user),
                 db: DbSession = Depends(get_session),
                 error: str = "", run: int = 0, source: str = "",
                 sort: str = "best", saved: str = "",
                 tier: list[int] = Query(default=[])):
    ctx = _matches_context(request, user, db, error=error, run=run, source=source,
                           sort=sort, saved=saved, tier=tier)
    return templates.TemplateResponse(request, "matches.html", ctx)


@router.get("/matches/results", response_class=HTMLResponse)
def matches_results(request: Request, user: User = Depends(require_user),
                    db: DbSession = Depends(get_session),
                    run: int = 0, source: str = "", sort: str = "best",
                    saved: str = "", tier: list[int] = Query(default=[])):
    """The list alone, re-rendered by the live filter bar (R7/R16)."""
    ctx = _matches_context(request, user, db, run=run, source=source,
                           sort=sort, saved=saved, tier=tier)
    return templates.TemplateResponse(request, "partials/results.html", ctx)
