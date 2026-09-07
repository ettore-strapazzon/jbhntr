"""One-off, idempotent backfill onto the credit economy (Guide v3.0, LEDGER-05).

Founder decision: no usage migration. Existing accounts are simply opened on the
new economy — every user gets the signup grant once, and anyone who has already
searched is marked as having used their free first scan (so they aren't handed a
retroactive one). Historic searches_used / documents_used are NOT debited, and no
premium goodwill grant is written. Safe to run repeatedly; callable from an admin
route and from startup.
"""

from __future__ import annotations

import logging

from ..config import config
from ..models import CreditLedger, OpsLog, User, utcnow
from . import credits

log = logging.getLogger("jbhntr.migrate_credits")


def run(db) -> dict:
    """Grant the signup credits to any user missing them; mark existing searchers'
    free scan as used. Returns counts; records an OpsLog row."""
    from . import referral
    granted = scan_marked = coded = 0
    have_grant = {uid for (uid,) in db.query(CreditLedger.user_id)
                  .filter(CreditLedger.reason == "signup_grant").all()}
    for user in db.query(User).all():
        if user.id not in have_grant:
            row = credits.grant(db, user, config.signup_grant_credits, "signup_grant",
                                idempotency_key=f"signup:{user.id}")
            if row is not None:
                granted += 1
        # Existing users who have searched don't get a retroactive free scan.
        if user.first_scan_used_at is None and (user.searches_used or 0) > 0:
            user.first_scan_used_at = user.created_at or utcnow()
            scan_marked += 1
        # Every account needs an invite code for the referral link (REFERRAL groundwork).
        if not user.referral_code:
            referral.ensure_code(db, user)
            coded += 1
    db.commit()
    res = {"granted": granted, "scan_marked": scan_marked, "coded": coded}
    db.add(OpsLog(kind="migrate_credits", detail=str(res)))
    db.commit()
    log.info("migrate_credits: %s", res)
    return res
