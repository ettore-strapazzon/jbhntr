"""Shared Jinja2 environment."""

from __future__ import annotations

import os
import time

from fastapi.templating import Jinja2Templates

from .config import ROOT, config

templates = Jinja2Templates(directory=str(ROOT / "web" / "app" / "templates"))
# Autoescaping is on by default — user text is never trusted in a template.
templates.env.globals["config"] = config
# Render reason prose as short bullets in the job card (R8.2).
from .services.text import as_bullets  # noqa: E402
templates.env.globals["as_bullets"] = as_bullets
# 1-5 rating labels for the feedback control (R9).
from .models import RATING_LABELS  # noqa: E402
templates.env.globals["rating_labels"] = RATING_LABELS
# Cache-buster for static assets. Changes every deploy (new commit SHA, or a
# fresh process start), so a CSS/JS change is never masked by a stale cache.
templates.env.globals["asset_v"] = (
    os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:8] or str(int(time.time()))
)
templates.env.globals["TIER_COLOURS"] = {
    1: "#0a7c42", 2: "#3d8b37", 3: "#b8860b", 4: "#9a6a00", 5: "#8b0000",
}
