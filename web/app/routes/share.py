"""Shareable match card (R3-01) — the atomic shared artefact.

Three routes:
  POST /job/{id}/share     owner-only; lazily mints JobResult.share_token, stores
                           the show-employer / show-name opt-ins, emits
                           match_card_shared, returns the HTMX share sheet.
  GET  /m/{token}          public, no-auth card page (verdict + two fit scores +
                           fits/watch-out + role, employer iff opted in, always
                           anonymous — no name source exists yet); CTA carries the
                           sharer's referral code.
  POST /job/{id}/unshare   owner-only "Stop sharing": clears the token and the
                           cached PNG so the page and the image 404 at once.
  GET  /m/{token}/card.png public OG image — a brand SVG card rasterised once by
                           cairosvg and cached to data/og/ (NOT the public
                           /static mount), falling back to the static default
                           PNG if rasterising is unavailable. X-Robots-Tag
                           noindex on every artefact response.

The helpers here (mint / revoke / PNG cache + serve / account-deletion cleanup /
referral CTA context) are shared with the market read (routes/market_read.py).

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

# OG PNG cache — deliberately OUTSIDE the public /static mount (COMPLIANCE_CARD
# C11): a PNG is reachable only through its token route, which 404s once the
# owner stops sharing or deletes the account. Git-ignored.
_OG_DIR = ROOT / "data" / "og"
NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive"}


def mint_share_token(row) -> str:
    """Lazy, idempotent public-handle mint shared by every artefact (match card
    on JobResult, market read on Search): mint iff null, never rotate."""
    if not row.share_token:
        row.share_token = secrets.token_urlsafe(9)
    return row.share_token


def card_png_path(token: str):
    return _OG_DIR / f"{token}.png"


def read_png_path(token: str):
    # Namespaced so a market read never collides with a match-card PNG.
    return _OG_DIR / f"r-{token}.png"


def drop_png(path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        log.exception("could not delete OG png %s", path.name)


def revoke_share(row, png_path) -> None:
    """Stop sharing (C11): delete the cached image, then clear the token so the
    public page and image 404 at once. Re-sharing mints a fresh token."""
    if row.share_token:
        drop_png(png_path(row.share_token))
    row.share_token = None


def delete_user_artefact_pngs(db: DbSession, user_id: int) -> None:
    """Account deletion: remove every cached card/read PNG before the rows go,
    so nothing public is left behind (C11)."""
    from ..models import Search
    for (tok,) in (db.query(JobResult.share_token)
                     .filter(JobResult.user_id == user_id,
                             JobResult.share_token.isnot(None))):
        drop_png(card_png_path(tok))
    for (tok,) in (db.query(Search.share_token)
                     .filter(Search.user_id == user_id,
                             Search.share_token.isnot(None))):
        drop_png(read_png_path(tok))


def referral_ctx(code: str) -> dict:
    """Template context for the public CTA + incentive disclosure (GC #8/MR6)."""
    return {"first_scan_free": config.first_scan_free,
            "ref_disclosed": bool(code),
            "referral_friend_credits": config.referral_friend_credits}


INCENTIVE = ("(Sign up from the {what} and you get bonus credits; I get some once "
             "you run your first scan.)")


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
    """Copy-ready share caption — GC's exact text (COMPLIANCE_CARD 2026-11-13
    #1): no coverage absolutes, referral incentive disclosed."""
    return ("I'm trying JBHNTR: it scores each job both ways, how it fits what I "
            "want and how I fit what they ask. One of my matches: "
            f"{url} " + INCENTIVE.format(what="card"))


@router.post("/job/{result_id}/share", response_class=HTMLResponse)
def share(result_id: int, request: Request,
          source: str = Form("matches"),
          prefs: str = Form(None), show_company: str = Form(None),
          user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    r = db.get(JobResult, result_id)
    if not r or r.user_id != user.id:
        return HTMLResponse("", status_code=404)

    if not r.share_token and prefs is None:
        # First share (or re-share after Stop sharing): employer starts OFF
        # (privacy by default, GC #5) whatever an older row stored.
        r.share_show_company = False
    mint_share_token(r)                         # lazy, idempotent mint
    # The sheet's toggle form re-submits with prefs=1; an unchecked checkbox
    # sends nothing, so presence of the field is the value.
    if prefs is not None:
        r.share_show_company = show_company is not None
        # Drop a cached OG png so it re-renders with the new employer choice.
        drop_png(card_png_path(r.share_token))
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


@router.post("/job/{result_id}/unshare", response_class=HTMLResponse)
def unshare(result_id: int, request: Request,
            user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    r = db.get(JobResult, result_id)
    if not r or r.user_id != user.id:
        return HTMLResponse("", status_code=404)
    revoke_share(r, card_png_path)
    db.add(r)
    db.commit()
    return templates.TemplateResponse(request, "partials/unshared.html", {
        "request": request, "sheet_id": f"share-sheet-{r.id}"})


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
        **referral_ctx(code),
    }


@router.get("/m/{token}", response_class=HTMLResponse)
def public_card(token: str, request: Request):
    db = SessionLocal()
    try:
        r = db.query(JobResult).filter(JobResult.share_token == token).first()
        if r is None:
            return HTMLResponse("This shared match could not be found.",
                                status_code=404, headers=NOINDEX)
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
                               "need." + (" See your own shortlist — first scan free."
                                          if config.first_scan_free else "")),
            "og_image": absolute_url(f"/m/{token}/card.png"),
            "og_url": absolute_url(f"/m/{token}"),
            "structured_data": [],
        })
        return templates.TemplateResponse(request, "m_card.html", ctx,
                                          headers=NOINDEX)
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
    footer = ("See your own shortlist - first scan free" if config.first_scan_free
              else "See your own shortlist on JBHNTR")
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
    <text x="80" y="455" font-size="26" font-weight="700">Fits the candidate's goals</text>
    <text x="1120" y="455" font-size="26" font-weight="700" text-anchor="end">{fr}</text>
    <rect x="80" y="470" width="1040" height="16" rx="8" fill="#1C3042"/>
    <rect x="80" y="470" width="{round(fr * 10.4, 1)}" height="16" rx="8" fill="#6E92C9"/>
    <text x="80" y="535" font-size="26" font-weight="700">Candidate fits the requirements</text>
    <text x="1120" y="535" font-size="26" font-weight="700" text-anchor="end">{fc}</text>
    <rect x="80" y="550" width="1040" height="16" rx="8" fill="#1C3042"/>
    <rect x="80" y="550" width="{round(fc * 10.4, 1)}" height="16" rx="8" fill="#6E92C9"/>
  </g>
  <text x="80" y="610" font-family="sans-serif" font-size="24" fill="#9FB2C4">{footer}</text>
</svg>"""


def rasterise_svg(svg: str, dest) -> bool:
    """Rasterise a 1200x630 SVG card to `dest` via cairosvg (reuses the cairo
    system lib weasyprint already needs in prod). Returns False if cairosvg is
    unavailable or rendering fails — the caller then serves the static default,
    so a missing rasteriser never breaks the unfurl or the boot."""
    try:
        import cairosvg  # noqa: PLC0415 — optional; absence is handled
    except Exception:
        return False
    try:
        _OG_DIR.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(dest),
                         output_width=1200, output_height=630)
        return dest.exists()
    except Exception:
        log.exception("OG card render failed for %s", dest.name)
        return False


def _render_og_png(r: JobResult, dest) -> bool:
    return rasterise_svg(_og_svg(r), dest)


def serve_og_png(dest, render) -> Response:
    """Serve a cached OG PNG, rendering it once on first fetch via `render()`
    (-> bool). Falls back to the static brand image when rasterising is
    unavailable so the link still unfurls everywhere."""
    if not dest.exists():
        render()                       # lazy, cache once
    if dest.exists():
        # Short-ish cache so a revoke/toggle isn't pinned at the edge for a day.
        return FileResponse(str(dest), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=3600",
                                     **NOINDEX})
    default = ROOT / "web" / "app" / "static" / config.og_image_path.split("/")[-1]
    if default.exists():
        return FileResponse(str(default), media_type="image/png", headers=NOINDEX)
    return RedirectResponse(config.og_image_path, status_code=302, headers=NOINDEX)


@router.get("/m/{token}/card.png")
def public_card_png(token: str):
    db = SessionLocal()
    try:
        r = db.query(JobResult).filter(JobResult.share_token == token).first()
    finally:
        db.close()
    if r is None:
        # Unknown token: 404, not another card and not a 500.
        return Response(status_code=404, headers=NOINDEX)
    dest = card_png_path(token)
    return serve_og_png(dest, lambda: _render_og_png(r, dest))
