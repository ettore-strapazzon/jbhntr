"""Server-side product events (PROOF-003).

record() is called after a successful action to log a funnel/activation event.
It is deliberately strict and safe:

* only allowlisted event names are stored;
* only allowlisted property keys, coerced to primitives, are kept — never CV
  text, objective text, job-description text, IP or email;
* it never raises: analytics must not break a product action.

The measurement that matters is signup -> first completed scan, then the share
of first shortlists that produce a save, rating or application.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("jbhntr.events")

# Controlled event vocabulary. Adding an event here is the only way to log it.
EVENT_NAMES = frozenset({
    "signup_completed", "cv_uploaded", "onboarding_completed",
    "scan_started", "scan_completed", "first_shortlist_viewed",
    "job_saved", "job_dismissed", "job_marked_applied", "match_rated",
    "document_generated", "premium_waitlist_joined",
    # R2-01 — activation localisation
    "onboarding_step_completed", "profile_threshold_reached",
    "scan_blocked_incomplete",
    # R2-01 — share / referral loop (K-factor). The share/view events are
    # defined now and emitted by the share artefacts next cycle.
    "match_card_shared", "market_read_shared", "shared_artifact_viewed",
    "invite_page_viewed", "invite_link_copied", "referred_signup",
    "referral_activated",
    # R2-01 — channel attribution (/go/{channel} redirect click)
    "channel_click",
    # R3-14 — post-scan gate prompt ("vs how you search today")
    "gate_prompt_shown", "gate_prompt_answered", "gate_prompt_dismissed",
})

# Property keys that may be stored, all non-identifying and low-cardinality.
ALLOWED_PROPS = frozenset({
    "kind", "tier", "rating", "source", "count", "n", "step_name", "channel",
    # R3-04 — A/B arm ('meter' | 'control'), so first-scan rate reads per cohort.
    "variant",
    # R3-14 — gate answer: much_better | better | same | worse (4 values).
    "answer",
})


# R3-22 — a view/click event counts only a person loading the page: a top-level
# document navigation (Sec-Fetch-Dest "document", or absent on older browsers),
# not a speculative prefetch, and not a link-preview crawler / bot / script.
# Without this, <img src=/m/{token}> on any site, or Slack/WhatsApp unfurling a
# shared link, inflates shared_artifact_viewed, channel_click and
# invite_page_viewed. The page/redirect itself is served either way.
_BOT_UA = re.compile(
    r"(?<!cu)bot\b|bot/|crawl|spider|slurp|facebookexternalhit|facebookcatalog|meta-external"
    r"|embedly|whatsapp|telegram|skypeuripreview|vkshare|pinterest|bitly|outbrain"
    r"|quora link preview|preview|nuzzel|iframely|headless|lighthouse|curl/|wget"
    r"|python-requests|python-httpx|python-urllib|aiohttp|go-http-client|okhttp"
    r"|java/|libwww|httpclient|scrapy|validator",
    re.I)


def view_skip_reason(headers) -> str | None:
    """Why this request must not count as a view, or None if it should."""
    dest = (headers.get("sec-fetch-dest") or "").lower()
    if dest and dest != "document":
        return "embed"                                 # img/iframe/script/fetch...
    purpose = (headers.get("sec-purpose") or headers.get("purpose")
               or headers.get("x-purpose") or headers.get("x-moz") or "").lower()
    if "prefetch" in purpose or "prerender" in purpose:
        return "prefetch"
    ua = headers.get("user-agent") or ""
    if not ua.strip() or _BOT_UA.search(ua):
        return "bot"
    return None


def countable_view(request, name: str = "") -> bool:
    """True if `request` is a real page view/click to record. Skips are logged at
    debug with the reason only (no UA, no IP) so a KPI dip can be explained."""
    reason = view_skip_reason(request.headers)
    if reason:
        log.debug("product event not counted: %s (%s)", name or "view", reason)
    return reason is None


def _clean(props: dict) -> dict:
    out: dict = {}
    for k, v in (props or {}).items():
        if k in ALLOWED_PROPS and isinstance(v, (str, int, float, bool)):
            out[k] = v[:64] if isinstance(v, str) else v
    return out


def record(db, name: str, user_id: int | None = None, **props) -> None:
    """Log one product event. Silently no-ops on an unknown name or any error."""
    if name not in EVENT_NAMES:
        log.warning("ignoring unknown product event: %s", name)
        return
    try:
        from ..models import ProductEvent
        db.add(ProductEvent(name=name, user_id=user_id, properties=_clean(props)))
        db.commit()
    except Exception:
        # Never let instrumentation break the request that triggered it.
        try:
            db.rollback()
        except Exception:
            pass
        log.exception("failed to record product event %s", name)


def record_once(db, name: str, user_id: int) -> None:
    """Log a milestone event at most once per user (e.g. onboarding_completed,
    first_shortlist_viewed). No-ops if it already exists or on any error."""
    if name not in EVENT_NAMES:
        log.warning("ignoring unknown product event: %s", name)
        return
    try:
        from ..models import ProductEvent
        exists = (db.query(ProductEvent.id)
                  .filter(ProductEvent.name == name,
                          ProductEvent.user_id == user_id).first())
        if exists:
            return
        db.add(ProductEvent(name=name, user_id=user_id, properties={}))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        log.exception("failed to record milestone event %s", name)
