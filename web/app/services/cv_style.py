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
    font_family: str = ""               # specific font name if identified (for preview)
    accent_rgb: tuple | None = None     # heading colour, or None
    heading_upper: bool = False
    heading_bold: bool = True
    margin_mm: int = 20
    source: str = "none"                # docx | pdf | pdf-vision | none
    docx_bytes: bytes | None = None     # original .docx, for template passthrough (not cached)


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


def _rgb_from_hex(s: str) -> tuple | None:
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        rgb = tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        return None if rgb == (0, 0, 0) else rgb     # plain black -> no accent
    except ValueError:
        return None


def public_style(sp: "StyleProfile") -> dict:
    """A small, JSON-safe view of the profile for the live preview (and to tell the
    user how much we could match)."""
    stack = _CSS_FONT.get(sp.font_class, _CSS_FONT["sans"])
    font = f"'{sp.font_family}', {stack}" if getattr(sp, "font_family", "") else stack
    return {
        "font": font,
        "accent": _hex(sp.accent_rgb) or "#1f2a24",
        "upper": bool(sp.heading_upper),
        "bold": bool(getattr(sp, "heading_bold", True)),
        "source": sp.source,
        "font_class": sp.font_class,
    }


def latest_cv_material(db: DbSession, user_id: int) -> Material | None:
    return (db.query(Material)
            .filter(Material.user_id == user_id, Material.kind == "cv")
            .order_by(Material.created_at.desc())
            .first())


_CACHE_FIELDS = ("font_class", "font_family", "accent_rgb", "heading_upper",
                 "heading_bold", "margin_mm", "source")


def _to_json(sp: "StyleProfile") -> str:
    import json
    return json.dumps({f: getattr(sp, f) for f in _CACHE_FIELDS})


def _from_json(s: str) -> "StyleProfile":
    import json
    d = json.loads(s)
    acc = d.get("accent_rgb")
    return StyleProfile(
        font_class=d.get("font_class", "sans"), font_family=d.get("font_family", ""),
        accent_rgb=tuple(acc) if acc else None,
        heading_upper=bool(d.get("heading_upper")),
        heading_bold=bool(d.get("heading_bold", True)),
        margin_mm=int(d.get("margin_mm", 20)), source=d.get("source", "none"))


def _from_vision(v: dict) -> StyleProfile:
    return StyleProfile(
        font_class=v.get("font_class", "sans"),
        font_family=(v.get("font_family") or "").strip(),
        accent_rgb=_rgb_from_hex(v.get("accent_hex", "")),
        heading_upper=bool(v.get("heading_upper")),
        heading_bold=bool(v.get("heading_bold", True)),
        source="pdf-vision")


def profile_for(db: DbSession, user_id: int) -> StyleProfile:
    """The cached CV style profile. Extracted once per upload (vision for PDFs,
    python-docx for DOCX) and reused; the vision call never happens on a page view
    once cached."""
    mat = latest_cv_material(db, user_id)
    if not mat:
        return StyleProfile()
    if mat.style_json:
        try:
            return _from_json(mat.style_json)
        except Exception:
            pass
    sp = _extract(db, mat)
    try:
        mat.style_json = _to_json(sp)
        db.commit()
    except Exception:
        db.rollback()
    return sp


def _extract(db: DbSession, mat) -> StyleProfile:
    try:
        raw = decrypt_bytes(mat.ciphertext)
    except Exception:
        log.exception("cv_style: decrypt failed")
        return StyleProfile()
    mime = (mat.mime or "").lower()
    fn = (mat.filename or "").lower()
    is_docx = "word" in mime or "officedocument" in mime or fn.endswith(".docx")
    is_pdf = "pdf" in mime or fn.endswith(".pdf")
    if is_pdf:
        # Vision first — it SEES the design (fonts, colours, layout) a text parser
        # can't. Falls back to the crude pypdf font-class read if vision is off/fails.
        from . import cv_vision
        from .profile_service import engine_settings
        vis = cv_vision.vision_style(cv_vision.render_cv_image(raw, mime, fn),
                                     engine_settings())
        sp = _from_vision(vis) if vis else _from_pdf(raw)
    elif is_docx:
        sp = _from_docx(raw)
    else:
        sp = StyleProfile()
    # Mirror UPPER-CASE section headers if the extractor didn't already flag them.
    sp.heading_upper = sp.heading_upper or _text_looks_upper_headed(mat.text or "")
    return sp


def docx_template_bytes(db: DbSession, user_id: int) -> bytes | None:
    """Raw bytes of the user's uploaded CV when it's a DOCX — the template the DOCX
    export renders into. Fetched on demand (not cached; export is infrequent)."""
    mat = latest_cv_material(db, user_id)
    if not mat:
        return None
    mime = (mat.mime or "").lower()
    fn = (mat.filename or "").lower()
    if not ("word" in mime or "officedocument" in mime or fn.endswith(".docx")):
        return None
    try:
        return decrypt_bytes(mat.ciphertext)
    except Exception:
        return None


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
