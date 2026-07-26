"""Shared Jinja2 environment."""

from __future__ import annotations

import os
import time

from fastapi.templating import Jinja2Templates

from .config import ROOT, config

templates = Jinja2Templates(directory=str(ROOT / "web" / "app" / "templates"))
# Autoescaping is on by default — user text is never trusted in a template.
templates.env.globals["config"] = config
# Cache-buster for static assets. Changes every deploy (new commit SHA, or a
# fresh process start), so a CSS/JS change is never masked by a stale cache.
templates.env.globals["asset_v"] = (
    os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:8] or str(int(time.time()))
)
templates.env.globals["TIER_COLOURS"] = {
    1: "#0a7c42", 2: "#3d8b37", 3: "#b8860b", 4: "#9a6a00", 5: "#8b0000",
}
