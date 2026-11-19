"""Passwords, file encryption, upload validation, CSRF.

Everything here protects user CVs, which are the most sensitive thing this
service stores — see docs/SECURITY_AND_GDPR.md.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from passlib.context import CryptContext

from .config import config

log = logging.getLogger("jbhntr.security")

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: Optional[str]) -> bool:
    """Constant-ish time check that tolerates accounts with no password.

    Google-only accounts have `password_hash = None`. We still run a dummy
    verify so the response time doesn't reveal whether an account exists.
    """
    if not hashed:
        _pwd.verify(password, _pwd.hash("dummy"))  # burn the same time
        return False
    try:
        return _pwd.verify(password, hashed)
    except Exception:
        return False


def password_problems(password: str) -> list[str]:
    out = []
    if len(password) < 10:
        out.append("Use at least 10 characters.")
    if password.isdigit() or password.isalpha():
        out.append("Mix letters with numbers or symbols.")
    if password.lower() in {"password12", "123456789012", "qwertyuiop"}:
        out.append("That password is too common.")
    return out


# --------------------------------------------------------------------------- #
# File encryption
# --------------------------------------------------------------------------- #
def _fernet() -> Fernet:
    key = config.file_encryption_key
    if not key:
        raise RuntimeError(
            "FILE_ENCRYPTION_KEY is not set — refusing to store uploads in plaintext. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet;"
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_bytes(raw: bytes) -> bytes:
    return _fernet().encrypt(raw)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as exc:
        raise RuntimeError(
            "Could not decrypt a stored file — FILE_ENCRYPTION_KEY has changed."
        ) from exc


def rotate_key(old_key: str, new_key: str, ciphertext: bytes) -> bytes:
    """Re-encrypt one blob under a new key (used by a key-rotation script)."""
    return Fernet(new_key.encode()).encrypt(Fernet(old_key.encode()).decrypt(ciphertext))


# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #
# Extension alone is trivially spoofed, so the leading bytes are checked too.
MAGIC = {
    b"%PDF": ("pdf", "application/pdf"),
    b"PK\x03\x04": ("docx", "application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document"),
}
TEXT_EXTS = {".txt", ".md"}


class UploadError(ValueError):
    pass


def validate_upload(filename: str, raw: bytes) -> tuple[str, str]:
    """Return (extension, mime) or raise UploadError.

    Accepts PDF, DOCX, TXT and MD only. Anything else — including a renamed
    executable — is rejected before it is ever stored.
    """
    if not raw:
        raise UploadError("That file is empty.")
    if len(raw) > config.max_upload_bytes:
        mb = config.max_upload_bytes / 1024 / 1024
        raise UploadError(f"File is too large — the limit is {mb:.0f} MB.")

    lowered = (filename or "").lower()
    for magic, (ext, mime) in MAGIC.items():
        if raw.startswith(magic):
            if ext == "docx" and not lowered.endswith(".docx"):
                raise UploadError("That looks like a zip, not a .docx file.")
            return ext, mime

    if any(lowered.endswith(e) for e in TEXT_EXTS):
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadError("Text files must be UTF-8.")
        return lowered.rsplit(".", 1)[-1], "text/plain"

    raise UploadError("Unsupported file type. Please upload a PDF, DOCX, TXT or MD.")


def extract_text(ext: str, raw: bytes) -> str:
    """Pull plain text out of an upload so the AI can read it."""
    try:
        if ext == "pdf":
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        if ext == "docx":
            import io

            from docx import Document as Docx

            return "\n".join(p.text for p in Docx(io.BytesIO(raw)).paragraphs).strip()
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        log.warning("Could not extract text from a %s upload: %s", ext, exc)
        return ""


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #
def csrf_token(session_token: str) -> str:
    return hmac.new(
        config.secret_key.encode(), session_token.encode(), "sha256"
    ).hexdigest()


def csrf_ok(session_token: str, submitted: str) -> bool:
    return bool(submitted) and hmac.compare_digest(csrf_token(session_token), submitted)


# --------------------------------------------------------------------------- #
# Same-origin check (browser cross-site request refusal)
# --------------------------------------------------------------------------- #
def require_same_origin(request: Request) -> None:
    """Reject a browser cross-site request: Sec-Fetch-Site cross-site/same-site, or
    an Origin (including the opaque `null`) whose host is not ours. Requests with
    neither header — curl/script callers — pass unchanged. Use after the route's
    auth gate (require_admin on /admin and /boardroom); also guards POST /logout."""
    if request.headers.get("sec-fetch-site", "") in ("cross-site", "same-site"):
        raise HTTPException(status_code=403, detail="Cross-site request refused")
    origin = request.headers.get("origin")
    if origin is not None:
        from urllib.parse import urlsplit
        if origin == "null" or urlsplit(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(status_code=403, detail="Cross-origin request refused")


def new_secret(length: int = 48) -> str:
    return secrets.token_urlsafe(length)


# R3-42: cap request bodies before Starlette parses them — multipart is spooled to
# temp disk before require_admin runs, so this must sit outside routing.
BODY_LIMIT_DEFAULT = 2 * 1024 * 1024                  # > the 1 MB CV upload + multipart overhead
BODY_LIMITS = {"/boardroom/send": 11 * 1024 * 1024}   # 5 files / 10 MB attachments + text


class BodySizeLimit:
    """Pure ASGI middleware: 413 on an over-cap Content-Length up front; bodies without
    one (chunked) are counted as they stream and cut off once over the cap."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = BODY_LIMITS.get(scope["path"], BODY_LIMIT_DEFAULT)
        length = dict(scope["headers"]).get(b"content-length", b"").decode("latin-1")
        if length and (not length.isdigit() or int(length) > limit):
            from starlette.responses import PlainTextResponse
            return await PlainTextResponse("Request body too large.", 413)(scope, receive, send)

        seen = 0

        async def capped_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    # Handled by Starlette's ExceptionMiddleware (and passed through by FastAPI).
                    raise HTTPException(status_code=413, detail="Request body too large.")
            return message

        await self.app(scope, capped_receive, send)
