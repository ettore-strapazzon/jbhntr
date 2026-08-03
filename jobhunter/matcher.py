"""Score each posting against the candidate profile using Claude (cheap model).

Uses structured outputs so the response is always a valid MatchResult. The
candidate context + profile + feedback examples go in a cached system prompt
(reused across every job in the run); only the per-job data varies, so prompt
caching keeps the input cost low.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import llm
from .config import Materials, Profile, Settings
from .models import JobPosting, MatchResult

log = logging.getLogger("jobhunter.matcher")

DESC_CHAR_CAP = 3000  # bound per-job tokens

MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "tier": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Criteria tags this job meets. Use ONLY tags from the "
                           "provided list; omit any that don't apply.",
        },
        "score": {"type": "integer"},
        "fit_role": {
            "type": "integer",
            "description": "0-100: how well the JOB matches what the candidate "
                           "wants (objective, seniority, company shape, sector, "
                           "location). Ignores whether they're qualified.",
        },
        "fit_candidate": {
            "type": "integer",
            "description": "0-100: how well the CANDIDATE meets what the job "
                           "asks for (the required skills and experience). "
                           "Ignores whether they'd want it.",
        },
        "reasons": {"type": "string"},
        "role": {"type": "string"},
        "company": {"type": "string"},
        "location": {"type": "string"},
        "vertical": {"type": "string"},
        "seniority": {"type": "string"},
        "remote": {"type": "string"},
    },
    "required": [
        "tier",
        "tags",
        "score",
        "fit_role",
        "fit_candidate",
        "reasons",
        "role",
        "company",
        "location",
        "vertical",
        "seniority",
        "remote",
    ],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Stage 1: cheap triage on title/company/location only.
#
# Full scoring sends the whole job description (~3k tokens each). Triage sends
# ~20 tokens per job and judges 25 jobs in a single call, so it costs roughly
# 1-2% of a full pass. It is deliberately tuned for RECALL: it only needs to
# throw out the obviously-irrelevant, and stage 2 does the real judging.
# --------------------------------------------------------------------------- #
TRIAGE_BATCH = 25
# Concurrent scoring calls. Bounded so we stay under provider rate limits while
# cutting the wall-clock time of the (previously serial) scoring loop.
SCORE_WORKERS = 6

# Bump whenever the scoring PROMPT or MatchResult schema changes. It is part of
# the score-cache key, so a bump cleanly invalidates every cached score — the
# guard that lets matching keep being refined while caching is on.
PROMPT_VERSION = 6

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "promising": {"type": "boolean"},
                },
                "required": ["index", "promising"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def _triage_system_prompt(profile: Profile, candidate=None, company_profile=None) -> str:
    lines = [
        "You are triaging job titles for a candidate. For each numbered job "
        "you see only the title, company and location — not the description.",
        "",
        "Mark `promising: true` if the job could PLAUSIBLY be a fit worth "
        "reading in full. Mark false ONLY when the title makes it clearly the "
        "wrong profession or the wrong seniority — a nurse, a welder, a "
        "graduate intern, a senior C++ engineer for a non-engineer.",
        "IMPORTANT: err on the side of true. A later step reads the full "
        "description and does the real filtering. Wrongly discarding a good "
        "job here is far worse than passing through a mediocre one — the "
        "mediocre one costs a few cents, the discarded one is lost for good.",
        "You are seeing a title and nothing else. A title is weak evidence: if "
        "the job might reasonably turn out to be relevant once you read the "
        "description, that is enough for `true`. Anything adjacent to the "
        "candidate's field, or that you are unsure about, is `true`.",
        "Do NOT reject on location — every job here has already passed the "
        "candidate's geography filter, and the location shown may be blank or "
        "approximate.",
        "Judge by meaning, not keywords: a title implying the right work counts "
        "even if it uses different wording than the candidate's own.",
        "As a sanity check on your calibration: on a typical batch you should "
        "be keeping a third or more. Keeping only a handful means you are "
        "being far too strict.",
        "Return one verdict per job, using the given index.",
        "",
        "## Candidate is looking for",
        profile.objective or "(not specified)",
        f"Seniority: {', '.join(profile.seniority) or 'any'}",
        f"Verticals: {', '.join(profile.verticals) or 'any'}",
    ]
    # The derived profile (read from the CV/about-me) is far richer than any
    # hand-written keyword list, so prefer it when available.
    if candidate is not None and not candidate.is_empty():
        lines += ["", "## Candidate profile", candidate.as_prompt_block()]
    elif profile.keywords_nice:
        lines.append(f"Relevant skills: {', '.join(profile.keywords_nice)}")

    # You only see the company NAME at this stage, so knowing the kind of
    # employer wanted is a useful nudge for borderline titles.
    if company_profile is not None and not company_profile.is_empty():
        lines += [
            "",
            "## Preferred kind of company",
            company_profile.as_prompt_block(),
            "Lean towards `true` for companies of this kind.",
        ]
    return "\n".join(lines)


def _system_prompt(
    profile: Profile,
    materials: Materials,
    feedback_examples: list[dict],
    company_profile=None,
    criteria=None,
) -> str:
    parts = [
        "You are a meticulous job-matching assistant. A match must work BOTH "
        "ways, and you weigh them together:",
        "  (a) the JOB fits the candidate — objective, seniority, company shape, "
        "location; and",
        "  (b) the CANDIDATE meets the job's CORE REQUIREMENTS — the main skills "
        "and experience the advert actually asks for.",
        "A perfect company and an impressive title do NOT make a match if the "
        "candidate plausibly cannot do the core job. Read the requirements and "
        "check them against the candidate's real background before you score. "
        "Be honest and calibrated — most jobs are not strong matches.",
        "",
        "Assign a tier:",
        "  1 = Excellent — squarely what they're looking for; apply now",
        "  2 = Strong — right function family and level at a company of the "
        "right shape; worth applying even if the advert doesn't tick everything",
        "  3 = Possible — genuinely relevant, with real gaps or unknowns",
        "  4 = Weak — adjacent at best; a long shot",
        "  5 = No — not this person's role, or a blocker below applies",
        "",
        "CALIBRATION — the tiers must all get used.",
        "Tier 3 is the normal verdict for a relevant-but-imperfect job, and it "
        "should be your most common non-rejection answer. A job is NOT pushed "
        "to tier 4 merely because it is imperfect, because some criteria are "
        "unmet, or because the description is thin. Reserve 4 and 5 for jobs "
        "that are genuinely the wrong role, or that hit a blocker below. If you "
        "find yourself giving almost everything 4-5, you are miscalibrated.",
        "",
        "BLOCKERS — only these force tier 4 or 5:",
        "- The advert demands substantial specific experience in a field absent "
        "from the candidate's background (e.g. '7 years in enterprise sales', "
        "'qualified lawyer'). Do not rationalise it as adjacent.",
        "- The role's CORE value-add is deep domain expertise the candidate "
        "lacks — regulatory, legal, compliance, licensing, clinical, actuarial, "
        "tax, or deep technical — EVEN when the title dresses it as 'strategy' "
        "or 'operations', and EVEN at a company the candidate admires. A 'Head "
        "of Regulatory Strategy' is a regulatory-expert role; an admired "
        "employer, CEO-adjacency or senior level do NOT rescue it. If doing the "
        "job well would require expertise the candidate has never demonstrated, "
        "it is tier 4 — state the missing expertise plainly.",
        "- The core FUNCTION is a different job family from what the candidate "
        "wants — engineering, quota-carrying sales, clinical or support work "
        "for someone seeking strategy/operations. Judge the actual day-job, not "
        "the title: a 'Partnerships Lead' carrying a quota is a sales job.",
        "  A function that OVERLAPS the target (programme management, business "
        "operations, corporate development, founder's office, transformation) "
        "is not a blocker — that is tier 2-3 territory depending on how much of "
        "the day-job matches.",
        "- LOCATION is a HARD blocker. If the advert states an on-site or hybrid "
        "location in a country the candidate did NOT list, and offers no remote "
        "option they could take from their own region, it is tier 5 — no matter "
        "how good the role, company or title is. A dream on-site job in the wrong "
        "country is still the wrong country: do NOT soften it to tier 3 or 4, and "
        "do NOT let a strong role pull the tier back up. Infer the country from "
        "the advert (a city, state or region names one) as well as the stated "
        "field. Only when the location is genuinely absent or unresolvable is it "
        "an unknown (tier 3) rather than a conflict; a clearly named foreign city "
        "is NOT unclear.",
        "State any blocker explicitly in your reasons — never write 'no "
        "significant concerns' when one exists.",
        "",
        "SENIORITY — weigh it heavily, both ways. Judge the role's level against "
        "BOTH the candidate's target seniority AND the seniority their CV actually "
        "demonstrates. A role clearly BELOW that level — an individual-contributor, "
        "analyst, associate, or ordinary manager role for a candidate who is, and "
        "is seeking, executive / head / director / VP / C-level — is a weak match "
        "however well the function or sector fits: score fit_role low and cap it at "
        "tier 3, dropping to tier 4 when the gap is large (e.g. an analyst role for "
        "a seasoned executive). A role clearly ABOVE the candidate's demonstrated "
        "level is a stretch and should not sit in tier 1. Title words alone are not "
        "proof of level — read the scope (team size, budget, P&L, reporting line) — "
        "but when the advert's level plainly undershoots the candidate, say so in "
        "the reasons and let it hold the tier down.",
        "Give THREE numbers, each 0-100:",
        "- `fit_role`: how well the JOB matches what the candidate wants "
        "(objective, seniority, company shape, sector, location). Judge desire, "
        "not qualification — a dream role they're underqualified for still "
        "scores high here.",
        "- `fit_candidate`: how well the CANDIDATE meets what the job asks for "
        "(the required skills and experience). Judge qualification, not desire — "
        "a job they'd hate but could clearly do scores high here.",
        "- `score`: overall, for ranking within a tier. It should broadly track "
        "the WEAKER of the two above — a role is only as good as its limiting "
        "side — but use judgement.",
        "Then a 1-3 sentence reason, and extract "
        "role/company/location/vertical/seniority/remote.",
        "",
        "## Candidate objective",
        profile.objective or "(not specified)",
        f"Target seniority: {', '.join(profile.seniority) or 'any'}",
        f"Target company types: {', '.join(profile.company_type) or 'any'}",
        f"Preferred verticals: {', '.join(profile.verticals) or 'any'}",
        f"Locations: {', '.join(profile.locations) or 'any'}",
        f"Job types: {', '.join(profile.job_type) or 'any'}",
        f"Nice-to-have skills: {', '.join(profile.keywords_nice) or 'none'}",
    ]
    if profile.salary_floor_eur:
        parts += [
            f"Salary floor (EUR): {profile.salary_floor_eur}",
            "SALARY RULE — read carefully. Most adverts do not state pay, and that "
            "says nothing about the role. Treat an undisclosed salary as NEUTRAL: "
            "do not lower the tier or score for it, do not describe it as a "
            "concern, a risk, a red flag or 'uncertainty', and do not mention it "
            "in your reasons at all. Only count salary against a job when a figure "
            "is explicitly stated AND falls below the floor — in that one case say "
            "so plainly.",
        ]

    # What kind of EMPLOYER the candidate wants, learned from the companies they
    # listed as seeds. The job ad rarely states this, so it's a strong signal:
    # two identical job titles at differently-shaped companies are not equal.
    if company_profile is not None and not company_profile.is_empty():
        parts += [
            "",
            "## The kind of company the candidate wants",
            "(derived from companies they named as ones they admire)",
            company_profile.as_prompt_block(),
            "Treat a strong company-shape match as a genuine positive, and a "
            "clear mismatch as a genuine negative — even when the job title "
            "itself looks right.",
        ]

    # Tagging makes each verdict traceable to concrete criteria, and makes the
    # output sheet filterable.
    if criteria is not None and not criteria.is_empty():
        parts += [
            "",
            "## Criteria — tag each job with every one it meets",
            criteria.as_prompt_block(),
            "",
            f"Allowed tags (use ONLY these): {criteria.tag_list_for_prompt()}",
            "Apply a tag only when the job or company genuinely meets it.",
            "Tags are evidence, not a scorecard. Most adverts are too short to "
            "demonstrate more than a handful of criteria, so a low tag count is "
            "usually missing information rather than a bad job — do NOT drop a "
            "job to tier 4-5 just because few tags applied. Meeting many "
            "MUST-HAVE criteria is positive evidence that supports tier 1-2; "
            "meeting few is neutral.",
        ]

    parts += ["", "## Candidate background", materials.combined_context() or "(none provided)"]

    if feedback_examples:
        parts += ["", "## Learn from the candidate's past feedback"]
        for ex in feedback_examples[-20:]:  # recent examples only
            verdict = ex.get("verdict", "")
            why = ex.get("why", "")
            title = ex.get("title", "")
            company = ex.get("company", "")
            parts.append(f"- [{verdict}] {title} @ {company}: {why}")
        parts.append(
            "Weight these strongly: adjust tiers to reflect what the candidate "
            "marked as good or bad matches and why."
        )

    return "\n".join(parts)


def _user_prompt(job: JobPosting) -> str:
    desc = (job.description or "")[:DESC_CHAR_CAP]
    return (
        "Score this posting.\n\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location}\n"
        f"Salary (raw): {job.salary_text or 'not stated — treat as neutral'}\n"
        f"Source: {job.source}\n"
        f"Description:\n{desc or '(no description available)'}"
    )


class Matcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = llm.get_client(settings)
        self.failures = 0          # jobs the last score() call could not judge

    def triage(
        self, jobs: list[JobPosting], profile: Profile, candidate=None,
        company_profile=None,
    ) -> list[JobPosting]:
        """Stage 1: drop the obviously-irrelevant, cheaply and in batches."""
        if not jobs:
            return []
        system = _triage_system_prompt(profile, candidate, company_profile)
        survivors: list[JobPosting] = []
        for start in range(0, len(jobs), TRIAGE_BATCH):
            batch = jobs[start : start + TRIAGE_BATCH]
            keep = self._triage_batch(system, batch)
            survivors.extend(keep)
        log.info(
            "Triage: %d/%d jobs worth a full read (%.0f%% filtered out)",
            len(survivors),
            len(jobs),
            100 * (1 - len(survivors) / len(jobs)) if jobs else 0,
        )
        return survivors

    def _triage_batch(self, system, batch: list[JobPosting]) -> list[JobPosting]:
        listing = "\n".join(
            f"{i}. {j.title} | {j.company} | {j.location}" for i, j in enumerate(batch)
        )
        try:
            data = self.client.json(
                system=system,
                user="Triage these jobs:\n" + listing,
                schema=TRIAGE_SCHEMA,
                tier=llm.SCORING,
                max_tokens=1500,
            )
            verdicts = data.get("verdicts", [])
        except Exception as exc:
            # On failure, keep the whole batch — never silently lose jobs.
            log.warning("Triage batch failed (keeping all %d): %s", len(batch), exc)
            return list(batch)

        keep_idx = {v["index"] for v in verdicts if v.get("promising")}
        seen_idx = {v["index"] for v in verdicts}
        # Any job the model forgot to rate is kept, not dropped.
        return [j for i, j in enumerate(batch) if i in keep_idx or i not in seen_idx]

    def score(
        self,
        jobs: list[JobPosting],
        profile: Profile,
        materials: Materials,
        feedback_examples: Optional[list[dict]] = None,
        company_profile=None,
        criteria=None,
    ) -> list[tuple[JobPosting, MatchResult]]:
        system = _system_prompt(
            profile, materials, feedback_examples or [], company_profile, criteria
        )
        # Score concurrently: each job is an independent LLM call, and doing
        # them one at a time was the bulk of the wall-clock time. pool.map keeps
        # input order so ranking is deterministic.
        results: list[tuple[JobPosting, MatchResult]] = []
        self.failures = 0
        with ThreadPoolExecutor(max_workers=SCORE_WORKERS) as pool:
            scored = pool.map(lambda job: (job, self._score_one(system, job)), jobs)
            for i, (job, match) in enumerate(scored, 1):
                if match is not None:
                    results.append((job, match))
                else:
                    self.failures += 1
                if i % 20 == 0:
                    log.info("Scored %d/%d", i, len(jobs))
        # A silent partial run looks exactly like "few good jobs today", which
        # sent us hunting through the filters when the real cause was an
        # exhausted API balance. Say so loudly.
        if self.failures:
            log.warning(
                "%d of %d jobs could not be scored (%.0f%%) — results are "
                "INCOMPLETE. Check the errors above; an exhausted API balance "
                "or rate limit is the usual cause.",
                self.failures, len(jobs), 100 * self.failures / len(jobs),
            )
        log.info("Scored %d postings", len(results))
        return results

    def _score_one(self, system: str, job: JobPosting) -> Optional[MatchResult]:
        try:
            data = self.client.json(
                system=system,
                user=_user_prompt(job),
                schema=MATCH_SCHEMA,
                tier=llm.SCORING,
                max_tokens=600,
            )
        except Exception as exc:
            log.warning("Scoring failed for %r: %s", job.title, exc)
            return None

        try:
            # Clamp score into range defensively.
            data["score"] = max(0, min(100, int(data.get("score", 0))))
            return MatchResult(**data)
        except Exception as exc:
            log.warning("Bad match JSON for %r: %s", job.title, exc)
            return None
