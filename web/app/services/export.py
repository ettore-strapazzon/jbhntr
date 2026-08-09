"""Render a tailored document (plain text) to PDF or DOCX (§11.8, F-10).

Both backends are pure-Python with no system libraries, so they run the same on
a laptop and on Railway. The type is deliberately plain and one-column — a first
draft the user finishes, not a designed artefact.
"""

from __future__ import annotations

import io

# fpdf2's core fonts are latin-1 only; tailored text can carry smart quotes,
# dashes and bullets. Fold the common ones to ASCII so the PDF stays readable
# without shipping a Unicode TTF.
_SUBS = {
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "•": "-", "…": "...",
    " ": " ", "‐": "-", "‑": "-",
}


def _ascii(text: str) -> str:
    for bad, good in _SUBS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def to_pdf(title: str, body: str) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(20, 18, 20)

    # Reset x to the left margin + advance y after each cell; without this, fpdf2
    # leaves x at the right margin and the next multi_cell has ~0 width and raises.
    def mc(h, txt):
        pdf.multi_cell(0, h, txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if title:
        pdf.set_font("Helvetica", "B", 15)
        mc(8, _ascii(title))
        pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    for line in _ascii(body).split("\n"):
        if line.strip():
            mc(6, line)
        else:
            pdf.ln(3)
    return bytes(pdf.output())


def to_docx(title: str, body: str) -> bytes:
    from docx import Document as Docx

    doc = Docx()
    if title:
        doc.add_heading(title, level=1)
    for line in body.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _line_kind(line: str) -> str:
    s = line.strip()
    if not s:
        return "blank"
    if s[0] in "-•*▪◦·":
        return "bullet"
    # Heading heuristic: short, no sentence-ending punctuation, title/upper case.
    if len(s) <= 40 and not s.endswith((".", ",", ";")) and (s.isupper() or s.istitle() or s.endswith(":")):
        return "heading"
    return "body"


_FAMILY = {"serif": "Times", "mono": "Courier", "sans": "Helvetica"}


def to_pdf_styled(title: str, body: str, style) -> bytes:
    """PDF matched to the candidate's CV style profile (approximate: font class,
    accent colour, margins, heading/bullet treatment)."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    fam = _FAMILY.get(getattr(style, "font_class", "sans"), "Helvetica")
    accent = getattr(style, "accent_rgb", None) or (34, 34, 34)
    upper = bool(getattr(style, "heading_upper", False))
    m = getattr(style, "margin_mm", 20) or 20

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.set_margins(m, 16, m)

    def mc(h, txt):
        pdf.multi_cell(0, h, txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if title:
        pdf.set_font(fam, "B", 15)
        pdf.set_text_color(*accent)
        mc(8, _ascii(title.upper() if upper else title))
        pdf.ln(2)

    for line in _ascii(body).split("\n"):
        kind = _line_kind(line)
        if kind == "blank":
            pdf.ln(3)
        elif kind == "heading":
            pdf.set_font(fam, "B", 12)
            pdf.set_text_color(*accent)
            mc(7, line.strip().upper() if upper else line.strip())
        elif kind == "bullet":
            pdf.set_font(fam, "", 11)
            pdf.set_text_color(20, 20, 20)
            # ASCII bullet — fpdf core fonts are latin-1 and can't encode "•".
            mc(6, "  - " + line.strip().lstrip("-•*▪◦· ").strip())
        else:
            pdf.set_font(fam, "", 11)
            pdf.set_text_color(20, 20, 20)
            mc(6, line)
    return bytes(pdf.output())


def to_docx_templated(orig_docx: bytes, title: str, body: str) -> bytes:
    """DOCX rendered into a copy of the user's own .docx, so its theme fonts,
    colours and named styles carry. Layout collapses to single-column."""
    from docx import Document as Docx

    doc = Docx(io.BytesIO(orig_docx))
    # Clear the existing body (paragraphs + tables) but keep styles/theme/section.
    body_el = doc.element.body
    for child in list(body_el):
        if child.tag.endswith("}p") or child.tag.endswith("}tbl"):
            body_el.remove(child)

    def _add(text: str, style: str | None):
        try:
            doc.add_paragraph(text, style=style) if style else doc.add_paragraph(text)
        except KeyError:
            doc.add_paragraph(text)         # style not in this template

    if title:
        _add(title, "Heading 1")
    for line in body.split("\n"):
        kind = _line_kind(line)
        if kind == "blank":
            _add("", None)
        elif kind == "heading":
            _add(line.strip(), "Heading 2")
        elif kind == "bullet":
            _add(line.strip().lstrip("-•*▪◦· ").strip(), "List Bullet")
        else:
            _add(line, None)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
