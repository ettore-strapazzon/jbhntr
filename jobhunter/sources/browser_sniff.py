"""Rung 1 of the careers ladder: render a JavaScript-only agency portal with Bright
Data's Scraping Browser (a REMOTE Chromium reached over CDP — no local browser, and
it clears anti-bot walls like Incapsula), then read the jobs off the rendered DOM.

Used only when Rung 0 (sitemap / listing JSON-LD, both free) found nothing, so the
paid browser runs at most once per company per poll. The high-value pattern is:
render the listing once -> pull the job DETAIL links from the hydrated DOM -> fetch
those detail pages over plain HTTP (they are usually server-rendered with a
JobPosting JSON-LD, even when the listing is a SPA) -> extract full JDs for free.

Fail-soft everywhere: no credentials, an import error, or a render failure just
returns [] and the caller falls through to the LLM extractor.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from .base import http_client, strip_html

log = logging.getLogger("jobhunter.browser")

_CDP_HOST = "brd.superproxy.io:9222"
_NAV_TIMEOUT = 90_000     # ms — Bright Data recommends ~2 min ceilings
_SETTLE_MS = 4_000        # let the SPA's XHR job list populate after load
_MAX_LINKS = 60           # detail pages to follow per portal per poll

# Where an agency's job search commonly lives (it/fr/de/es/en).
JOBS_PATHS = (
    "offerte-lavoro", "offerte-di-lavoro", "lavora-con-noi", "candidati",
    "ricerca-lavoro", "cerca-lavoro", "jobs", "careers", "offerte", "vacancies",
    "empleo", "ofertas-de-empleo", "emploi", "offres-emploi", "stellenangebote",
)
# A rendered anchor is a job detail link if its href carries one of these.
_DETAIL_HINTS = (
    "offerte-lavoro", "offerta", "/lavoro", "/job", "/jobs/", "/vacan", "/position",
    "/opening", "/emploi", "/empleo", "/stelle", "/annunci", "/req", "/posting",
    "job-description", "jobdetail", "job-detail", "viewoffer", "/offer",
)


def is_configured(settings) -> bool:
    return bool(getattr(settings, "brightdata_browser_auth", ""))


async def _render(url: str, auth: str) -> str:
    """Rendered HTML of one URL via the Bright Data Scraping Browser."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"wss://{auth}@{_CDP_HOST}")
        try:
            page = await browser.new_page()
            page.set_default_navigation_timeout(_NAV_TIMEOUT)
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(_SETTLE_MS)
            return await page.content()
        finally:
            await browser.close()


def render_html(url: str, settings) -> str:
    """Sync wrapper: rendered HTML, or "" (no creds / any failure)."""
    auth = getattr(settings, "brightdata_browser_auth", "")
    if not auth:
        return ""
    import asyncio
    try:
        return asyncio.run(_render(url, auth))
    except Exception as exc:
        log.warning("Browser render failed for %s: %s", url, str(exc)[:160])
        return ""


def _detail_links(html: str, base_url: str) -> list[str]:
    """Absolute job-detail URLs linked from a rendered listing page."""
    out: list[str] = []
    seen: set[str] = set()
    host = urlparse(base_url).netloc
    for href in re.findall(r'href=["\']([^"\']+)["\']', html):
        low = href.lower()
        if not any(h in low for h in _DETAIL_HINTS):
            continue
        url = urljoin(base_url, href)
        # keep it on the company's own site, drop obvious non-detail listing pages
        if urlparse(url).netloc.replace("www.", "") not in host.replace("www.", ""):
            if host.replace("www.", "") not in urlparse(url).netloc:
                continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def fetch_portal(domain: str, company: str, settings) -> list:
    """Render a JS agency portal and return its openings with full JDs. [] on any
    failure. Renders the listing once (paid), then reads detail pages over free HTTP.
    Import kept local so the module (and playwright) is optional."""
    if not is_configured(settings):
        return []
    from .careers_scrape import _detail_posting, _jsonld_jobs

    base = f"https://{domain}"
    html = ""
    for path in JOBS_PATHS:
        html = render_html(f"{base}/{path}", settings)
        if html and len(html) > 3000 and any(h in html.lower() for h in _DETAIL_HINTS):
            base = f"{base}/{path}"
            break
        html = ""
    if not html:
        html = render_html(base, settings)      # last resort: the home/landing page
    if not html:
        return []

    # Best case: the hydrated DOM already carries JobPosting JSON-LD.
    jobs = _jsonld_jobs(html, base, company)
    if jobs:
        log.info("Browser portal %s: %d via rendered JSON-LD", company, len(jobs))
        return jobs

    # Otherwise follow the detail links and read each detail page's JSON-LD over HTTP
    # (detail pages are usually server-rendered even when the listing is a SPA).
    links = _detail_links(html, base)
    if not links:
        return []
    out: list = []
    with http_client(timeout=12.0) as c:
        for u in links[:_MAX_LINKS]:
            try:
                r = c.get(u, follow_redirects=True)
                if r.status_code != 200:
                    continue
                p = _detail_posting(u, r.text, company, domain)
                if p:
                    out.append(p)
            except Exception:
                continue
    # If detail pages were ALSO JS-only (no JSON-LD over HTTP), render a few.
    if not out:
        for u in links[:8]:
            dh = render_html(u, settings)
            if dh:
                p = _detail_posting(u, dh, company, domain)
                if p:
                    out.append(p)
    log.info("Browser portal %s: %d openings (%d detail links)",
             company, len(out), len(links))
    return out
