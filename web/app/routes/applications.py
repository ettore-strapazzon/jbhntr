"""My Jobs — the pipeline tracker: everything saved or applied, grouped by stage,
with a needs-you strip and per-job timelines. Deliberately not a CRM."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import Document, JobEvent, JobResult, JobState, User, aware, utcnow
from ..services import job_events, job_state
from ..templating import templates

router = APIRouter()

FOLLOW_UP_DAYS = 7      # applied this long ago, still in "Applied" -> nudge a follow-up
OFFER_DECIDE_DAYS = 5   # in "Offer" with no change this long -> nudge a decision


def _nudge(st: JobState, r: JobResult, stage: str, today: date) -> dict | None:
    # 1. An explicit next step due within a week (or overdue).
    if st.next_step_on and st.next_step_on <= today + timedelta(days=7):
        overdue = st.next_step_on < today
        return {"company": r.company, "text": st.next_step or "Next step",
                "when": st.next_step_on, "overdue": overdue, "order": 0 if overdue else 2}
    # 2. Sat in "Applied" too long.
    if stage == "Applied":
        applied = aware(st.applied_at)
        if applied and (utcnow() - applied).days >= FOLLOW_UP_DAYS:
            days = (utcnow() - applied).days
            return {"company": r.company, "text": f"Follow up — applied {days} days ago",
                    "when": None, "overdue": False, "order": 3}
    # 3. An offer awaiting a decision.
    if stage == "Offer":
        upd = aware(st.updated_at)
        if upd and (utcnow() - upd).days >= OFFER_DECIDE_DAYS:
            return {"company": r.company, "text": "Decide on this offer",
                    "when": None, "overdue": False, "order": 1}
    return None


@router.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request, user: User = Depends(require_user),
                      db: DbSession = Depends(get_session)):
    states = (db.query(JobState)
              .filter(JobState.user_id == user.id,
                      JobState.dismissed.is_(False),
                      or_(JobState.saved.is_(True), JobState.applied_at.isnot(None)))
              .all())
    keys = [s.dedup_key for s in states]

    result_by_key: dict[str, JobResult] = {}
    events_by_key: dict[str, list] = defaultdict(list)
    if keys:
        for r in (db.query(JobResult)
                  .filter(JobResult.user_id == user.id, JobResult.dedup_key.in_(keys))
                  .order_by(JobResult.id)):
            result_by_key[r.dedup_key] = r          # newest id wins
        for ev in (db.query(JobEvent)
                   .filter(JobEvent.user_id == user.id, JobEvent.dedup_key.in_(keys))
                   .order_by(JobEvent.occurred_on.desc(), JobEvent.id.desc())):
            events_by_key[ev.dedup_key].append(ev)

    docs: dict[int, set[str]] = defaultdict(set)
    for d in db.query(Document).filter(Document.user_id == user.id):
        docs[d.job_result_id].add(d.kind)

    groups = {s: [] for s in job_state.STAGE_ORDER}
    counts = {s: 0 for s in job_state.STAGE_ORDER}
    needs = []
    today = date.today()
    for st in states:
        r = result_by_key.get(st.dedup_key)
        if not r:
            continue
        stage = job_state.stage_of(st)
        groups[stage].append({"st": st, "r": r, "stage": stage,
                              "docs": docs.get(r.id, set()),
                              "events": events_by_key.get(st.dedup_key, [])})
        counts[stage] += 1
        n = _nudge(st, r, stage, today)
        if n:
            needs.append(n)

    for s in groups:
        groups[s].sort(key=lambda x: aware(x["st"].updated_at) or utcnow(), reverse=True)
    needs.sort(key=lambda n: n["order"])

    return templates.TemplateResponse(request, "applications.html", {
        "request": request, "user": user,
        "groups": groups, "counts": counts, "needs": needs,
        "stage_order": job_state.STAGE_ORDER,
        "pipeline_stages": job_state.PIPELINE_STAGES,
        "close_outcomes": job_state.CLOSE_OUTCOMES,
        "event_kinds": job_events.EVENT_KINDS,
        "has_any": bool(groups and any(counts.values())),
    })
