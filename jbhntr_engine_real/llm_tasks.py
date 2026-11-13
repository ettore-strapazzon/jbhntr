"""Small LLM tasks carved out of shell services (repo-split step 1).

Each one is a prompt + schema that is engine IP, previously embedded in a
DB-owning shell service. The shell keeps the DB/HTTP half and calls these
through the ``jbhntr_engine`` façade:

* ``resolve_countries``  ← ``web/app/services/corpus_service._resolve_country_batch``
* ``translate_terms``    ← ``web/app/services/term_localize._translate``
* ``extract_posting``    ← ``web/app/services/import_service._extract_posting``
"""

from __future__ import annotations

import logging

from jobhunter import llm
from jobhunter.models import JobPosting

log = logging.getLogger("jbhntr.engine.tasks")

# --------------------------------------------------------------------------- #
# Country resolution for the long tail of locations the alias maps can't place.
_COUNTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "code": {
                        "type": "string",
                        "description": "ISO 3166-1 alpha-2 country code, lowercase "
                                       "(e.g. 'gb', 'it', 'us'). Empty string if the "
                                       "location is remote/global/anywhere or names "
                                       "no identifiable country.",
                    },
                },
                "required": ["index", "code"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

_GEO_SYS = (
    "You map job-posting location strings to a single country. For each numbered "
    "location return its ISO 3166-1 alpha-2 code in lowercase. If the location is "
    "remote/global/anywhere, or names no identifiable country, return an empty "
    "string. Judge only the place named — do not guess from anything else. Return "
    "exactly one result per input index."
)


def resolve_countries(locations: list[str], settings) -> list[str]:
    """LLM: location strings -> ISO alpha-2 codes (aligned to input order).

    Returns "" for any it can't place. Never raises — a failed batch just yields
    all-empty, so those rows are marked checked and simply carry no country tag.
    """
    listing = "\n".join(f"{i}. {loc}" for i, loc in enumerate(locations))
    try:
        data = llm.get_client(settings).json(
            system=_GEO_SYS, user="Locations:\n" + listing,
            schema=_COUNTRY_SCHEMA, tier=llm.SCORING, max_tokens=1500)
    except Exception as exc:
        log.warning("Country-resolve batch failed (%d locations): %s", len(locations), exc)
        return ["" for _ in locations]

    out = ["" for _ in locations]
    for item in data.get("results", []):
        i = item.get("index")
        code = (item.get("code") or "").strip().lower()
        if isinstance(i, int) and 0 <= i < len(out) and len(code) == 2 and code.isalpha():
            out[i] = code
    return out


# --------------------------------------------------------------------------- #
# Role-title localization for non-English markets.
_TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "variants": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["term", "variants"],
            },
        }
    },
    "required": ["results"],
}


def translate_terms(settings, terms: list[str], language: str) -> dict[str, list[str]]:
    """LLM-translate each role title into 1-3 realistic local variants."""
    system = (
        f"You localize job-role titles into {language} as they actually appear in "
        f"real {language} job postings. For each title give 1-3 common local "
        "variants a candidate would search — the natural translation(s), plus the "
        "English form ONLY if it's genuinely common locally (e.g. 'Chief of Staff' "
        "is often kept in English in Italian startups). Titles only, no extra words."
    )
    user = "Localize these role titles:\n" + "\n".join(f"- {t}" for t in terms)
    try:
        out = llm.get_client(settings).json(
            system=system, user=user, schema=_TRANSLATE_SCHEMA, tier=llm.SCORING,
            max_tokens=1200, cache_system=False)
    except Exception as exc:
        log.warning("term localization failed (%s): %s", language, exc)
        return {}
    mapped: dict[str, list[str]] = {}
    for row in (out or {}).get("results", []):
        term = (row.get("term") or "").strip()
        variants = [str(v).strip() for v in (row.get("variants") or []) if str(v).strip()]
        if term and variants:
            mapped[term] = variants
    return mapped


# --------------------------------------------------------------------------- #
# Structure one imported job page into a posting.
_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_job": {"type": "boolean",
                   "description": "true only if the page is a single job posting"},
        "title": {"type": "string"},
        "company": {"type": "string"},
        "location": {"type": "string",
                     "description": "city/country, or 'Remote', as stated"},
        "description": {"type": "string",
                        "description": "the full role description text"},
    },
    "required": ["is_job", "title", "company", "location", "description"],
    "additionalProperties": False,
}


def extract_posting(url: str, page_text: str, settings) -> JobPosting | None:
    """Structure a single job page's visible text into a JobPosting.

    Returns None when the page is not a single job posting. LLM/transport errors
    propagate — the shell maps them to a user-facing message.
    """
    data = llm.get_client(settings).json(
        system="You extract a single job posting's fields from raw page text. "
               "If the page is not a job posting, set is_job=false.",
        user=f"Page URL: {url}\n\nPage text:\n{page_text}",
        schema=_EXTRACT_SCHEMA, tier=llm.SCORING, max_tokens=2000, cache_system=False)
    if not data.get("is_job") or not (data.get("title") or "").strip():
        return None
    loc = (data.get("location") or "").strip()
    return JobPosting(
        source="import", title=(data.get("title") or "").strip()[:300],
        company=(data.get("company") or "").strip()[:200], location=loc[:200],
        description=(data.get("description") or "").strip(), url=url,
        is_remote="remote" in loc.lower(),
    )
