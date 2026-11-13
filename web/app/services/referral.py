"""Referral codes (REFERRAL groundwork).

A short, unambiguous, unique-per-user code used to build invite links, the
friend's starter bonus at signup, and the inviter's reward. The inviter's reward
is delayed and soft-capped (R3-11, TERMS §6 / GTM §5): recorded as a pending
ReferralReward at the friend's activation, released by release_due() once the
payout delay has passed and the friend has triaged, held past the monthly
ceiling until an admin unlock.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy.exc import IntegrityError

from ..config import config
from ..models import User

# No 0/O/1/I/L — codes get read off a screen and typed by hand.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _mint(n: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def ensure_code(db, user: User) -> str:
    """Return the user's referral code, minting and storing a unique one on first
    use. Caller commits. Idempotent: an existing code is returned untouched."""
    if user.referral_code:
        return user.referral_code
    for _ in range(6):
        code = _mint()
        if not db.query(User).filter(User.referral_code == code).first():
            user.referral_code = code
            db.add(user)
            return code
    # Astronomically unlikely to get here; a longer code makes a clash negligible.
    user.referral_code = _mint(12)
    db.add(user)
    return user.referral_code


def invite_url(code: str) -> str:
    """The shareable link a user hands to a friend."""
    return f"{config.base_url.rstrip('/')}/signup?ref={code}"


def resolve(db, code: str) -> User | None:
    """The user who owns `code`, or None. Case-insensitive; codes are stored upper."""
    code = (code or "").strip().upper()[:12]
    if not code:
        return None
    return db.query(User).filter(User.referral_code == code).first()


def attach_and_reward_friend(db, friend: User, code: str) -> User | None:
    """At signup with a valid invite code: record who referred this account and grant
    the friend their starter bonus. Returns the inviter, or None when the code is
    empty/unknown, a self-referral, or the friend is already attributed. Idempotent
    on the friend (the bonus grant is keyed on the friend's id). Caller need not
    commit — this does."""
    if friend.referred_by_user_id:
        return None
    inviter = resolve(db, code)
    if inviter is None or inviter.id == friend.id:
        return None
    friend.referred_by_user_id = inviter.id
    db.add(friend)
    from . import credits
    credits.grant(db, friend, config.referral_friend_credits, "referral_bonus",
                  idempotency_key=f"referral_bonus:{friend.id}")
    db.commit()
    from . import events
    events.record(db, "referred_signup", user_id=friend.id, source="referral")
    return inviter


TRIAGE_EVENTS = ("job_saved", "job_dismissed", "job_marked_applied", "match_rated")
_log = logging.getLogger("jbhntr.referral")


def _ledger_key(friend_id: int) -> str:
    # Same key the old immediate payout used, so a friend already paid under the
    # old rule can never be paid again by a release.
    return f"referral:{friend_id}"


def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def reward_inviter_if_activated(db, friend: User) -> None:
    """The friend activated (completed a scan): record the inviter's reward as
    PENDING — never pay now (R3-11, TERMS §6 / GTM §5). Past the inviter's soft
    monthly ceiling the reward is HELD for a human unlock instead. Idempotent on
    the friend (one ReferralReward per friend), safe after every completed scan.
    No-op for a non-referred user. Never raises into the caller."""
    inviter_id = friend.referred_by_user_id
    if not inviter_id:
        return
    # Mirror the activation into ProductEvent so the funnel/K-factor dashboard
    # reads one table. record_once keeps it to a single event per friend even
    # though this runs after every completed scan.
    from . import events
    events.record_once(db, "referral_activated", friend.id)
    try:
        from ..models import CreditLedger, ReferralReward, utcnow
        if db.get(User, inviter_id) is None:
            return
        if db.query(ReferralReward.id).filter_by(friend_id=friend.id).first():
            release_due(db, friend_id=friend.id)     # opportunistic; still gated
            return
        now = utcnow()
        this_month = (db.query(ReferralReward)
                      .filter(ReferralReward.inviter_id == inviter_id,
                              ReferralReward.activated_at >= _month_start(now))
                      .count())
        rw = ReferralReward(inviter_id=inviter_id, friend_id=friend.id,
                            amount=config.referral_credits, activated_at=now)
        if (db.query(CreditLedger.id)
                .filter(CreditLedger.idempotency_key == _ledger_key(friend.id)).first()):
            rw.status, rw.released_at = "paid", now  # paid under the old rule
        elif this_month >= config.referral_monthly_ceiling:
            rw.status, rw.hold_reason = "held", "monthly_ceiling"
        db.add(rw)
        try:
            db.commit()
        except IntegrityError:                       # raced: the other insert won
            db.rollback()
    except Exception:  # a reward must never break the scan that triggered it
        db.rollback()
        _log.exception("inviter reward failed for friend %s", friend.id)


def has_triaged(db, friend_id: int) -> bool:
    """The friend's first triage action: saved / dismissed / marked applied /
    rated a match (event), or any JobState they created (belt and braces if an
    analytics write was lost)."""
    from ..models import JobState, ProductEvent
    if (db.query(ProductEvent.id)
            .filter(ProductEvent.user_id == friend_id,
                    ProductEvent.name.in_(TRIAGE_EVENTS)).first()):
        return True
    return db.query(JobState.id).filter(JobState.user_id == friend_id).first() is not None


def release_due(db, *, now=None, friend_id: int | None = None) -> int:
    """Pay every PENDING reward whose payout delay has elapsed AND whose friend
    has triaged. Idempotent: the ledger grant is keyed referral:{friend_id} and a
    paid row is never revisited, so re-running (cron + opportunistic) pays once.
    Returns how many rewards were paid this run."""
    from datetime import timedelta

    from ..models import ReferralReward, utcnow
    from . import credits
    now = now or utcnow()
    cutoff = now - timedelta(hours=config.referral_payout_delay_hours)
    q = db.query(ReferralReward).filter(ReferralReward.status == "pending",
                                        ReferralReward.activated_at <= cutoff)
    if friend_id is not None:
        q = q.filter(ReferralReward.friend_id == friend_id)
    paid = 0
    for rw in q.order_by(ReferralReward.id).all():
        try:
            if not has_triaged(db, rw.friend_id):
                continue
            inviter = db.get(User, rw.inviter_id)
            if inviter is None:
                continue
            credits.grant(db, inviter, rw.amount, "referral_activated",
                          ref_type="referral", ref_id=str(rw.friend_id),
                          idempotency_key=_ledger_key(rw.friend_id))
            rw.status, rw.released_at = "paid", now
            db.add(rw)
            db.commit()
            paid += 1
        except Exception:
            db.rollback()
            _log.exception("referral release failed for reward %s", rw.id)
    return paid


def unlock(db, reward_id: int) -> bool:
    """Admin: move a HELD reward back to pending so the next release run pays it
    (still subject to the delay + triage). False if it isn't held."""
    from ..models import ReferralReward, utcnow
    rw = db.get(ReferralReward, reward_id)
    if rw is None or rw.status != "held":
        return False
    rw.status, rw.unlocked_at = "pending", utcnow()
    db.add(rw)
    db.commit()
    return True


def hold(db, reward_id: int, reason: str = "review") -> bool:
    """Admin: hold a PENDING reward for review (duplicate/fraud suspicion,
    TERMS §6). False if it isn't pending (already paid or held)."""
    from ..models import ReferralReward
    rw = db.get(ReferralReward, reward_id)
    if rw is None or rw.status != "pending":
        return False
    rw.status, rw.hold_reason = "held", (reason or "review")[:24]
    db.add(rw)
    db.commit()
    return True
