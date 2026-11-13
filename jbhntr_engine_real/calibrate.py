"""Aggregator tracker liveness check (PRIVATE engine side).

Carved out of ``web/app/services/aggregator_calibrate.py`` (R3-16): which
sources hand out expiring redirect trackers, the aggregator landing hosts a dead
tracker bounces to, and the residential-browser check (Bright Data Scraping
Browser over CDP) that reads a tracker's real fate. The shell keeps the DB side
(age buckets, cutoff, purge) and calls these through the ``jbhntr_engine``
façade (``AGGREGATOR_SOURCES``, ``aggregator_check_configured``,
``aggregator_link_statuses``, ``aggregator_link_dead``).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

log = logging.getLogger("jbhntr.calibrate")

_CDP_HOST = "brd.superproxy.io:9222"
AGGREGATOR_SOURCES: tuple[str, ...] = ("api:careerjet", "api:jooble")
_DEAD_STATUSES = (404, 410)

# A dead careerjet/jooble tracker doesn't 404 through a real browser — it bounces the
# viewer to a "similar jobs" search on one of the aggregator's OWN domains. So landing
# back on any of these (rather than a real employer/ATS site) means the job is gone.
_AGG_HOSTS = ("jobviewtrack.com", "careerjet.", "optioncarriere.", "opcionempleo.",
              "jobrapido.", "jooble.", "whatjobs.", "trovit.", "jobisjob.")


def aggregator_link_dead(status, final_url: str) -> bool:
    if status in _DEAD_STATUSES:
        return True
    if status is None:
        return False                    # couldn't load — unknown, not counted dead
    host = urlparse(final_url or "").netloc.lower()
    return any(h in host for h in _AGG_HOSTS)


def _auth() -> str:
    from jbhntr_engine import Settings
    return getattr(Settings.from_env(), "brightdata_browser_auth", "") or ""


def aggregator_check_configured() -> bool:
    """True when the residential browser credentials are set."""
    return bool(_auth())


async def _statuses(urls: list[str], auth: str, connections: int = 3) -> dict[str, tuple]:
    """{url: (final_status, final_url)}. The Bright Data Scraping Browser is one page
    per CDP session — opening several pages on ONE session errors them all (that's why
    an earlier run read 214/215 as None). So open a few SEPARATE sessions and let each
    walk its slice sequentially (fresh page per URL). We keep the final URL because a
    dead tracker bounces to a 200 aggregator page rather than 404ing; images/media/CSS
    are blocked to keep Browser bandwidth (=cost) low."""
    from playwright.async_api import async_playwright

    out: dict[str, tuple] = {}

    async def _block(route):
        if route.request.resource_type in ("image", "media", "font", "stylesheet"):
            await route.abort()
        else:
            await route.continue_()

    async with async_playwright() as p:
        async def _worker(chunk: list[str]):
            try:
                browser = await p.chromium.connect_over_cdp(f"wss://{auth}@{_CDP_HOST}")
            except Exception as exc:
                log.warning("calibrate: CDP connect failed: %s", str(exc)[:160])
                for u in chunk:
                    out[u] = (None, "")
                return
            try:
                for u in chunk:
                    page = await browser.new_page()
                    page.set_default_navigation_timeout(45000)
                    try:
                        try:
                            await page.route("**/*", _block)
                        except Exception:
                            pass
                        resp = await page.goto(u, wait_until="domcontentloaded")
                        await page.wait_for_timeout(1000)      # let JS/meta redirects settle
                        out[u] = ((resp.status if resp else None), page.url)
                    except Exception:
                        out[u] = (None, "")
                    finally:
                        try:
                            await page.close()
                        except Exception:
                            pass
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass

        chunks = [urls[i::connections] for i in range(connections)]
        await asyncio.gather(*[_worker(c) for c in chunks if c])
    return out


def aggregator_link_statuses(urls: list[str]) -> dict[str, tuple]:
    """Sync wrapper -> {url: (status, final_url)}. Returns {} if no creds or it fails."""
    auth = _auth()
    if not auth or not urls:
        return {}
    try:
        return asyncio.run(_statuses(urls, auth))
    except Exception as exc:
        log.warning("calibrate: browser check failed: %s", str(exc)[:200])
        return {}
