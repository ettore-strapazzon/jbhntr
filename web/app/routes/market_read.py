"""Shareable "my market read" (R3-02) — the scan-level shared artefact.

Reuses the R3-01 match-card machine in routes/share.py (lazy token mint, cairosvg
OG renderer + static fallback, anon view event) on `Search` instead of
`JobResult`:

  POST /search/{id}/share  owner-only, completed scans only; lazily mints
                           Search.share_token, stores the anonymise toggle,
                           emits market_read_shared, returns the HTMX sheet.
  GET  /r/{token}          public, no-auth v1 stage funnel read straight off the
                           Search counts (raw -> located -> ranked -> scored).
                           No reason histogram (v2, needs engine work — §2.3).
  POST /search/{id}/unshare owner-only "Stop sharing": token + PNG cleared, so
                           the page and the image 404 at once.
  GET  /r/{token}/card.png public OG image (cairosvg, cached outside /static,
                           static fallback, X-Robots-Tag noindex).

Privacy (ARTEFACTS_SPEC §2.4): anonymised by default = aggregate counts only.
With anonymise off the read adds the owner's target role label + countries.
Never the name, email, CV/objective text, or any employer names — regardless
of the toggle.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import SessionLocal, get_session
from ..models import Profile, Search, User
from ..seo import absolute_url
from ..services import referral
from ..services.events import countable_view, record
from ..templating import templates
from ..config import config
from .share import (
    INCENTIVE, NOINDEX, drop_png, mint_share_token, rasterise_svg, read_png_path,
    referral_ctx, revoke_share, serve_og_png,
)

router = APIRouter()

STAGES = (  # (Search attribute, public label) — ARTEFACTS_SPEC §2.2
    ("raw_count", "Roles scanned"),
    ("located_count", "In the target locations"),
    ("ranked_count", "Shortlisted to score in detail"),
    ("scored_count", "Worth a decision"),
)


def _png_path(token: str):
    return read_png_path(token)


def _drop_png(token: str) -> None:
    drop_png(read_png_path(token))


def headline_of(s: Search) -> str:
    return (f"{s.raw_count or 0:,} roles scanned → "
            f"{s.scored_count or 0:,} worth a decision.")


def _caption(url: str, s: Search) -> str:
    """GC's exact caption (COMPLIANCE_CARD 2026-11-13, MR6): this read's real
    counts only, referral incentive disclosed."""
    return (f"I ran a JBHNTR scan: {s.raw_count or 0:,} live roles, narrowed to "
            f"{s.scored_count or 0:,} worth a decision. My market read: {url} "
            + INCENTIVE.format(what="read"))


def _funnel(s: Search) -> list[dict]:
    top = max(s.raw_count or 0, 1)
    rows = []
    for attr, label in STAGES:
        n = max(0, getattr(s, attr) or 0)
        rows.append({"label": label, "n": n,
                     # Bars proportional to the top stage; a non-zero stage never
                     # collapses to an invisible sliver.
                     "pct": 0 if not n else max(2, round(100 * min(n, top) / top))})
    return rows


def _context_line(db: DbSession, s: Search) -> str:
    """Target role + countries — only ever shown with anonymise OFF. Built from
    short structured fields, never the free-text objective/about-me/CV."""
    if s.share_anonymous:
        return ""
    p = db.query(Profile).filter(Profile.user_id == s.user_id).first()
    if p is None:
        return ""
    roles = [str(x).strip() for x in (p.search_terms or p.derived_roles or []) if str(x).strip()]
    countries = [str(x).strip() for x in (p.countries or []) if str(x).strip()]
    parts = []
    if roles:
        parts.append(roles[0][:60])
    if countries:
        parts.append(", ".join(countries[:3]) + (" +more" if len(countries) > 3 else ""))
    return " · ".join(parts)


@router.post("/search/{search_id}/share", response_class=HTMLResponse)
def share_read(search_id: int, request: Request,
               source: str = Form("matches"),
               prefs: str = Form(None), anonymous: str = Form(None),
               user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    s = db.get(Search, search_id)
    # Owner-only, and only a completed scan has a read worth sharing.
    if not s or s.user_id != user.id or s.status != "done":
        return HTMLResponse("", status_code=404)

    mint_share_token(s)
    if prefs is not None:
        # Toggle form re-submit: an unchecked checkbox sends nothing, so the
        # field's presence is the value. Drop the cached PNG so it re-renders.
        s.share_anonymous = anonymous is not None
        _drop_png(s.share_token)
    db.add(s)
    db.commit()

    src = source if source in ("matches", "read") else "matches"
    if prefs is None:
        # One event per Share click (incl. re-shares) — not per toggle save.
        record(db, "market_read_shared", user_id=user.id, source=src)
    referral.ensure_code(db, user)
    db.commit()

    url = absolute_url(f"/r/{s.share_token}")
    return templates.TemplateResponse(request, "partials/read_share_sheet.html", {
        "request": request, "s": s, "source": src,
        "share_url": url, "og_url": absolute_url(f"/r/{s.share_token}/card.png"),
        "caption": _caption(url, s),
    })


@router.post("/search/{search_id}/unshare", response_class=HTMLResponse)
def unshare_read(search_id: int, request: Request,
                 user: User = Depends(require_user),
                 db: DbSession = Depends(get_session)):
    s = db.get(Search, search_id)
    if not s or s.user_id != user.id:
        return HTMLResponse("", status_code=404)
    revoke_share(s, read_png_path)
    db.add(s)
    db.commit()
    return templates.TemplateResponse(request, "partials/unshared.html", {
        "request": request, "sheet_id": f"read-share-sheet-{s.id}"})


@router.get("/r/{token}", response_class=HTMLResponse)
def public_read(token: str, request: Request):
    db = SessionLocal()
    try:
        s = db.query(Search).filter(Search.share_token == token).first()
        if s is None:
            return HTMLResponse("This market read could not be found.",
                                status_code=404, headers=NOINDEX)
        owner = db.get(User, s.user_id)
        code = referral.ensure_code(db, owner) if owner else ""
        db.commit()
        ready = s.status == "done"
        if ready and countable_view(request, "shared_artifact_viewed"):   # R3-22
            record(db, "shared_artifact_viewed", user_id=None, kind="read")
        headline = headline_of(s)
        ctx = {
            "request": request, "user": None, "s": s, "ready": ready,
            "headline": headline, "stages": _funnel(s),
            "context_line": _context_line(db, s) if ready else "",
            "cta_url": referral.invite_url(code) if code else "/signup",
            **referral_ctx(code),
            "meta_title": "A job market read | JBHNTR",
            "meta_description": ("One scan of the live job market, narrowed both "
                                 "ways to the roles worth a decision."),
            "meta_robots": "noindex,nofollow,noarchive",   # per-user, thin
            "og_title": headline if ready else "A JBHNTR market read",
            "og_description": ("One scan of the live market, narrowed both ways."
                               + (" Get your own market read — first scan free."
                                  if config.first_scan_free else "")),
            "og_image": absolute_url(f"/r/{token}/card.png"),
            "og_url": absolute_url(f"/r/{token}"),
            "structured_data": [],
        }
        return templates.TemplateResponse(request, "r_read.html", ctx,
                                          headers=NOINDEX)
    finally:
        db.close()


def _og_svg(s: Search, context_line: str) -> str:
    """The 1200x630 read card. Plain sans-serif (no web fonts) so cairo resolves
    it identically everywhere."""
    e = html.escape
    raw, scored = s.raw_count or 0, s.scored_count or 0
    bars = []
    y = 300
    for row in _funnel(s):
        w = round(row["pct"] * 7.0, 1)          # 700px track
        bars.append(
            f'<text x="80" y="{y + 26}" font-size="24" fill="#9FB2C4">{e(row["label"])}</text>'
            f'<rect x="420" y="{y}" width="700" height="34" rx="4" fill="#1C3042"/>'
            f'<rect x="420" y="{y}" width="{w}" height="34" rx="4" fill="#6E92C9"/>'
            f'<text x="1110" y="{y + 25}" font-size="22" font-weight="700" '
            f'text-anchor="end" fill="#FBF8F2">{row["n"]:,}</text>')
        y += 56
    ctx = (f'<text x="80" y="250" font-family="sans-serif" font-size="28" '
           f'fill="#9FB2C4">{e(context_line[:70])}</text>' if context_line else "")
    footer = ("Get your own market read - first scan free" if config.first_scan_free
              else "Get your own market read on JBHNTR")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#0B1A27"/>
  <rect x="0" y="0" width="1200" height="12" fill="#6E92C9"/>
  <text x="80" y="100" font-family="sans-serif" font-size="34" font-weight="700" letter-spacing="3" fill="#9FB2C4">JBHNTR · MARKET READ</text>
  <text x="80" y="190" font-family="sans-serif" font-size="46" font-weight="800" fill="#F2E9C9">{raw:,} roles scanned → {scored:,} worth a decision</text>
  {ctx}
  <g font-family="sans-serif">{''.join(bars)}</g>
  <text x="80" y="600" font-family="sans-serif" font-size="24" fill="#9FB2C4">{footer}</text>
</svg>"""


@router.get("/r/{token}/card.png")
def public_read_png(token: str):
    db = SessionLocal()
    try:
        s = db.query(Search).filter(Search.share_token == token).first()
        if s is None:
            return Response(status_code=404, headers=NOINDEX)   # unknown token
        line = _context_line(db, s)
    finally:
        db.close()
    dest = read_png_path(token)
    if s.status != "done":                         # not ready: brand default
        return serve_og_png(dest, lambda: False)
    return serve_og_png(dest, lambda: rasterise_svg(_og_svg(s, line), dest))
