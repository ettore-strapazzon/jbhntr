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
import logging
import secrets
import threading
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
log = logging.getLogger("jbhntr.admin")


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


def _fmt(n: float) -> str:
    n = int(round(n))
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1e3:.1f}k".replace(".0k", "k")
    return str(n)


def _dual_line_svg(dates, left, right, left_label, right_label,
                   left_color="#174b3e", right_color="#c08a2e") -> str:
    """A dual-axis daily line chart as inline SVG (CSP-safe: no JS/chart libs).

    `dates` are short x labels; `left`/`right` are the two daily series, plotted
    against independent Y axes (left labels + right labels) so a small metric and
    a large one can share the same time axis."""
    W, H, ml, mr, mt, mb = 700, 260, 48, 56, 26, 34
    iw, ih = W - ml - mr, H - mt - mb
    n = max(1, len(dates))
    xs = [ml + (iw * i / (n - 1) if n > 1 else iw / 2) for i in range(n)]
    lmax = max(left) or 1
    rmax = max(right) or 1
    ly = lambda v: mt + ih - (v / lmax) * ih
    ry = lambda v: mt + ih - (v / rmax) * ih

    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px;'
         f'font:11px system-ui,sans-serif" xmlns="http://www.w3.org/2000/svg">']
    # gridlines + both Y axes' tick values
    for f in (0, 0.25, 0.5, 0.75, 1):
        y = mt + ih - f * ih
        p.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{ml + iw}" y2="{y:.0f}" stroke="#e5e2dc"/>')
        p.append(f'<text x="{ml - 6}" y="{y + 3:.0f}" text-anchor="end" '
                 f'fill="{left_color}">{_fmt(lmax * f)}</text>')
        p.append(f'<text x="{ml + iw + 6}" y="{y + 3:.0f}" text-anchor="start" '
                 f'fill="{right_color}">{_fmt(rmax * f)}</text>')
    # x-axis date ticks (~6)
    step = max(1, (n - 1) // 6) if n > 1 else 1
    for i in range(0, n, step):
        p.append(f'<text x="{xs[i]:.0f}" y="{H - 14}" text-anchor="middle" '
                 f'fill="#5e5b55">{dates[i]}</text>')
    # the two series
    lp = " ".join(f"{xs[i]:.1f},{ly(left[i]):.1f}" for i in range(n))
    rp = " ".join(f"{xs[i]:.1f},{ry(right[i]):.1f}" for i in range(n))
    p.append(f'<polyline points="{lp}" fill="none" stroke="{left_color}" stroke-width="2"/>')
    p.append(f'<polyline points="{rp}" fill="none" stroke="{right_color}" stroke-width="2"/>')
    # legend
    p.append(f'<rect x="{ml}" y="6" width="11" height="11" rx="2" fill="{left_color}"/>')
    p.append(f'<text x="{ml + 16}" y="15" fill="#1c1b19">{left_label} (left)</text>')
    lx = ml + 16 + int(len(left_label) * 6.2) + 46
    p.append(f'<rect x="{lx}" y="6" width="11" height="11" rx="2" fill="{right_color}"/>')
    p.append(f'<text x="{lx + 16}" y="15" fill="#1c1b19">{right_label} (right)</text>')
    p.append("</svg>")
    return "".join(p)


def _gather(db: DbSession) -> dict:
    now = utcnow()

    # --- growth over time: unique visitors/day + jobs-added/day (dual-axis line) ---
    order = [now.date() - timedelta(days=i) for i in range(29, -1, -1)]
    vday = func.date(PageView.created_at)
    vrows = (db.query(vday, func.count(func.distinct(PageView.visitor)))
             .filter(PageView.created_at >= aware(_since(30)),
                     PageView.visitor.isnot(None), PageView.visitor != "")
             .group_by(vday).all())
    vmap = {str(d)[:10]: int(c or 0) for d, c in vrows}
    jday = func.date(CorpusStat.created_at)
    jrows = (db.query(jday, func.sum(CorpusStat.added))
             .filter(CorpusStat.created_at >= aware(_since(30))).group_by(jday).all())
    jmap = {str(d)[:10]: int(c or 0) for d, c in jrows}
    growth_svg = _dual_line_svg(
        [d.strftime("%d %b") for d in order],
        [vmap.get(d.isoformat(), 0) for d in order],
        [jmap.get(d.isoformat(), 0) for d in order],
        "Unique visitors", "Jobs added")

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
        "growth_svg": growth_svg,
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


@router.post("/admin/run-maintenance")
def admin_run_maintenance(_: bool = Depends(require_admin)):
    """Operator: run the reaper now and record a corpus snapshot in the background,
    so the churn/growth charts get a data point without waiting for the nightly
    cron. Bounded (the reaper caps its own work)."""
    from urllib.parse import quote

    from ..services.cron import _record_corpus_stat
    from ..services.reaper import run as reaper_run

    def _work():
        try:
            res = reaper_run()
            _record_corpus_stat({"reaper": res})
            log.info("manual maintenance: %s", res)
        except Exception:
            log.exception("manual maintenance failed")

    threading.Thread(target=_work, daemon=True).start()
    msg = "Maintenance started (reaper + corpus snapshot). Refresh in a minute."
    return RedirectResponse(f"/admin?reset_msg={quote(msg)}", status_code=303)


@router.post("/admin/deep-clean")
def admin_deep_clean(_: bool = Depends(require_admin)):
    """Operator: link-check EVERY due job now (not just the nightly 5k) and record
    a snapshot, to clear out accumulated dead/404 links in one pass. Slow — runs
    in the background."""
    from urllib.parse import quote

    from ..services.cron import _record_corpus_stat
    from ..services.reaper import run as reaper_run

    def _work():
        try:
            res = reaper_run(check_limit=0)      # 0 = check all due jobs
            _record_corpus_stat({"reaper": res})
            log.info("deep clean: %s", res)
        except Exception:
            log.exception("deep clean failed")

    threading.Thread(target=_work, daemon=True).start()
    msg = ("Deep clean started: checking every stored link (this can take a while). "
           "Refresh the churn table in a few minutes.")
    return RedirectResponse(f"/admin?reset_msg={quote(msg)}", status_code=303)


@router.post("/admin/run-discovery")
def admin_run_discovery(_: bool = Depends(require_admin)):
    """Operator: run similar-company discovery + custom careers-page scraping now,
    instead of waiting for the weekly cron. Premium users with seed companies get
    processed; the companies found feed everyone's corpus. Needs an LLM key on this
    service. Slow — runs in the background."""
    from urllib.parse import quote

    from jobhunter.config import Settings
    from ..db import SessionLocal
    from ..services.companies_service import (
        discover_all_active, scrape_custom_companies,
    )

    def _work():
        db = SessionLocal()
        try:
            found = discover_all_active(db, force=True)
            scraped = scrape_custom_companies(db, Settings.from_env())
            log.info("manual discovery: %s | scrape: %s", found, scraped)
        except Exception:
            log.exception("manual discovery failed")
        finally:
            db.close()

    threading.Thread(target=_work, daemon=True).start()
    msg = ("Discovery + scraping started (premium users with seed companies). "
           "Needs an LLM key on this service. Refresh the corpus panel in a few minutes.")
    return RedirectResponse(f"/admin?reset_msg={quote(msg)}", status_code=303)


@router.post("/admin/clear-board")
def admin_clear_board(_: bool = Depends(require_admin), email: str = Form(...),
                      db: DbSession = Depends(get_session)):
    """Operator: wipe a user's stored search results so their board starts empty
    and the next search shows only fresh, verified matches. Saved/applied state
    (JobState) is kept."""
    from urllib.parse import quote

    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user:
        msg = f"No account for {email}."
    else:
        r = db.query(JobResult).filter(JobResult.user_id == user.id).delete(
            synchronize_session=False)
        s = db.query(Search).filter(Search.user_id == user.id).delete(
            synchronize_session=False)
        db.commit()
        msg = (f"Cleared {user.email}: {r} results across {s} searches removed. "
               f"Their board is empty; the next search shows only fresh matches.")
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
