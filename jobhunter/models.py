"""Core data models shared across the pipeline."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Five bands give useful separation between "drop everything and apply" and
# "worth a look", which a 3-tier scale collapsed together.
MatchTier = Literal[1, 2, 3, 4, 5]

TIER_LABELS = {
    1: "Excellent",   # apply now
    2: "Strong",      # clearly worth applying
    3: "Possible",    # decent but with real gaps
    4: "Weak",        # long shot
    5: "No",          # not a fit
}


REMOTE_WORDS = ("remote", "anywhere", "worldwide", "distributed", "global")


def _norm(text: str) -> str:
    """Lowercase, collapse whitespace — for stable dedup keys."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


class JobPosting(BaseModel):
    """A normalized job posting from any source."""

    source: str  # e.g. "adzuna", "linkedin", "remotive"
    title: str
    company: str = ""
    location: str = ""
    description: str = ""  # plain text; may be truncated by the source
    url: str = ""
    posted_date: Optional[date] = None
    salary_text: str = ""  # raw salary string if disclosed
    # Set by remote-only sources. Location text alone is unreliable: a genuinely
    # remote listing may say "Europe" or "Berlin", with no mention of "remote".
    is_remote: bool = False

    @field_validator("source", "title", "company", "location", "description",
                     "url", "salary_text", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        # Feeds sometimes send an explicit null for a field (Findwork does for
        # `role`). dict.get's default doesn't catch that, so one bad record
        # would fail validation and abort the whole source. Coerce here so any
        # adapter is robust to nulls without repeating the guard everywhere.
        return "" if v is None else v

    def looks_remote(self) -> bool:
        """True if this job can be done remotely, by flag or by wording."""
        if self.is_remote:
            return True
        blob = f"{self.location} {self.title}".lower()
        return any(w in blob for w in REMOTE_WORDS)

    def short_id(self) -> str:
        """Short, stable handle you can quote back to the tool.

        Shown in the sheet and the digest so you can run
        `python -m jobhunter.apply <id>` for the ones you want.
        """
        return self.dedup_key().split(":", 1)[1][:8]

    def dedup_key(self) -> str:
        """Stable identity for a posting, independent of where we found it.

        Keyed on company + title, NOT the URL: the same job listed on LinkedIn,
        an aggregator and the company's own board has three different URLs but
        is one job, and seeing it three times in the digest is just noise.

        Location is excluded because sources word it differently ("Milan",
        "Milano, Italia", "Milan, Lombardy, Italy") for the same role.

        Postings with no company (rare, some feeds) fall back to including the
        URL, so unrelated jobs sharing a title don't collapse into one.
        """
        company, title = _norm(self.company), _norm(self.title)
        if company and title:
            return "ct:" + hashlib.sha1(f"{company}|{title}".encode("utf-8")).hexdigest()

        url = self.url.split("?")[0].rstrip("/")
        if url:
            return "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()
        blob = f"{company}|{title}|{_norm(self.location)}"
        return "cth:" + hashlib.sha1(blob.encode("utf-8")).hexdigest()


class MatchResult(BaseModel):
    """The matcher's verdict on a single posting."""

    tier: MatchTier = Field(description="1 excellent … 5 no")
    score: int = Field(ge=0, le=100, description="0-100 fit score within the tier")
    # Two-directional score (F-07): how well the job fits what you want, and how
    # well you fit what the job asks for. Default to `score` for older cached rows.
    fit_role: int = Field(default=0, ge=0, le=100)
    fit_candidate: int = Field(default=0, ge=0, le=100)
    reasons: str = Field(description="1-3 sentences: why this tier/score")
    # Structured fields the matcher extracts for the output sheet.
    role: str = ""
    company: str = ""
    location: str = ""
    vertical: str = ""
    seniority: str = ""
    remote: str = ""  # "remote" | "hybrid" | "onsite" | ""
    tags: list[str] = Field(
        default_factory=list,
        description="Criteria this job meets, for filtering in the sheet",
    )

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, str(self.tier))


class RankedJob(BaseModel):
    """A posting plus its match result and any generated documents."""

    job: JobPosting
    match: MatchResult
    cv_link: str = ""
    cl_link: str = ""
    tailored: bool = False  # True if documents were generated for this job
    # Raw generated text, so `apply` can show it when Drive isn't configured.
    documents: dict[str, str] = Field(default_factory=dict)
