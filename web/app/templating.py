"""Shared Jinja2 environment."""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

from .config import ROOT, config

templates = Jinja2Templates(directory=str(ROOT / "web" / "app" / "templates"))
# Autoescaping is on by default — user text is never trusted in a template.
templates.env.globals["config"] = config
templates.env.globals["TIER_COLOURS"] = {
    1: "#0a7c42", 2: "#3d8b37", 3: "#b8860b", 4: "#9a6a00", 5: "#8b0000",
}
