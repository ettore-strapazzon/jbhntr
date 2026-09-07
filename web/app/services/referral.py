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
    """The shareable link. `ref` is ignored until REFERRAL wires redemption, so the
    link is safe to circulate now and starts crediting once that ships."""
    return f"{config.base_url.rstrip('/')}/signup?ref={code}"
