"""The premium daily/weekly digest (R13.4).

Non-negotiable rules baked in here, not in the template: never send an empty
digest, cap at eight roles, never repeat a role already digested / dismissed /
saved / applied, and honour each user's frequency.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session as DbSession

from ..models import User, utcnow
from . import email as mail
from . import matches_service
from .job_state import get_or_create
from .profile_service import strength

log = logging.getLogger("jbhntr.digest")
DIGEST_CAP = 8


def _fresh(card) -> bool:
    st = card.st
    return not (st and (st.saved or st.applied_at or st.dismissed or st.digest_sent_at))


def build_digest(db: DbSession, user: User) -> dict | None:
    """Context for one user's digest, or None when there is nothing worth sending."""
    m = matches_service.build(db, user)
    main = [c for g in m.groups for c in g.cards if _fresh(c)]      # tier 1-3
    longs = [c for c in m.long_shots if _fresh(c)]
    if not main:
        return None                                                # the empty-day rule

    main.sort(key=lambda c: -c.r.score)
    rows = main[:DIGEST_CAP]
    from .text import as_bullets

    def row(c):
        r = c.r
        return {
            "id": r.id, "score": r.score, "tier_label": r.tier_label,
            "title": r.title, "company": r.company, "location": r.location,
            "good": (as_bullets(r.why_good, 1) or [""])[0],
            "bad": (as_bullets(r.why_bad, 1) or [""])[0],
        }

    st = strength(db, user)
    ctx = {
        "n": len(main), "top_score": main[0].r.score,
        "top_title": main[0].r.title, "top_company": main[0].r.company,
        "top_location": main[0].r.location,
        "reviewed": m.latest.raw_count if m.latest else 0,
        "jobs": [row(c) for c in rows],
        "remaining": max(0, len(main) - len(rows)),
        "remaining_longshots": len(longs),
        "closing": _closing(db, user, st),
        "email": user.email,
    }
    # Mark everything covered so it is never repeated.
    for c in main + longs:
        get_or_create(db, user.id, c.r.dedup_key).digest_sent_at = utcnow()
    db.commit()
    return ctx


def _closing(db, user, st) -> str:
    from ..models import Feedback
    rated = db.query(Feedback).filter(Feedback.user_id == user.id,
                                      Feedback.rating.isnot(None)).count()
    if rated < 5:
        return "Rate a few of these out of five. It is the fastest way to make tomorrow's list better."
    if st.below_good and st.nudge:
        return f"Your profile is thin on {st.nudge.signal}. Two minutes there changes what turns up here."
    return "Nothing to do. Tomorrow's run is already scheduled."


def run_digests(db: DbSession, *, is_weekly_day: bool) -> dict:
    """Send digests to premium users who are due one. Called by the cron."""
    sent = 0
    users = (db.query(User)
               .filter(User.plan == "premium", User.digest.in_(("daily", "weekly")))
               .all())
    for user in users:
        if user.digest == "weekly" and not is_weekly_day:
            continue
        if not user.is_premium:
            continue
        try:
            ctx = build_digest(db, user)
            if ctx and mail.send_digest(user.email, ctx, mail.make_unsub_token(user.id)):
                sent += 1
        except Exception:
            log.exception("digest failed for user %s", user.id)
    log.info("digests sent: %d", sent)
    return {"sent": sent}
