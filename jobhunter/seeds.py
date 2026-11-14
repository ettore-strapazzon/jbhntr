"""Seed companies — the "find me more like these" examples for discovery.

A seed can be written either way in `config/companies.yaml`:

    seeds:
      - Stripe                     # a name
      - https://satispay.com       # a website  (preferred)
      - satispay.com               # bare domain also fine

**Websites are the better input**, especially for smaller or country-specific
companies: a domain is unambiguous, and we can fetch the site to learn what the
company actually does instead of relying on the model recognising the name.

Fetched descriptions are cached in `data/seed_profiles.json`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import DATA_DIR
from .models import ProgressFn, StopFn, report_progress, stop_requested

log = logging.getLogger("jobhunter.seeds")

SEED_CACHE = DATA_DIR / "seed_profiles.json"
BLURB_CHARS = 300


@dataclass
class Seed:
    raw: str
    name: str
    domain: str = ""
    blurb: str = ""  # what the company does, scraped from its site

    def slug(self) -> str:
        """Best-guess ATS handle for this company."""
        if self.domain:
            return re.sub(r"[^a-z0-9]", "", self.domain.split(".")[0].lower())
        return re.sub(r"[^a-z0-9]", "", self.name.lower())

    def label(self) -> str:
        """One line describing this seed, for the discovery prompt."""
        bits = self.name
        if self.domain:
            bits += f" ({self.domain})"
        if self.blurb:
            bits += f" — {self.blurb}"
        return bits


def looks_like_url(text: str) -> bool:
    t = (text or "").strip()
    if not t or " " in t:
        return False
    return t.startswith(("http://", "https://")) or bool(
        re.match(r"^[a-z0-9][a-z0-9\-]*(\.[a-z0-9\-]+)+$", t, re.I)
    )


def domain_of(text: str) -> str:
    t = (text or "").strip()
    if not t.startswith(("http://", "https://")):
        t = "https://" + t
    host = urlparse(t).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def name_from_domain(domain: str) -> str:
    """satispay.com -> Satispay ; back-market.com -> Back Market"""
    label = domain.split(".")[0]
    return " ".join(w.capitalize() for w in re.split(r"[-_]", label) if w)


def parse(raw: str) -> Seed:
    """Turn a raw seed string into a Seed (no network)."""
    raw = (raw or "").strip()
    if looks_like_url(raw):
        d = domain_of(raw)
        return Seed(raw=raw, name=name_from_domain(d), domain=d)
    return Seed(raw=raw, name=raw)


# --------------------------------------------------------------------------- #
# Enrichment: fetch the site to learn what the company does
# --------------------------------------------------------------------------- #
def _load_cache() -> dict:
    if not SEED_CACHE.exists():
        return {}
    try:
        return json.loads(SEED_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    SEED_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SEED_CACHE.write_text(json.dumps(cache, indent=0), encoding="utf-8")


def _scrape_blurb(domain: str) -> str:
    """Title + meta description + a little body text from the company's site."""
    from bs4 import BeautifulSoup

    from .sources.base import http_client

    try:
        with http_client(timeout=12.0) as c:
            r = c.get(f"https://{domain}")
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return ""

    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string.strip())
    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parts.append(tag["content"].strip())
            break
    if not parts:
        h1 = soup.find("h1")
        if h1:
            parts.append(h1.get_text(" ", strip=True))

    blurb = " — ".join(dict.fromkeys(p for p in parts if p))
    blurb = re.sub(r"\s+", " ", blurb).strip()
    return blurb[:BLURB_CHARS]


# TLDs tried when a seed is given as a bare company name. Ordered by how
# likely an Italian/EU startup is to use them.
GUESS_TLDS = ("com", "io", "it", "co", "ai", "app", "eu", "finance", "xyz")


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) > 2]


# Text that means we landed on a parked / for-sale / squatted domain.
PARKED_MARKERS = (
    "is your first and best source",
    "domain is for sale",
    "buy this domain",
    "this domain may be for sale",
    "domain for sale",
    "parked",
    "godaddy",
    "sedo",
    "related searches",
    "under construction",
)


def guess_domain(name: str) -> tuple[str, str]:
    """Find a company's website from its name alone. Returns (domain, blurb).

    A guess is only accepted when the fetched PAGE TEXT mentions the company.
    Checking the domain would be circular — we built it from the name — which
    is how a gambling site ended up matching "Rent2Cash". Parked/for-sale pages
    are rejected too. A bad guess therefore degrades to "no website" rather
    than to misleading context, which matters because these blurbs steer
    company discovery.
    """
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    if len(base) < 3:
        return "", ""
    tokens = _name_tokens(name)
    for tld in GUESS_TLDS:
        domain = f"{base}.{tld}"
        blurb = _scrape_blurb(domain)
        if not blurb or len(blurb) < 4:
            continue
        low = blurb.lower()
        if any(marker in low for marker in PARKED_MARKERS):
            continue
        # The name must appear in the page itself. Also compare with all
        # punctuation/spacing stripped, so "JetHR" still matches "Jet HR".
        compact = re.sub(r"[^a-z0-9]", "", low)
        if not (any(t in low for t in tokens) or base in compact):
            continue
        return domain, blurb
    return "", ""


def resolve(
    raw_seeds: list[str], enrich: bool = True, guess_domains: bool = False,
    progress: Optional[ProgressFn] = None, should_stop: Optional[StopFn] = None,
) -> list[Seed]:
    """Parse seeds and (optionally) fetch a description for each.

    With ``guess_domains`` we also try to find a website for seeds written as
    plain names — that's what gives the model real context for small companies
    it may not recognise.

    Slow on a cold cache (R3-32): website seeds are fetched one by one (12 s
    httpx timeout per phase, so ~12-24 s for a dead host) and a name-only seed
    tries up to 9 TLDs in turn, 8 seeds at a time. With 100 seeds that is
    ~20-40 min + ~47 min. So, like the other long stages, ``progress(done,
    total)`` reports each finished network lookup (on the caller's thread) and
    ``should_stop()`` is asked before each new one; once True no new lookup
    starts and the partial seeds come back. Unfinished lookups are not cached.
    """
    seeds = [parse(s) for s in raw_seeds if (s or "").strip()]
    if not enrich:
        return seeds

    cache = _load_cache()
    changed = False

    total = sum(1 for s in seeds if s.domain and s.domain not in cache)
    if guess_domains:
        total += sum(1 for s in seeds if not s.domain and
                     "name:" + re.sub(r"[^a-z0-9]", "", s.name.lower()) not in cache)
    done = 0
    stopped = False

    # 1. Seeds that already carry a domain.
    for s in seeds:
        if not s.domain:
            continue
        if s.domain in cache:
            s.blurb = cache[s.domain] or ""
            continue
        if stop_requested(should_stop):
            stopped = True
            break
        s.blurb = _scrape_blurb(s.domain)
        cache[s.domain] = s.blurb
        changed = True
        done += 1
        report_progress(progress, done, total)

    # 2. Name-only seeds: try to discover their website (in parallel).
    if guess_domains and not stopped:
        todo = []
        for s in seeds:
            if s.domain:
                continue
            key = "name:" + re.sub(r"[^a-z0-9]", "", s.name.lower())
            if key in cache:
                hit = cache[key]
                if hit:
                    s.domain, s.blurb = hit.get("domain", ""), hit.get("blurb", "")
                continue
            todo.append((s, key))

        if todo and not stop_requested(should_stop):
            from concurrent.futures import ThreadPoolExecutor, as_completed

            log.info("Looking up websites for %d name-only seeds...", len(todo))
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(guess_domain, s.name): (s, key) for s, key in todo}
                for fut in as_completed(futures):
                    s, key = futures[fut]
                    try:
                        domain, blurb = fut.result()
                    except Exception as exc:       # guess_domain swallows fetch errors
                        log.warning("Website lookup for %r failed: %s", s.name, exc)
                        domain, blurb = "", ""
                    s.domain, s.blurb = domain, blurb
                    cache[key] = {"domain": domain, "blurb": blurb} if domain else None
                    changed = True
                    done += 1
                    report_progress(progress, done, total)       # caller's thread
                    if done < total and stop_requested(should_stop):
                        log.info("Seed lookup stopped by caller at %d/%d", done, total)
                        pool.shutdown(wait=False, cancel_futures=True)
                        break

    if changed:
        _save_cache(cache)

    if seeds:
        log.info(
            "Seeds: %d total, %d with a website, %d described from their site",
            len(seeds),
            sum(1 for s in seeds if s.domain),
            sum(1 for s in seeds if s.blurb),
        )
    return seeds
