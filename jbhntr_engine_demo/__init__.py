"""jbhntr_engine_demo — the PUBLIC demo engine behind the ``jbhntr_engine`` façade.

Implements the same ``BACKEND_API`` as the private engine with deterministic,
canned behaviour so the open-source shell runs end-to-end (sign up → profile →
scan → match cards → draft documents) with no private code:

* **No private sources.** ``collect_all_sources`` returns a fixed, fictional set
  of postings (``example.com`` links). Every real connector name the shell's
  ingest tables refer to resolves to a no-op returning ``[]``.
* **No prompts, no LLM, no network calls of its own.** ``llm.is_configured`` is
  False; the demo client answers any JSON request with an empty object shaped
  by the schema. Scoring is plain keyword overlap.
* **Deterministic.** Same inputs → same outputs, every run (tests rely on it).

Select it explicitly with ``JBHNTR_ENGINE=demo``. It reports
``ENGINE_KIND = "demo"`` and the boot guard refuses it in production.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Optional

import httpx

from jbhntr_engine.types import (
    JobPosting, MatchResult, ProgressFn, RankedJob, StopFn, report_progress,
    stop_requested, tier_for_score,
)

ENGINE_KIND = "demo"
PROMPT_VERSION = "demo-1"

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2}


# --------------------------------------------------------------------------- #
# llm — a no-key stand-in. The shell checks is_configured() before LLM work;
# anything that calls the client anyway gets an empty, schema-shaped answer.
def _empty_for(schema: dict) -> Any:
    kind = (schema or {}).get("type")
    if kind == "object":
        return {k: _empty_for(v) for k, v in (schema.get("properties") or {}).items()}
    return {"array": [], "string": "", "integer": 0, "number": 0,
            "boolean": False}.get(kind, None)


class _DemoClient:
    supports_web_search = False

    def json(self, *, system: str = "", user: str = "", schema: dict | None = None,
             **_: Any) -> dict:
        return _empty_for(schema or {"type": "object"}) or {}

    def text(self, *, user: str = "", **_: Any) -> str:
        return ""


llm = SimpleNamespace(
    SCORING="scoring",
    GENERATION="generation",
    is_configured=lambda settings: False,
    get_client=lambda settings: _DemoClient(),
)


# --------------------------------------------------------------------------- #
# geo — a small public lookup (country names, a few capitals, ISO codes).
_COUNTRIES = {
    "united kingdom": "gb", "uk": "gb", "england": "gb", "london": "gb",
    "manchester": "gb", "ireland": "ie", "dublin": "ie",
    "united states": "us", "usa": "us", "new york": "us", "san francisco": "us",
    "canada": "ca", "toronto": "ca", "italy": "it", "milan": "it", "rome": "it",
    "germany": "de", "berlin": "de", "munich": "de", "france": "fr", "paris": "fr",
    "spain": "es", "madrid": "es", "barcelona": "es", "netherlands": "nl",
    "amsterdam": "nl", "sweden": "se", "stockholm": "se", "portugal": "pt",
    "lisbon": "pt",
}


def _country_of(text: str) -> str:
    hay = f" {(text or '').lower()} "
    for name in sorted(_COUNTRIES, key=len, reverse=True):   # longest name wins
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", hay):
            return _COUNTRIES[name]
    return ""


geo = SimpleNamespace(country_of=_country_of)


# --------------------------------------------------------------------------- #
# embeddings — off by default (the scan uses the live/canned path), but a
# deterministic hashed bag-of-words is provided so callers that embed still work.
_DIM = 64


def _embed_one(text: str, settings=None) -> list[float]:
    vec = [0.0] * _DIM
    for w in _words(text):
        vec[int(hashlib.sha1(w.encode()).hexdigest(), 16) % _DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


embeddings = SimpleNamespace(
    is_configured=lambda settings: False,
    model_name=lambda settings: "demo-hash-64",
    embed=lambda texts, settings: [_embed_one(t) for t in texts],
    embed_one=_embed_one,
    cosine=_cosine,
)


# --------------------------------------------------------------------------- #
# candidate / company profile / criteria — derived without a model.
@dataclass
class Candidate:
    headline: str = ""
    target_roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    seniority: str = ""
    avoid: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.headline or self.target_roles or self.skills)

    def as_prompt_block(self) -> str:
        return "; ".join(filter(None, [self.headline, ", ".join(self.target_roles)]))


@dataclass
class CompanyProfile:
    headline: str = ""
    traits: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.headline or self.traits)

    def as_prompt_block(self) -> str:
        return self.headline


@dataclass
class Criteria:
    must_have: list[dict] = field(default_factory=list)
    nice_have: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.must_have or self.nice_have)

    def all_tags(self) -> list[str]:
        return [c["tag"] for c in self.must_have] + [c["tag"] for c in self.nice_have]

    def must_tags(self) -> set[str]:
        return {c["tag"] for c in self.must_have}

    def as_prompt_block(self) -> str:
        return ", ".join(self.all_tags())

    def tag_list_for_prompt(self) -> str:
        return ", ".join(self.all_tags())

    def qualifies(self, tags: list[str], min_must: int, min_nice: int) -> bool:
        got = set(tags)
        return (len(got & self.must_tags()) >= min_must
                and len(got & {c["tag"] for c in self.nice_have}) >= min_nice)


def derive_candidate(profile, materials, settings, refresh: bool = False) -> Candidate:
    roles = list(dict.fromkeys(list(profile.search_terms) or ["Operations Manager"]))
    return Candidate(headline=(profile.objective or "")[:120], target_roles=roles[:5],
                     seniority=", ".join(profile.seniority))


def derive_company_profile(seed_labels, settings, refresh: bool = False) -> CompanyProfile:
    labels = [s for s in (seed_labels or []) if s]
    return CompanyProfile(headline=("Like " + ", ".join(labels[:3])) if labels else "")


def derive_criteria(profile, seed_labels, settings, refresh: bool = False) -> Criteria:
    must = [{"tag": t.lower().replace(" ", "-"), "description": t}
            for t in list(profile.keywords_must)[:5]]
    nice = [{"tag": t.lower().replace(" ", "-"), "description": t}
            for t in list(profile.keywords_nice)[:5]]
    return Criteria(must_have=must, nice_have=nice)


# --------------------------------------------------------------------------- #
# Matcher — keyword overlap between the candidate's targets and the posting.
class Matcher:
    def __init__(self, settings):
        self.settings = settings
        self.failures = 0

    def triage(self, jobs, profile, candidate=None, company_profile=None,
               progress: Optional[ProgressFn] = None,
               should_stop: Optional[StopFn] = None):
        if stop_requested(should_stop):
            return []
        report_progress(progress, len(jobs), len(jobs))
        return list(jobs)[:40]

    def score(self, jobs, profile, materials, feedback_examples=None,
              company_profile=None, criteria=None,
              progress: Optional[ProgressFn] = None,
              should_stop: Optional[StopFn] = None):
        wanted = _words(" ".join(list(profile.search_terms) + list(profile.keywords_must)
                                 + list(profile.keywords_nice) + [profile.objective or ""]))
        out = []
        for job in jobs:
            title = _words(job.title)
            body = _words(job.description)
            hits = sorted(wanted & (title | body))
            raw = 30 + 25 * len(wanted & title) + 5 * len(wanted & body)
            score = max(0, min(100, raw))
            match = MatchResult(
                tier=tier_for_score(score), score=score, fit_role=score, fit_candidate=score,
                reasons=(f"Demo engine: matches {', '.join(hits)}." if hits
                         else "Demo engine: no keyword overlap with your targets."),
                strengths=[f"mentions {h}" for h in hits[:3]],
                concerns=([] if hits else ["no overlap with your target roles"]),
                role=job.title, company=job.company, location=job.location,
                remote="remote" if job.is_remote else "",
                tags=[h for h in hits[:5]],
            )
            out.append((job, match))
            report_progress(progress, len(out), len(jobs))
            if stop_requested(should_stop):
                break
        return out


class Generator:
    """Template documents — no model. Shapes match the real Generator's."""

    def __init__(self, settings, drive=None):
        self.settings = settings
        self.drive = drive

    def tailor_top(self, ranked: list[RankedJob], profile, materials, limit=None) -> None:
        for r in ranked[: (limit or len(ranked))]:
            r.tailored = True
            r.documents = {"cv": materials.base_cv or "Your CV (demo engine)",
                           "cover_letter": self._letter(r.job)}

    def cover_letter(self, profile, materials, job) -> Optional[dict]:
        return {"cover_letter": self._letter(job),
                "tone_note": "Demo engine: a fixed template, not a tailored letter."}

    def refine(self, kind, previous, feedback, profile, materials, job):
        return {"content": previous or "", "change_note": "Demo engine: no revision applied."}

    @staticmethod
    def _letter(job) -> str:
        return (f"Dear {job.company or 'hiring'} team,\n\n"
                f"I am applying for the {job.title} role.\n\n"
                "(Generated by the JBHNTR demo engine.)")


# --------------------------------------------------------------------------- #
# filtering + tagging
_GENERIC_LOC = {"remote", "anywhere", "worldwide", "global", "fully"}


def is_generic_remote(loc_hay: str) -> bool:
    return not any(w not in _GENERIC_LOC for w in _WORD.findall(loc_hay or ""))


def remote_mode(job: JobPosting) -> str:
    hay = f"{job.title} {job.location} {job.description}".lower()
    if job.is_remote or "remote" in hay:
        return "remote"
    if "hybrid" in hay:
        return "hybrid"
    return "onsite" if job.location else "unknown"


def deterministic_tags(job: JobPosting) -> dict:
    code = _country_of(job.location)
    return {"countries": [code] if code else [], "remote_mode": remote_mode(job),
            "salary_min": None, "salary_max": None, "has_salary": False}


def prefilter(job: JobPosting, profile) -> bool:
    wanted = {c for c in (_country_of(loc) for loc in (profile.locations or [])) if c}
    if not wanted:
        return True
    return _country_of(job.location) in wanted or remote_mode(job) == "remote"


def cap_per_company(jobs, limit: int = 10, terms=None):
    seen: dict[str, int] = {}
    out = []
    for j in jobs:
        key = (j.company or "").lower()
        if seen.get(key, 0) < limit:
            seen[key] = seen.get(key, 0) + 1
            out.append(j)
    return out


# --------------------------------------------------------------------------- #
# seeds + sources — a fixed, fictional catalogue.
@dataclass
class Seed:
    raw: str
    name: str
    domain: str = ""

    def label(self) -> str:
        return f"{self.name} ({self.domain})" if self.domain else self.name


def resolve_seeds(raw_seeds, enrich: bool = True, guess_domains: bool = False):
    return [Seed(raw=s, name=s.strip()) for s in (raw_seeds or []) if (s or "").strip()]


_CATALOGUE = (
    ("Chief of Staff", "Northwind Labs", "London, United Kingdom", False),
    ("Head of Operations", "Northwind Labs", "Remote", True),
    ("Business Operations Manager", "Contoso Health", "Dublin, Ireland", False),
    ("Product Manager", "Contoso Health", "Berlin, Germany", False),
    ("Senior Product Manager", "Fabrikam Pay", "Milan, Italy", False),
    ("Strategy & Operations Lead", "Fabrikam Pay", "Remote", True),
    ("Program Manager", "Tailspin Mobility", "Paris, France", False),
    ("Operations Manager", "Tailspin Mobility", "Madrid, Spain", False),
    ("Data Analyst", "Litware Analytics", "Amsterdam, Netherlands", False),
    ("Marketing Manager", "Litware Analytics", "New York, United States", False),
    ("Finance Manager", "Adventure Works", "Toronto, Canada", False),
    ("People Partner", "Adventure Works", "Stockholm, Sweden", False),
)


def _canned(source: str = "demo") -> list[JobPosting]:
    out = []
    for i, (title, company, loc, remote) in enumerate(_CATALOGUE, start=1):
        out.append(JobPosting(
            source=source, title=title, company=company, location=loc,
            url=f"https://example.com/demo-jobs/{i}", is_remote=remote,
            description=(f"{company} is hiring a {title}. You will own planning, "
                         "cross-functional delivery and reporting. Demo posting "
                         "from the JBHNTR demo engine — not a real job."),
        ))
    return out


def collect_all_sources(profile, settings,
                        progress: Optional[ProgressFn] = None,
                        should_stop: Optional[StopFn] = None) -> list[JobPosting]:
    if stop_requested(should_stop):          # the one canned "source" never starts
        return []
    jobs = _canned()
    report_progress(progress, 1, 1)          # one canned "source"
    return jobs


def _none(*_a, **_k) -> list:
    return []


AGGREGATORS: dict[str, Callable] = {"demo": lambda profile, settings: _canned()}
BOARD_NAMES: tuple[str, ...] = ()
fetch_boards = _none
# Every provider name the shell's ingest tables refer to, as a no-op.
KEYED_PROVIDERS: dict[str, Callable] = {
    name: _none for name in ("careerjet", "reed", "web3career", "usajobs", "jsearch",
                             "serpapi", "francetravail", "jobtech", "bundesagentur")
}
KEYED_MAX_TERMS = 5


def http_client(timeout: float = 20.0, ua: str = "JBHNTR-demo/1.0") -> httpx.Client:
    """A plain HTTP client for the shell's own fetches (the demo engine itself
    never calls out)."""
    return httpx.Client(timeout=timeout, headers={"User-Agent": ua}, follow_redirects=True)


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


# --------------------------------------------------------------------------- #
# company ATS boards, discovery, careers pages, agencies, portals — all inert.
ATS_FETCHERS: dict[str, Callable] = {}
parse_ats_job = lambda url: ("", "", "")            # noqa: E731
board_location_index = lambda ats, org: {}          # noqa: E731
enrich_description = lambda job: False              # noqa: E731

discover_companies = lambda profile, settings, target, **kw: ([], [])   # noqa: E731
discover_suggest = lambda profile, settings, n, exemplars, exclude, **kw: []   # noqa: E731
discover_research = lambda profile, settings, n, exemplars, **kw: ""   # noqa: E731
discover_extract_companies = lambda notes, settings, exclude: []   # noqa: E731
verify_company = lambda name, slug, domain="": None   # noqa: E731


def company_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


scrape_careers = _none
AGENCY_HINTS: dict[str, Any] = {}
agency_hint_for = lambda company, country: None     # noqa: E731
agency_domain_for = lambda company, country: ""     # noqa: E731
agency_is_ignored = lambda company: False           # noqa: E731
browser_configured = lambda settings: False         # noqa: E731
browser_fetch_portal = _none
browser_debug_portal = lambda domain, settings, listing="": {}   # noqa: E731

# --------------------------------------------------------------------------- #
# engine-side helpers — the shell's fail-soft paths take over.
recover_apply_url = lambda company, title: None     # noqa: E731
panel_deliberate = lambda kind, materials, job, settings, config: None   # noqa: E731
vision_style = lambda images, settings: None        # noqa: E731
translate_terms = lambda settings, terms, language: {}   # noqa: E731
extract_posting = lambda url, page_text, settings: None   # noqa: E731


def resolve_countries(locations: list[str], settings) -> list[str]:
    return [_country_of(loc) for loc in locations]


# --- R3-16: demo equivalents of the engine-side heuristics/tables/prompts ----- #
def structured_cv(materials, job, settings, sections: list[str]) -> dict | None:
    """No prompt in the demo: None makes the shell fall back to the demo Generator."""
    return None


# No real sources, so nothing is scheduled; fallbacks keep the runner's shape.
INGEST_PLAN: dict = {
    "lane_a_aggregators": (), "localized_aggregators": frozenset(),
    "keyed_settings": {}, "source_cadence": {}, "source_countries": {},
    "default_terms": ["operations manager", "product manager"],
    "default_countries": ["United States", "United Kingdom"],
    "terms_cap": 5, "terms_max": 10, "countries_cap": 2, "countries_max": 4,
    "agency_markets": 0, "agency_n": 0,
}

AGGREGATOR_HOSTS: tuple[str, ...] = ()
AGGREGATOR_SOURCES: tuple[str, ...] = ()


def resolve_company_domain(name: str, code: str) -> str:
    return ""                                         # demo resolves nothing


def company_domain_debug(name: str, code: str) -> dict:
    return {"lookup_status": "demo", "lookup_raw": "", "lookup_domains": [],
            "guesses": [], "resolved": ""}


is_aggregator_host = lambda host: False               # noqa: E731
is_foreign_tld = lambda domain, code: False           # noqa: E731
is_unscrapable_url = lambda url: False                # noqa: E731
is_tracker_url = lambda url: False                    # noqa: E731


def extract_job_body(html: str) -> str:
    """Whole-page text (no JD heuristics in the demo)."""
    return re.sub(r"\s+", " ", strip_html(html or "")).strip()


def classify_link(url: str, client) -> str:
    """Status-code-only link check: 404/410 gone, 200 active, anything else unknown."""
    if not url:
        return "unknown"
    try:
        r = client.get(url, follow_redirects=True)
    except Exception:
        return "unknown"
    if r.status_code in (404, 410):
        return "gone"
    return "active" if r.status_code == 200 else "unknown"


aggregator_check_configured = lambda: False           # noqa: E731
aggregator_link_statuses = lambda urls: {}            # noqa: E731
aggregator_link_dead = lambda status, final_url: status in (404, 410)   # noqa: E731


def engine_logger(component: str):
    import logging
    return logging.getLogger("jbhntr.engine.demo")
