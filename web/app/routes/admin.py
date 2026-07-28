"""Operator dashboard at /admin.

One read-only page for the person running JBHNTR: waiting list, search volume,
feedback ratings, document counts, and privacy-safe pageview rollups. Everything
here is aggregate SELECTs — no writes, no per-user PII beyond the email the user
gave us and the waiting-list they opted into.

Gate: HTTP Basic auth against config.admin_token (any username). If the token is
unset the whole surface 404s, so it is never accidentally open in a fresh deploy.
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from ..config import config
from ..db import get_session
from ..models import Document, Feedback, PageView, Search, User, utcnow
from ..templating import templates

router = APIRouter()
_basic = HTTPBasic(auto_error=False)


def require_admin(credentials: HTTPBasicCredentials | None = Depends(_basic)) -> bool:
    """Basic-auth gate. Unset token => 404 (feature off). Bad token => 401 prompt."""
    if not config.admin_token:
        raise HTTPException(status_code=404)
    ok = credentials is not None and secrets.compare_digest(
        credentials.password, config.admin_token)
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": 'Basic realm="JBHNTR admin"'})
    return True


def _since(days: int):
    return utcnow() - timedelta(days=days)


def _gather(db: DbSession) -> dict:
    now = utcnow()

    # --- people ---
    total_users = db.query(User).count()
    google_users = db.query(User).filter(User.google_sub.isnot(None)).count()
    premium_users = db.query(User).filter(User.plan == "premium").count()

    # --- waiting list (the important one): every opted-in user + when ---
    waitlist = (db.query(User.email, User.premium_requested_at)
                .filter(User.premium_requested_at.isnot(None))
                .order_by(User.premium_requested_at.desc()).all())

    # --- searches ---
    total_searches = db.query(Search).count()
    searches_7d = db.query(Search).filter(Search.started_at >= _since(7)).count()
    searches_30d = db.query(Search).filter(Search.started_at >= _since(30)).count()
    status_counts = dict(db.query(Search.status, func.count(Search.id))
                         .group_by(Search.status).all())

    # per-user search volume (top 50)
    per_user = (db.query(User.email, func.count(Search.id).label("n"),
                         func.max(Search.started_at).label("last"))
                .join(Search, Search.user_id == User.id)
                .group_by(User.id).order_by(func.count(Search.id).desc())
                .limit(50).all())

    # average completed-search duration, computed in Python (DB-portable)
    done = (db.query(Search.started_at, Search.finished_at)
            .filter(Search.status == "done", Search.finished_at.isnot(None)).all())
    durations = [(f - s).total_seconds() for s, f in done if s and f]
    avg_search_secs = round(sum(durations) / len(durations)) if durations else None

    # --- feedback ratings ---
    rated = db.query(Feedback).filter(Feedback.rating.isnot(None))
    ratings_count = rated.count()
    avg_rating = db.query(func.avg(Feedback.rating)).filter(
        Feedback.rating.isnot(None)).scalar()
    dist = dict(db.query(Feedback.rating, func.count(Feedback.id))
                .filter(Feedback.rating.isnot(None))
                .group_by(Feedback.rating).all())
    rating_dist = [(i, dist.get(i, 0)) for i in range(5, 0, -1)]

    # --- documents ---
    doc_counts = dict(db.query(Document.kind, func.count(Document.id))
                      .group_by(Document.kind).all())

    # --- pageviews (privacy-safe: no IP, no user link) ---
    pv_7d = db.query(PageView).filter(PageView.created_at >= _since(7)).count()
    pv_30d = db.query(PageView).filter(PageView.created_at >= _since(30)).count()
    top_countries = (db.query(PageView.country, func.count(PageView.id).label("n"))
                     .filter(PageView.created_at >= _since(30))
                     .group_by(PageView.country).order_by(func.count(PageView.id).desc())
                     .limit(12).all())
    top_paths = (db.query(PageView.path, func.count(PageView.id).label("n"))
                 .filter(PageView.created_at >= _since(30))
                 .group_by(PageView.path).order_by(func.count(PageView.id).desc())
                 .limit(12).all())

    return {
        "now": now,
        "total_users": total_users, "google_users": google_users,
        "premium_users": premium_users, "waitlist": waitlist,
        "total_searches": total_searches, "searches_7d": searches_7d,
        "searches_30d": searches_30d, "status_counts": status_counts,
        "per_user": per_user, "avg_search_secs": avg_search_secs,
        "ratings_count": ratings_count,
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
        "rating_dist": rating_dist,
        "cv_count": doc_counts.get("cv", 0), "cl_count": doc_counts.get("cl", 0),
        "pv_7d": pv_7d, "pv_30d": pv_30d,
        "top_countries": top_countries, "top_paths": top_paths,
    }


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, _: bool = Depends(require_admin),
                    db: DbSession = Depends(get_session)):
    ctx = _gather(db)
    return templates.TemplateResponse(request, "admin.html", {"request": request, **ctx})


@router.get("/admin/waitlist.csv")
def waitlist_csv(_: bool = Depends(require_admin),
                 db: DbSession = Depends(get_session)):
    rows = (db.query(User.email, User.premium_requested_at)
            .filter(User.premium_requested_at.isnot(None))
            .order_by(User.premium_requested_at.desc()).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "requested_at"])
    for email, when in rows:
        w.writerow([email, when.isoformat() if when else ""])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="waitlist.csv"'})
