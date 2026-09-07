"""Referral codes (REFERRAL groundwork).

A short, unambiguous, unique-per-user code used to build invite links. Full
redemption (crediting inviter and friend) lands in the REFERRAL step; this module
only mints a code and hands back the invite URL, so the welcome email and the
/credits page can show them now.
"""

from __future__ import annotations

import secrets

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
    return inviter


def reward_inviter_if_activated(db, friend: User) -> None:
    """Pay the inviter once the friend they referred has activated (completed their
    first market scan). Idempotent on the friend, so it is safe to call after every
    completed scan. No-op for a non-referred user. Never raises into the caller."""
    inviter_id = friend.referred_by_user_id
    if not inviter_id:
        return
    try:
        inviter = db.get(User, inviter_id)
        if inviter is None:
            return
        from . import credits
        credits.grant(db, inviter, config.referral_credits, "referral_activated",
                      idempotency_key=f"referral:{friend.id}")
    except Exception:  # a reward must never break the scan that triggered it
        import logging
        logging.getLogger("jbhntr.referral").exception(
            "inviter reward failed for friend %s", friend.id)
