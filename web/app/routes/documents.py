"""Tailored-document view + export (§11.8, F-10).

The old flow handed back a .txt attachment. This renders the draft on a page you
can edit in place, then export as PDF, DOCX or text — a first draft you finish,
not a download you fight with.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
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
    from ..services import cv_style, gdocs
    r, doc = _doc(db, user, result_id, kind)
    if not r or not doc:
        return RedirectResponse("/matches", status_code=303)
    # Thin-input nudge: a cover letter with nothing of the user's to learn from.
    has_cl = db.query(Material).filter(Material.user_id == user.id,
                                       Material.kind == "cover_letter").count() > 0
    revisions = (db.query(Document)
                 .filter(Document.job_result_id == result_id, Document.kind == kind,
                         Document.user_id == user.id)
                 .order_by(Document.created_at.desc())
                 .all())
    return templates.TemplateResponse(request, "document.html", {
        "request": request, "user": user, "r": r, "doc": doc, "kind": kind,
        "kind_label": KIND_LABEL[kind], "saved": saved,
        "cl_thin": (kind == "cl" and not has_cl),
        "revisions": revisions,
        "refined": (request.query_params.get("refined") == "1"),
        "error": request.query_params.get("error", ""),
        "gdoc_enabled": gdocs.enabled(),
        "preview_style": cv_style.public_style(cv_style.profile_for(db, user.id)),
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

    # Match the CV export to the candidate's uploaded CV style (cover letters stay
    # plain prose). Falls back to the plain renderers when there's no CV on file.
    from ..services import cv_style
    style = cv_style.profile_for(db, user.id) if kind == "cv" else None

    if fmt == "pdf":
        data = (export.to_pdf_styled(title, body, style) if kind == "cv"
                else export.to_pdf(title, body))
        media = "application/pdf"
        name = _filename(r, kind, "pdf")
    elif fmt == "docx":
        if kind == "cv" and style and style.source == "docx" and style.docx_bytes:
            data = export.to_docx_templated(style.docx_bytes, title, body)
        else:
            data = export.to_docx(title, body)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        name = _filename(r, kind, "docx")
    else:  # txt
        data, media = body.encode("utf-8"), "text/plain; charset=utf-8"
        name = _filename(r, kind, "txt")

    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/document/{result_id}/{kind}/refine")
def refine(result_id: int, kind: str, feedback: str = Form(...),
           content: str = Form(default=""),
           user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """Redraft the CV/CL from the user's feedback + the current draft, as a new
    revision. Free — the job's allowance was already spent on the first draft."""
    from ..services.events import record
    from ..services.profile_service import build_generation_context
    from ..services.text import humanise

    r, doc = _doc(db, user, result_id, kind)
    if not r or not doc:
        return RedirectResponse("/applications", status_code=303)
    if not feedback.strip():
        return RedirectResponse(f"/document/{result_id}/{kind}", status_code=303)

    base = content.strip() or doc.content        # refine what the user currently sees
    gen, eng_profile, eng_materials, posting = build_generation_context(db, user, r, config)
    out = gen.refine(kind, base, feedback, eng_profile, eng_materials, posting)
    if not out or not out.get("content"):
        return RedirectResponse(
            f"/document/{result_id}/{kind}?error=" + quote("Refine returned nothing. Try again."),
            status_code=303)

    db.add(Document(user_id=user.id, job_result_id=result_id, kind=kind,
                    content=humanise(out["content"]),
                    note=humanise(out.get("change_note", "")) or doc.note))
    db.commit()
    record(db, "document_refined", user_id=user.id, kind=kind)
    return RedirectResponse(f"/document/{result_id}/{kind}?refined=1", status_code=303)


@router.post("/document/{result_id}/{kind}/gdoc")
def open_gdoc(result_id: int, kind: str, content: str = Form(default=""),
              user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """Create (or reuse) a formatted Google Doc from the current draft and redirect
    to it. The service account creates it and shares it with the user as editor."""
    from ..services import gdocs

    r, doc = _doc(db, user, result_id, kind)
    if not r or not doc:
        return RedirectResponse("/applications", status_code=303)
    if not gdocs.enabled():
        return RedirectResponse(
            f"/document/{result_id}/{kind}?error=" + quote("Google Docs isn't configured."),
            status_code=303)
    # Persist current edits so the Doc matches the page, then reuse an existing Doc
    # for this (unchanged) draft rather than spawning duplicates.
    if content and content != doc.content:
        doc.content = content
        doc.gdoc_url = ""            # content changed -> make a fresh doc
        db.commit()
    if doc.gdoc_url:
        return RedirectResponse(doc.gdoc_url, status_code=303)

    title = (f"CV — {r.title} at {r.company}" if kind == "cv"
             else f"Cover letter — {r.company}")
    url = gdocs.create_doc(title, doc.content, user.email)
    if not url:
        return RedirectResponse(
            f"/document/{result_id}/{kind}?error=" + quote(
                "Couldn't create the Google Doc. Try again, or download DOCX."),
            status_code=303)
    doc.gdoc_url = url
    db.commit()
    from ..services.events import record
    record(db, "gdoc_created", user_id=user.id, kind=kind)
    return RedirectResponse(url, status_code=303)


@router.post("/document/{result_id}/{kind}/restore/{doc_id}")
def restore(result_id: int, kind: str, doc_id: int,
            user: User = Depends(require_user), db: DbSession = Depends(get_session)):
    """Restore an older revision by appending a fresh copy (history stays append-only)."""
    r, _ = _doc(db, user, result_id, kind)
    src = db.get(Document, doc_id)
    if r and src and src.user_id == user.id and src.job_result_id == result_id and src.kind == kind:
        db.add(Document(user_id=user.id, job_result_id=result_id, kind=kind,
                        content=src.content, note=src.note))
        db.commit()
    return RedirectResponse(f"/document/{result_id}/{kind}", status_code=303)
