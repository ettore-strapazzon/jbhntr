"""Bridge between the database and the `jobhunter` engine.

The engine reads a `Profile` (from YAML) and `Materials` (from a folder). Here
we build exactly those objects from a user's database rows, so the engine runs
unchanged for web users. This is the only real coupling between the two halves.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from jobhunter.config import Materials as EngineMaterials
from jobhunter.config import Profile as EngineProfile

from ..config import config
from ..models import Material, Profile, SeedCompany, User

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
            return len(val.strip()) >= 30  # a token answer isn't an answer
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
