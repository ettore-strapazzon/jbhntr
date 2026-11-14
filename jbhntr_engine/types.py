"""Engine contract types — the wire types shared by the shell and every engine.

PUBLIC contract (open-core split, REPO_SPLIT_EXECUTION_PLAN §4): moved here from
``jobhunter/models.py`` (which is now an alias of this module) so the real
engine and the demo engine return the very same classes. Addition over
modification: add optional fields, never change a field's meaning.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# In-stage progress (R3-29). The long engine stages (``Matcher.score``,
# ``collect_all_sources``, and since R3-31 ``Matcher.triage``) take an optional keyword ``progress(done, total)``:
# counts in the stage's own work units, called on the CALLER's thread (the shell
# writes its heartbeat with a non-thread-safe DB session), as often as the engine
# likes — throttling is the caller's job. It is an observer: the engine never
# lets it change the stage's outcome, so it is invoked via ``report_progress``.
ProgressFn = Callable[[int, int], None]


def report_progress(progress: Optional[ProgressFn], done: int, total: int) -> None:
    """Call ``progress(done, total)`` if given; a failing callback is logged, never raised."""
    if progress is None:
        return
    try:
        progress(done, total)
    except Exception as exc:
        logging.getLogger("jbhntr.engine").warning("progress callback failed: %s", exc)


# Cancellation (R3-30). The same two stages take an optional keyword
# ``should_stop()``: the engine asks it on the CALLER's thread between units of
# work (jobs, sources, ATS companies, triage batches) and, once it returns True, stops starting
# new work and returns what it already has. Partial output is not a valid stage
# result — the caller asked to stop, so the caller discards it. A stop is a
# return, not an exception: a raise inside a source would be swallowed by the
# per-source catch-all. Asked via ``stop_requested``, which fails open (keep
# going) so a broken hook can never cut a healthy stage short.
StopFn = Callable[[], bool]


def stop_requested(should_stop: Optional[StopFn]) -> bool:
    """True only if ``should_stop()`` says so; a missing or failing hook means go on."""
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception as exc:
        logging.getLogger("jbhntr.engine").warning("should_stop hook failed: %s", exc)
        return False


# Five bands give useful separation between "drop everything and apply" and
# "worth a look", which a 3-tier scale collapsed together.
MatchTier = Literal[1, 2, 3, 4, 5]

TIER_LABELS = {
    1: "Excellent",   # 4 pips · 85-100
    2: "Strong",      # 3 pips · 70-84
    3: "Fair",        # 2 pips · 55-69
    4: "Long shot",   # 1 pip  · <55
    5: "No",          # never shown (filtered out)
}


def tier_for_score(score: int) -> int:
    """Map a 0-100 match score to its display tier (bands per TIER_LABELS).
    ponytail: the same bands are duplicated in app.js for the live self-score
    slider — keep them in sync if the thresholds ever move."""
    s = score or 0
    return 1 if s >= 85 else 2 if s >= 70 else 3 if s >= 55 else 4


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
    # Separated for the card's FITS vs WATCH-OUT columns, so a gap never lands
    # under strengths. Optional (older cached rows fall back to splitting reasons).
    strengths: list[str] = Field(default_factory=list,
                                 description="short positive points (fit)")
    concerns: list[str] = Field(default_factory=list,
                                description="short negative points (gaps / watch-outs)")
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
