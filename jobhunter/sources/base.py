"""Source interface and helpers.

Each source is a callable that takes the Profile + Settings and returns a list
of normalized JobPosting objects. Sources must never raise to the caller — the
orchestrator wraps them, but sources should also fail soft and return [] so a
single flaky board never aborts a run.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Callable

import httpx

from ..config import Profile, Settings
from ..models import JobPosting

log = logging.getLogger("jobhunter.sources")

# A realistic desktop UA. Rotated per-request where it matters (LinkedIn).
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Signature: (profile, settings) -> list[JobPosting]
SourceFn = Callable[[Profile, Settings], list[JobPosting]]

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Turn an HTML fragment into readable plain text."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def http_client(timeout: float = 20.0, ua: str = DEFAULT_UA) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
    )
