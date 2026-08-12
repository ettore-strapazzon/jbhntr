"""Render a tailored CV as a full HTML/CSS document — the high-fidelity path.

The old export drew the PDF with fpdf primitives (no real fonts, no columns).
This instead builds a proper HTML/CSS CV, styled from the candidate's
vision-extracted profile (font family, accent colour, uppercase headings,
single/two-column layout), and lets a real engine render it: WeasyPrint for the
downloadable PDF, or the browser itself for an exact on-screen preview / print.

Content structure comes from ``export.parse_lines`` so it stays consistent with
every other renderer. The output is a standalone document (inline <style>, no
external requests) so it renders identically server-side and in the browser.
"""

from __future__ import annotations

import html as _html

from .export import _split_org, _split_role, parse_lines

# Map the vision "font_class"/"font_family" onto a CSS stack. The first names are
# metric-compatible open fonts we apt-install on Railway (Liberation = Arial/
# Times/Courier metrics, Carlito = Calibri, Caladea = Cambria, EB Garamond =
# Garamond), so the PDF matches common CV fonts closely; later names let a
# browser preview fall back to the real system font.
_FONT_STACKS = {
    "sans": "'Liberation Sans', 'Arimo', Arial, 'Helvetica Neue', Helvetica, sans-serif",
    "serif": "'Liberation Serif', 'Tinos', 'Times New Roman', Times, serif",
    "mono": "'Liberation Mono', 'Cousine', 'Courier New', monospace",
}
# Specific well-known families → a matching stack (metric-compatible first).
_FAMILY_STACKS = {
    "calibri": "'Carlito', Calibri, 'Liberation Sans', Arial, sans-serif",
    "cambria": "'Caladea', Cambria, 'Liberation Serif', Georgia, serif",
    "garamond": "'EB Garamond', Garamond, 'Liberation Serif', Georgia, serif",
    "georgia": "Georgia, 'Liberation Serif', 'Times New Roman', serif",
    "arial": "'Liberation Sans', 'Arimo', Arial, Helvetica, sans-serif",
    "helvetica": "'Liberation Sans', 'Arimo', Helvetica, Arial, sans-serif",
    "times": "'Liberation Serif', 'Tinos', 'Times New Roman', Times, serif",
    "verdana": "Verdana, 'DejaVu Sans', 'Liberation Sans', sans-serif",
}


def _font_stack(style) -> str:
    fam = (getattr(style, "font_family", "") or "").strip().lower()
    for key, stack in _FAMILY_STACKS.items():
        if key in fam:
            return stack
    return _FONT_STACKS.get(getattr(style, "font_class", "sans"), _FONT_STACKS["sans"])


def _accent_css(style) -> str:
    rgb = getattr(style, "accent_rgb", None)
    if rgb:
        return "rgb(%d, %d, %d)" % tuple(rgb)
    return "#1f2a24"


def _esc(text: str) -> str:
    return _html.escape(text or "", quote=False)


def _org_html(text: str) -> str:
    comp, rest = _split_org(text)
    if rest:
        return f'<div class="org"><span class="org-name">{_esc(comp)}</span>' \
               f'<span class="muted">{_esc(rest)}</span></div>'
    return f'<div class="org"><span class="org-name">{_esc(comp)}</span></div>'


def _role_html(text: str) -> str:
    role, dates = _split_role(text)
    if dates:
        return f'<div class="role"><span class="role-title">{_esc(role)}</span> ' \
               f'<span class="muted dates">{_esc(dates)}</span></div>'
    return f'<div class="role"><span class="role-title">{_esc(text)}</span></div>'


def _body_to_blocks(body: str, upper: bool) -> str:
    """Turn the parsed lines into HTML blocks, grouping consecutive bullets into
    a single <ul>."""
    out: list[str] = []
    bullets: list[str] = []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for kind, text in parse_lines(body):
        if kind == "bullet":
            bullets.append(text)
            continue
        flush()
        if kind == "name":
            out.append(f'<h1>{_esc(text)}</h1>')
        elif kind == "subtitle":
            out.append(f'<div class="subtitle">{_esc(text)}</div>')
        elif kind == "contact":
            out.append(f'<div class="contact">{_esc(text)}</div>')
        elif kind == "heading":
            label = text.upper() if upper else text
            out.append(f'<h2>{_esc(label)}</h2>')
        elif kind == "org":
            out.append(_org_html(text))
        elif kind == "orgdesc":
            out.append(f'<div class="orgdesc">{_esc(text)}</div>')
        elif kind == "role":
            out.append(_role_html(text))
        elif kind == "blank":
            pass  # spacing handled by CSS margins
        else:
            out.append(f'<p>{_esc(text)}</p>')
    flush()
    return "\n".join(out)


def _css(style) -> str:
    accent = _accent_css(style)
    font = _font_stack(style)
    bold = getattr(style, "heading_bold", True)
    margin = getattr(style, "margin_mm", 18) or 18
    hweight = "700" if bold else "600"
    return f"""
    @page {{ size: A4; margin: {margin}mm {margin}mm; }}
    * {{ box-sizing: border-box; }}
    html {{ -weasy-hyphens: none; }}
    body {{
        font-family: {font};
        color: #212121;
        font-size: 10.5pt;
        line-height: 1.42;
        margin: 0;
    }}
    h1 {{
        font-size: 22pt; font-weight: 800; color: {accent};
        margin: 0 0 2px; letter-spacing: .2px; line-height: 1.1;
    }}
    .subtitle {{ font-size: 11.5pt; color: #555; margin: 0 0 3px; }}
    .contact {{
        font-size: 8.8pt; color: #6e6e6e; margin: 0 0 8px;
        padding-bottom: 7px; border-bottom: 1px solid #cfcbc2;
    }}
    h2 {{
        font-size: 11pt; font-weight: {hweight}; color: {accent};
        letter-spacing: .6px; margin: 15px 0 6px;
        padding-bottom: 3px; border-bottom: 1px solid #cfcbc2;
    }}
    .org {{ margin: 9px 0 0; font-size: 10.8pt; }}
    .org-name {{ font-weight: 700; color: #1a1a1a; }}
    .orgdesc {{ font-style: italic; color: #555; margin: 0 0 1px; }}
    .role {{ margin: 1px 0 3px; }}
    .role-title {{ font-weight: 700; color: #1a1a1a; }}
    .muted {{ color: #6e6e6e; font-weight: 400; }}
    .dates {{ font-size: 9.6pt; }}
    p {{ margin: 3px 0; }}
    ul {{ margin: 3px 0 4px; padding-left: 16px; }}
    li {{ margin: 2px 0; padding-left: 2px; }}
    li::marker {{ color: {accent}; }}
    """


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


def _blocking_fetcher(url: str, *args, **kwargs):
    """Refuse every external/URL fetch. The CV HTML is fully self-contained
    (inline CSS, system fonts), so a document should never reach the network —
    blocking it removes any SSRF/local-file surface from the render step."""
    raise ValueError(f"external resource blocked: {url}")


def to_pdf(body: str, style) -> bytes:
    """Render the CV to a PDF via WeasyPrint. Raises if WeasyPrint (or its
    system libraries) are unavailable — callers fall back to the fpdf renderer."""
    from weasyprint import HTML

    html = render_cv_html(body, style, standalone=True)
    return HTML(string=html, url_fetcher=_blocking_fetcher).write_pdf()


def render_cv_html(body: str, style, *, standalone: bool = True) -> str:
    """Return the CV as HTML. ``standalone`` wraps it in a full <html> document
    with inline CSS (for WeasyPrint / a print tab); otherwise returns just the
    styled <section> (to embed in the app's own page)."""
    upper = bool(getattr(style, "heading_upper", False))
    blocks = _body_to_blocks(body, upper)
    css = _css(style)
    if not standalone:
        return f'<style>{css}</style>\n<section class="cv-doc">{blocks}</section>'
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>CV</title><style>{css}</style></head>"
        f"<body>{blocks}</body></html>"
    )
