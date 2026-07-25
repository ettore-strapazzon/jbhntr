"""Authentication: sessions, signup/login, Google OAuth, login throttling."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from .config import config
from .db import get_session
from .models import Profile, Session, User, utcnow
from .security import hash_password, verify_password

COOKIE = "jbhntr_session"

# In-memory throttle. Fine for one instance; move to Redis when you scale out.
_attempts: dict[str, list[float]] = defaultdict(list)
MAX_ATTEMPTS = 8
WINDOW_S = 900  # 15 minutes


def throttled(key: str) -> bool:
    now = time.time()
    hits = [t for t in _attempts[key] if now - t < WINDOW_S]
    _attempts[key] = hits
    return len(hits) >= MAX_ATTEMPTS


def record_attempt(key: str) -> None:
    _attempts[key].append(time.time())


def clear_attempts(key: str) -> None:
    _attempts.pop(key, None)


# --------------------------------------------------------------------------- #
def create_user(db: DbSession, email: str, password: Optional[str] = None,
                google_sub: Optional[str] = None) -> User:
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password) if password else None,
        google_sub=google_sub,
        tos_accepted_at=utcnow(),
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id))  # empty profile so onboarding has a home
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: DbSession, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    # verify_password burns the same time when the account doesn't exist, so
    # timing doesn't reveal whether an email is registered.
    if verify_password(password, user.password_hash if user else None):
        return user
    return None


def login(db: DbSession, user: User) -> Session:
    session = Session.issue(user.id, config.session_days)
    user.last_login_at = utcnow()
    db.add(session)
    db.commit()
    return session


def logout(db: DbSession, token: str) -> None:
    db.query(Session).filter(Session.token == token).delete()
    db.commit()


def set_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE, token,
        max_age=config.session_days * 86400,
        httponly=True,                       # JS cannot read it → XSS can't steal it
        secure=not config.debug,             # HTTPS only in production
        samesite="lax",                      # blocks cross-site CSRF navigation
        path="/",
    )


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/")


# --------------------------------------------------------------------------- #
def current_session(request: Request, db: DbSession = Depends(get_session)) -> Optional[Session]:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    session = db.get(Session, token)
    if not session or not session.is_valid:
        return None
    return session


def current_user(request: Request, db: DbSession = Depends(get_session)) -> Optional[User]:
    """Logged-in user, or None. Use for pages that work either way."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    session = db.get(Session, token)
    if not session or not session.is_valid:
        return None
    return db.get(User, session.user_id)


def require_user(request: Request, db: DbSession = Depends(get_session)) -> User:
    """Dependency for pages that require login."""
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user
