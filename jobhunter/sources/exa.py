"""Exa (exa.ai) — a similar-company candidate generator for discovery (Lane C).

Exa is **not** a job feed. Given a seed company's URL, `findSimilar` returns other
company sites of the same character; a profile-derived query broadens the net.
Whatever comes back is an *unverified candidate*: `discover.verify()` still probes
each one for a real ATS board before it is ever watched, so an invented or
no-longer-hiring company simply fails and never reaches the registry.

Everything here fails soft — a missing key, a network error or an exhausted
monthly budget returns `[]`, so discovery always degrades to the LLM round rather
than breaking.

Pricing (2026): $7 / 1k searches. We never request page contents, so each API
call is exactly one search (~$0.007). A small counter in ``data/exa_usage.json``
caps the month's spend at ``settings.exa_monthly_budget_usd`` and then blocks
further calls until the next month.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from ..config import DATA_DIR
from ..seeds import domain_of, name_from_domain
from .base import http_client

log = logging.getLogger("jobhunter.sources.exa")

API_BASE = "https://api.exa.ai"
COST_PER_SEARCH_USD = 0.007          # $7 / 1k searches; contents not requested
USAGE_FILE = DATA_DIR / "exa_usage.json"


# --------------------------------------------------------------------------- #
# Monthly budget counter
# --------------------------------------------------------------------------- #
def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load_usage() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _searches_this_month() -> int:
    return int((_load_usage().get(_month_key()) or {}).get("searches", 0))


def _budget_ok(settings) -> bool:
    """False once this month's Exa spend would meet the budget. <=0 = uncapped."""
    budget = float(getattr(settings, "exa_monthly_budget_usd", 0) or 0)
    if budget <= 0:
        return True
    return _searches_this_month() * COST_PER_SEARCH_USD < budget


def _record_call(n: int = 1) -> None:
    usage = _load_usage()
    month = usage.get(_month_key()) or {}
    month["searches"] = int(month.get("searches", 0)) + n
    usage[_month_key()] = month
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(json.dumps(usage, indent=0), encoding="utf-8")
    except Exception:  # pragma: no cover - a write failure must not break discovery
        pass


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def is_configured(settings) -> bool:
    return bool(getattr(settings, "exa_api_key", ""))


def _as_url(x: str) -> str:
    x = (x or "").strip()
    return x if x.startswith(("http://", "https://")) else "https://" + x


def _norm_domains(domains) -> list[str]:
    out: list[str] = []
    for d in domains or []:
        dd = domain_of(d) if d else ""
        if dd and dd not in out:
            out.append(dd)
    return out


def _slug(domain: str) -> str:
    return re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())


def _clean_name(title: str) -> str:
    """Exa returns page titles ('Stripe | Payments Infrastructure'); keep the
    company part before the first spaced separator."""
    head = re.split(r"\s[|\-–—:·]\s", (title or "").strip(), maxsplit=1)[0]
    return re.sub(r"\s+", " ", head).strip()[:120]


def _to_candidates(results, why: str, exclude_domains) -> list[dict]:
    """Map Exa results to the SUGGEST_SCHEMA candidate shape, deduped by domain."""
    excl = set(_norm_domains(exclude_domains))
    out: list[dict] = []
    seen: set[str] = set()
    for r in results or []:
        url = (r.get("url") or "").strip()
        dom = domain_of(url) if url else ""
        if not dom or dom in excl or dom in seen:
            continue
        seen.add(dom)
        name = _clean_name(r.get("title") or "") or name_from_domain(dom)
        out.append({
            "name": name,
            "slug": _slug(dom),
            "domain": dom,
            "url": url,
            "why": why,
            "source_hint": "exa",
        })
    return out


def _post(settings, endpoint: str, payload: dict) -> dict | None:
    """POST to the Exa API. Returns parsed JSON, or None on budget/error (fail soft)."""
    if not _budget_ok(settings):
        log.info("Exa monthly budget (~$%.0f) reached; falling back to the LLM round.",
                 float(getattr(settings, "exa_monthly_budget_usd", 0) or 0))
        return None
    try:
        with http_client(timeout=20.0) as client:
            resp = client.post(
                f"{API_BASE}/{endpoint}",
                headers={"x-api-key": settings.exa_api_key,
                         "Content-Type": "application/json"},
                json=payload,
            )
        resp.raise_for_status()
        _record_call()                        # a billable search happened
        return resp.json()
    except Exception as exc:
        log.warning("Exa %s failed: %s", endpoint, exc)
        return None


def find_similar(settings, url: str, n: int | None = None,
                 exclude_domains=()) -> list[dict]:
    """Companies similar to a seed company URL. [] on any failure."""
    if not is_configured(settings) or not (url or "").strip():
        return []
    n = int(n or getattr(settings, "exa_similar_per_seed", 25))
    src = _as_url(url)
    payload = {
        "url": src,
        "numResults": max(1, min(n, 100)),
        "category": "company",
        "excludeSourceDomain": True,          # never return the seed itself
    }
    norm = _norm_domains(exclude_domains)
    if norm:
        payload["excludeDomains"] = norm
    data = _post(settings, "findSimilar", payload)
    if not data:
        return []
    seed_name = name_from_domain(domain_of(src)) or "your seeds"
    return _to_candidates(data.get("results", []), f"Similar to {seed_name}",
                          exclude_domains)


def search_companies(settings, query: str, n: int = 25,
                     exclude_domains=()) -> list[dict]:
    """Companies matching a natural-language profile query. [] on any failure."""
    if not is_configured(settings) or not (query or "").strip():
        return []
    payload = {
        "query": query.strip(),
        "numResults": max(1, min(int(n), 100)),
        "type": "auto",
        "category": "company",
    }
    norm = _norm_domains(exclude_domains)
    if norm:
        payload["excludeDomains"] = norm
    data = _post(settings, "search", payload)
    if not data:
        return []
    return _to_candidates(data.get("results", []), "Matches your search profile",
                          exclude_domains)
