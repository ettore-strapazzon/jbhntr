"""One provider-agnostic email sender (§11.13).

Plain SMTP driven by env vars. When SMTP isn't configured, send() is a safe
no-op that logs what it *would* have sent — so the flows that call it (password
reset, premium confirmation, search-complete) all work in development and don't
break in production until you add credentials. Swapping in Resend/Postmark/SES
later is a change to this one file.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from itsdangerous import BadData, URLSafeTimedSerializer

from ..config import config

log = logging.getLogger("jbhntr.email")


def is_configured() -> bool:
    return bool(config.smtp_host and config.smtp_from)


def send(to: str, subject: str, body: str) -> bool:
    """Send one plain-text email. Returns True if actually dispatched."""
    if not is_configured():
        log.info("email not configured — would send to %s: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = config.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as s:
            if config.smtp_tls:
                s.starttls(context=ssl.create_default_context())
            if config.smtp_user:
                s.login(config.smtp_user, config.smtp_password)
            s.send_message(msg)
        return True
    except Exception:
        log.exception("email send to %s failed", to)
        return False


# --- password-reset tokens (signed, no table needed) ---------------------- #
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.secret_key, salt="jbhntr-pwreset")


def make_reset_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_reset_token(token: str) -> int | None:
    try:
        data = _serializer().loads(token, max_age=config.reset_token_minutes * 60)
        return int(data["uid"])
    except (BadData, KeyError, ValueError, TypeError):
        return None


def send_password_reset(email: str, token: str) -> bool:
    link = f"{config.base_url.rstrip('/')}/reset?token={token}"
    return send(email, "Reset your JBHNTR password",
                "Someone asked to reset the password for this JBHNTR account.\n\n"
                f"Set a new one here (the link lasts {config.reset_token_minutes} minutes):\n{link}\n\n"
                "If it wasn't you, ignore this email — nothing changes.")


def send_welcome(email: str) -> bool:
    link = f"{config.base_url.rstrip('/')}/matches"
    return send(email, "Welcome to JBHNTR",
                "Welcome — you're in.\n\n"
                f"You've got {config.free_searches} free searches to start. Upload your CV, "
                "say what you're after in your own words, and JBHNTR builds you a scored "
                "shortlist with the reasoning attached.\n\n"
                f"Start here:\n{link}")


def send_premium_confirmation(email: str) -> bool:
    return send(email, "You're on the JBHNTR premium list",
                "Thanks. Premium is not on sale yet. You will hear from us once, "
                "when it opens, and nothing in between.")


