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


# Provenance (AX-3): turn a raw source token into a human phrase for the card, so
# a ranking reads as reasoned ("found via the company's own careers board") rather
# than opaque ("Source: greenhouse"). Supports the "direct career-page coverage" claim.
_ATS = ("greenhouse", "lever", "ashby", "workday", "smartrecruiters", "recruitee",
        "personio", "teamtailor", "workable", "jobvite", "icims")
_GOV = ("francetravail", "jobtech", "bundesagentur", "arbeitsagentur", "usajobs")
_BOARDS = ("careerjet", "jooble", "reed", "adzuna", "serpapi", "jsearch", "findwork",
           "web3career", "indeed", "linkedin")


def source_phrase(source: str) -> str:
    s = (source or "").lower()
    s = s[4:] if s.startswith("api:") else s
    if "career" in s or any(k in s for k in _ATS):
        return "the company’s own careers board"
    if any(k in s for k in _GOV):
        return "a public job service"
    if any(k in s for k in _BOARDS):
        return "a job board"
    return source or "the market scan"


templates.env.globals["source_phrase"] = source_phrase

# Strength word from the tier at render time (AX-2), not the value stored on the
# row when it was scored — so a relabel shows immediately on old and new results
# alike, with no re-scan needed.
from jobhunter.models import TIER_LABELS, tier_for_score  # noqa: E402


def tier_word(tier) -> str:
    try:
        return TIER_LABELS.get(int(tier), "")
    except (TypeError, ValueError):
        return ""


templates.env.globals["tier_word"] = tier_word
# Self-score helpers: turn a 0-100 into its tier number / word (for the feedback
# slider's initial server render; app.js keeps it live as the slider moves).
templates.env.globals["score_tier"] = lambda s: tier_for_score(int(s or 0))
templates.env.globals["score_word"] = lambda s: TIER_LABELS[tier_for_score(int(s or 0))]
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
