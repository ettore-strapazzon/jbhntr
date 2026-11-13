"""Company website-domain resolution heuristics (PRIVATE engine side).

Carved out of ``web/app/services/companies_service.py`` (R3-16): the aggregator
host list, the country->TLD map, the Clearbit lookup and the guess/score/probe
order that turns a company name into its real website, so the careers-page and
ATS probes have something to work on. The shell reaches these only through the
``jbhntr_engine`` façade (``resolve_company_domain``, ``company_domain_debug``,
``AGGREGATOR_HOSTS``, ``is_aggregator_host``, ``is_foreign_tld``).
"""

from __future__ import annotations

import re

from jobhunter.sources import agency_hints as _agency
from jobhunter.sources import base as _base

# Hosts that are NOT an employer's own site — aggregators and their redirect
# trackers. A corpus URL on one of these gives us no employer domain, so we must
# fall through to Clearbit resolution instead of mistaking the tracker for the
# company's website (jobviewtrack.com is careerjet's redirect — the #1 offender).
AGGREGATOR_HOSTS: tuple[str, ...] = (
    "careerjet", "jobviewtrack", "adzuna", "jooble", "indeed", "linkedin",
    "glassdoor", "monster", "totaljobs", "jobrapido", "neuvoo", "talent.com",
    "ziprecruiter", "simplyhired", "whatjobs", "jobisjob", "trovit", "jobsora",
    "stepstone", "infojobs", "lever.co", "greenhouse.io", "myworkdayjobs",
    "bebee", "joblift", "jobtome", "learn4good", "kariera",
)

# ISO country code -> the TLD that market's companies most often use, for domain
# guessing when the corpus gives us no employer domain (careerjet's thin tail).
_COUNTRY_TLD = {
    "it": "it", "fr": "fr", "de": "de", "es": "es", "nl": "nl", "se": "se",
    "pl": "pl", "pt": "pt", "dk": "dk", "no": "no", "fi": "fi", "at": "at",
    "ch": "ch", "be": "be", "ie": "ie", "uk": "co.uk", "gb": "co.uk",
    "br": "com.br", "mx": "com.mx", "ca": "ca",
}

_CLEARBIT = "https://autocomplete.clearbit.com/v1/companies/suggest"


def is_aggregator_host(host: str) -> bool:
    """True when ``host`` is an aggregator / tracker, not an employer's own site."""
    h = (host or "").lower()
    return any(a in h for a in AGGREGATOR_HOSTS)


def is_foreign_tld(domain: str, code: str) -> bool:
    """True when a country-targeted resolve landed on a DIFFERENT country's ccTLD
    (an Italy scrape resolving to gottardo.de / staffspa.co.uk) — a mis-resolution
    to skip. Generic TLDs (com/io/co/ai…) and the target market's own ccTLD pass."""
    if not code:
        return False
    last = (domain or "").lower().rsplit(".", 1)[-1]
    if len(last) != 2 or last in ("io", "co", "ai"):   # 2-letter generics aren't ccTLDs
        return False
    return last != code.lower()


def _guess_domains(name: str, code: str) -> list[str]:
    """Candidate website domains for a company we have no domain for: the
    squished name across common TLDs, market TLD first. Best-effort — wrong
    guesses simply don't resolve or yield no ATS board (verify only accepts a
    board that actually returns jobs), so there's no false-positive risk."""
    base = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if len(base) < 2:
        return []
    tlds = ["com", "io", "co", "ai"]
    t = _COUNTRY_TLD.get((code or "").lower())
    if t and t not in tlds:
        tlds.insert(0, t)          # a local company is likelier foo.it than foo.com
    return [f"{base}.{tld}" for tld in tlds]


def _live_domain(guesses: list[str]) -> str:
    """First candidate domain that answers an HTTP request — the company's real
    site, so verify() can probe its careers page. Short timeout; stops at first."""
    for d in guesses:
        try:
            with _base.http_client(timeout=6.0) as c:
                r = c.get(f"https://{d}", follow_redirects=True)
            if r.status_code < 400:
                return d
        except Exception:
            continue
    return ""


def _clearbit_domains(name: str) -> list[str]:
    """Free, keyless company-name -> domain suggestions (Clearbit autocomplete),
    best-match first. This is the real fix for the long tail whose domain doesn't
    resemble its name (Satispay->satispay.com, not the .it a guess would try).
    Fail-soft: [] on any error / rate-limit, so we fall back to TLD guessing."""
    try:
        with _base.http_client(timeout=8.0) as c:
            r = c.get(_CLEARBIT, params={"query": name})
        if r.status_code != 200:
            return []
        return [d["domain"] for d in r.json()
                if isinstance(d, dict) and d.get("domain")]
    except Exception:
        return []


def resolve_company_domain(name: str, code: str) -> str:
    """Best-effort employer domain for a company we have none for. Ask Clearbit
    (real, name-matched domains), rank them, append TLD guesses as a fallback, and
    return the first candidate that actually answers HTTP. '' if none resolve."""
    # A pinned override wins outright (fixes Clearbit mis-resolutions like
    # Orienta -> a Malaysian newspaper, Synergie's real site synergie-italia.it).
    pinned = _agency.domain_for(name, code)
    if pinned:
        return pinned

    norm = re.sub(r"[^a-z0-9]+", "", (name or "").lower())

    def _score(dom: str) -> int:
        base = re.sub(r"[^a-z0-9]+", "", dom.split(".")[0].lower())
        s = 50 if base == norm else (20 if norm and norm in base else 0)
        t = _COUNTRY_TLD.get((code or "").lower())
        if t and dom.endswith("." + t):
            s += 5
        return -s

    cands = sorted(_clearbit_domains(name), key=_score) + _guess_domains(name, code)
    # For an in-country company, try the market-TLD of the COMPANY NAME first
    # (Orienta -> orienta.it), ahead of Clearbit — whose top hit for an ambiguous
    # name can be a wrong foreign site (Orienta -> orientaldaily.com.my). A staffing
    # agency's localised portal (randstad.it) also carries THIS country's jobs.
    t = _COUNTRY_TLD.get((code or "").lower())
    if t:
        name_slug = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
        if len(name_slug) >= 2:
            cands = [f"{name_slug}.{t}"] + cands
    seen: set[str] = set()
    ordered: list[str] = []
    for d in cands:
        if d and d not in seen:
            seen.add(d)
            ordered.append(d)
    return _live_domain(ordered[:6])


def company_domain_debug(name: str, code: str) -> dict:
    """Operator diagnostics for one name: the raw Clearbit answer, the ranked
    Clearbit domains, the TLD guesses and the final resolution."""
    raw_status = raw = ""
    try:
        with _base.http_client(timeout=8.0) as c:
            r = c.get(_CLEARBIT, params={"query": name})
        raw_status = str(r.status_code)
        raw = (str(r.json())[:300] if r.status_code == 200 else (r.text or "")[:300])
    except Exception as exc:
        raw_status = f"EXCEPTION {type(exc).__name__}: {str(exc)[:160]}"
    return {"lookup_status": raw_status, "lookup_raw": raw,
            "lookup_domains": _clearbit_domains(name),
            "guesses": _guess_domains(name, code),
            "resolved": resolve_company_domain(name, code)}
