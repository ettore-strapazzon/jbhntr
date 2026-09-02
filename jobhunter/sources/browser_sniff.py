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


async def _render(url: str, auth: str, capture_json: bool = False):
    """Render one URL via the Bright Data Scraping Browser. Returns the HTML, and —
    when capture_json — the list of (url, parsed-JSON) XHR/fetch responses the page
    made, which is where a JS agency portal's jobs actually come from."""
    from playwright.async_api import async_playwright

    bodies: list = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"wss://{auth}@{_CDP_HOST}")
        try:
            page = await browser.new_page()
            page.set_default_navigation_timeout(_NAV_TIMEOUT)

            # Bandwidth = cost on the Browser API. Drop images/media/fonts/CSS — we
            # only read the HTML + the JS-loaded job data, so this cuts traffic ~2-3x.
            async def _block(route):
                if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                    await route.abort()
                else:
                    await route.continue_()
            try:
                await page.route("**/*", _block)
            except Exception:
                pass

            if capture_json:
                async def _on_response(resp):
                    try:
                        ct = (resp.headers or {}).get("content-type", "")
                        if "json" in ct and resp.request.resource_type in ("xhr", "fetch"):
                            bodies.append((resp.url, await resp.json()))
                    except Exception:
                        pass
                page.on("response", _on_response)

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(_SETTLE_MS)
            html = await page.content()
            return (html, bodies) if capture_json else html
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


def render_capture(url: str, settings) -> tuple:
    """Sync wrapper: (rendered HTML, [(response_url, json)]) or ("", [])."""
    auth = getattr(settings, "brightdata_browser_auth", "")
    if not auth:
        return "", []
    import asyncio
    try:
        return asyncio.run(_render(url, auth, capture_json=True))
    except Exception as exc:
        log.warning("Browser capture failed for %s: %s", url, str(exc)[:160])
        return "", []


# Keys that mark a JSON object as a job posting (multi-language).
_TITLE_KEYS = ("title", "jobtitle", "job_title", "titolo", "position", "posizione",
               "jobname", "job_name", "offertitle", "roletitle")
_DESC_KEYS = ("description", "jobdescription", "job_description", "descrizione",
              "body", "content", "jobdesc", "descriptionhtml", "fulldescription")
_LOC_KEYS = ("location", "city", "citta", "città", "luogo", "place", "sede",
             "region", "regione", "province", "provincia", "worklocation")
_URL_KEYS = ("url", "joburl", "job_url", "link", "applyurl", "apply_url", "detailurl",
             "detail_url", "permalink", "canonicalurl", "slug", "jobid", "id")


def _pick(d: dict, keys) -> str:
    low = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = low.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):                 # e.g. location: {name: ...}
            for kk in ("name", "label", "value", "text", "city"):
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk].strip()
    return ""


def _looks_job(d) -> bool:
    if not isinstance(d, dict):
        return False
    keys = {k.lower() for k in d.keys()}
    return (any(t in keys for t in _TITLE_KEYS)
            and (any(x in keys for x in _DESC_KEYS) or any(x in keys for x in _LOC_KEYS)))


def _find_job_arrays(data, out: list, depth: int = 0) -> None:
    if depth > 9 or len(out) > 6:
        return
    if isinstance(data, list):
        jobs = [x for x in data if _looks_job(x)]
        if len(jobs) >= 2:
            out.append(jobs)
        for x in data:
            _find_job_arrays(x, out, depth + 1)
    elif isinstance(data, dict):
        for v in data.values():
            _find_job_arrays(v, out, depth + 1)


def _jobs_from_json(bodies: list, company: str, host: str) -> list:
    """Extract JobPostings from captured API JSON: find the array(s) of job-like
    objects and map their title/description/location/url by key heuristics."""
    from ..models import JobPosting
    arrays: list = []
    for _url, body in bodies:
        _find_job_arrays(body, arrays)
    # de-dupe by identity, keep the largest arrays first
    arrays.sort(key=len, reverse=True)
    out: list = []
    seen: set = set()
    for arr in arrays:
        for d in arr:
            title = _pick(d, _TITLE_KEYS)
            if not title:
                continue
            desc = _pick(d, _DESC_KEYS)
            desc = re.sub(r"\s+", " ", strip_html(desc)).strip()
            url = _pick(d, _URL_KEYS)
            key = (title.lower(), _pick(d, _LOC_KEYS).lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(JobPosting(
                source=f"scrape:{host}", title=title, company=company,
                location=_pick(d, _LOC_KEYS), description=desc[:8000],
                url=url if url.startswith("http") else ""))
    return out


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


def debug_portal(domain: str, settings) -> dict:
    """Diagnostic: render each candidate jobs path and report what came back, so we
    can see WHY extraction found nothing (wrong page, jobs on another host, no
    JSON-LD, links not matching hints)."""
    from .careers_scrape import _jsonld_jobs
    info: dict = {"domain": domain, "tried": []}
    if not is_configured(settings):
        info["error"] = "no BROWSER_AUTH"
        return info
    base = f"https://{domain}"
    html, bodies, rendered = "", [], base
    for path in JOBS_PATHS:
        u = f"{base}/{path}"
        h, b = render_capture(u, settings)
        info["tried"].append({"url": u, "len": len(h), "json_resp": len(b),
                              "hint": any(x in h.lower() for x in _DETAIL_HINTS),
                              "jsonld": "jobposting" in h.lower()})
        if h and len(h) > 3000 and any(x in h.lower() for x in _DETAIL_HINTS):
            html, bodies, rendered = h, b, u
            break
    if not html:
        html, bodies = render_capture(base, settings)
        info["home_len"] = len(html)
        rendered = base
    if html:
        info["rendered"] = rendered
        info["json_responses"] = len(bodies)
        arrays: list = []
        for _u, body in bodies:
            _find_job_arrays(body, arrays)
        info["job_arrays_found"] = [len(a) for a in arrays][:6]
        info["json_jobs"] = len(_jobs_from_json(bodies, "x", domain))
        info["json_response_urls"] = [u[:90] for u, _ in bodies][:10]
        info["jsonld_jobs"] = len(_jsonld_jobs(html, rendered, "x"))
        info["portal_subdomain"] = _portal_subdomain(html, domain)
        from collections import Counter
        raw = [h for h in re.findall(r'href=["\']([^"\']+)["\']', html)
               if "javascript" not in h.lower() and len(h) > 1][:400]
        info["href_hosts"] = Counter(urlparse(urljoin(rendered, h)).netloc
                                     for h in raw).most_common(6)
    return info


def _portal_subdomain(html: str, domain: str) -> str:
    """A jobs-portal subdomain the page links to (candidate.adecco.com, jobs.x.com),
    for agencies whose marketing site hands the actual jobs to a separate SPA."""
    core = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    for href in re.findall(r'href=["\']([^"\']+)["\']', html):
        h = urlparse(href).netloc.lower()
        if not h:
            continue
        sub = h.split(".")[0]
        if sub in ("candidate", "candidati", "jobs", "careers", "lavoro", "offerte",
                   "career", "recruiting", "apply") and core in h:
            return f"https://{h}/"
    return ""


def _from_render(html: str, bodies: list, page_url: str, company: str, host: str) -> list:
    """Jobs from a rendered page: captured API JSON first (SPAs), then rendered
    JSON-LD."""
    from .careers_scrape import _jsonld_jobs
    jobs = _jobs_from_json(bodies, company, host)
    if jobs:
        return jobs
    return _jsonld_jobs(html, page_url, company)


def fetch_portal(domain: str, company: str, settings) -> list:
    """Render a JS agency portal and return its openings with full JDs. [] on any
    failure. Captures the portal's own job API (the SPA data source) — the robust
    path — and follows a separate jobs subdomain (candidate.adecco.com) when the
    marketing site delegates to one. Import kept local so playwright stays optional."""
    if not is_configured(settings):
        return []
    from .careers_scrape import _detail_posting

    base = f"https://{domain}"
    html, bodies, rendered = "", [], base
    for path in JOBS_PATHS:
        h, b = render_capture(f"{base}/{path}", settings)
        if h and len(h) > 3000 and any(x in h.lower() for x in _DETAIL_HINTS):
            html, bodies, rendered = h, b, f"{base}/{path}"
            break
    if not html:
        html, bodies = render_capture(base, settings)
    if not html:
        return []

    jobs = _from_render(html, bodies, rendered, company, domain)
    if jobs:
        log.info("Browser portal %s: %d via render (API/JSON-LD)", company, len(jobs))
        return jobs[:_MAX_SITEMAP]

    # Marketing site delegates jobs to a separate SPA (candidate.adecco.com): render it.
    portal = _portal_subdomain(html, domain)
    if portal:
        ph, pb = render_capture(portal, settings)
        jobs = _from_render(ph, pb, portal, company, domain)
        if jobs:
            log.info("Browser portal %s: %d via jobs subdomain %s",
                     company, len(jobs), portal)
            return jobs[:_MAX_SITEMAP]

    # Last resort: DOM detail links -> read each detail page's JSON-LD over HTTP.
    links = _detail_links(html, rendered)
    out: list = []
    if links:
        with http_client(timeout=12.0) as c:
            for u in links[:_MAX_LINKS]:
                try:
                    r = c.get(u, follow_redirects=True)
                    if r.status_code == 200:
                        p = _detail_posting(u, r.text, company, domain)
                        if p:
                            out.append(p)
                except Exception:
                    continue
    log.info("Browser portal %s: %d openings (%d detail links)", company, len(out), len(links))
    return out
