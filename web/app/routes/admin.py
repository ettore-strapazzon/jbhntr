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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from ..config import config
from ..db import get_session
from ..models import (
    SITE_FEEDBACK_QUESTIONS, Company, CorpusStat, Document, Feedback, Job,
    JobResult, PageView, ProductEvent, Search, SiteFeedback, User, aware, utcnow,
)
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


def _chart(day_counts: dict, days: int = 30) -> dict:
    """Turn {date: count} into a bar-chart spec for the last `days` days, oldest
    first and zero-filled, with each bar's height as a percentage of the peak."""
    today = utcnow().date()
    order = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    vals = [int(day_counts.get(d, 0)) for d in order]
    peak = max(vals) if vals else 0
    bars = [{"label": d.strftime("%d %b"), "v": v,
             "pct": round(v / peak * 100) if peak else 0}
            for d, v in zip(order, vals)]
    return {"bars": bars, "peak": peak, "total": sum(vals), "days": days}


def _bucket_by_day(rows, value_attr=None):
    """{date: count-or-summed-value} keyed by each row's created_at date. With
    `value_attr` it sums that attribute (e.g. 'added'); otherwise counts rows."""
    out: dict = {}
    for r in rows:
        ts = aware(r.created_at)
        if not ts:
            continue
        d = ts.date()
        out[d] = out.get(d, 0) + (getattr(r, value_attr) if value_attr else 1)
    return out


def _gather(db: DbSession) -> dict:
    now = utcnow()

    # --- growth over time (daily bar charts) ---
    signup_rows = db.query(User).filter(User.created_at >= aware(_since(30))).all()
    signups_chart = _chart(_bucket_by_day(signup_rows))
    stat_rows = db.query(CorpusStat).filter(CorpusStat.created_at >= aware(_since(30))).all()
    jobs_added_chart = _chart(_bucket_by_day(stat_rows, "added"))

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

    # --- pageviews + unique visitors (privacy-safe: no IP, no user link) ---
    pv_7d = db.query(PageView).filter(PageView.created_at >= _since(7)).count()
    pv_30d = db.query(PageView).filter(PageView.created_at >= _since(30)).count()

    _has_visitor = PageView.visitor.isnot(None) & (PageView.visitor != "")
    uv_7d = db.query(func.count(func.distinct(PageView.visitor))).filter(
        PageView.created_at >= _since(7), _has_visitor).scalar() or 0
    uv_30d = db.query(func.count(func.distinct(PageView.visitor))).filter(
        PageView.created_at >= _since(30), _has_visitor).scalar() or 0

    # distinct visitors per country (30d) — the "who, by country" view
    uv = func.count(func.distinct(PageView.visitor))
    visitors_by_country = (db.query(PageView.country, uv.label("n"))
                           .filter(PageView.created_at >= _since(30), _has_visitor)
                           .group_by(PageView.country).order_by(uv.desc())
                           .limit(12).all())

    top_paths = (db.query(PageView.path, func.count(PageView.id).label("n"))
                 .filter(PageView.created_at >= _since(30))
                 .group_by(PageView.path).order_by(func.count(PageView.id).desc())
                 .limit(12).all())

    # --- every user, newest first, with their search count (for the audit links).
    # No email here: the audit flow is pseudonymous, users are referenced by number.
    counts = dict(db.query(Search.user_id, func.count(Search.id))
                  .group_by(Search.user_id).all())
    users = [
        {"id": u.id, "plan": u.plan,
         "created_at": u.created_at, "searches": counts.get(u.id, 0)}
        for u in db.query(User).order_by(User.created_at.desc()).limit(200).all()
    ]

    # --- alpha feedback (SiteFeedback): averages + the latest submissions ---
    fb_q = db.query(SiteFeedback)
    fb_count = fb_q.count()
    fb_avgs = []
    for name, label in SITE_FEEDBACK_QUESTIONS:
        col = getattr(SiteFeedback, name)
        avg = db.query(func.avg(col)).filter(col.isnot(None)).scalar()
        n = db.query(func.count(col)).filter(col.isnot(None)).scalar() or 0
        fb_avgs.append({"label": label, "avg": round(avg, 2) if avg is not None else None, "n": n})
    recent_fb = []
    rows = (db.query(SiteFeedback).order_by(SiteFeedback.created_at.desc())
            .limit(50).all())
    for fb in rows:
        # Pseudonymous author label — a user number, never the email.
        who = f"User #{fb.user_id}" if fb.user_id else "anonymous"
        recent_fb.append({
            "who": who, "created_at": fb.created_at, "path": fb.path,
            "ratings": [(label, getattr(fb, name)) for name, label in SITE_FEEDBACK_QUESTIONS],
            "likes": fb.likes, "dislikes": fb.dislikes,
            "broken": fb.broken, "other": fb.other,
        })

    # --- product events (PROOF-003): the activation funnel ---
    ev = dict(db.query(ProductEvent.name, func.count(ProductEvent.id))
              .filter(ProductEvent.created_at >= _since(30))
              .group_by(ProductEvent.name).all())
    funnel = [(label, ev.get(name, 0)) for name, label in (
        ("signup_completed", "Signed up"),
        ("cv_uploaded", "Uploaded a CV"),
        ("onboarding_completed", "Finished onboarding"),
        ("scan_started", "Started a scan"),
        ("scan_completed", "Completed a scan"),
        ("first_shortlist_viewed", "Viewed first shortlist"),
        ("match_rated", "Rated a match"),
        ("job_saved", "Saved a role"),
        ("job_marked_applied", "Marked applied"),
        ("job_dismissed", "Dismissed a role"),
        ("document_generated", "Generated a draft"),
        ("premium_waitlist_joined", "Joined the waitlist"),
    )]

    # --- corpus health: size, freshness, coverage, top sources, daily churn ---
    corpus_total = db.query(Job).count()
    fresh_1d = db.query(Job).filter(Job.last_seen_at >= aware(_since(1))).count()
    fresh_7d = db.query(Job).filter(Job.last_seen_at >= aware(_since(7))).count()
    fresh_30d = db.query(Job).filter(Job.last_seen_at >= aware(_since(30))).count()
    stale_45d = db.query(Job).filter(Job.last_seen_at < aware(_since(45))).count()
    embedded_n = db.query(Job).filter(Job.embedding.isnot(None)).count()
    unchecked_n = db.query(Job).filter(Job.last_checked_at.is_(None)).count()
    remote_mix = dict(db.query(Job.remote_mode, func.count(Job.id))
                      .group_by(Job.remote_mode).all())
    top_sources = (db.query(Job.source, func.count(Job.id).label("n"))
                   .group_by(Job.source).order_by(func.count(Job.id).desc())
                   .limit(20).all())
    corpus_daily = (db.query(CorpusStat)
                    .order_by(CorpusStat.created_at.desc()).limit(14).all())

    # Discovery / custom-scrape footprint (the new premium-sourced companies).
    scraped_jobs = db.query(Job).filter(Job.source.like("scrape:%")).count()
    companies_total = db.query(Company).count()
    companies_custom = db.query(Company).filter(Company.ats == "custom").count()
    companies_polled = (db.query(Company)
                        .filter(Company.last_polled_at >= aware(_since(2))).count())

    return {
        "now": now,
        "funnel": funnel,
        "signups_chart": signups_chart, "jobs_added_chart": jobs_added_chart,
        "corpus_total": corpus_total, "fresh_1d": fresh_1d, "fresh_7d": fresh_7d,
        "fresh_30d": fresh_30d, "stale_45d": stale_45d, "embedded_n": embedded_n,
        "unchecked_n": unchecked_n, "remote_mix": remote_mix,
        "top_sources": top_sources, "corpus_daily": corpus_daily,
        "scraped_jobs": scraped_jobs, "companies_total": companies_total,
        "companies_custom": companies_custom, "companies_polled": companies_polled,
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
        "uv_7d": uv_7d, "uv_30d": uv_30d,
        "visitors_by_country": visitors_by_country, "top_paths": top_paths,
        "users": users,
        "fb_count": fb_count, "fb_avgs": fb_avgs, "recent_fb": recent_fb,
    }


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, _: bool = Depends(require_admin),
                    db: DbSession = Depends(get_session), reset_msg: str = ""):
    ctx = _gather(db)
    return templates.TemplateResponse(request, "admin.html",
        {"request": request, "reset_msg": reset_msg, **ctx})


@router.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_user(user_id: int, request: Request, _: bool = Depends(require_admin),
               db: DbSession = Depends(get_session)):
    """Backend double-check: one user's profile / search preferences and, for each
    search, the results with score, two-way fit, and why-it-fits / why-it-doesn't.
    Operator-only (behind the admin gate); it necessarily shows the user's own CV
    and profile so matching can be evaluated."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404)

    # Ratings this user gave their own matches, so we can show agreement/disagreement.
    ratings = dict(db.query(Feedback.job_result_id, Feedback.rating)
                   .filter(Feedback.user_id == user_id,
                           Feedback.rating.isnot(None)).all())

    # Searches newest-first, each with its results ordered best-first.
    searches = sorted(user.searches, key=lambda s: s.started_at or utcnow(), reverse=True)
    runs = []
    for s in searches:
        results = sorted(s.results, key=lambda r: (r.tier, -r.score))
        runs.append({"search": s, "results": results})

    # Privacy: this view is for checking match quality, so it never renders the
    # user's CV/cover-letter text, their filenames, their about-me prose, or their
    # email. Materials are reduced to counts by kind (was a CV present at all?).
    from collections import Counter
    mat_counts = Counter(m.kind for m in user.materials)

    return templates.TemplateResponse(request, "admin_user.html", {
        "request": request, "u": user, "profile": user.profile,
        "materials_summary": dict(mat_counts), "materials_total": sum(mat_counts.values()),
        "seeds": [s.value for s in user.seeds],
        "runs": runs, "ratings": ratings,
    })


@router.post("/admin/reset-usage")
def admin_reset_usage(_: bool = Depends(require_admin), email: str = Form(...)):
    """Operator action: reset a user's free searches + CV/CL allowance."""
    from ..services.reset_usage import reset
    from urllib.parse import quote
    msg = reset(email)
    return RedirectResponse(f"/admin?reset_msg={quote(msg)}", status_code=303)


@router.post("/admin/set-plan")
def admin_set_plan(_: bool = Depends(require_admin), email: str = Form(...),
                   plan: str = Form(...), db: DbSession = Depends(get_session)):
    """Operator action: put an account on Premium (or back on Free) — used while
    payments are disabled to grant testers access."""
    from urllib.parse import quote
    plan = plan if plan in ("free", "premium") else "free"
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user:
        msg = f"No account for {email}."
    else:
        user.plan = plan
        user.premium_until = None   # no expiry while payments are off
        db.commit()
        msg = f"{user.email} is now {plan}."
    return RedirectResponse(f"/admin?reset_msg={quote(msg)}", status_code=303)


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
