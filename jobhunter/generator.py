"""Generate tailored CV + cover letter for top matches (stronger model).

Only the top-N tier-1 matches get freshly tailored documents; everything else
reuses the base CV (no generation, no cost). Generated docs are uploaded to
Drive and the links attached to the RankedJob.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from . import llm
from .config import Materials, Profile, Settings
from .gdrive import Drive
from .models import RankedJob

log = logging.getLogger("jobhunter.generator")

DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "cv": {"type": "string", "description": "Full tailored CV in plain text/markdown"},
        "cover_letter": {"type": "string", "description": "Full cover letter in plain text"},
    },
    "required": ["cv", "cover_letter"],
    "additionalProperties": False,
}

# Cover letter on its own, with a short note on the tone chosen for this company.
COVER_LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "cover_letter": {"type": "string", "description": "Full cover letter in plain text"},
        "tone_note": {"type": "string", "description": "2-3 sentences: the tone this "
                      "company likely responds to, and how the letter matches it to the "
                      "candidate's own voice"},
    },
    "required": ["cover_letter", "tone_note"],
    "additionalProperties": False,
}

REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "The full revised document"},
        "change_note": {"type": "string", "description": "1-2 sentences: what changed"},
    },
    "required": ["content", "change_note"],
    "additionalProperties": False,
}


class Generator:
    def __init__(self, settings: Settings, drive: Optional[Drive] = None):
        self.settings = settings
        self.client = llm.get_client(settings)
        self.drive = drive

    def tailor_top(
        self,
        ranked: list[RankedJob],
        profile: Profile,
        materials: Materials,
        limit: Optional[int] = None,
    ) -> None:
        """Mutates the given matches in place, attaching cv_link / cl_link.

        `limit` overrides the profile cap — used by `jobhunter.apply`, where you
        picked the jobs yourself and every one should be written.
        """
        if limit is not None:
            targets = ranked[:limit]
        else:
            # Otherwise: best tier-1 matches only, capped by the profile.
            targets = sorted(
                [r for r in ranked if r.match.tier == 1],
                key=lambda r: r.match.score,
                reverse=True,
            )[: profile.top_n_tailored]
        if not targets:
            log.info("No matches to tailor.")
            return

        system = self._system_prompt(profile, materials)
        for r in targets:
            docs = self._generate(system, r)
            if not docs:
                continue
            r.tailored = True
            r.documents = docs  # kept so we can print them if Drive is unavailable
            title_stub = f"{r.job.title} - {r.job.company}".strip(" -")[:120]
            if self.drive:
                r.cv_link = self.drive.create_doc(f"CV - {title_stub}", docs["cv"])
                r.cl_link = self.drive.create_doc(
                    f"Cover letter - {title_stub}", docs["cover_letter"]
                )
        log.info("Tailored documents for %d matches", len(targets))

    def _system_prompt(self, profile: Profile, materials: Materials) -> str:
        return (
            "You are an expert career writer. Using the candidate's real "
            "background, produce a tailored CV and a tailored cover letter for a "
            "specific job. Rules:\n"
            "- Never invent experience, employers, dates, or credentials. Use only "
            "what the candidate's materials support; re-emphasize and re-order to "
            "fit the role.\n"
            "- Adjust the CV toward the job, do not twist it to match. Keep every "
            "role, title, seniority, scope and result faithful to what the candidate "
            "actually did. You may reorder, re-emphasize and reword to surface the "
            "experience most relevant to this posting, and mirror the job's "
            "terminology only where it genuinely describes the candidate's real work. "
            "Do not overstate impact, inflate seniority, claim skills the materials "
            "do not evidence, or reframe the candidate as a different profile. The "
            "result must read as the same person's honest CV, angled toward this "
            "role, that they could defend line by line in an interview.\n"
            "- Your job is to REFRAME and RE-EMPHASISE this CV for the target role, "
            "NOT to shorten, summarise or trim it. Tailoring means reordering and "
            "rewording so the most relevant experience leads; it is NEVER cutting "
            "content.\n"
            "- PRESERVE ALL SUBSTANCE. Keep every employer, role, title and date, AND "
            "every quantified achievement the candidate states: every metric, number, "
            "percentage, monetary figure ($/EUR), deal size, team size, client/user "
            "count, market-cap and timeframe. Never drop, round away or make vague a "
            "number or an accomplishment — these are the most valuable part of a CV.\n"
            "- Keep roughly the same depth per role as the source: if a role has "
            "several detailed bullets with metrics, the tailored role keeps a "
            "comparable set, reworded to foreground what matters for THIS job. Do not "
            "reduce a rich role to one or two generic lines.\n"
            "- INCLUDE EVERY position — never drop, merge or omit any employer, role or "
            "date; the tailored CV contains their COMPLETE work history.\n"
            "- The tailored CV must be at least as complete and detailed as the "
            "candidate's original. A shorter, thinner or vaguer CV than the one they "
            "uploaded is a FAILURE, however well written. Lead with the most relevant "
            "experience, keep it ATS-friendly, but never at the cost of substance.\n"
            "- Keep the candidate's OWN CV structure: the same section headings and "
            "order, and the same bullet and date formatting conventions as the CV in "
            "their materials. Change the content to fit the job; keep the form "
            "recognisably theirs.\n"
            "- Cover letter: specific to the company and role, 3-4 short paragraphs, "
            "no clichés, confident but not boastful.\n"
            "- Write like a person, not an AI. Plain, direct language. Do NOT use em "
            "dashes (—) or en dashes (–) — use commas, full stops or parentheses. "
            "Avoid buzzwords, filler, and stock AI phrasing (\"leverage\", "
            "\"passionate about\", \"in today's fast-paced world\").\n"
            "- OUTPUT PLAIN TEXT ONLY — no markdown. Do not use **, *, _, #, backticks "
            "or any markup. Put each section heading on its own line (in the "
            "candidate's own wording/case), and start every bullet with '- '.\n"
            "- Layout the CV so a plain-text reader can parse its structure: the "
            "candidate's NAME on the first line (keep their exact capitalisation, do "
            "not upper-case it), then a short subtitle line, then a contact line. For "
            "each role use two lines — 'Employer - Location' then 'Job Title (dates)' — "
            "before its bullet points.\n\n"
            "## Candidate materials\n" + (materials.combined_context() or "(none)")
        )

    def _generate(self, system, r: RankedJob) -> Optional[dict]:
        job = r.job
        user = (
            "Tailor a CV and cover letter for this job.\n\n"
            f"Title: {job.title}\nCompany: {job.company}\n"
            f"Location: {job.location}\n"
            f"Description:\n{(job.description or '')[:6000] or '(no description available)'}"
        )
        try:
            return self.client.json(
                system=system,
                user=user,
                schema=DOC_SCHEMA,
                tier=llm.GENERATION,
                # A full CV + cover letter in one JSON response overran 4000 and
                # truncated (invalid JSON -> "returned nothing"), which hit the
                # longer CV more than the letter.
                max_tokens=8000,
            )
        except Exception as exc:
            log.warning("Generation failed for %r: %s", job.title, exc)
            return None

    def cover_letter(self, profile: Profile, materials: Materials, job) -> Optional[dict]:
        """A cover letter tuned to the company's likely tone, plus a short note
        explaining that tone choice. Returns {cover_letter, tone_note} or None.

        "Research" is grounded in the posting itself (mission, product, culture
        cues) rather than a live web call, so it stays reliable and keyless; the
        candidate's own voice comes from their materials.
        """
        system = (
            "You are an expert cover-letter writer. Work in two steps.\n"
            "1. Read the job posting and infer what kind of company this is and "
            "the tone it would respond best to — formal or warm, technical or "
            "mission-led, buttoned-up or scrappy — using the mission, product, "
            "language and culture cues in the posting.\n"
            "2. Write a cover letter that blends the candidate's authentic voice "
            "(from their materials below) with that tone.\n"
            "Rules:\n"
            "- Never invent experience, employers, dates or credentials. Use only "
            "what the candidate's materials support.\n"
            "- 3-4 short paragraphs, specific to this company and role, no clichés.\n"
            "- Write like a person: plain, direct language. No em dashes (—) or en "
            "dashes (–); no stock AI phrasing (\"leverage\", \"passionate about\").\n"
            "- Also return tone_note: 2-3 sentences on the tone you judged this "
            "company wants and how you matched it to the candidate.\n\n"
            "## Candidate materials\n" + (materials.combined_context() or "(none)")
        )
        user = (
            "Write the cover letter for this job.\n\n"
            f"Title: {job.title}\nCompany: {job.company}\n"
            f"Location: {job.location}\n"
            f"Description:\n{(job.description or '')[:6000] or '(no description available)'}"
        )
        try:
            return self.client.json(
                system=system, user=user, schema=COVER_LETTER_SCHEMA,
                tier=llm.GENERATION, max_tokens=4000,
            )
        except Exception as exc:
            log.warning("Cover-letter generation failed for %r: %s", job.title, exc)
            return None

    def refine(self, kind, previous, feedback, profile, materials, job):
        """Revise an existing CV ('cv') or cover letter ('cl') per the candidate's
        feedback. Returns {content, change_note} or None."""
        label = "CV" if kind == "cv" else "cover letter"
        system = self._system_prompt(profile, materials) + (
            f"\n\n## Revision task\nYou are revising an existing {label} for this "
            "candidate. Apply their requested changes exactly. Keep everything "
            "truthful and in their own voice and structure; change only what the "
            "feedback asks plus what is needed for coherence. Never invent "
            "experience. Return the FULL revised document, not a diff or a summary."
        )
        user = (
            f"Current {label}:\n\n{previous}\n\n"
            f"Requested changes:\n{feedback}\n\n"
            f"Role: {job.title} at {job.company}."
        )
        try:
            return self.client.json(system=system, user=user, schema=REFINE_SCHEMA,
                                    tier=llm.GENERATION, max_tokens=8000)
        except Exception as exc:
            log.warning("Refine failed for %r: %s", job.title, exc)
            return None
