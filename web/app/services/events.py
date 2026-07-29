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

log = logging.getLogger("jbhntr.events")

# Controlled event vocabulary. Adding an event here is the only way to log it.
EVENT_NAMES = frozenset({
    "signup_completed", "cv_uploaded", "onboarding_completed",
    "scan_started", "scan_completed", "first_shortlist_viewed",
    "job_saved", "job_dismissed", "job_marked_applied", "match_rated",
    "document_generated", "premium_waitlist_joined",
})

# Property keys that may be stored, all non-identifying and low-cardinality.
ALLOWED_PROPS = frozenset({"kind", "tier", "rating", "source", "count", "n"})


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
