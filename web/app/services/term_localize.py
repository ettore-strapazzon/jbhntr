"""Localize role titles into a market's language for the ingest.

Non-English markets post jobs in their own language — an Italian company hiring a
head of operations posts "Responsabile Operativo" / "Direttore Operativo", not
the English title. Querying only English terms therefore misses most of the
market. This translates each role into the target country's language (a bounded,
cached LLM call) so the ingest asks in the right language, per country.
"""

from __future__ import annotations

import logging

from jbhntr_engine import translate_terms
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

def _translate(settings, terms: list[str], language: str) -> dict[str, list[str]]:
    """LLM-translate each role title into 1-3 realistic local variants.
    The prompt lives in the engine (jbhntr_engine.translate_terms)."""
    return translate_terms(settings, terms, language)


def localized_terms(db: DbSession, settings, terms: list[str], code: str) -> list[str]:
    """Localized variants of `terms` for the given country code, cached per
    (term, lang). Returns [] for English-language markets or when no LLM.

    Uses its OWN short-lived DB session for the translation cache, so it can never
    touch (or poison) the ingest's transaction — localization must never break the
    ingest. Fully fail-soft: any error just falls back to English-only terms. The
    passed `db` is intentionally unused for isolation."""
    language = LANG_BY_CODE.get((code or "").lower())
    if not language or not terms:
        return []
    from ..db import SessionLocal

    want = set(terms)
    cached: dict[str, list[str]] = {}
    s = SessionLocal()
    try:
        cached = {tr.term: (tr.variants or [])
                  for tr in s.query(TermTranslation).filter(TermTranslation.lang == code)
                  if tr.term in want}
        missing = [t for t in terms if t not in cached]
        if missing:
            fresh = _translate(settings, missing, language)
            for term in missing:
                cached[term] = fresh.get(term, [])
                try:
                    with s.begin_nested():
                        s.add(TermTranslation(term=term, lang=code, variants=cached[term]))
                except IntegrityError:
                    pass                    # raced/duplicate — fine
            s.commit()
    except Exception as exc:
        log.warning("term localization failed for %s: %s", code, exc)
        return []
    finally:
        s.close()

    out: list[str] = []
    for t in terms:
        for v in cached.get(t, []):
            if v not in terms and v not in out:
                out.append(v)
    return out
