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
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..config import ROOT
from ..db import get_session
from ..models import BoardroomMessage, aware
from ..templating import templates
from .admin import require_admin  # reuse the existing admin gate verbatim

router = APIRouter()

STATE = ROOT / "company" / "state"
UPDATES = ROOT / "company" / "updates"


def _ts(m: BoardroomMessage) -> str:
    dt = aware(m.created_at)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ""


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
def boardroom(request: Request, _: bool = Depends(require_admin),
              db: DbSession = Depends(get_session)):
    cycle_log = _read(STATE / "CYCLE_LOG.md")
    goal, budget = _charter_bits(_read(ROOT / "company" / "CHARTER.md"))
    sprint_name, sprint_table = _current_sprint(_read(STATE / "BACKLOG.md"))
    # Conversation thread, oldest -> newest. Bodies render through Jinja's auto-
    # escaping (not | safe), so the chat is plain text and injects nothing.
    msgs = db.query(BoardroomMessage).order_by(BoardroomMessage.id.asc()).all()
    messages = [{"role": m.role,
                 "role_label": "Founder" if m.role == "founder" else "CEO",
                 "body": m.body,
                 "ts": _ts(m)} for m in msgs]
    return templates.TemplateResponse(request, "boardroom.html", {
        "request": request,
        "messages": messages,
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


@router.post("/boardroom/send")
def boardroom_send(_: bool = Depends(require_admin), body: str = Form(""),
                   db: DbSession = Depends(get_session)):
    """Founder posts a message from the browser form. Blank input is a no-op."""
    body = (body or "").strip()
    if body:
        db.add(BoardroomMessage(role="founder", body=body, handled=False))
        db.commit()
    return RedirectResponse("/boardroom", status_code=303)


@router.get("/boardroom/peek")
def boardroom_peek(_: bool = Depends(require_admin),
                   db: DbSession = Depends(get_session)):
    """Cheap, side-effect-free count of unhandled founder messages, so the VM's
    1-minute chat responder can skip spinning up Claude when there is nothing waiting."""
    n = (db.query(BoardroomMessage)
         .filter(BoardroomMessage.role == "founder",
                 BoardroomMessage.handled.is_(False))
         .count())
    return JSONResponse({"count": n})


@router.get("/boardroom/pull")
def boardroom_pull(_: bool = Depends(require_admin),
                   db: DbSession = Depends(get_session)):
    """The VM cycle fetches new founder instructions, each delivered once: return
    all unhandled founder messages and mark them handled in the same call."""
    rows = (db.query(BoardroomMessage)
            .filter(BoardroomMessage.role == "founder",
                    BoardroomMessage.handled.is_(False))
            .order_by(BoardroomMessage.id.asc()).all())
    out = [{"id": m.id, "body": m.body,
            "created_at": aware(m.created_at).isoformat() if aware(m.created_at) else None}
           for m in rows]
    for m in rows:
        m.handled = True
    db.commit()
    return JSONResponse(out)


@router.post("/boardroom/reply")
async def boardroom_reply(request: Request, _: bool = Depends(require_admin),
                          db: DbSession = Depends(get_session)):
    """The VM cycle posts a CEO reply (form or JSON `body`)."""
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        data = await request.json()
        body = (data.get("body") if isinstance(data, dict) else "") or ""
    else:
        form = await request.form()
        body = form.get("body") or ""
    body = body.strip()
    if not body:
        return JSONResponse({"ok": False, "error": "empty body"}, status_code=400)
    m = BoardroomMessage(role="ceo", body=body, handled=True)
    db.add(m)
    db.commit()
    return JSONResponse({"ok": True, "id": m.id}, status_code=200)
