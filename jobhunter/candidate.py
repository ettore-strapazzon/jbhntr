"""Derive a compact candidate summary from your CV, about-me and objective.

Why this exists: the triage stage only sees a job title, company and location,
so it needs a short, sharp description of who you are. Hand-maintaining a
keyword list for that is both a chore and dangerous — a hard keyword filter
silently drops good jobs whose wording differs ("Django" but never "Python",
"server-side" but never "backend").

So we ask the model once to read your actual materials and extract the things
that matter: the roles you'd plausibly fit, your real skills, your domains, and
the role types that are clearly not for you. That is cached and reused, and
only recomputed when your materials or objective actually change.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import llm
from .config import DATA_DIR, Materials, Profile, Settings

log = logging.getLogger("jobhunter.candidate")

CACHE_PATH = DATA_DIR / "candidate_profile.json"

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One sentence: who this candidate is professionally.",
        },
        "target_roles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Job titles they could plausibly hold next, including "
                           "common wording variants.",
        },
        "skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete skills/technologies evidenced by their materials.",
        },
        "domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Industries/domains they have experience in or want.",
        },
        "seniority": {"type": "string"},
        "avoid": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Role types clearly NOT a fit for this candidate.",
        },
    },
    "required": ["headline", "target_roles", "skills", "domains", "seniority", "avoid"],
    "additionalProperties": False,
}


@dataclass
class Candidate:
    headline: str = ""
    target_roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    seniority: str = ""
    avoid: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.headline or self.target_roles or self.skills)

    def as_prompt_block(self) -> str:
        """Compact description used in the triage prompt."""
        lines = []
        if self.headline:
            lines.append(self.headline)
        if self.seniority:
            lines.append(f"Seniority: {self.seniority}")
        if self.target_roles:
            lines.append("Roles that fit: " + ", ".join(self.target_roles))
        if self.skills:
            lines.append("Skills: " + ", ".join(self.skills))
        if self.domains:
            lines.append("Domains: " + ", ".join(self.domains))
        if self.avoid:
            lines.append("Clearly NOT a fit: " + ", ".join(self.avoid))
        return "\n".join(lines)


COMPANY_CACHE_PATH = DATA_DIR / "company_profile.json"

COMPANY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One sentence: the kind of company these all are.",
        },
        "stage": {"type": "string", "description": "Typical funding/maturity stage."},
        "size": {"type": "string", "description": "Typical headcount range."},
        "sectors": {"type": "array", "items": {"type": "string"}},
        "geographies": {"type": "array", "items": {"type": "string"}},
        "traits": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Shared characteristics: business model, culture, how "
                           "they operate, what working there is like.",
        },
        "anti_traits": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What these companies are NOT — the kinds of employer "
                           "this pattern rules out.",
        },
    },
    "required": ["headline", "stage", "size", "sectors", "geographies", "traits",
                 "anti_traits"],
    "additionalProperties": False,
}


@dataclass
class CompanyProfile:
    """The common shape of the companies the candidate admires."""

    headline: str = ""
    stage: str = ""
    size: str = ""
    sectors: list[str] = field(default_factory=list)
    geographies: list[str] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    anti_traits: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.headline or self.traits)

    def as_prompt_block(self) -> str:
        lines = []
        if self.headline:
            lines.append(self.headline)
        if self.stage:
            lines.append(f"Stage: {self.stage}")
        if self.size:
            lines.append(f"Size: {self.size}")
        if self.sectors:
            lines.append("Sectors: " + ", ".join(self.sectors))
        if self.geographies:
            lines.append("Where: " + ", ".join(self.geographies))
        if self.traits:
            lines.append("Shared traits: " + "; ".join(self.traits))
        if self.anti_traits:
            lines.append("Rules out: " + "; ".join(self.anti_traits))
        return "\n".join(lines)


def derive_company_profile(
    seed_labels: list[str], settings: Settings, refresh: bool = False
) -> CompanyProfile:
    """Extract what the candidate's favourite companies have in common.

    Seeds tell us the kind of *employer* the candidate wants, which the job
    description alone never says. Turning them into an explicit pattern lets the
    matcher reward a job at a company of that shape — not just a matching title.
    """
    if not seed_labels:
        return CompanyProfile()

    fp = hashlib.sha1("|".join(sorted(seed_labels)).encode("utf-8")).hexdigest()
    if not refresh and COMPANY_CACHE_PATH.exists():
        try:
            cached = json.loads(COMPANY_CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fp:
                return CompanyProfile(**cached["company_profile"])
        except Exception:
            pass

    if not llm.is_configured(settings):
        return CompanyProfile()

    prompt = "\n".join(
        [
            "These are companies a candidate admires and would like to work for. "
            "Work out what they have in COMMON, so we can recognise other "
            "companies of the same kind.",
            "",
            "Focus on the pattern, not the individual companies: stage, size, "
            "sector, geography, business model, and how they operate. Be concrete "
            "and specific — vague traits like 'innovative' are useless. If the "
            "list is genuinely mixed, say so in the headline rather than forcing "
            "a false pattern.",
            "",
            "## The companies",
            *[f"- {label}" for label in seed_labels],
        ]
    )

    try:
        data = llm.get_client(settings).json(
            system="You identify what a set of companies have in common.",
            user=prompt,
            schema=COMPANY_SCHEMA,
            tier=llm.SCORING,
            max_tokens=1500,
            cache_system=False,
        )
        cp = CompanyProfile(**data)
    except Exception as exc:
        log.warning("Could not derive company profile (%s); continuing without.", exc)
        return CompanyProfile()

    COMPANY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPANY_CACHE_PATH.write_text(
        json.dumps({"fingerprint": fp, "company_profile": cp.__dict__}, indent=1),
        encoding="utf-8",
    )
    log.info("Derived target-company profile from %d seeds", len(seed_labels))
    return cp


def _fingerprint(profile: Profile, materials: Materials) -> str:
    blob = "|".join(
        [
            profile.objective,
            ",".join(profile.seniority),
            ",".join(profile.verticals),
            ",".join(profile.company_type),
            ",".join(profile.keywords_nice),
            materials.combined_context(),
        ]
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def derive(
    profile: Profile, materials: Materials, settings: Settings, refresh: bool = False
) -> Candidate:
    """Return the cached candidate summary, recomputing it if inputs changed."""
    fp = _fingerprint(profile, materials)

    if not refresh and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fp:
                return Candidate(**cached["candidate"])
        except Exception:
            pass

    if not llm.is_configured(settings):
        return Candidate()

    context = materials.combined_context()
    prompt = "\n".join(
        [
            "Read this candidate's materials and summarise what kind of job they "
            "should be shown. Be generous with `target_roles` and `skills`: include "
            "common alternative wordings and closely-adjacent titles, because these "
            "are used to decide which job ADVERTS are worth reading in full. "
            "Missing a good job is worse than including a mediocre one.",
            "",
            "Use `avoid` only for role types that are unambiguously wrong for them.",
            "",
            "## Their stated objective",
            profile.objective or "(not stated)",
            "",
            f"Target seniority: {', '.join(profile.seniority) or 'unspecified'}",
            f"Preferred sectors: {', '.join(profile.verticals) or 'unspecified'}",
            f"Skills they highlighted: {', '.join(profile.keywords_nice) or 'none given'}",
            "",
            "## Their CV / background / about-me",
            context or "(no materials provided)",
        ]
    )

    try:
        data = llm.get_client(settings).json(
            system="You summarise candidates for job matching.",
            user=prompt,
            schema=CANDIDATE_SCHEMA,
            tier=llm.SCORING,
            max_tokens=2000,
            cache_system=False,
        )
        cand = Candidate(**data)
    except Exception as exc:
        log.warning("Could not derive candidate profile (%s); using profile.yaml only.", exc)
        return Candidate()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"fingerprint": fp, "candidate": cand.__dict__}, indent=1),
        encoding="utf-8",
    )
    log.info(
        "Derived candidate profile: %d target roles, %d skills",
        len(cand.target_roles), len(cand.skills),
    )
    return cand
