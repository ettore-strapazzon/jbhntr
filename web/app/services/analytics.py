"""Privacy-safe visitor counting.

We never store an IP address. Instead each pageview carries a `visitor` token:
a SHA-256 of (a secret salt that rotates every day) + the caller's IP + the
user-agent. The same person on the same day produces the same token — so we can
count distinct visitors — but the token cannot be reversed to an IP and a fresh
salt tomorrow makes it useless for following anyone across days. This is the same
technique Plausible and Cloudflare use to count visitors without consent banners.
"""

from __future__ import annotations

import hashlib
from datetime import date

from fastapi import Request

from ..config import config
from ..models import utcnow


def client_ip(request: Request) -> str:
    """The caller's real IP, read transiently from proxy headers. Never stored."""
    for header in ("cf-connecting-ip", "true-client-ip"):
        v = request.headers.get(header)
        if v:
            return v.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()          # first hop is the client
    return request.client.host if request.client else ""


def _daily_salt(day: date) -> bytes:
    # Derived from SECRET_KEY so it is stable within a day and unknowable to
    # anyone without the key; changes at UTC midnight so tokens never carry over.
    return hashlib.sha256(f"{config.secret_key}|{day.isoformat()}".encode()).digest()


def visitor_hash(ip: str, user_agent: str, day: date | None = None) -> str:
    """One-way daily token for (ip, user-agent). Empty IP -> empty token (uncounted)."""
    if not ip:
        return ""
    day = day or utcnow().date()
    h = hashlib.sha256()
    h.update(_daily_salt(day))
    h.update(b"|")
    h.update(ip.encode("utf-8", "ignore"))
    h.update(b"|")
    h.update((user_agent or "").encode("utf-8", "ignore"))
    return h.hexdigest()
