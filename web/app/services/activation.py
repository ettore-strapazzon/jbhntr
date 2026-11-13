"""R3-04 activation meter — the first A/B test (ARTEFACTS_SPEC §8.4).

A profile-completeness strip with a "Run my free scan" CTA, shown to users who
have not run their first scan yet. Two rules carry the whole feature:

* The CTA's enabled state is bound to ``Completeness.can_search`` (i.e.
  ``not missing_required``) — the exact check ``start_search`` enforces. It is
  NOT ``score >= REQUIRED_WEIGHT`` (an optional-heavy profile can read ~91% and
  still be locked) and NOT ``Strength.can_search`` (the band one).
* Assignment is deterministic: a salted hash of the user id picks 'meter' or
  'control', so the same user always sees the same arm with no stored state,
  and every funnel event can carry the arm for a per-cohort first-scan rate.

KPI: first-scan rate = users with ``scan_started`` / users with
``signup_completed``, per ``variant`` (see ``first_scan_rate_by_variant``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..config import config
from ..models import Search, User
from .profile_service import FIELDS, REQUIRED_WEIGHT, Completeness, completeness

EXPERIMENT = "r3-04-meter"
VARIANTS = ("meter", "control")

# Where each field is edited — profile anchors, and the onboarding step that owns it.
PROFILE_HREF = {
    "cv": "/profile#documents", "cover_letter": "/profile#documents",
    "linkedin": "/profile#documents",
    "about_me": "/profile#you", "objective": "/profile#you",
}
ONBOARDING_HREF = {
    "cv": "/onboarding/upload",
    "about_me": "/onboarding/words", "objective": "/onboarding/words",
}
_KEY_BY_LABEL = {label: key for key, (label, _req) in FIELDS.items()}

MAX_MISSING_SHOWN = 4   # "top missing fields"; the rest collapse into "+N more"


def assign_variant(user_id: int) -> str:
    """Deterministic arm for a user. Kill switch: ACTIVATION_METER=on|off."""
    mode = (getattr(config, "activation_meter", "ab") or "ab").lower()
    if mode == "on":
        return "meter"
    if mode == "off":
        return "control"
    digest = hashlib.sha256(f"{EXPERIMENT}:{int(user_id)}".encode()).digest()
    return VARIANTS[digest[0] % 2]


def has_scanned(db: Session, user: User) -> bool:
    """True once the user has run a real market scan (an imported single job
    doesn't count — it's not the first-scan activation step)."""
    if user.first_scan_used_at is not None:
        return True
    return db.query(Search.id).filter(
        Search.user_id == user.id, Search.stage != "Imported job").first() is not None


@dataclass
class MissingField:
    label: str
    href: str


@dataclass
class Meter:
    score: int
    unlock_at: int                 # REQUIRED_WEIGHT — never a literal in the copy
    cta_enabled: bool              # == Completeness.can_search, nothing else
    missing: list[MissingField] = field(default_factory=list)   # top N required
    more_missing: int = 0
    free: bool = True              # first scan on us?
    surface: str = "profile"       # 'onboarding' strip is sticky; profile has sticky subtabs

    @property
    def locked(self) -> bool:
        return not self.cta_enabled


def build_meter(state: Completeness, *, surface: str = "profile",
                free: bool = True) -> Meter:
    """Pure: map a Completeness to what the strip renders. `surface` picks the
    link targets ('profile' anchors or 'onboarding' steps)."""
    hrefs = ONBOARDING_HREF if surface == "onboarding" else PROFILE_HREF
    default = "/onboarding/aim" if surface == "onboarding" else "/profile#targets"
    missing = []
    for label in state.missing_required:
        key = _KEY_BY_LABEL.get(label, "")
        missing.append(MissingField(label, hrefs.get(key, default)))
    return Meter(
        score=state.score, unlock_at=REQUIRED_WEIGHT,
        cta_enabled=state.can_search,          # the gate start_search enforces
        missing=missing[:MAX_MISSING_SHOWN],
        more_missing=max(0, len(missing) - MAX_MISSING_SHOWN),
        free=free, surface=surface,
    )


def meter_for(db: Session, user: User, *, surface: str = "profile") -> Meter | None:
    """The meter to render for this user, or None (control arm, or already
    scanned). Also records profile_threshold_reached the first time the gate
    is seen open, tagged with the arm."""
    if has_scanned(db, user):
        return None
    state = completeness(db, user)
    if state.can_search:
        note_threshold(db, user)
    if assign_variant(user.id) != "meter":
        return None
    free = bool(config.first_scan_free and user.first_scan_used_at is None)
    return build_meter(state, surface=surface, free=free)


def note_threshold(db: Session, user: User) -> None:
    """Emit profile_threshold_reached once per user, with the variant."""
    from ..models import ProductEvent
    from .events import record
    try:
        seen = db.query(ProductEvent.id).filter(
            ProductEvent.name == "profile_threshold_reached",
            ProductEvent.user_id == user.id).first()
    except Exception:
        return
    if not seen:
        record(db, "profile_threshold_reached", user_id=user.id,
               variant=assign_variant(user.id))


def first_scan_rate_by_variant(db: Session) -> dict[str, dict]:
    """KPI readout: per arm, signed-up users, those who started a scan, rate.
    Arm is read from the signup_completed event's `variant` (intent-to-treat);
    older signups without it are re-derived from the deterministic hash."""
    from ..models import ProductEvent
    signups = db.query(ProductEvent.user_id, ProductEvent.properties).filter(
        ProductEvent.name == "signup_completed", ProductEvent.user_id.isnot(None)).all()
    scanned = {uid for (uid,) in db.query(ProductEvent.user_id).filter(
        ProductEvent.name == "scan_started").distinct()}
    out = {v: {"signups": 0, "scanned": 0, "rate": None} for v in VARIANTS}
    for uid, props in signups:
        arm = (props or {}).get("variant") or assign_variant(uid)
        if arm not in out:
            continue
        out[arm]["signups"] += 1
        out[arm]["scanned"] += uid in scanned
    for row in out.values():
        row["rate"] = round(row["scanned"] / row["signups"], 3) if row["signups"] else None
    return out
