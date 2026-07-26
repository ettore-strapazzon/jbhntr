"""Bridge between the database and the `jobhunter` engine.

The engine reads a `Profile` (from YAML) and `Materials` (from a folder). Here
we build exactly those objects from a user's database rows, so the engine runs
unchanged for web users. This is the only real coupling between the two halves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from jobhunter.config import Materials as EngineMaterials
from jobhunter.config import Profile as EngineProfile

from ..config import config
from ..models import Feedback, Material, Profile, SeedCompany, User

# A long-text answer must reach this length to count as filled — a token reply
# ("PM roles") carries no signal. The rule is now stated in the UI and enforced
# by `minlength`; this constant is the single source of truth (F-04).
MIN_TEXT = 30


def text_too_short(value: str) -> bool:
    """True if a non-empty long-text answer is below the minimum. Empty is not
    'too short' — that's just an unfilled optional/required field handled by
    completeness; this catches the silent 'saved but doesn't count' case."""
    v = (value or "").strip()
    return 0 < len(v) < MIN_TEXT


# Field → (label shown to the user, is it required?)
FIELDS: dict[str, tuple[str, bool]] = {
    "cv":           ("At least one CV",            True),
    "about_me":     ("About you",                  True),
    "objective":    ("What you're looking for",    True),
    "seniority":    ("Seniority",                  True),
    "company_type": ("Company type",               True),
    "verticals":    ("Sectors",                    True),
    "locations":    ("Locations",                  True),
    "job_type":     ("Job type",                   True),
    "cover_letter": ("A cover letter",             False),
    "linkedin":     ("LinkedIn profile export",    False),
    "seeds":        ("Companies you admire",       False),
    "search_terms": ("Job titles to search",       False),
    "salary_floor": ("Salary floor",               False),
}


@dataclass
class Completeness:
    missing_required: list[str]
    missing_optional: list[str]
    score: int          # 0-100, weighted toward required fields

    @property
    def can_search(self) -> bool:
        return not self.missing_required

    @property
    def should_improve(self) -> bool:
        """Thin profiles produce bad matches; nudge before they blame us."""
        return self.can_search and self.score < config.quality_threshold


def _present(db: Session, user: User) -> dict[str, bool]:
    profile = user.profile
    kinds = {m.kind for m in db.query(Material).filter(Material.user_id == user.id)}
    seed_count = db.query(SeedCompany).filter(SeedCompany.user_id == user.id).count()

    def filled(attr: str) -> bool:
        val = getattr(profile, attr, None) if profile else None
        if isinstance(val, str):
            return len(val.strip()) >= MIN_TEXT  # a token answer isn't an answer
        return bool(val)

    return {
        "cv": "cv" in kinds,
        "about_me": filled("about_me"),
        "objective": filled("objective"),
        "seniority": filled("seniority"),
        "company_type": filled("company_type"),
        "verticals": filled("verticals"),
        "locations": filled("locations"),
        "job_type": filled("job_type"),
        "cover_letter": "cover_letter" in kinds,
        "linkedin": "linkedin" in kinds,
        "seeds": seed_count > 0,
        "search_terms": filled("search_terms"),
        "salary_floor": bool(profile and profile.salary_floor_eur),
    }


def completeness(db: Session, user: User) -> Completeness:
    present = _present(db, user)
    missing_req = [FIELDS[k][0] for k, (_, req) in FIELDS.items()
                   if req and not present.get(k)]
    missing_opt = [FIELDS[k][0] for k, (_, req) in FIELDS.items()
                   if not req and not present.get(k)]

    # Required fields carry 70% of the score, optional the remaining 30%.
    req_keys = [k for k, (_, r) in FIELDS.items() if r]
    opt_keys = [k for k, (_, r) in FIELDS.items() if not r]
    req_hit = sum(1 for k in req_keys if present.get(k)) / len(req_keys)
    opt_hit = sum(1 for k in opt_keys if present.get(k)) / len(opt_keys)
    score = round(req_hit * 70 + opt_hit * 30)

    return Completeness(missing_req, missing_opt, score)


# --------------------------------------------------------------------------- #
# Profile strength (§5.5): the binary "ready to search" gate tells a user
# nothing once they clear it, but matching, CV tailoring and cover letters all
# keep improving well past that point. This models a four-band strength that
# keeps asking, honestly, and always states the payoff in *output* terms — never
# "you are 68% done". Bands: thin (search locked) < basic < good < strong.

# Character targets for a long-text field to count as "full" depth.
OBJECTIVE_TARGET = 400
ABOUT_TARGET = 600

# Four depth labels for a single long-text field, low → high (§11.4).
DEPTH_LABELS = [
    "Too short to be useful",
    "Enough to search with",
    "Good — the matcher has something to work with",
    "Strong — this is what makes matches personal",
]


def text_depth(value: str, target: int) -> int:
    """0-3 depth level for one long-text answer, by length against its target."""
    n = len((value or "").strip())
    if n < MIN_TEXT:
        return 0
    if n < target * 0.4:
        return 1
    if n < target * 0.85:
        return 2
    return 3


# Per-band headline + one-line consequence, shown on Profile (§11.9).
BAND_COPY = {
    "thin":   ("Not enough to search yet.",
               "Add what's still missing and your first search unlocks."),
    "basic":  ("Enough to search with.",
               "Matches will be broad, and tailored documents will sound generic."),
    "good":   ("Solid.",
               "Matching is reliable. A second CV or a cover letter is what improves the writing."),
    "strong": ("Strong.",
               "Matching and writing both have your own material to work from. "
               "Keep voting on results and it keeps sharpening."),
}
BAND_ORDER = ["thin", "basic", "good", "strong"]


@dataclass
class Signal:
    """One thing the user can add, with where it lands on its own target."""
    label: str          # "CVs"
    value_label: str    # "1 of 3"
    improves: str       # "Matching · CV writing"
    level: int          # 0 none · 1 partial · 2 full


@dataclass
class Nudge:
    """The single highest-impact next step, phrased as an outcome."""
    signal: str         # short label of what's thin, e.g. "your 'about you'"
    payoff: str         # what adding it buys, in output terms
    href: str           # where to go and fix it


@dataclass
class Strength:
    band: str                       # thin | basic | good | strong
    headline: str                   # bold sentence for the band
    consequence: str                # the one-line output consequence
    signals: list[Signal] = field(default_factory=list)
    nudge: Optional[Nudge] = None   # None at strong, or when search is locked

    @property
    def can_search(self) -> bool:
        return self.band != "thin"

    @property
    def index(self) -> int:
        return BAND_ORDER.index(self.band)

    @property
    def below_good(self) -> bool:
        return self.index < BAND_ORDER.index("good")


def strength(db: Session, user: User) -> Strength:
    profile = user.profile
    obj = (profile.objective if profile else "") or ""
    about = (profile.about_me if profile else "") or ""

    counts = dict(
        db.query(Material.kind, func.count())
          .filter(Material.user_id == user.id)
          .group_by(Material.kind)
          .all()
    )
    cv_n = counts.get("cv", 0)
    cl_n = counts.get("cover_letter", 0)
    linkedin = counts.get("linkedin", 0) > 0
    seeds_n = db.query(SeedCompany).filter(SeedCompany.user_id == user.id).count()
    votes_n = db.query(Feedback).filter(Feedback.user_id == user.id).count()

    obj_d, about_d = text_depth(obj, OBJECTIVE_TARGET), text_depth(about, ABOUT_TARGET)

    can_search = completeness(db, user).can_search
    good = can_search and obj_d >= 2 and about_d >= 2 and cv_n >= 1
    strong = (good and obj_d >= 3 and about_d >= 3
              and (cv_n >= 2 or cl_n >= 1)
              and (linkedin or seeds_n >= 5 or votes_n >= 10))
    band = "strong" if strong else "good" if good else "basic" if can_search else "thin"

    def lvl(n: int, partial: int, full: int) -> int:
        return 2 if n >= full else 1 if n >= partial else 0

    signals = [
        Signal("CVs", f"{cv_n} of 3", "Matching · CV writing", lvl(cv_n, 1, 2)),
        Signal("Cover letters", f"{cl_n} of 3", "Cover-letter writing", lvl(cl_n, 1, 2)),
        Signal("Objective", DEPTH_LABELS[obj_d], "Matching", 2 if obj_d >= 3 else 1 if obj_d >= 1 else 0),
        Signal("About you", DEPTH_LABELS[about_d], "Matching · CV · cover letters",
               2 if about_d >= 3 else 1 if about_d >= 1 else 0),
        Signal("LinkedIn export", "Yes" if linkedin else "No", "Matching", 2 if linkedin else 0),
        Signal("Companies you admire", str(seeds_n), "Matching · reach", lvl(seeds_n, 1, 5)),
        Signal("Feedback given", str(votes_n), "Matching", lvl(votes_n, 1, 10)),
    ]

    # One nudge at a time, chosen by expected impact — highest-value field first.
    nudge = None
    if band != "thin":
        if about_d < 3:
            nudge = Nudge("your ‘about you’",
                          "it's the biggest lever on match quality, and it's the voice your tailored CVs borrow",
                          "/profile#you")
        elif obj_d < 3:
            nudge = Nudge("what you're looking for",
                          "spell out what you don't want too, and borderline matches get sorted correctly",
                          "/profile#you")
        elif cv_n < 2:
            nudge = Nudge("a second CV",
                          "one framed for a different kind of role makes tailoring noticeably sharper",
                          "/profile#documents")
        elif cl_n < 1:
            nudge = Nudge("a cover letter of your own",
                          "add one and generated letters start to read like you wrote them",
                          "/profile#documents")
        elif not linkedin:
            nudge = Nudge("your LinkedIn export",
                          "it fills in history a one-page CV usually trims",
                          "/profile#documents")
        elif seeds_n < 5:
            nudge = Nudge("companies you admire",
                          "a few names pulls in roles from places like them",
                          "/profile#targets")
        elif votes_n < 10:
            nudge = Nudge("your feedback",
                          "thumbs-down the weak matches and the next run reflects it",
                          "/matches")

    headline, consequence = BAND_COPY[band]
    return Strength(band, headline, consequence, signals, nudge)


# How the user wants to work. Drives which location tokens we generate.
WORK_MODES = ["onsite", "hybrid", "remote"]

# Countries offered in the picker. Adzuna-covered ones (best data) first, then
# other markets Careerjet reaches / we can match by name. Names must be ones
# jobhunter.geo recognises so nothing is a dead option.
COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Australia", "New Zealand",
    "Ireland", "Italy", "Germany", "France", "Spain", "Portugal",
    "Netherlands", "Belgium", "Austria", "Switzerland", "Poland", "Sweden",
    "Denmark", "Norway", "Finland", "Greece", "Romania", "Czechia",
    "India", "Singapore", "United Arab Emirates", "Japan", "Brazil", "Mexico",
    "South Africa",
]


def infer_structured_location(locations: list[str]) -> tuple[list[str], list[str]]:
    """Best-effort (work_modes, countries) from legacy free-text location tokens.

    Profiles created before the structured step stored only tokens like
    "Milan" or "Remote-Italy". Without this, opening the profile page would
    show empty controls and a save would wipe those locations. Region-only
    tokens (Remote-EU) can't map to one country and are simply skipped — the
    user re-picks countries, which is more precise anyway.
    """
    from jobhunter import geo

    name_by_code = {}
    for name in COUNTRIES:
        code = geo._country_of(name)
        if code:
            name_by_code.setdefault(code, name)

    modes: list[str] = []
    countries: list[str] = []
    for tok in locations:
        t = tok.strip()
        if not t:
            continue
        if t.lower().startswith("remote"):
            if "remote" not in modes:
                modes.append("remote")
        elif "onsite" not in modes:
            modes.append("onsite")
        code = geo._country_of(t)
        if code and code in name_by_code and name_by_code[code] not in countries:
            countries.append(name_by_code[code])
    return modes, countries


def build_location_tokens(
    work_modes: list[str], countries: list[str], remote_anywhere: bool
) -> list[str]:
    """Turn the structured location step into the engine's location tokens.

    onsite/hybrid in a country -> the country name ("United States").
    remote + a country base    -> "Remote-United States".
    remote from anywhere       -> "Remote-Anywhere".
    The matcher and geo derivation read these tokens; the UI keeps the
    structured fields so the form can round-trip.
    """
    modes = {m for m in work_modes if m in WORK_MODES}
    place_based = bool(modes & {"onsite", "hybrid"})
    tokens: list[str] = []
    for c in countries:
        c = c.strip()
        if not c:
            continue
        if place_based:
            tokens.append(c)
        if "remote" in modes:
            tokens.append(f"Remote-{c}")
    if remote_anywhere:
        tokens.append("Remote-Anywhere")
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


# Preset groups for the country token field (F-03). Names must match COUNTRIES.
COUNTRY_PRESETS: dict[str, list[str]] = {
    "eu": ["Ireland", "Italy", "Germany", "France", "Spain", "Portugal",
           "Netherlands", "Belgium", "Austria", "Poland", "Sweden", "Denmark",
           "Finland", "Greece", "Romania", "Czechia"],
    "uk-ie": ["United Kingdom", "Ireland"],
    "north-america": ["United States", "Canada", "Mexico"],
}


def remote_anywhere_on(profile: Profile | None) -> bool:
    return bool(profile and "Remote-Anywhere" in (profile.locations or []))


def rebuild_locations(profile: Profile, remote_anywhere: bool | None = None) -> None:
    """Recompute the engine location tokens from the structured fields.

    The country token field owns geography and auto-saves via HTMX, so it must
    keep `locations` in step on every change — completeness reads `locations`,
    not `countries`. When `remote_anywhere` is left None we preserve whatever
    the current tokens imply.
    """
    if remote_anywhere is None:
        remote_anywhere = remote_anywhere_on(profile)
    profile.locations = build_location_tokens(
        profile.work_modes or [], profile.countries or [], remote_anywhere)


def set_countries(profile: Profile, countries: list[str],
                  remote_anywhere: bool | None = None) -> None:
    """Replace the country list (validated, de-duplicated) and rebuild tokens."""
    profile.countries = [c for c in dict.fromkeys(countries) if c in COUNTRIES]
    rebuild_locations(profile, remote_anywhere)


# --------------------------------------------------------------------------- #
def split_list(text: str, limit: int = 20) -> list[str]:
    """Parse a free-text list field.

    The forms say "one per line", but people type "Milan, Turin, Remote-EU" on
    a single line. Splitting on newlines alone stored that as ONE entry, which
    the engine then tried to match literally against job locations — nothing
    matched, and searches came back empty. Accept both separators.
    """
    items: list[str] = []
    for line in (text or "").splitlines():
        for part in line.split(","):
            part = part.strip()
            if part and part not in items:
                items.append(part)
    return items[:limit]


def build_engine_profile(db: Session, user: User) -> EngineProfile:
    """Turn DB rows into the Profile object the engine expects."""
    p = user.profile
    seeds = [s.value for s in db.query(SeedCompany).filter(SeedCompany.user_id == user.id)]

    raw = {
        "objective": p.objective if p else "",
        "seniority": p.seniority if p else [],
        "company_type": p.company_type if p else [],
        "verticals": p.verticals if p else [],
        # Re-split defensively: profiles saved before split_list existed may
        # hold "Milan, Turin" as a single entry.
        "locations": split_list("\n".join(p.locations)) if p else [],
        "job_type": p.job_type if p else [],
        "keywords_must": [],   # deliberately empty — see the engine's dedup docs
        "keywords_nice": [],
        "salary_floor_eur": p.salary_floor_eur if p else None,
        "keep_tier_max": 3,
        "two_stage_triage": True,
        "criteria_count": 20,
        "sources": {
            # LinkedIn is intentionally absent for web users (legal), and the
            # engine simply skips it when no search URLs are configured.
            "aggregators": ["adzuna", "remotive", "remoteok", "arbeitnow"],
            # Every free, no-key board we have an adapter for. Web users have no
            # LinkedIn coverage, so breadth here is what replaces it. Paid and
            # key-gated sources are handled separately (see keyed.PROVIDERS).
            "boards": [
                "weworkremotely", "weworkremotely-management", "jobicy",
                "themuse", "arbeitsagentur", "cryptocurrencyjobs", "landingjobs",
                "berlinstartupjobs", "workingnomads", "fourdayweek",
                "realworkfromanywhere", "himalayas", "nodesk",
            ],
            "search_terms": (p.search_terms if p and p.search_terms else []),
            "linkedin_search_urls": [],
            "custom_sites": [],
            "custom_rss": [],
        },
        "_seeds": seeds,  # read by build_seed_labels(), not by the engine
    }
    return EngineProfile(raw=raw)


def build_engine_materials(db: Session, user: User) -> EngineMaterials:
    """Assemble the candidate's documents from the encrypted store."""
    m = EngineMaterials()
    for row in db.query(Material).filter(Material.user_id == user.id):
        text = (row.text or "").strip()
        if not text:
            continue
        if row.kind == "cv":
            m.base_cv += text + "\n"
        elif row.kind == "cover_letter":
            m.cover_letters += text + "\n"
        elif row.kind == "linkedin":
            m.linkedin_export += text + "\n"
    if user.profile and user.profile.about_me:
        m.about_me = user.profile.about_me
    return m


def seed_values(db: Session, user: User) -> list[str]:
    return [s.value for s in db.query(SeedCompany).filter(SeedCompany.user_id == user.id)]
