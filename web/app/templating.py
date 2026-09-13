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
# Fit-tier colours are owned entirely by CSS (`.tier-{1..5}` → `var(--tier-N)`),
# which re-maps them per theme (light navy ramp; dark cornflower ramp with navy
# ink). Chips render as `class="tier tier-{n}"` with no inline colour, so nothing
# here needs a hex table — a Python one only re-introduces the un-themeable inline
# fills QA-05 warned about. If a non-HTML surface (email, OG image) ever needs the
# hexes, define them there, not as a global.
