"""Match a generated CV's look to the candidate's latest uploaded CV.

Fidelity ceiling (see handoff §C): DOCX upload -> theme fonts/colours carry
exactly via a template passthrough; PDF upload -> font class + margins only.
Pure-Python (python-docx, pypdf, fpdf2); no system libraries.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession

from ..models import Material
from ..security import decrypt_bytes

log = logging.getLogger("jbhntr.cv_style")

_SERIF_HINTS = ("times", "georgia", "garamond", "cambria", "minion", "serif", "book antiqua")
_MONO_HINTS = ("courier", "consolas", "mono", "menlo")


@dataclass
class StyleProfile:
    font_class: str = "sans"            # sans | serif | mono
    accent_rgb: tuple | None = None     # heading colour, or None
    heading_upper: bool = False
    margin_mm: int = 20
    source: str = "none"                # docx | pdf | none
    docx_bytes: bytes | None = None     # original .docx, for template passthrough


def _class_from_name(name: str) -> str:
    n = (name or "").lower()
    if any(h in n for h in _MONO_HINTS):
        return "mono"
    if any(h in n for h in _SERIF_HINTS):
        return "serif"
    return "sans"


def latest_cv_material(db: DbSession, user_id: int) -> Material | None:
    return (db.query(Material)
            .filter(Material.user_id == user_id, Material.kind == "cv")
            .order_by(Material.created_at.desc())
            .first())


def profile_for(db: DbSession, user_id: int) -> StyleProfile:
    mat = latest_cv_material(db, user_id)
    if not mat:
        return StyleProfile()
    try:
        raw = decrypt_bytes(mat.ciphertext)
    except Exception:
        log.exception("cv_style: decrypt failed")
        return StyleProfile()
    mime = (mat.mime or "").lower()
    if "word" in mime or "officedocument" in mime or (mat.filename or "").lower().endswith(".docx"):
        return _from_docx(raw)
    if "pdf" in mime or (mat.filename or "").lower().endswith(".pdf"):
        return _from_pdf(raw)
    return StyleProfile()


def _from_docx(raw: bytes) -> StyleProfile:
    from docx import Document as Docx
    from docx.shared import EMU

    sp = StyleProfile(source="docx", docx_bytes=raw)
    try:
        doc = Docx(io.BytesIO(raw))
        # Body font from the Normal style.
        try:
            nm = doc.styles["Normal"].font.name
            if nm:
                sp.font_class = _class_from_name(nm)
        except Exception:
            pass
        # Accent from Heading 1/2 colour if set.
        for hs in ("Heading 1", "Heading 2"):
            try:
                col = doc.styles[hs].font.color
                if col and col.rgb is not None:
                    sp.accent_rgb = (col.rgb[0], col.rgb[1], col.rgb[2])
                    break
            except Exception:
                continue
        # Margins (EMU -> mm).
        try:
            sec = doc.sections[0]
            sp.margin_mm = max(12, min(28, int(EMU(sec.left_margin).mm)))
        except Exception:
            pass
    except Exception:
        log.exception("cv_style: docx parse failed")
    return sp


def _from_pdf(raw: bytes) -> StyleProfile:
    sp = StyleProfile(source="pdf")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        names = []
        for page in reader.pages[:2]:
            fonts = (page.get("/Resources") or {}).get("/Font") or {}
            for f in fonts.values():
                try:
                    bf = f.get_object().get("/BaseFont")
                    if bf:
                        names.append(str(bf))
                except Exception:
                    continue
        if names:
            sp.font_class = _class_from_name(" ".join(names))
    except Exception:
        log.exception("cv_style: pdf parse failed")
    return sp     # accent left None for PDF (not reliably recoverable)
