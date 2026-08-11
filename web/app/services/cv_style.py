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


# CSS font stacks for the in-platform preview, keyed by detected class.
_CSS_FONT = {
    "serif": "Georgia, 'Times New Roman', serif",
    "mono": "'Courier New', ui-monospace, monospace",
    "sans": "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
}


def _hex(rgb: tuple | None) -> str:
    return "#%02x%02x%02x" % rgb if rgb else ""


def public_style(sp: "StyleProfile") -> dict:
    """A small, JSON-safe view of the profile for the live preview (and to tell the
    user how much we could match)."""
    return {
        "font": _CSS_FONT.get(sp.font_class, _CSS_FONT["sans"]),
        "accent": _hex(sp.accent_rgb) or "#1f2a24",
        "upper": bool(sp.heading_upper),
        "source": sp.source,
        "font_class": sp.font_class,
    }


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
        sp = _from_docx(raw)
    elif "pdf" in mime or (mat.filename or "").lower().endswith(".pdf"):
        sp = _from_pdf(raw)
    else:
        sp = StyleProfile()
    # Best-effort: if the CV's own section headers are written in UPPER CASE
    # (common in designed CVs), mirror that in the tailored output.
    sp.heading_upper = sp.heading_upper or _text_looks_upper_headed(mat.text or "")
    return sp


def _text_looks_upper_headed(text: str) -> bool:
    """True if several short ALL-CAPS lines (section headers) appear in the CV."""
    caps = 0
    for ln in (text or "").splitlines():
        s = ln.strip()
        if 3 <= len(s) <= 32 and s == s.upper() and any(c.isalpha() for c in s):
            caps += 1
            if caps >= 2:
                return True
    return False


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
