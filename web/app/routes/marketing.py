"""Public marketing surface: homepage, robots.txt and sitemap.xml (Guide v2).

The homepage handler lives here (moved out of main.py). Public product pages
(/how-it-works, /security, /pricing, /compare/linkedin-jobs) are added in the
PUB phase; when they ship, add their paths to seo.PUBLIC_PATHS so the sitemap
picks them up.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import seo
from ..config import config
from ..templating import templates

router = APIRouter()

# Authenticated / private route prefixes kept out of search indexes. robots.txt
# Disallow is a prefix match, so "/document" also covers "/documents", etc.
PRIVATE_PREFIXES = (
    "/account", "/admin", "/applications", "/auth", "/document", "/forgot",
    "/generate", "/job", "/login", "/logout", "/matches", "/onboarding",
    "/premium", "/profile", "/reset", "/search", "/signup", "/unsubscribe",
)


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    from ..auth import current_user
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        user = current_user(request, db)
        if user:
            return RedirectResponse("/matches", status_code=303)
        ctx = {
            "request": request,
            **seo.public_seo(
                title=seo.DEFAULT_TITLE,
                description=seo.DEFAULT_DESCRIPTION,
                path="/",
                og_title="Don't let job hunting become your next job.",
                schema=[
                    seo.organization_schema(),
                    seo.website_schema(),
                    seo.software_application_schema(),
                ],
            ),
        }
        return templates.TemplateResponse(request, "landing.html", ctx)
    finally:
        db.close()


@router.get("/robots.txt")
def robots_txt() -> Response:
    lines = ["User-agent: *", "Allow: /"]
    lines += [f"Disallow: {p}" for p in PRIVATE_PREFIXES]
    lines += ["", f"Sitemap: {seo.absolute_url('/sitemap.xml')}", ""]
    return Response("\n".join(lines), media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml")
def sitemap_xml() -> Response:
    urls = "".join(
        f"<url><loc>{seo.absolute_url(p)}</loc></url>" for p in seo.PUBLIC_PATHS
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(xml, media_type="application/xml")
