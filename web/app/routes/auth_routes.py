"""Signup, login, logout, Google OAuth."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from ..auth import (
    authenticate, clear_attempts, clear_cookie, create_user, login, logout,
    record_attempt, set_cookie, throttled,
)
from ..config import config
from ..db import get_session
from ..models import User
from ..security import password_problems
from ..templating import templates

log = logging.getLogger("jbhntr.auth")
router = APIRouter()

GENERIC_LOGIN_ERROR = "That email or password isn't right."


def _render(request: Request, page: str, **ctx):
    return templates.TemplateResponse(request, page, {"request": request, **ctx})


# --------------------------------------------------------------------------- #
@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    return _render(request, "signup.html")


@router.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    accept_tos: str = Form(default=""),
    marketing: str = Form(default=""),
    db: DbSession = Depends(get_session),
):
    email = (email or "").strip().lower()
    errors: list[str] = []

    if "@" not in email or len(email) > 320:
        errors.append("Enter a valid email address.")
    if not accept_tos:
        errors.append("Please accept the Terms and Privacy Policy.")
    errors += password_problems(password)

    if not errors and db.query(User).filter(User.email == email).first():
        # Don't confirm the address exists; point them at login instead.
        errors.append("That email can't be used. If you already have an account, log in.")

    if errors:
        return _render(request, "signup.html", errors=errors, email=email)

    user = create_user(db, email, password=password)
    user.marketing_opt_in = bool(marketing)
    db.commit()

    session = login(db, user)
    response = RedirectResponse("/onboarding", status_code=303)
    set_cookie(response, session.token)
    return response


# --------------------------------------------------------------------------- #
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return _render(request, "login.html", google_enabled=bool(config.google_client_id))


@router.post("/login")
def do_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: DbSession = Depends(get_session),
):
    key = f"{request.client.host if request.client else 'unknown'}|{email.lower()}"
    if throttled(key):
        return _render(request, "login.html",
                       errors=["Too many attempts. Please wait 15 minutes."],
                       google_enabled=bool(config.google_client_id))

    user = authenticate(db, email, password)
    if not user:
        record_attempt(key)
        # Identical message whether the account exists or the password is wrong.
        return _render(request, "login.html", errors=[GENERIC_LOGIN_ERROR], email=email,
                       google_enabled=bool(config.google_client_id))

    clear_attempts(key)
    session = login(db, user)
    response = RedirectResponse("/matches", status_code=303)
    set_cookie(response, session.token)
    return response


@router.get("/logout")
@router.post("/logout")
def do_logout(request: Request, db: DbSession = Depends(get_session)):
    from ..auth import COOKIE

    token = request.cookies.get(COOKIE)
    if token:
        logout(db, token)
    response = RedirectResponse("/", status_code=303)
    clear_cookie(response)
    return response


# --------------------------------------------------------------------------- #
# Google OAuth — only mounted when credentials are configured.
# --------------------------------------------------------------------------- #
def _oauth():
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


@router.get("/auth/google")
async def google_start(request: Request):
    if not config.google_client_id:
        return RedirectResponse("/login", status_code=303)
    oauth = _oauth()
    return await oauth.google.authorize_redirect(
        request, f"{config.base_url}/auth/google/callback"
    )


@router.get("/auth/google/callback")
async def google_callback(request: Request, db: DbSession = Depends(get_session)):
    if not config.google_client_id:
        return RedirectResponse("/login", status_code=303)
    try:
        oauth = _oauth()
        token = await oauth.google.authorize_access_token(request)
        info = token.get("userinfo") or {}
        email = (info.get("email") or "").strip().lower()
        sub = info.get("sub")
        if not email or not sub:
            raise ValueError("Google returned no email")
    except Exception as exc:
        log.warning("Google sign-in failed: %s", exc)
        return _render(request, "login.html",
                       errors=["Google sign-in failed. Please try again."],
                       google_enabled=True)

    user = db.query(User).filter(User.google_sub == sub).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_sub = sub  # link Google to the existing account
            db.commit()
        else:
            user = create_user(db, email, google_sub=sub)

    session = login(db, user)
    destination = "/matches" if user.profile and user.profile.objective else "/onboarding"
    response = RedirectResponse(destination, status_code=303)
    set_cookie(response, session.token)
    return response


# --------------------------------------------------------------------------- #
# Password reset (§11.13). Tokens are signed (no table); emails go through the
# provider-agnostic sender, so this works once SMTP is configured and is a
# safe no-op — with the link logged — before then.
# --------------------------------------------------------------------------- #
RESET_SENT = ("If that email has an account, we've sent a reset link. "
              "Check your inbox.")


@router.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request):
    return _render(request, "forgot.html")


@router.post("/forgot", response_class=HTMLResponse)
def forgot(request: Request, email: str = Form(...),
           db: DbSession = Depends(get_session)):
    from ..services import email as mail

    user = db.query(User).filter(User.email == email.strip().lower()).first()
    # Only send to real password accounts, but always show the same message so
    # the response can't be used to enumerate accounts.
    if user and user.password_hash:
        mail.send_password_reset(user.email, mail.make_reset_token(user.id))
    return _render(request, "forgot.html", sent=RESET_SENT)


@router.get("/reset", response_class=HTMLResponse)
def reset_form(request: Request, token: str = ""):
    from ..services.email import read_reset_token

    if read_reset_token(token) is None:
        return _render(request, "reset.html",
                       errors=["That reset link is invalid or has expired."])
    return _render(request, "reset.html", token=token)


@router.post("/reset", response_class=HTMLResponse)
def reset(request: Request, token: str = Form(...), password: str = Form(...),
          db: DbSession = Depends(get_session)):
    from ..security import hash_password
    from ..services.email import read_reset_token

    uid = read_reset_token(token)
    if uid is None:
        return _render(request, "reset.html",
                       errors=["That reset link is invalid or has expired."])
    problems = password_problems(password)
    if problems:
        return _render(request, "reset.html", token=token, errors=problems)

    user = db.get(User, uid)
    if not user:
        return _render(request, "reset.html",
                       errors=["That account no longer exists."])
    user.password_hash = hash_password(password)
    # Invalidate existing sessions so a leaked session can't outlive the reset.
    from ..models import Session as DbSess
    db.query(DbSess).filter(DbSess.user_id == user.id).delete()
    db.commit()

    session = login(db, user)
    response = RedirectResponse("/matches", status_code=303)
    set_cookie(response, session.token)
    return response
