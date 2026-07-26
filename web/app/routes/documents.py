"""Tailored-document view + export (§11.8, F-10).

The old flow handed back a .txt attachment. This renders the draft on a page you
can edit in place, then export as PDF, DOCX or text — a first draft you finish,
not a download you fight with.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Document, JobResult, Material, User
from ..services import export
from ..templating import templates

router = APIRouter()

KIND_LABEL = {"cv": "CV", "cl": "cover letter"}


def _doc(db: DbSession, user: User, result_id: int, kind: str):
    if kind not in ("cv", "cl"):
        return None, None
    r = db.get(JobResult, result_id)
    if not r or r.user_id != user.id:
        return None, None
    doc = (db.query(Document)
             .filter(Document.job_result_id == result_id, Document.kind == kind,
                     Document.user_id == user.id)
             .order_by(Document.created_at.desc())
             .first())
    return r, doc


def _filename(r: JobResult, kind: str, ext: str) -> str:
    stem = "CV" if kind == "cv" else "CoverLetter"
    safe = "".join(c for c in (r.company or "job") if c.isalnum() or c in " -_")[:40].strip()
    return f"{stem}-{safe or 'job'}.{ext}"


@router.get("/document/{result_id}/{kind}", response_class=HTMLResponse)
def view(result_id: int, kind: str, request: Request, saved: str = "",
         user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    r, doc = _doc(db, user, result_id, kind)
    if not r or not doc:
        return RedirectResponse("/matches", status_code=303)
    # Thin-input nudge: a cover letter with nothing of the user's to learn from.
    has_cl = db.query(Material).filter(Material.user_id == user.id,
                                       Material.kind == "cover_letter").count() > 0
    return templates.TemplateResponse(request, "document.html", {
        "request": request, "user": user, "r": r, "doc": doc, "kind": kind,
        "kind_label": KIND_LABEL[kind], "saved": saved,
        "cl_thin": (kind == "cl" and not has_cl),
    })


@router.post("/document/{result_id}/{kind}/save")
def save(result_id: int, kind: str, content: str = Form(default=""),
         user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    r, doc = _doc(db, user, result_id, kind)
    if r and doc:
        doc.content = content
        db.commit()
    return RedirectResponse(f"/document/{result_id}/{kind}?saved=1", status_code=303)


@router.post("/document/{result_id}/{kind}/export/{fmt}")
def export_doc(result_id: int, kind: str, fmt: str, content: str = Form(default=""),
               user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    r, doc = _doc(db, user, result_id, kind)
    if not r or not doc:
        return RedirectResponse("/matches", status_code=303)
    # Exporting also persists the current edits, so the file matches the page.
    if content and content != doc.content:
        doc.content = content
        db.commit()
    body = doc.content
    title = f"{r.title} — {r.company}" if kind == "cv" else ""

    if fmt == "pdf":
        data, media = export.to_pdf(title, body), "application/pdf"
        name = _filename(r, kind, "pdf")
    elif fmt == "docx":
        data = export.to_docx(title, body)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        name = _filename(r, kind, "docx")
    else:  # txt
        data, media = body.encode("utf-8"), "text/plain; charset=utf-8"
        name = _filename(r, kind, "txt")

    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
