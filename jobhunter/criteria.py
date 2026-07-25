"""The criteria that define a good match — and double as the tag vocabulary.

One derived list does three jobs:

1. **Company discovery** — the criteria become explicit search targets, so we
   look for companies that *meet stated conditions* rather than vaguely
   "similar" ones.
2. **Job tagging** — every scored job is tagged with the criteria it meets, so
   the Google Sheet is filterable ("show me everything tagged founder-adjacent").
3. **Explaining decisions** — a tier becomes traceable to concrete criteria
   instead of a paragraph of prose.

Criteria come in two groups:

* ``must_have``  — core, non-negotiable-ish traits of the right opportunity.
* ``nice_have``  — desirable extras that raise a match but aren't required.

A company/job qualifies when it meets at least ``min_must`` must-haves and
``min_nice`` nice-to-haves (both configurable in profile.yaml). That "1 must +
1 nice" style rule keeps discovery broad enough to surface new things while
still anchored to what actually matters.

Derived once from your seeds + profile, cached, and recomputed only when those
change.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import llm
from .config import DATA_DIR, Profile, Settings

log = logging.getLogger("jobhunter.criteria")

CACHE_PATH = DATA_DIR / "criteria.json"

CRITERIA_SCHEMA = {
    "type": "object",
    "properties": {
        "must_have": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "short kebab-case id, e.g. 'founder-adjacent'",
                    },
                    "description": {
                        "type": "string",
                        "description": "What must be true for a job/company to meet it.",
                    },
                },
                "required": ["tag", "description"],
                "additionalProperties": False,
            },
        },
        "nice_have": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["tag", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["must_have", "nice_have"],
    "additionalProperties": False,
}


@dataclass
class Criteria:
    must_have: list[dict] = field(default_factory=list)
    nice_have: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.must_have or self.nice_have)

    def all_tags(self) -> list[str]:
        return [c["tag"] for c in self.must_have] + [c["tag"] for c in self.nice_have]

    def must_tags(self) -> set[str]:
        return {c["tag"] for c in self.must_have}

    def as_prompt_block(self) -> str:
        lines = ["MUST-HAVE criteria:"]
        lines += [f"  [{c['tag']}] {c['description']}" for c in self.must_have]
        lines.append("NICE-TO-HAVE criteria:")
        lines += [f"  [{c['tag']}] {c['description']}" for c in self.nice_have]
        return "\n".join(lines)

    def tag_list_for_prompt(self) -> str:
        return ", ".join(self.all_tags())

    def qualifies(self, tags: list[str], min_must: int, min_nice: int) -> bool:
        """Does something carrying these tags clear the configured bar?"""
        got = set(tags)
        must = len(got & self.must_tags())
        nice = len(got & {c["tag"] for c in self.nice_have})
        return must >= min_must and nice >= min_nice


def _fingerprint(profile: Profile, seed_labels: list[str]) -> str:
    blob = "|".join(
        [
            profile.objective,
            ",".join(profile.verticals),
            ",".join(profile.company_type),
            ",".join(profile.seniority),
            ",".join(sorted(seed_labels)),
            str(profile.criteria_count),
        ]
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def derive(
    profile: Profile,
    seed_labels: list[str],
    settings: Settings,
    refresh: bool = False,
) -> Criteria:
    """Build the criteria/tag vocabulary from the profile and seed companies."""
    fp = _fingerprint(profile, seed_labels)
    if not refresh and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fp:
                return Criteria(**cached["criteria"])
        except Exception:
            pass

    if not llm.is_configured(settings):
        return Criteria()

    total = max(8, profile.criteria_count)
    n_must = max(3, total // 2)
    prompt = "\n".join(
        [
            f"Define about {total} concrete criteria describing the opportunities "
            "this candidate is looking for: roughly "
            f"{n_must} MUST-HAVE and {total - n_must} NICE-TO-HAVE.",
            "",
            "These are used two ways, so they must be checkable from a job advert "
            "or a company's public profile:",
            "  1. to search for companies that meet them",
            "  2. as tags applied to each job found",
            "",
            "Rules:",
            "- Each `tag` is short, lowercase, kebab-case, and reusable "
            "(e.g. 'founder-adjacent', 'series-a-to-c', 'fintech', 'italy-based').",
            "- Each `description` states plainly what makes it true.",
            "- MUST-HAVE = the core of what the candidate wants; without these it "
            "is not the right opportunity.",
            "- NICE-TO-HAVE = things that make a good match better.",
            "- Cover role shape, company stage/size, sector, geography and ways of "
            "working. Avoid vague traits like 'innovative' or 'exciting'.",
            "- No duplicates or near-synonyms.",
            "",
            "## The candidate's objective",
            profile.objective or "(not stated)",
            f"Seniority: {', '.join(profile.seniority) or 'any'}",
            f"Company types: {', '.join(profile.company_type) or 'any'}",
            f"Sectors: {', '.join(profile.verticals) or 'any'}",
            f"Locations: {', '.join(profile.locations) or 'any'}",
        ]
    )
    if seed_labels:
        prompt += "\n\n## Companies they admire (infer the pattern)\n" + "\n".join(
            f"- {s}" for s in seed_labels[:40]
        )

    try:
        data = llm.get_client(settings).json(
            system="You define precise, checkable job-search criteria.",
            user=prompt,
            schema=CRITERIA_SCHEMA,
            tier=llm.SCORING,
            max_tokens=3000,
            cache_system=False,
        )
        crit = Criteria(**data)
    except Exception as exc:
        log.warning("Could not derive criteria (%s); continuing without tags.", exc)
        return Criteria()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"fingerprint": fp, "criteria": crit.__dict__}, indent=1),
        encoding="utf-8",
    )
    log.info(
        "Derived %d must-have and %d nice-to-have criteria",
        len(crit.must_have), len(crit.nice_have),
    )
    return crit
