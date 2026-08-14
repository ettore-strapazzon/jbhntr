"""Structured CV generation.

Instead of asking a model for free-text (which drifts in format and quietly
drops roles and metrics when it "summarises"), we ask it to fill a STRUCTURED CV
— explicit fields for the headline, each employer's positions, each position's
bullets, education and skills. That makes three things reliable:

* honesty — the headline is its own field, ruled to be the candidate's real
  identity, never the target job's title;
* completeness — every role and every bullet is a discrete field, so nothing
  gets lost in a prose rewrite;
* structure — we serialise the fields to a canonical plain-text layout that the
  shared renderer (export.parse_lines) parses exactly, so the PDF/preview are
  deterministic rather than heuristic.

Baseline rule: keep the SAME sections the candidate's own CV has. A model may
suggest ONE extra section, flagged (added=true), only when the original is thin
for the role — never silently restructure.
"""

from __future__ import annotations

import logging

from jobhunter import llm

from .export import parse_lines

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


def original_sections(base_cv: str) -> list[str]:
    """The section headings in the candidate's uploaded CV — the baseline set the
    tailored CV must keep."""
    if not base_cv:
        return []
    seen, out = set(), []
    for kind, text in parse_lines(base_cv):
        if kind == "heading":
            key = text.strip().lower()
            if key not in seen:
                seen.add(key)
                out.append(text.strip())
    return out


def _clean(s) -> str:
    return (s or "").strip() if isinstance(s, str) else ""


def serialize(cv: dict) -> str:
    """Render the structured CV to canonical plain text that export.parse_lines
    parses exactly: name / headline / contact, then per section a heading and its
    content, with 'Employer - Location', an optional description line, and each
    position as 'Title (Dates)' followed by '- ' bullets."""
    lines: list[str] = []
    name = _clean(cv.get("name"))
    if name:
        lines.append(name)
    headline = _clean(cv.get("headline"))
    if headline:
        lines.append(headline)
    contact = _clean(cv.get("contact"))
    if contact:
        lines.append(contact)
    # Opening summary paragraph — headingless, right under the contact line.
    summary = _clean(cv.get("summary"))
    if summary:
        lines.append("")
        lines.append(summary)

    for sec in cv.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = _clean(sec.get("title"))
        stype = _clean(sec.get("type")) or "bullets"
        lines.append("")
        if title:
            lines.append(title)
        if stype == "summary":
            text = _clean(sec.get("text"))
            if text:
                lines.append(text)
        elif stype == "skills":
            for ln in sec.get("lines") or []:
                if _clean(ln):
                    lines.append(_clean(ln))
        elif stype == "experience":
            for e in sec.get("entries") or []:
                if not isinstance(e, dict):
                    continue
                org = _clean(e.get("org"))
                loc = _clean(e.get("location"))
                if not org:
                    continue
                lines.append(f"{org} - {loc}" if loc else org)
                desc = _clean(e.get("description"))
                if desc:
                    lines.append(desc if desc.endswith((".", "!", "?")) else desc + ".")
                for p in e.get("positions") or []:
                    if not isinstance(p, dict):
                        continue
                    ptitle = _clean(p.get("title"))
                    dates = _clean(p.get("dates"))
                    if not ptitle and not dates:
                        continue
                    lines.append(f"{ptitle} ({dates})" if dates else ptitle)
                    for b in p.get("bullets") or []:
                        if _clean(b):
                            lines.append("- " + _clean(b))
        else:  # bullets (and any unknown type)
            for b in sec.get("bullets") or []:
                if _clean(b):
                    lines.append("- " + _clean(b))
    return "\n".join(lines).strip() + "\n"


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


def build_cv(materials, job, settings, config) -> str | None:
    """Generate a tailored CV as canonical plain text, or None to let the caller
    fall back to the legacy generator."""
    try:
        client = llm.get_client(settings)
        sections = original_sections(getattr(materials, "base_cv", "") or "")
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
        text = serialize(cv)
        return text if text.strip() else None
    except Exception as exc:
        log.warning("Structured CV build failed: %s", exc)
        return None
