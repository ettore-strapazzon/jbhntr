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

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path

import markdown as md
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse, Response)
from sqlalchemy.orm import Session as DbSession

from ..config import ROOT
from ..db import get_session
from ..models import BoardroomAttachment, BoardroomMessage, TeamLogEntry, aware
from ..security import decrypt_bytes, encrypt_bytes, require_same_origin
from ..templating import templates
from .admin import (admin_csrf_token, require_admin,  # reuse the admin gate verbatim
                    require_admin_csrf)

router = APIRouter()

STATE = ROOT / "company" / "state"
UPDATES = ROOT / "company" / "updates"
COMPANY = ROOT / "company"
DOCS = ROOT / "company" / "docs"
# R3-40: Founder chat attachments. Outside /static and git-ignored; reachable only
# through the admin-gated download route. Ephemeral on Railway unless a volume is mounted.
ATTACH_DIR = ROOT / "data" / "boardroom_attachments"
MAX_FILES = 5
MAX_TOTAL = 10 * 1024 * 1024
# Leading-byte signature -> (mime, extensions the name may carry). The name never decides the type.
_MAGIC = [(b"\x89PNG\r\n\x1a\n", "image/png", {".png"}),
          (b"\xff\xd8\xff", "image/jpeg", {".jpg", ".jpeg"}),
          (b"GIF87a", "image/gif", {".gif"}), (b"GIF89a", "image/gif", {".gif"}),
          (b"%PDF-", "application/pdf", {".pdf"})]
_TEXT_EXTS = {".txt", ".md", ".csv"}


class AttachmentError(ValueError):
    pass


def _safe_name(filename: str) -> str:
    """Basename only, [A-Za-z0-9._-], no leading dot, capped — never a path."""
    base = re.split(r"[\\/]", filename or "")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")[-100:]
    return name or "file"


def _sniff(name: str, raw: bytes) -> str:
    """Mime from the allowlist, or AttachmentError. Content AND extension must agree."""
    ext = Path(name).suffix.lower()
    for magic, mime, exts in _MAGIC:
        if raw.startswith(magic):
            if ext not in exts:
                raise AttachmentError(f"{name}: content does not match its extension.")
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        if ext != ".webp":
            raise AttachmentError(f"{name}: content does not match its extension.")
        return "image/webp"
    if ext in _TEXT_EXTS:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise AttachmentError(f"{name}: text files must be UTF-8.") from None
        if "\x00" in text or re.match(r"\s*<(!doctype\s+html|html|script|svg)\b", text, re.I):
            raise AttachmentError(f"{name}: not a plain-text file.")
        return "text/plain; charset=utf-8"
    raise AttachmentError(f"{name}: unsupported type (PNG, JPEG, GIF, WebP, PDF, TXT, MD, CSV only).")


async def _read_attachments(files: list[UploadFile]) -> list[tuple[str, str, bytes]]:
    """Validate the whole upload before anything is stored: count, total size, type."""
    files = [f for f in files if f.filename]  # an empty <input type=file> posts one nameless part
    if len(files) > MAX_FILES:
        raise AttachmentError(f"At most {MAX_FILES} files per message.")
    out, total = [], 0
    for f in files:
        raw = await f.read(MAX_TOTAL - total + 1)
        total += len(raw)
        if total > MAX_TOTAL:
            raise AttachmentError("Attachments are limited to 10 MB per message.")
        name = _safe_name(f.filename)
        if not raw:
            raise AttachmentError(f"{name}: file is empty.")
        out.append((name, _sniff(name, raw), raw))
    return out


def _att_meta(db: DbSession, ids: list[int]) -> dict[int, list[dict]]:
    """message id -> [{id, name, type, size, expired}] for the given messages. expired = the row
    outlived its file (redeploy without a volume, or nightly retention ran first)."""
    out: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        for a in (db.query(BoardroomAttachment)
                  .filter(BoardroomAttachment.message_id.in_(ids))
                  .order_by(BoardroomAttachment.id.asc())):
            out[a.message_id].append({"id": a.id, "name": a.name, "type": a.mime, "size": a.size,
                                        "expired": not (ATTACH_DIR / str(a.id)).is_file()})
    return out


def _ts(m: BoardroomMessage) -> str:
    dt = aware(m.created_at)
    return dt.isoformat() if dt else ""  # ISO UTC; boardroom.js fmt_time localises it (R3-49)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _html(text: str) -> str:
    """Our own Markdown → HTML, with tables + fenced code. Content is first-party,
    but Markdown's HTML output is still inert (no scripts), so this is safe."""
    return md.markdown(text or "", extensions=["tables", "fenced_code"])


# R3-47: ONE redaction rule set, owned by the stdlib-only ops/team/bridge.py (run by the VM as a piped script,
# so it can't import a sibling module) — load it by path rather than copy its patterns. The bridge's own-token
# rule stays bridge-side (the server has no runtime token); the pattern rules apply here too.
_spec = importlib.util.spec_from_file_location("jbhntr_team_bridge", ROOT / "ops" / "team" / "bridge.py")
_bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bridge)
DETAIL_CAP = _bridge.DETAIL_CAP  # 8000 chars; a work-notes blob, not a document store


def _safe_html(text: str) -> str:
    """Markdown → HTML for agent-written (untrusted) text: raw HTML and links/images
    are disabled, so tags render as escaped text and no javascript: URL can form."""
    m = md.Markdown(extensions=["tables", "fenced_code"])
    m.preprocessors.deregister("html_block")
    for p in ("html", "reference", "link", "image_link", "image_reference",
              "short_reference", "short_image_ref", "autolink", "automail"):
        m.inlinePatterns.deregister(p)
    return m.convert(text or "")


def _task_key(task: str) -> str:
    """Leading backlog id (`R3-38 …` → `R3-38`), else the whole task string."""
    m = re.match(r"\s*([A-Za-z][A-Za-z0-9]*-\d+)\b", task or "")
    return m.group(1) if m else (task or "")


WORKING_MAX_H = 6                          # an older `started` row means the run died (R3-46)
WORK_END = ("shipped", "blocked", "review")


def _elapsed(seconds: float) -> str:
    """'12 min' / '1 h 5 min' — mirrors elapsed() in boardroom.js."""
    m = max(0, int(seconds // 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


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


# ---- R3-52 Roadmap: one progress card per epic. Epics = the 7-column table in docs/strategy/ROADMAP.md
# (#, Epic, Outcome, Owner, Live, Top roadblocks, Expected live); tasks = active-sprint BACKLOG rows
# (id | owner | task | … | status) whose task starts with [E#]. Built % = done ÷ counted, computed here.
_NOT_COUNTED = {"cancelled", "canceled", "superseded", "withdrawn"}
_LIVE_KINDS = {"live", "notlive", "paused", "partly"}


def _cells(row: str) -> list[str]:
    """Markdown table row → stripped cells; a `|` inside `code` never splits a cell."""
    out, cur, code = [], "", False
    for ch in row.strip().removeprefix("|").removesuffix("|"):
        code ^= ch == "`"
        if ch == "|" and not code:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out + [cur.strip()]


def _plain(s: str) -> str:
    """Inline Markdown → one plain line (links, bold, code, italics stripped)."""
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*([^*\s][^*]*)\*", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _active_sprint(backlog: str) -> str:
    """The top `## Sprint` section only; everything from the next `## Sprint` heading on is cut."""
    m = re.search(r"(?ms)^## Sprint.*?(?=^## Sprint|\Z)", backlog or "")
    return m.group(0) if m else ""


def _tally(g: dict) -> dict:
    g["done"] = sum(t["status"] == "done" for t in g["tasks"])
    g["total"] = len(g["tasks"])
    g["pct"] = round(g["done"] * 100 / g["total"]) if g["total"] else 0
    return g


def _parse_epics(roadmap: str, backlog: str) -> dict:
    epics, by_id, in_table = [], {}, False
    for ln in (roadmap or "").splitlines():
        if not re.match(r"^\s*\|.*\|\s*$", ln):
            in_table = False
            continue
        c = _cells(ln) + [""] * 7
        if c[0] == "#" and c[1].lower().startswith("epic"):
            in_table = not epics  # the first epic table only
            continue
        if in_table and re.fullmatch(r"E\d+", c[0]):
            live = _plain(c[4])
            e = {"id": c[0], "name": _plain(c[1]), "outcome": _plain(c[2]), "owner": _plain(c[3]),
                 "live": live, "roadblocks": c[5], "expected_live": _plain(c[6]), "tasks": [],
                 "roadblocks_html": re.sub(r"^<p>|</p>$", "", _html(c[5])),  # first-party ROADMAP.md
                 "live_kind": k if (k := re.sub(r"[^a-z]", "", live.lower())) in _LIVE_KINDS else "other"}
            epics.append(e)
            by_id[e["id"]] = e
    other = {"id": "", "name": "Other", "tasks": []}
    for ln in _active_sprint(backlog).splitlines():
        if not re.match(r"^\|\s*[A-Za-z][A-Za-z0-9]*-\w+\s*\|", ln):
            continue  # header, separator, prose
        c = _cells(ln)
        st = (re.search(r"[A-Za-z]+", c[-1]) or [""])[0].lower()
        if st in _NOT_COUNTED or len(c) < 3:
            continue
        tag = re.match(r"\[(E\d+)\]\s*", c[2])
        g = by_id.get(tag.group(1)) if tag else None
        title = _plain(c[2][tag.end():] if g else c[2])
        if len(title) > 140:
            title = title[:139].strip() + "…"
        (g or other)["tasks"].append({"id": c[0], "owner": _plain(c[1]), "title": title, "status": st})
    return {"epics": [_tally(e) for e in epics], "other": _tally(other)}


def _request_blocks(requests_md: str) -> list[str]:
    return [b for b in re.split(r"(?m)^(?=### R-)", requests_md) if b.startswith("### R-")]


def _header_status(block: str) -> str:
    """Status word of `### R-NNN · title · <status> <date>` (last `·` field, 1st word),
    also behind an emoji or **markup** (`· ✅ answered`, `· **done**`); `on hold` is one word."""
    last = re.sub(r"^[\W_]+", "", block.split("\n", 1)[0].split("·")[-1]).lower()
    m = re.match(r"on hold\b|[a-z]+", last)
    return m.group(0) if m else ""


_CLOSED = {"done", "closed", "answered", "superseded", "approved", "cancelled", "withdrawn"}


def _req_status(block: str) -> str:
    """R3-45: `closed` / `later` (on hold, parked) / `open` — from the header only."""
    s = _header_status(block)
    return "closed" if s in _CLOSED else "later" if s in ("on hold", "parked") else "open"


def _group_requests(requests_md: str) -> dict[str, list[str]]:
    """R3-45: Do now (open, file order) / Later (on hold, parked) / last 5 closed, newest first."""
    g: dict[str, list[str]] = {"open": [], "later": [], "closed": []}
    for block in _request_blocks(requests_md):
        # strip the trailing `---` separator that precedes the next request
        g[_req_status(block)].append(re.sub(r"\n+---\s*$", "", block.strip()))
    return {"now": g["open"], "later": g["later"], "closed": g["closed"][-5:][::-1]}


# R3-45 (port of the stale-header check): a body that records the WHOLE request as resolved under an
# open/parked header. A done part/step/line, "partial", "except", "still open/needed" or "only … left"
# doesn't count; `>` reply templates and ``` commands are skipped.
_RESOLVED = re.compile(r"✅[\s*]*(?:[Dd]one|[Aa]nswered|[Cc]losed)\b|\bDONE\b"
                       r"|^[\s*_]*(?:[Cc]losed|CLOSED|[Ss]uperseded|SUPERSEDED)\b")
_PARTIAL = re.compile(r"\bpartial\b|\bexcept\b|\bstill (?:open|needed)\b|\bonly\b[^.;]*\bleft\b"
                      r"|\b(?:part|step|line|sitting|block)s?\s+[\w–-]+(?:\s*(?:\+|,|and|–|-)\s*\w+)*\s*"
                      r"(?:is\s+|are\s+)?(?:already\s+)?(?:✅\s*)?(?:done|passed|answered|closed)\b", re.I)


def _stale_requests(requests_md: str) -> list[tuple[str, str]]:
    """(id, offending line) for each non-closed request whose body says it is resolved."""
    out = []
    for block in _request_blocks(requests_md):
        lines = block.split("\n")
        if _req_status(block) == "closed":
            continue
        rid = lines[0].split()[1]
        own = re.compile(r"\b%s\s+(?:done|closed|complete|completed|superseded)\b" % re.escape(rid), re.I)
        fence = False
        for ln in lines[1:]:
            if ln.lstrip().startswith("```"):
                fence = not fence
                continue
            if fence or ln.lstrip().startswith(">"):
                continue
            if own.search(ln) or (_RESOLVED.search(ln) and not _PARTIAL.search(ln)):
                out.append((rid, ln.strip()[:160]))
                break
    return out


def _req_item(block: str) -> dict:
    """One Founder's-tasks `<details>`: header (inline Markdown) as summary, the rest as body."""
    head, _, body = block.partition("\n")
    return {"id": head.split()[1], "open": _req_status(head) == "open",
            "head_html": re.sub(r"^<p>|</p>$", "", _html(head[4:].strip())), "body_html": _html(body)}


def _update_files() -> list[Path]:
    return sorted((p for p in UPDATES.glob("20*.md")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name)), reverse=True)


def _latest_update() -> str:
    files = _update_files()
    return _read(files[0]) if files else ""


def _all_updates() -> list[dict]:
    """Every morning update, newest first, rendered — for the Updates tab."""
    return [{"date": p.stem, "html": _html(_read(p))} for p in _update_files()]


# R3-51: the Documents tab and viewer read any company/ file whose relative path passes this rule:
# plain segments (no leading dot, so no `..`, `.env`, `.github`), no absolute/backslash/empty segment,
# a document extension, nothing secret-looking. _doc_target() then also refuses symlink escapes.
_SAFE_DOC = re.compile(r"(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\.(?:md|txt|csv|pdf)")
_SECRETISH = re.compile(r"secret|token|credential|password|passwd|private|\.env\b|apikey|api_key", re.I)


def _safe_doc_path(path: str | None) -> bool:
    return bool(path) and len(path) <= 300 and bool(_SAFE_DOC.fullmatch(path)) and not _SECRETISH.search(path)


def _doc_target(path: str | None) -> Path | None:
    """company/-relative path → the real file, or None (bad name, missing, or resolves outside company/)."""
    if not _safe_doc_path(path):
        return None
    base = COMPANY.resolve()
    target = (base / path).resolve()
    return target if base in target.parents and target.is_file() else None


def _doc_index() -> list[str]:
    """Every readable company/ file (company/-relative, sorted) — the Documents tree (R3-51)."""
    return sorted(rel for p in COMPANY.rglob("*")
                  if _doc_target(rel := p.relative_to(COMPANY).as_posix()))


def _entry_dict(e: TeamLogEntry) -> dict:
    return {"id": e.id, "agent": e.agent, "task": e.task, "status": e.status,
            "summary": e.summary, "cycle": e.cycle, "ts": _ts(e),
            "key": _task_key(e.task), "detail_html": _safe_html(e.detail) if e.detail else ""}


def _team_feed(db: DbSession, limit: int = 100) -> tuple[list[dict], list[str], int]:
    """The most recent team-log entries (newest first) for the initial render, the
    set of agents seen, and the max id so the page can poll only newer ones."""
    rows = (db.query(TeamLogEntry)
            .order_by(TeamLogEntry.id.desc()).limit(limit).all())
    entries = [_entry_dict(e) for e in rows]
    now, ended = datetime.now(timezone.utc), set()
    # R3-46, same rule as workingNow() in boardroom.js: newest first, a `started` row works until a
    # later shipped/blocked/review row for its task id in the same cycle, and only for WORKING_MAX_H.
    for r, e in zip(rows, entries):
        age = (now - aware(r.created_at)).total_seconds() if r.created_at else None
        live = e["status"] == "started" and (e["key"], e["cycle"]) not in ended \
            and age is not None and age < WORKING_MAX_H * 3600
        e["working"] = _elapsed(age) if live else ""
        if e["status"] in WORK_END:
            ended |= {(e["key"], e["cycle"])}  # set-union, not the add method: the public-GET write scan is textual
    agents = sorted({e["agent"] for e in entries if e["agent"]})
    last_id = rows[0].id if rows else 0
    return entries, agents, last_id


@router.get("/boardroom", response_class=HTMLResponse)
def boardroom(request: Request, _: bool = Depends(require_admin),
              db: DbSession = Depends(get_session)):
    cycle_log = _read(STATE / "CYCLE_LOG.md")
    goal, budget = _charter_bits(_read(ROOT / "company" / "CHARTER.md"))
    sprint_name, sprint_table = _current_sprint(_read(STATE / "BACKLOG.md"))
    # Conversation thread, oldest -> newest. Bodies render through Jinja's auto-
    # escaping (not | safe), so the chat is plain text and injects nothing.
    msgs = db.query(BoardroomMessage).order_by(BoardroomMessage.id.asc()).all()
    atts = _att_meta(db, [m.id for m in msgs])
    messages = [{"role": m.role,
                 "role_label": "Founder" if m.role == "founder" else "CEO",
                 "body": m.body, "attachments": atts[m.id],
                 "ts": _ts(m)} for m in msgs]
    team_entries, team_agents, team_last_id = _team_feed(db)
    return templates.TemplateResponse(request, "boardroom.html", {
        "request": request,
        "admin_csrf": admin_csrf_token(),
        "messages": messages,
        "last_id": msgs[-1].id if msgs else 0,
        "goal_html": _html(goal),
        "budget_html": _html(budget),
        "sprint_name": sprint_name,
        "now_html": _html(_last_cycle(cycle_log)),
        "tasks_html": _html(sprint_table),
        "req_groups": {k: [_req_item(b) for b in v]
                       for k, v in _group_requests(_read(STATE / "REQUESTS.md")).items()},
        "docs": _doc_index(),
        "updates": _all_updates(),
        "team_entries": team_entries,
        "team_agents": team_agents,
        "team_last_id": team_last_id,
        "kpis_html": _html(_read(STATE / "KPIS.md")),
        "roadmap_html": _html(_read(STATE / "BACKLOG.md")),
        "epics": _parse_epics(_read(DOCS / "strategy" / "ROADMAP.md"), _read(STATE / "BACKLOG.md")),
        "timeline_html": _html(_read(DOCS / "strategy" / "TIMELINE.md")),
        "history_html": _html(cycle_log),
    })


@router.post("/boardroom/log")
async def boardroom_log(request: Request, _: bool = Depends(require_admin),
                        _xs: None = Depends(require_same_origin),
                        db: DbSession = Depends(get_session)):
    """The VM cycle posts one per-agent activity entry AS it works (form or JSON:
    agent, task, status, summary, cycle, optional Markdown `detail`). Powers the live 'Live team' feed."""
    ctype = request.headers.get("content-type", "")
    data = await request.json() if "application/json" in ctype else await request.form()
    agent = (str(data.get("agent", "")).strip())[:16]
    if not agent:
        return JSONResponse({"ok": False, "error": "agent required"}, status_code=400)
    e = TeamLogEntry(agent=agent,
                     task=(str(data.get("task", "")).strip())[:200],
                     status=(str(data.get("status", "")).strip())[:24],
                     summary=str(data.get("summary", "")).strip(),
                     cycle=(str(data.get("cycle", "")).strip())[:32],
                     detail=_bridge.redact(str(data.get("detail", "")).strip())[:DETAIL_CAP])  # redact, then clip
    db.add(e)
    db.commit()
    return JSONResponse({"ok": True, "id": e.id})


@router.get("/boardroom/team.json")
def boardroom_team(after: int = 0, _: bool = Depends(require_admin),
                   db: DbSession = Depends(get_session)):
    """Team-log entries with id > `after` (ascending), for the live poll."""
    rows = (db.query(TeamLogEntry)
            .filter(TeamLogEntry.id > after)
            .order_by(TeamLogEntry.id.asc()).all())
    return JSONResponse([_entry_dict(e) for e in rows])


@router.get("/boardroom/doc", response_class=HTMLResponse)
def boardroom_doc(path: str, request: Request, raw: bool = False,
                  _: bool = Depends(require_admin)):
    """Read one company/ file (path relative to company/, confined by _doc_target: no traversal,
    no symlink escape, no secret-looking names). `raw=1` returns the text for the tab's viewer
    (R3-51); otherwise Markdown renders as a page and other types download."""
    target = _doc_target(path)
    if target is None:
        return HTMLResponse("Not found", status_code=404)
    if raw and target.suffix.lower() != ".pdf":
        return PlainTextResponse(_read(target), headers={"X-Content-Type-Options": "nosniff",
                                                         "Cache-Control": "private, no-store"})
    if target.suffix.lower() == ".md":
        return templates.TemplateResponse(request, "boardroom_doc.html", {
            "request": request, "title": target.name,
            "body_html": _html(_read(target)),
        })
    return FileResponse(str(target), filename=target.name)


@router.post("/boardroom/send")
async def boardroom_send(_: bool = Depends(require_admin),
                         _csrf: None = Depends(require_admin_csrf), body: str = Form(""),
                         files: list[UploadFile] = File(default=[]),
                         db: DbSession = Depends(get_session)):
    """Founder posts a message (+ up to 5 files, 10 MB total; R3-40) from the browser
    form. Blank input is a no-op; any bad file rejects the whole message (400)."""
    body = (body or "").strip()
    try:
        uploads = await _read_attachments(files)
    except AttachmentError as e:
        return PlainTextResponse(str(e), status_code=400)
    if body or uploads:
        m = BoardroomMessage(role="founder", body=body, handled=False)
        db.add(m)
        db.flush()
        ATTACH_DIR.mkdir(parents=True, exist_ok=True)
        for name, mime, raw in uploads:
            a = BoardroomAttachment(message_id=m.id, name=name, mime=mime, size=len(raw))
            db.add(a)
            db.flush()
            (ATTACH_DIR / str(a.id)).write_bytes(encrypt_bytes(raw))  # stored under its int id only
        db.commit()
    return RedirectResponse("/boardroom", status_code=303)


@router.get("/boardroom/attachment/{att_id}")
def boardroom_attachment(att_id: int, _: bool = Depends(require_admin),
                         db: DbSession = Depends(get_session)):
    """Download one chat attachment (read-only). Always a download, never rendered inline."""
    a = db.get(BoardroomAttachment, att_id)
    path = ATTACH_DIR / str(att_id)
    if a is None:
        return PlainTextResponse("Not found", status_code=404)
    try:
        raw = decrypt_bytes(path.read_bytes())
    except (OSError, RuntimeError):  # file gone, or unreadable under the current key
        return PlainTextResponse("This attachment has expired.", status_code=410)
    return Response(raw, media_type=a.mime, headers={
        "Content-Disposition": f'attachment; filename="{a.name}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store"})


@router.get("/boardroom/messages.json")
def boardroom_messages(after: int = 0, _: bool = Depends(require_admin),
                       db: DbSession = Depends(get_session)):
    """Messages with id > `after`, for the page's live auto-update poll. Read-only;
    bodies go out as plain text and are rendered via textContent (no injection)."""
    rows = (db.query(BoardroomMessage)
            .filter(BoardroomMessage.id > after)
            .order_by(BoardroomMessage.id.asc()).all())
    atts = _att_meta(db, [m.id for m in rows])
    return JSONResponse([{"id": m.id, "role": m.role,
                          "role_label": "Founder" if m.role == "founder" else "CEO",
                          "body": m.body, "attachments": atts[m.id], "ts": _ts(m)} for m in rows])


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
                   _xs: None = Depends(require_same_origin),
                   db: DbSession = Depends(get_session)):
    """The VM cycle fetches new founder instructions, each delivered once: return
    all unhandled founder messages and mark them handled in the same call.
    Consumes messages, so a browser cross-site GET is refused (R3-21); the VM's
    header-less `curl -u admin:… $APP/boardroom/pull` passes unchanged."""
    rows = (db.query(BoardroomMessage)
            .filter(BoardroomMessage.role == "founder",
                    BoardroomMessage.handled.is_(False))
            .order_by(BoardroomMessage.id.asc()).all())
    atts = _att_meta(db, [m.id for m in rows])
    out = [{"id": m.id, "body": m.body, "attachments": atts[m.id],
            "created_at": aware(m.created_at).isoformat() if aware(m.created_at) else None}
           for m in rows]
    for m in rows:
        m.handled = True
    db.commit()
    return JSONResponse(out)


@router.post("/boardroom/reply")
async def boardroom_reply(request: Request, _: bool = Depends(require_admin),
                          _xs: None = Depends(require_same_origin),
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
