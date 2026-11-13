"""Vision-based CV style extraction.

Programmatic text extraction (pypdf) is blind to a CV's design. A vision model
*sees* the rendered page — fonts, colours, heading treatment, layout — the way a
person (or claude.ai) does, so it recovers formatting a text parser can't. We
render the uploaded CV's first page to a PNG (PyMuPDF, a pure wheel — no system
libraries), send it to a vision-capable model with a strict schema, and get back
a small style profile. Called once per upload; the result is cached on Material.

Never raises to the caller — returns None on any failure so the caller falls back
to the deterministic docx/pdf extraction.

Open-core split: the shell keeps the rendering; the vision prompt + schema live
in the engine (``jbhntr_engine.vision_style``).
"""

from __future__ import annotations

import logging

log = logging.getLogger("jbhntr.cv_vision")


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
    """Ask the engine's vision model for the CV's style (schema dict or None).
    The prompt lives in the engine (jbhntr_engine.vision_style)."""
    from jbhntr_engine import vision_style as _engine_vision_style
    return _engine_vision_style(images, settings)
