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

from jbhntr_engine import structured_cv

from .export import parse_lines

log = logging.getLogger("jbhntr.cv_build")


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


def build_cv(materials, job, settings, config) -> str | None:
    """Generate a tailored CV as canonical plain text, or None to let the caller
    fall back to the legacy generator. The schema, prompt and model call are
    engine-side (``jbhntr_engine.structured_cv``, R3-16); the shell owns the
    baseline-sections parse and the serialisation its renderer reads."""
    try:
        sections = original_sections(getattr(materials, "base_cv", "") or "")
        cv = structured_cv(materials, job, settings, sections)
        if not isinstance(cv, dict) or not cv.get("sections"):
            return None
        text = serialize(cv)
        return text if text.strip() else None
    except Exception as exc:
        log.warning("Structured CV build failed: %s", exc)
        return None
