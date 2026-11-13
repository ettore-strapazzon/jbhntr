"""Structured-CV generation prompt (PRIVATE engine side).

Carved out of ``web/app/services/cv_build.py`` (R3-16): the structured CV
schema, the honesty/completeness/section-preservation system prompt and the
model call. The shell keeps the baseline-sections parse and the serialiser
(coupled to its export renderer) and calls ``jbhntr_engine.structured_cv``.
"""

from __future__ import annotations

import logging

from jobhunter import llm

log = logging.getLogger("jbhntr.cv_build")

# Natural, guided schema. It nests deeper than strict json-schema mode allows, so
# llm.json falls back to prompt-guided JSON — hence every consumer below reads
# defensively with .get() and tolerates missing/renamed fields.
_POSITION = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "dates": {"type": "string", "description": "e.g. 'Nov 2022 - Present'"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "bullets"],
}
_ENTRY = {
    "type": "object",
    "properties": {
        "org": {"type": "string"},
        "location": {"type": "string"},
        "description": {"type": "string",
                        "description": "the company's one-line description, if the "
                                       "source CV has one; else empty"},
        "positions": {"type": "array", "items": _POSITION},
    },
    "required": ["org", "positions"],
}
_SECTION = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "heading in the candidate's own "
                  "wording, e.g. SELECTED HIGHLIGHTS / PROFESSIONAL EXPERIENCE / "
                  "EDUCATION / SKILLS"},
        "type": {"type": "string", "enum": ["summary", "bullets", "experience", "skills"]},
        "text": {"type": "string", "description": "for a 'summary' section"},
        "bullets": {"type": "array", "items": {"type": "string"},
                    "description": "for a 'bullets' section"},
        "lines": {"type": "array", "items": {"type": "string"},
                  "description": "for a 'skills' section, e.g. 'Data: SQL, Tableau'"},
        "entries": {"type": "array", "items": _ENTRY,
                    "description": "for an 'experience' section"},
        "added": {"type": "boolean",
                  "description": "true only if this section was NOT in the original CV "
                                 "and you are suggesting it"},
    },
    "required": ["title", "type"],
}
CV_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "headline": {"type": "string",
                     "description": "the candidate's REAL professional identity — never "
                                    "the target job's title or a title they have not held"},
        "contact": {"type": "string",
                    "description": "one line, ' | '-separated: phone, email, links, languages"},
        "summary": {"type": "string",
                    "description": "the opening professional-summary paragraph that leads "
                                   "the CV, with NO heading (as most CVs have right under "
                                   "the contact line). Keep it if the candidate's CV or "
                                   "about-me supports one; tailor it to the role."},
        "sections": {"type": "array", "items": _SECTION},
    },
    "required": ["name", "headline", "sections"],
}


def _system(materials, sections: list[str]) -> str:
    ctx = getattr(materials, "combined_context", lambda: "")() or "(none)"
    skeleton = ", ".join(sections) if sections else "(infer from the CV)"
    return (
        "You are an expert career writer. Fill the structured CV for a specific "
        "job using ONLY the candidate's real materials. Rules:\n"
        "- HONEST HEADLINE: 'headline' is the candidate's genuine professional "
        "identity and seniority, based on their real roles — NEVER the target "
        "job's title or a title they have not held. Angle the wording toward the "
        "role; never misrepresent.\n"
        "- Never invent employers, roles, dates, metrics or credentials. Every "
        "line must be defensible in an interview.\n"
        "- PRESERVE ALL SUBSTANCE: keep every employer, every position and every "
        "quantified achievement (numbers, %, $, EUR, deal/team/client sizes, "
        "market-cap, timeframes) the materials contain. Keep each employer's "
        "one-line description if the source CV has one. Reframe and reorder to fit "
        "the job; do not shorten or drop content. Comparable depth per role.\n"
        "- OPENING SUMMARY: if the candidate's CV opens with a professional-summary "
        "paragraph (or their about-me supports one), fill the 'summary' field with "
        "it, tailored to this role. Do not drop it.\n"
        f"- KEEP THE SAME SECTIONS as the candidate's CV: {skeleton}. You may add "
        "at most ONE extra section, flagged added=true, only if the original is "
        "genuinely thin for this role; otherwise add nothing.\n"
        "- Draw on ALL the materials below — the CV(s) for facts and history, the "
        "about-me and past cover letters for the candidate's own voice and framing "
        "— to write the strongest honest CV. Lead with the most relevant "
        "experience. Plain text field values (no markdown). Dates like "
        "'Nov 2022 - Present'.\n\n"
        "## Candidate materials\n" + ctx
    )


def structured_cv(materials, job, settings, sections: list[str]) -> dict | None:
    """Fill the structured CV for ``job`` from the candidate's materials. Returns the
    dict (name/headline/contact/summary/sections) or None on any failure, so the
    caller falls back to the legacy generator. Never raises."""
    try:
        client = llm.get_client(settings)
        user = (
            "Fill the CV for this job.\n\n"
            f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n"
            f"Description:\n{(job.description or '')[:6000] or '(no description available)'}"
        )
        cv = client.json(system=_system(materials, sections), user=user,
                         schema=CV_SCHEMA, tier=llm.GENERATION, max_tokens=8000,
                         cache_system=False)
        if not isinstance(cv, dict) or not cv.get("sections"):
            return None
        return cv
    except Exception as exc:
        log.warning("Structured CV build failed: %s", exc)
        return None
