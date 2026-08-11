"""Vision-based CV style extraction.

Programmatic text extraction (pypdf) is blind to a CV's design. A vision model
*sees* the rendered page — fonts, colours, heading treatment, layout — the way a
person (or claude.ai) does, so it recovers formatting a text parser can't. We
render the uploaded CV's first page to a PNG (PyMuPDF, a pure wheel — no system
libraries), send it to a vision-capable model with a strict schema, and get back
a small style profile. Called once per upload; the result is cached on Material.

Never raises to the caller — returns None on any failure so the caller falls back
to the deterministic docx/pdf extraction.
"""

from __future__ import annotations

import logging

log = logging.getLogger("jbhntr.cv_vision")

_VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "font_class": {"type": "string", "enum": ["serif", "sans", "mono"],
                       "description": "the CV's main body font family class"},
        "font_family": {"type": "string",
                        "description": "the specific font name if identifiable "
                                       "(e.g. 'Calibri', 'Garamond'), else empty"},
        "accent_hex": {"type": "string",
                       "description": "the dominant colour used for the name / "
                                      "section headings as #rrggbb; '' if plain black"},
        "heading_upper": {"type": "boolean",
                          "description": "true if section headers are UPPER CASE"},
        "heading_bold": {"type": "boolean",
                         "description": "true if section headers are bold"},
        "layout": {"type": "string", "enum": ["single", "two-column"]},
    },
    "required": ["font_class", "font_family", "accent_hex", "heading_upper",
                 "heading_bold", "layout"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a document-design analyst. Look at this CV/résumé image and describe "
    "its VISUAL STYLE only (not the content). Report the body font family class, "
    "the specific font if you recognise it, the accent colour used for the "
    "candidate's name and section headings, whether section headers are uppercase "
    "and/or bold, and whether the page is single- or two-column. Judge colours "
    "from what you see; use '' for accent if headings are plain black."
)


def render_cv_image(raw: bytes, mime: str, filename: str = "",
                    max_pages: int = 1, dpi: int = 130) -> list[bytes]:
    """Render the first page(s) of a PDF upload to PNG bytes. DOCX/other -> []
    (those use the deterministic python-docx path instead)."""
    is_pdf = "pdf" in (mime or "").lower() or (filename or "").lower().endswith(".pdf")
    if not is_pdf:
        return []
    try:
        import pymupdf
        doc = pymupdf.open(stream=raw, filetype="pdf")
        out = []
        for page in list(doc)[:max_pages]:
            pix = page.get_pixmap(dpi=dpi)
            out.append(pix.tobytes("png"))
        doc.close()
        return out
    except Exception:
        log.exception("cv_vision: PDF render failed")
        return []


def vision_style(images: list[bytes], settings) -> dict | None:
    """Ask a vision model for the CV's style. Returns the schema dict or None."""
    if not images:
        return None
    from jobhunter import llm
    if not llm.is_configured(settings):
        return None
    model = getattr(settings, "scoring_model", "") or None
    try:
        data = llm.get_client(settings).json(
            system=_SYSTEM,
            user="Analyse this CV's visual style and return the JSON.",
            schema=_VISION_SCHEMA, tier=llm.SCORING, max_tokens=500,
            cache_system=False, model=model, images=images[:2])
        return data or None
    except Exception as exc:
        log.warning("cv_vision: vision call failed: %s", exc)
        return None
