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

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(20, 18, 20)

    if title:
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(0, 8, _ascii(title))
        pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    for line in _ascii(body).split("\n"):
        if line.strip():
            pdf.multi_cell(0, 6, line)
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
