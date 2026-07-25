"""Generic scraper for user-supplied job boards.

Each entry in profile.sources.custom_sites is a dict:

    - url: "https://boards.greenhouse.io/acme"
      name: "Acme"                       # optional label
      job_selector: "div.opening"        # optional CSS: the repeated card
      title_selector: "a"                # optional CSS within the card
      link_selector: "a"                 # optional CSS within the card (href)
      location_selector: "span.location" # optional CSS within the card

If selectors are omitted, a heuristic extractor collects anchors whose href
looks like a job link (greenhouse/lever/ashby/`/jobs/`/`/careers/`). This is
best-effort — provide selectors for reliable extraction. Fails soft per-site.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client

log = logging.getLogger("jobhunter.sources.custom")

JOB_URL_HINTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "/jobs/",
    "/job/",
    "/careers/",
    "/positions/",
    "/vacancy/",
    "workable.com",
)


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for site in profile.custom_sites:
        url = site.get("url")
        if not url:
            continue
        try:
            jobs.extend(_scrape_site(site))
        except Exception as exc:
            log.warning("Custom site %s failed: %s", url, exc)
    log.info("Custom sites: %d postings", len(jobs))
    return jobs


def _scrape_site(site: dict) -> list[JobPosting]:
    url = site["url"]
    name = site.get("name") or urlparse(url).netloc
    with http_client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

    out: list[JobPosting] = []
    job_sel = site.get("job_selector")

    if job_sel:
        for card in soup.select(job_sel):
            title_el = _sel(card, site.get("title_selector"))
            link_el = _sel(card, site.get("link_selector") or "a")
            loc_el = _sel(card, site.get("location_selector"))
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)
            href = link_el.get("href") if link_el else ""
            if not title:
                continue
            out.append(
                JobPosting(
                    source=f"custom:{name}",
                    title=title[:200],
                    company=name,
                    location=loc_el.get_text(strip=True) if loc_el else "",
                    url=urljoin(url, href) if href else url,
                )
            )
        return out

    # Heuristic fallback: anchors that look like job links.
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        full = urljoin(url, href)
        if not any(h in full for h in JOB_URL_HINTS):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or full in seen:
            continue
        seen.add(full)
        out.append(
            JobPosting(
                source=f"custom:{name}",
                title=title[:200],
                company=name,
                url=full,
            )
        )
    return out


def _sel(node, selector):
    return node.select_one(selector) if selector else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from ..config import load_profile

    for j in fetch(load_profile(), Settings.from_env())[:10]:
        print(j.title, "|", j.company, "|", j.url)
