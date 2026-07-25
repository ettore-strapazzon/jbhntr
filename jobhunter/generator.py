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
            "- CV: keep it truthful, ATS-friendly, and concise. Lead with the most "
            "relevant experience for this role.\n"
            "- Cover letter: specific to the company and role, 3-4 short paragraphs, "
            "no clichés, confident but not boastful.\n\n"
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
                max_tokens=4000,
            )
        except Exception as exc:
            log.warning("Generation failed for %r: %s", job.title, exc)
            return None
