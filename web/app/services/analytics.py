"""Visitor counting.

Each pageview carries a `visitor` token: a one-way SHA-256 of a secret,
non-rotating salt (derived from SECRET_KEY) + the caller's IP + user-agent. The
salt does not change, so the same device/network produces the same token over
time — which lets us count *distinct people across days* (true monthly uniques),
not just per-day uniques. We still never store the raw IP: only the irreversible
token is persisted.

Privacy note: because the token is stable, it is a persistent pseudonymous
identifier (it can, in principle, tell that two visits days apart came from the
same device). That is a deliberate trade for cross-day accuracy. It is an
approximation — a changed IP (mobile networks, dynamic ISPs) or a browser update
mints a new token — so it counts distinct devices/networks, not literally people.
Review the lawful basis / disclosure for this before relying on it in the EU.
"""

from __future__ import annotations

import hashlib

from fastapi import Request

from ..config import config


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


def _salt() -> bytes:
    # Secret and stable: derived from SECRET_KEY so outsiders cannot recompute a
    # token, but never rotated, so the same visitor maps to the same token over time.
    return hashlib.sha256(f"{config.secret_key}|visitor-v1".encode()).digest()


def visitor_hash(ip: str, user_agent: str) -> str:
    """Stable one-way token for (ip, user-agent). Empty IP -> empty token (uncounted)."""
    if not ip:
        return ""
    h = hashlib.sha256()
    h.update(_salt())
    h.update(b"|")
    h.update(ip.encode("utf-8", "ignore"))
    h.update(b"|")
    h.update((user_agent or "").encode("utf-8", "ignore"))
    return h.hexdigest()
