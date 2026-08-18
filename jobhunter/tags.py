"""Deterministic tags for a job posting — no AI, computed once at ingestion.

These are the *reliable* dimensions (geography, work mode, salary) that are safe
to use as hard filters. Fuzzy dimensions (seniority band, vertical, function)
are deliberately NOT here: they belong to the embedding/LLM stages, because a
wrong tag used as a hard filter silently drops good jobs — the false-negative
error class this product avoids.

See docs/ARCHITECTURE.md → "Scaling: the shared job corpus".
"""

from __future__ import annotations

import re

from . import geo
from .models import JobPosting

REMOTE_MODES = ("remote", "hybrid", "onsite", "unknown")

# Multilingual, because a global corpus is full of non-English postings. Italian
# ("smart working", "da remoto", "ibrido", "in sede"), plus common French/German/
# Spanish/Portuguese terms — otherwise a Milan/Madrid hybrid role reads as
# "onsite" purely because it doesn't use the English word, and remote/hybrid
# filtering badly undercounts outside the US/UK.
_HYBRID = (
    "hybrid",
    "ibrid", "smart working", "lavoro agile",                                      # it (ibrid* stem)
    "hybride", "modèle hybride",                                                    # fr
    "mobiles arbeiten",                                                             # de
    "híbrid", "hibrid",                                                             # es (híbrid* stem)
)
_REMOTE = (
    "remote", "work from home", "work-from-home", "wfh", "fully remote",
    "anywhere", "distributed", "full remote",
    "da remoto", "in remoto", "lavoro da remoto", "telelavoro", "remoto",          # it
    "télétravail", "à distance", "en télétravail",                                 # fr
    "fernarbeit", "remote-arbeit",                                                  # de
    "teletrabajo", "trabajo remoto", "en remoto", "a distancia",                   # es
    "trabalho remoto", "remoto",                                                   # pt
)
_ONSITE = (
    "on-site", "on site", "onsite", "in office", "in-office",
    "in the office", "on-premise", "on premises",
    "in sede", "in presenza", "presso la sede",                                    # it
    "sur site", "présentiel", "sur place",                                         # fr
    "vor ort",                                                                     # de
    "presencial", "en oficina", "en la oficina",                                   # es
)

# A plausible annual-salary bound. The floor sits above four-digit years and
# small IDs ("Req 2024", "id 4501") so a naive digit scan doesn't tag them as
# pay — a wrong salary_min would then wrongly trip a below-floor penalty. The
# cost is that sub-10k figures (rare monthly/hourly quotes) aren't captured.
_SALARY_MIN = 10_000
_SALARY_MAX = 10_000_000


def remote_mode(job: JobPosting) -> str:
    """One of remote/hybrid/onsite/unknown from flags + wording.

    Hybrid wins over remote (hybrid ads usually also say "remote"); an explicit
    source flag or clear remote wording beats onsite.
    """
    blob = f"{job.title} {job.location} {job.description}".lower()
    if any(w in blob for w in _HYBRID):
        return "hybrid"
    if job.is_remote or any(w in blob for w in _REMOTE):
        return "remote"
    if any(w in blob for w in _ONSITE):
        return "onsite"
    # A posting that names a real, specific place and says nothing about remote or
    # hybrid is almost always on-site there. Inferring this (instead of leaving the
    # bulk of the corpus "unknown") makes on-site/hybrid filtering actually work.
    if geo.country_of(job.location):
        return "onsite"
    return "unknown"


def salary_range(job: JobPosting) -> tuple[int | None, int | None]:
    """(min, max) annual salary if the posting states plausible figures.

    Adzuna gives "50000-70000"; free-text ads give "$90k–$120k", "€45.000".
    Undisclosed salary stays (None, None) — never inferred, never penalised.
    """
    text = job.salary_text or ""
    if not text:
        return (None, None)
    nums: list[int] = []
    # Match numbers with optional thousands separators and an optional k suffix.
    for m in re.finditer(r"(\d[\d.,]*)\s*([kK])?", text):
        raw, k = m.group(1), m.group(2)
        digits = raw.replace(".", "").replace(",", "")
        if not digits.isdigit():
            continue
        val = int(digits)
        if k:
            val *= 1000
        if _SALARY_MIN <= val <= _SALARY_MAX:
            nums.append(val)
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


def deterministic_tags(job: JobPosting) -> dict:
    """All no-AI tags for one posting, ready to store on the corpus row."""
    code = geo.country_of(job.location)
    lo, hi = salary_range(job)
    return {
        "countries": [code] if code else [],
        "remote_mode": remote_mode(job),
        "salary_min": lo,
        "salary_max": hi,
        "has_salary": lo is not None,
    }
