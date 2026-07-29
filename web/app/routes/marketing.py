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
            "faq_pairs": seo.FAQ_PAIRS,
            **seo.public_seo(
                title=seo.DEFAULT_TITLE,
                description=seo.DEFAULT_DESCRIPTION,
                path="/",
                og_title="Don't let job hunting become your next job.",
                schema=[
                    seo.organization_schema(),
                    seo.website_schema(),
                    seo.software_application_schema(),
                    seo.faq_schema(list(seo.FAQ_PAIRS)),
                ],
            ),
        }
        return templates.TemplateResponse(request, "landing.html", ctx)
    finally:
        db.close()


def _public_page(request: Request, template: str, *, title: str,
                 description: str, path: str, og_title: str):
    from ..auth import current_user
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        user = current_user(request, db)
        ctx = {"request": request, "user": user, **seo.public_seo(
            title=title, description=description, path=path, og_title=og_title)}
        return templates.TemplateResponse(request, template, ctx)
    finally:
        db.close()


@router.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request):
    return _public_page(
        request, "marketing/how_it_works.html",
        title="How JBHNTR Works | AI Job Search and Two-Way Fit Scoring",
        description=("How JBHNTR turns your CV, goals and constraints into a "
                     "cross-source job scan, then scores each role against what "
                     "you want and what the employer requires."),
        path="/how-it-works",
        og_title="How JBHNTR searches the job market for you")


@router.get("/security", response_class=HTMLResponse)
def security(request: Request):
    return _public_page(
        request, "marketing/security.html",
        title="CV Privacy and Data Security | JBHNTR",
        description=("Learn how JBHNTR encrypts uploaded career documents, uses "
                     "AI providers, keeps profiles private by default and supports "
                     "export and deletion."),
        path="/security",
        og_title="Your CV is used to search for you, not to sell you")


@router.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return _public_page(
        request, "marketing/pricing.html",
        title="JBHNTR Pricing | Free Job Search and Planned Premium",
        description=("Run complete JBHNTR searches free. See current limits and "
                     "what planned Premium automation will add when it opens."),
        path="/pricing",
        og_title="Free to prove the search. Premium for continuity.")


@router.get("/compare/linkedin-jobs", response_class=HTMLResponse)
def compare_linkedin_jobs(request: Request):
    return _public_page(
        request, "marketing/compare_linkedin_jobs.html",
        title="JBHNTR vs LinkedIn Jobs | An Independent Job Search Agent",
        description=("A fair comparison of LinkedIn Jobs and JBHNTR: a "
                     "professional network with its own inventory, against an "
                     "independent agent that searches across sources and scores "
                     "fit both ways."),
        path="/compare/linkedin-jobs",
        og_title="LinkedIn Jobs and JBHNTR, compared honestly")


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
