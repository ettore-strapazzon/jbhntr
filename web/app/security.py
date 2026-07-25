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


def new_secret(length: int = 48) -> str:
    return secrets.token_urlsafe(length)
