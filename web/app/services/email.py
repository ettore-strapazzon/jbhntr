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

MAIL_FROM_NAME = "JBHNTR"   # display name in the inbox list (S-01)


def _from_header() -> str:
    from email.utils import formataddr
    return formataddr((MAIL_FROM_NAME, config.smtp_from))


def is_configured() -> bool:
    # A from-address plus either the HTTP API key or an SMTP host.
    return bool(config.smtp_from and (config.resend_api_key or config.smtp_host))


def _send_via_resend_api(to: str, subject: str, text: str,
                         html: str | None, headers: dict | None) -> bool:
    """POST to Resend over HTTPS (443). Used when RESEND_API_KEY is set, so it
    works on hosts that block outbound SMTP ports."""
    import httpx

    payload: dict = {"from": _from_header(), "reply_to": config.smtp_from,
                     "to": [to], "subject": subject, "text": text}
    if html:
        payload["html"] = html
    if headers:
        payload["headers"] = headers
    try:
        r = httpx.post("https://api.resend.com/emails", json=payload, timeout=15,
                       headers={"Authorization": f"Bearer {config.resend_api_key}"})
        if r.status_code >= 300:
            log.error("resend api send to %s failed: %s %s", to, r.status_code, r.text[:300])
            return False
        return True
    except Exception as exc:
        log.error("resend api send to %s failed: %s", to, exc)
        return False


def send(to: str, subject: str, text: str, html: str | None = None,
         headers: dict | None = None) -> bool:
    """Send one email. Plain text is the fallback; html is the alternative."""
    if not is_configured():
        log.info("email not configured — would send to %s: %s", to, subject)
        return False
    if config.resend_api_key:
        return _send_via_resend_api(to, subject, text, html, headers)
    msg = EmailMessage()
    msg["From"] = _from_header()
    msg["Reply-To"] = config.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(text)                       # plain text is the fallback
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as s:
            if config.smtp_tls:
                s.starttls(context=ssl.create_default_context())
            if config.smtp_user:
                s.login(config.smtp_user, config.smtp_password)
            s.send_message(msg)
        return True
    except Exception as exc:
        # Put the SMTP server's rejection reason on one line (the useful bit),
        # not buried in a stack trace.
        log.error("email send to %s failed: %s", to, exc)
        return False


def render(name: str, ctx: dict) -> tuple[str, str]:
    """(html, text) for templates/email/{name}.html and .txt (R13.1)."""
    from ..templating import templates
    env = templates.env
    base = config.base_url.rstrip("/")
    ctx = {**ctx, "base_url": base, "support_email": config.support_email, "config": config}
    # The shell shows an unsubscribe line only for opt-in mail that supplies a
    # signed unsubscribe token (digest, waiting-list). Transactional mail omits it.
    if ctx.get("unsub_token") and "unsub_url" not in ctx:
        ctx["unsub_url"] = f"{base}/unsubscribe?t={ctx['unsub_token']}"
    return (env.get_template(f"email/{name}.html").render(**ctx),
            env.get_template(f"email/{name}.txt").render(**ctx))


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


# --- unsubscribe tokens for the digest (signed, work without login) --------- #
def _unsub_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.secret_key, salt="jbhntr-unsub")


def make_unsub_token(user_id: int) -> str:
    return _unsub_serializer().dumps({"uid": user_id})


def read_unsub_token(token: str) -> int | None:
    try:
        return int(_unsub_serializer().loads(token, max_age=400 * 86400)["uid"])
    except (BadData, KeyError, ValueError, TypeError):
        return None


def send_password_reset(email: str, token: str) -> bool:
    html, text = render("reset", {"token": token})
    return send(email, "Reset your JBHNTR password", text, html)


def send_welcome(email: str) -> bool:
    html, text = render("welcome", {"free_searches": config.free_searches})
    return send(email, "You are in. One upload and the hunting starts.", text, html)


def send_digest(email: str, ctx: dict, unsub_token: str) -> bool:
    """Premium daily/weekly digest (R13.4). Caller guarantees it is non-empty."""
    html, text = render("digest", {**ctx, "unsub_token": unsub_token})
    base = config.base_url.rstrip("/")
    n = ctx.get("n", 0)
    top = ctx.get("top_score", 0)
    roles = "role" if n == 1 else "roles"
    subject = f"{n} new {roles}, best is {top}/100"
    return send(email, subject, text, html, headers={
        "List-Unsubscribe": f"<{base}/unsubscribe?t={unsub_token}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    })


def send_premium_confirmation(email: str) -> bool:
    return send(email, "You're on the JBHNTR premium list",
                "Thanks. Premium is not on sale yet. You will hear from us once, "
                "when it opens, and nothing in between.")


