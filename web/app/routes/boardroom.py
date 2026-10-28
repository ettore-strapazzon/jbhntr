"""Founder Boardroom at /boardroom.

A credential-protected, read-only page that shows — in natural language — what the
agent company is doing: the current/recent cycle, pending & future tasks, what is
waiting on the Founder, the latest morning update, the KPIs, and the full history.

It just renders the company's own Markdown state files (CYCLE_LOG / BACKLOG /
REQUESTS / KPIS / the newest updates/ file + CHARTER), which the autonomous cycles
commit+push, so the page always reflects the latest pushed state after a redeploy.

Gate: the SAME HTTP Basic auth as /admin — reuses require_admin, so an unset
admin_token => 404 (feature off), exactly like the operator dashboard.
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown as md
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..config import ROOT
from ..templating import templates
from .admin import require_admin  # reuse the existing admin gate verbatim

router = APIRouter()

STATE = ROOT / "company" / "state"
UPDATES = ROOT / "company" / "updates"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _html(text: str) -> str:
    """Our own Markdown → HTML, with tables + fenced code. Content is first-party,
    but Markdown's HTML output is still inert (no scripts), so this is safe."""
    return md.markdown(text or "", extensions=["tables", "fenced_code"])


def _last_cycle(cycle_log: str) -> str:
    """The most recent `## ` entry (what the agents just did)."""
    parts = re.split(r"(?m)^## ", cycle_log)
    return ("## " + parts[-1]) if len(parts) > 1 else cycle_log


def _charter_bits(charter: str) -> tuple[str, str]:
    """Goal + USD budget, pulled from the CHARTER `## Goal` bullets."""
    m = re.search(r"(?ms)^## Goal\b.*?(?=^## |\Z)", charter)
    section = m.group(0) if m else charter
    goal = budget = ""
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("-"):
            continue
        body = s.lstrip("-* ").strip()
        if not goal and "activated user" in body.lower():
            goal = body
        if not budget and "budget" in body.lower():
            budget = body
    return goal, budget


def _current_sprint(backlog: str) -> tuple[str, str]:
    """Current sprint name + a Markdown table of just its todo/doing rows."""
    m = re.search(r"(?ms)^## (Sprint[^\n]*)\n(.*?)(?=^## |\Z)", backlog)
    if not m:
        return "", ""
    name, body = m.group(1).strip(), m.group(2)
    rows = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    kept = []
    for i, ln in enumerate(rows):
        if i < 2:  # header + separator
            kept.append(ln)
            continue
        status = ln.rstrip().strip("|").split("|")[-1].lower()
        if "todo" in status or "doing" in status:
            kept.append(ln)
    # Only a header (+separator) and no data rows => nothing pending.
    return name, ("\n".join(kept) if len(kept) > 2 else "")


def _open_requests(requests_md: str) -> list[str]:
    """Each `### R-###` block whose Answer is empty / not ANSWERED."""
    out = []
    for block in re.split(r"(?m)^(?=### R-)", requests_md):
        if not block.startswith("### R-"):
            continue
        m = re.search(r"(?mi)^Answer:\s*(.*)$", block)
        answer = m.group(1).strip() if m else ""
        if "ANSWERED" not in answer.upper():
            # strip the trailing `---` separator that precedes the next request
            out.append(re.sub(r"\n+---\s*$", "", block.strip()))
    return out


def _latest_update() -> str:
    files = sorted(p for p in UPDATES.glob("20*.md")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name))
    return _read(files[-1]) if files else ""


@router.get("/boardroom", response_class=HTMLResponse)
def boardroom(request: Request, _: bool = Depends(require_admin)):
    cycle_log = _read(STATE / "CYCLE_LOG.md")
    goal, budget = _charter_bits(_read(ROOT / "company" / "CHARTER.md"))
    sprint_name, sprint_table = _current_sprint(_read(STATE / "BACKLOG.md"))
    return templates.TemplateResponse(request, "boardroom.html", {
        "request": request,
        "goal_html": _html(goal),
        "budget_html": _html(budget),
        "sprint_name": sprint_name,
        "now_html": _html(_last_cycle(cycle_log)),
        "tasks_html": _html(sprint_table),
        "requests_html": [_html(b) for b in _open_requests(_read(STATE / "REQUESTS.md"))],
        "update_html": _html(_latest_update()),
        "kpis_html": _html(_read(STATE / "KPIS.md")),
        "history_html": _html(cycle_log),
    })
