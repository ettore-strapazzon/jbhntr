"""Localize role titles into a market's language for the ingest.

Non-English markets post jobs in their own language — an Italian company hiring a
head of operations posts "Responsabile Operativo" / "Direttore Operativo", not
the English title. Querying only English terms therefore misses most of the
market. This translates each role into the target country's language (a bounded,
cached LLM call) so the ingest asks in the right language, per country.
"""

from __future__ import annotations

import logging

from jobhunter import llm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ..models import TermTranslation

log = logging.getLogger("jbhntr.localize")

# Country code -> language to translate role titles into. English-language markets
# are omitted (no localization needed).
LANG_BY_CODE = {
    "it": "Italian", "fr": "French", "de": "German", "es": "Spanish",
    "pt": "Portuguese", "nl": "Dutch", "se": "Swedish", "pl": "Polish",
    "dk": "Danish", "no": "Norwegian", "fi": "Finnish", "gr": "Greek",
    "ro": "Romanian", "cz": "Czech", "at": "German", "ch": "German",
    "be": "Dutch", "br": "Portuguese", "mx": "Spanish",
}

_SCHEMA = {
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


def _translate(settings, terms: list[str], language: str) -> dict[str, list[str]]:
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
            system=system, user=user, schema=_SCHEMA, tier=llm.SCORING,
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


def localized_terms(db: DbSession, settings, terms: list[str], code: str) -> list[str]:
    """Localized variants of `terms` for the given country code, cached per
    (term, lang). Returns [] for English-language markets or when no LLM."""
    language = LANG_BY_CODE.get((code or "").lower())
    if not language or not terms:
        return []

    cached = {tr.term: (tr.variants or [])
              for tr in db.query(TermTranslation).filter(TermTranslation.lang == code)
              if tr.term in set(terms)}
    missing = [t for t in terms if t not in cached]
    if missing:
        fresh = _translate(settings, missing, language)
        for term in missing:
            variants = fresh.get(term, [])
            cached[term] = variants
            try:
                with db.begin_nested():
                    db.add(TermTranslation(term=term, lang=code, variants=variants))
            except IntegrityError:
                pass                        # raced/duplicate — fine
        db.commit()

    out: list[str] = []
    for t in terms:
        for v in cached.get(t, []):
            if v not in terms and v not in out:
                out.append(v)
    return out
