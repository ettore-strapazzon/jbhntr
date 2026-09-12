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
templates.env.globals["TIER_COLOURS"] = {  # v3 fit tiers: navy-scaled, error red is failure-only
    1: "#17334B",  # navy 800     — strong fit
    2: "#35599A",  # cornflower 800
    3: "#5B87D0",  # cornflower 600
    4: "#97AEC1",  # navy 300
    5: "#718399",  # border-strong — weak fit, not a failure
}
