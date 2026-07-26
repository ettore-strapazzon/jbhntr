"""Applications (§11.10) — a plain table of everything marked applied, with the
documents you sent and a status column. Deliberately not a CRM."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Document, JobResult, JobState, User
from ..services.job_state import APPLICATION_STATUSES
from ..templating import templates

router = APIRouter()


@router.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request, user: User = Depends(require_user),
                      db: DbSession = Depends(get_session)):
    applied = (db.query(JobState)
                 .filter(JobState.user_id == user.id, JobState.applied_at.isnot(None))
                 .order_by(JobState.applied_at.desc())
                 .all())

    keys = [s.dedup_key for s in applied]
    # Latest result row per posting, so we have a title/company/apply link.
    result_by_key: dict[str, JobResult] = {}
    if keys:
        for r in (db.query(JobResult)
                    .filter(JobResult.user_id == user.id, JobResult.dedup_key.in_(keys))
                    .order_by(JobResult.id)):
            result_by_key[r.dedup_key] = r

    docs: dict[int, set[str]] = {}
    for d in db.query(Document).filter(Document.user_id == user.id):
        docs.setdefault(d.job_result_id, set()).add(d.kind)

    rows = []
    for st in applied:
        r = result_by_key.get(st.dedup_key)
        if r:
            rows.append({"st": st, "r": r, "docs": docs.get(r.id, set())})

    return templates.TemplateResponse(request, "applications.html", {
        "request": request, "user": user, "rows": rows,
        "statuses": APPLICATION_STATUSES,
    })
