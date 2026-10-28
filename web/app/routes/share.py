"""Shareable match card (R3-01) — the atomic shared artefact.

Three routes:
  POST /job/{id}/share     owner-only; lazily mints JobResult.share_token, stores
                           the show-employer / show-name opt-ins, emits
                           match_card_shared, returns the HTMX share sheet.
  GET  /m/{token}          public, no-auth card page (verdict + two fit scores +
                           fits/watch-out + role, employer iff opted in, always
                           anonymous — no name source exists yet); CTA carries the
                           sharer's referral code.
  GET  /m/{token}/card.png public OG image — a brand SVG card rasterised once by
                           cairosvg and cached to /static/og/, falling back to the
                           static default PNG if rasterising is unavailable.

The card never exposes apply_url, the job description, the company blurb or any
CV/email text (ARTEFACTS_SPEC §1.2).
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import ROOT, config
from ..db import SessionLocal, get_session
from ..models import JobResult, User
from ..seo import absolute_url
from ..services import referral
from ..services.events import record
from ..templating import templates

log = logging.getLogger("jbhntr.share")
router = APIRouter()

_OG_DIR = ROOT / "web" / "app" / "static" / "og"


def verdict_of(fit_role: int, fit_candidate: int) -> tuple[str | None, str]:
    """The two-way verdict, identical to job_card.html §0 — shown only when both
    fit dimensions exist so it never contradicts a one-sided score."""
    fr, fc = fit_role or 0, fit_candidate or 0
    if fr and fc:
        if fr >= 65 and fc >= 65:
            return "Apply now", "now"
        if fr >= 65:
            return "Worth a stretch", "stretch"
        if fc >= 65:
            return "Watch out", "watch"
    return None, ""


def _caption(url: str) -> str:
    """A copy-ready, honest share caption (GC clears external claim copy — see
    ARTEFACTS_SPEC §6 REQUEST). Plural/testing voice per CHARTER."""
    return ("A tool I'm testing scans every live role and scores each one both "
            "ways — how it fits what I want and how I fit what they ask. One of "
            f"my matches: {url}")


@router.post("/job/{result_id}/share", response_class=HTMLResponse)
def share(result_id: int, request: Request,
          source: str = Form("matches"),
          prefs: str = Form(None), show_company: str = Form(None),
          user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    r = db.get(JobResult, result_id)
    if not r or r.user_id != user.id:
        return HTMLResponse("", status_code=404)

    if not r.share_token:                       # lazy, idempotent mint
        r.share_token = secrets.token_urlsafe(9)
    # The sheet's toggle form re-submits with prefs=1; an unchecked checkbox
    # sends nothing, so presence of the field is the value. The initial Share
    # click carries no prefs, so the defaults (employer on) are kept.
    if prefs is not None:
        r.share_show_company = show_company is not None
        # Drop a cached OG png so it re-renders with the new employer choice.
        png = _OG_DIR / f"{r.share_token}.png"
        try:
            png.unlink(missing_ok=True)
        except Exception:
            pass
    db.add(r)
    db.commit()

    src = source if source in ("matches", "applications") else "matches"
    record(db, "match_card_shared", user_id=user.id, source=src)
    code = referral.ensure_code(db, user)
    db.commit()

    url = absolute_url(f"/m/{r.share_token}")
    return templates.TemplateResponse(request, "partials/share_sheet.html", {
        "request": request, "r": r, "source": src,
        "share_url": url, "og_url": absolute_url(f"/m/{r.share_token}/card.png"),
        "caption": _caption(url),
    })


def _card_context(db: DbSession, r: JobResult) -> dict:
    owner = db.get(User, r.user_id)
    code = referral.ensure_code(db, owner) if owner else ""
    db.commit()
    verdict, vcls = verdict_of(r.fit_role, r.fit_candidate)
    # The profile has no first-name field today, so there is no name to render —
    # the card stays anonymous, which is the safe default. share_show_name is
    # stored for when a real name source lands (then gate the name on it here).
    from ..services.text import as_bullets
    return {
        "r": r, "verdict": verdict, "vcls": vcls,
        "company": r.company if r.share_show_company else "",
        "owner_name": "",
        "good": as_bullets(r.why_good, 3), "bad": as_bullets(r.why_bad, 2),
        "cta_url": referral.invite_url(code) if code else "/signup",
    }


@router.get("/m/{token}", response_class=HTMLResponse)
def public_card(token: str, request: Request):
    db = SessionLocal()
    try:
        r = db.query(JobResult).filter(JobResult.share_token == token).first()
        if r is None:
            return HTMLResponse("This shared match could not be found.",
                                status_code=404)
        ctx = _card_context(db, r)
        record(db, "shared_artifact_viewed", user_id=None, kind="card")
        v = ctx["verdict"] or "A JBHNTR match"
        og_title = f"{v}: {r.title}" if r.title else v
        ctx.update({
            "request": request, "user": None,
            "meta_title": f"{og_title} | JBHNTR",
            "meta_description": ("A job match scored both ways on JBHNTR — how it "
                                 "fits what you want and how you fit what they ask."),
            "meta_robots": "noindex,nofollow,noarchive",   # per-user, thin
            "og_title": og_title,
            "og_description": ("Scored both ways: what you want and what they "
                               "need. See your own shortlist — first scan free."),
            "og_image": absolute_url(f"/m/{token}/card.png"),
            "og_url": absolute_url(f"/m/{token}"),
            "structured_data": [],
        })
        return templates.TemplateResponse(request, "m_card.html", ctx)
    finally:
        db.close()


def _og_svg(r: JobResult) -> str:
    """The 1200x630 social card as an SVG string. Plain sans-serif only (no web
    fonts) so cairo's fontconfig resolves it identically everywhere."""
    import html

    verdict, _ = verdict_of(r.fit_role, r.fit_candidate)
    v = html.escape((verdict or "A JBHNTR match")[:40])
    title = html.escape((r.title or "")[:60])
    company = html.escape((r.company if r.share_show_company else "")[:48])
    fr = max(0, min(100, r.fit_role or 0))
    fc = max(0, min(100, r.fit_candidate or 0))
    company_line = (f'<text x="80" y="356" font-family="sans-serif" '
                    f'font-size="32" fill="#9FB2C4">{company}</text>'
                    if company else "")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#0B1A27"/>
  <rect x="0" y="0" width="1200" height="12" fill="#6E92C9"/>
  <text x="80" y="110" font-family="sans-serif" font-size="34" font-weight="700" letter-spacing="3" fill="#9FB2C4">JBHNTR</text>
  <text x="80" y="210" font-family="sans-serif" font-size="58" font-weight="800" fill="#F2E9C9">{v}</text>
  <text x="80" y="300" font-family="sans-serif" font-size="46" font-weight="700" fill="#FBF8F2">{title}</text>
  {company_line}
  <g font-family="sans-serif" fill="#FBF8F2">
    <text x="80" y="455" font-size="26" font-weight="700">Fits what you want</text>
    <text x="1120" y="455" font-size="26" font-weight="700" text-anchor="end">{fr}</text>
    <rect x="80" y="470" width="1040" height="16" rx="8" fill="#1C3042"/>
    <rect x="80" y="470" width="{round(fr * 10.4, 1)}" height="16" rx="8" fill="#6E92C9"/>
    <text x="80" y="535" font-size="26" font-weight="700">You fit their requirements</text>
    <text x="1120" y="535" font-size="26" font-weight="700" text-anchor="end">{fc}</text>
    <rect x="80" y="550" width="1040" height="16" rx="8" fill="#1C3042"/>
    <rect x="80" y="550" width="{round(fc * 10.4, 1)}" height="16" rx="8" fill="#6E92C9"/>
  </g>
  <text x="80" y="610" font-family="sans-serif" font-size="24" fill="#9FB2C4">See your own shortlist - first scan free</text>
</svg>"""


def _render_og_png(r: JobResult, dest) -> bool:
    """Rasterise the match card to a 1200x630 PNG via cairosvg (reuses the cairo
    system lib weasyprint already needs in prod). Returns False if cairosvg is
    unavailable or rendering fails — the caller then serves the static default,
    so a missing rasteriser never breaks the unfurl or the boot."""
    try:
        import cairosvg  # noqa: PLC0415 — optional; absence is handled
    except Exception:
        return False
    try:
        _OG_DIR.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(bytestring=_og_svg(r).encode("utf-8"), write_to=str(dest),
                         output_width=1200, output_height=630)
        return dest.exists()
    except Exception:
        log.exception("OG card render failed for token %s", r.share_token)
        return False


@router.get("/m/{token}/card.png")
def public_card_png(token: str):
    db = SessionLocal()
    try:
        r = db.query(JobResult).filter(JobResult.share_token == token).first()
    finally:
        db.close()
    default = ROOT / "web" / "app" / "static" / config.og_image_path.split("/")[-1]
    if r is None:
        # Unknown token: 404, not another card and not a 500.
        return Response(status_code=404)
    dest = _OG_DIR / f"{token}.png"
    if not dest.exists():
        _render_og_png(r, dest)        # lazy, cache once
    if dest.exists():
        return FileResponse(str(dest), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})
    # Rasteriser unavailable — fall back to the static brand image so the link
    # still unfurls everywhere.
    if default.exists():
        return FileResponse(str(default), media_type="image/png")
    return RedirectResponse(config.og_image_path, status_code=302)
