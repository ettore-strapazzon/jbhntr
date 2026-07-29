"""Database models.

Array-ish fields are stored as JSON so the same schema works on both SQLite
(local dev) and Postgres (production) without dialect-specific types.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    """Normalise a stored datetime to timezone-aware UTC.

    Postgres returns aware datetimes; SQLite (local dev) returns naive ones.
    Comparing the two raises TypeError, so every read goes through here.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Null when the account was created through Google.
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)

    plan: Mapped[str] = mapped_column(String(16), default="free")  # free | premium
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    searches_used: Mapped[int] = mapped_column(Integer, default=0)
    documents_used: Mapped[int] = mapped_column(Integer, default=0)

    tos_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    digest: Mapped[str] = mapped_column(String(8), default="daily")   # daily | weekly | off (R13.4)
    # Set when a free user asks for premium while checkout is "coming soon" —
    # the flag the operator upgrades from manually (F-13).
    premium_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False,
                                              cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(cascade="all, delete-orphan")
    seeds: Mapped[list["SeedCompany"]] = relationship(cascade="all, delete-orphan")
    searches: Mapped[list["Search"]] = relationship(cascade="all, delete-orphan")

    @property
    def is_premium(self) -> bool:
        if self.plan != "premium":
            return False
        until = aware(self.premium_until)
        return until is None or until > utcnow()

    def searches_remaining(self, free_allowance: int) -> int | None:
        """None means unlimited (premium)."""
        if self.is_premium:
            return None
        return max(0, free_allowance - self.searches_used)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         unique=True, index=True)

    objective: Mapped[str] = mapped_column(Text, default="")     # "what I want"
    about_me: Mapped[str] = mapped_column(Text, default="")
    seniority: Mapped[list] = mapped_column(JSON, default=list)
    company_type: Mapped[list] = mapped_column(JSON, default=list)
    verticals: Mapped[list] = mapped_column(JSON, default=list)
    # Structured location inputs. `locations` holds the engine tokens derived
    # from these (e.g. "United States", "Remote-Italy") and stays the canonical
    # field the matcher/geo read.
    work_modes: Mapped[list] = mapped_column(JSON, default=list)   # onsite/hybrid/remote
    countries: Mapped[list] = mapped_column(JSON, default=list)    # picked country names
    locations: Mapped[list] = mapped_column(JSON, default=list)
    job_type: Mapped[list] = mapped_column(JSON, default=list)
    search_terms: Mapped[list] = mapped_column(JSON, default=list)
    salary_floor_eur: Mapped[int | None] = mapped_column(Integer, default=None)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="profile")


class Material(Base):
    """An uploaded document. Bytes are encrypted; extracted text is not."""

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # cv | cover_letter | linkedin
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    text: Mapped[str] = mapped_column(Text, default="")  # extracted, for the AI
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SeedCompany(Base):
    __tablename__ = "seed_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(255))  # name or website


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    # queued | running | done | failed
    stage: Mapped[str] = mapped_column(String(64), default="")  # human-readable progress
    raw_count: Mapped[int] = mapped_column(Integer, default=0)       # postings collected
    located_count: Mapped[int] = mapped_column(Integer, default=0)   # in your countries
    ranked_count: Mapped[int] = mapped_column(Integer, default=0)    # shortlisted to score
    scored_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    # "Email me when it's ready" (§11.6) — the worker emails on completion if set.
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    results: Mapped[list["JobResult"]] = relationship(cascade="all, delete-orphan")


class JobResult(Base):
    __tablename__ = "job_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    position: Mapped[int] = mapped_column(Integer, default=0)  # 1-based row number
    short_id: Mapped[str] = mapped_column(String(16), index=True)
    # Stable posting identity across runs (engine's job.dedup_key()). Lets a
    # result seen in run 2 map to the same match a user saved in run 1 — the
    # backbone of the accumulating Matches surface and per-user job state.
    dedup_key: Mapped[str] = mapped_column(String(120), default="", index=True)
    tier: Mapped[int] = mapped_column(Integer, default=5)
    tier_label: Mapped[str] = mapped_column(String(16), default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    fit_role: Mapped[int] = mapped_column(Integer, default=0)        # job fits what you want
    fit_candidate: Mapped[int] = mapped_column(Integer, default=0)   # you fit what they ask

    title: Mapped[str] = mapped_column(String(300), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    company_url: Mapped[str] = mapped_column(String(500), default="")
    company_blurb: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    apply_url: Mapped[str] = mapped_column(String(1000), default="")
    source: Mapped[str] = mapped_column(String(64), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)

    why_good: Mapped[str] = mapped_column(Text, default="")
    why_bad: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """Shared job corpus — one row per unique posting, tagged once at ingestion.

    A write-through cache over live searches (see docs/ARCHITECTURE.md). Nothing
    reads it for matching yet (Phase 2 slice 1); it exists so later slices can
    reuse tags/embeddings/scores instead of recomputing them per user.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)

    source: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    posted_date: Mapped[str] = mapped_column(String(20), default="")

    # Deterministic tags (jobhunter/tags.py) — the only ones safe as hard filters.
    countries: Mapped[list] = mapped_column(JSON, default=list)   # ISO codes
    remote_mode: Mapped[str] = mapped_column(String(12), default="unknown", index=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, default=None)
    salary_max: Mapped[int | None] = mapped_column(Integer, default=None)
    has_salary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Freshness — used by the TTL/re-crawl that must precede any corpus-as-source use.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # When the reaper last verified the URL was still live (None = never checked).
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Semantic embedding (list of floats) + the model that produced it, so a
    # model change can re-embed. None = not yet embedded. Used for search-time
    # cosine ranking (step 4); populated at ingestion when embeddings are on.
    embedding: Mapped[list | None] = mapped_column(JSON, default=None)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")


class Company(Base):
    """Shared company registry — employers whose public ATS board we poll.

    Grown from two sources: the seed list (config), and per-user discovery
    (seeds -> ~100 similar companies via discover.py). Shared across all users:
    a company discovered for one user feeds everyone's corpus. Only companies
    with a readable public ATS land here; the rest are skipped at discovery.
    See docs/INGESTION_ENGINE.md → Lane C.
    """
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("ats", "ats_token", name="uq_company_ats"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ats: Mapped[str] = mapped_column(String(24), index=True)       # greenhouse|lever|…
    ats_token: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(16), default="discovered")  # seed|discovered|manual
    discovered_for: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True)
    jobs_count: Mapped[int] = mapped_column(Integer, default=0)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScoreCache(Base):
    """A cached LLM verdict for one (job, full-scoring-context) combination.

    `input_hash` folds in everything that determines a score — the job content,
    the user's profile/materials/criteria/company-profile/feedback, the model,
    and matcher.PROMPT_VERSION — so a hit is only reused when nothing that
    produced it has changed. See docs/INGESTION_ENGINE.md step 5.
    """
    __tablename__ = "score_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dedup_key: Mapped[str] = mapped_column(String(80), index=True)

    tier: Mapped[int] = mapped_column(Integer, default=5)
    score: Mapped[int] = mapped_column(Integer, default=0)
    fit_role: Mapped[int] = mapped_column(Integer, default=0)
    fit_candidate: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    vertical: Mapped[str] = mapped_column(String(120), default="")
    seniority: Mapped[str] = mapped_column(String(60), default="")
    remote: Mapped[str] = mapped_column(String(16), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)

    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_result_id: Mapped[int] = mapped_column(ForeignKey("job_results.id", ondelete="CASCADE"),
                                               index=True)
    vote: Mapped[str] = mapped_column(String(8), default="")   # up | down, derived from rating
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1..5 (R9)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# 1-5 rating (R9): a usable training signal from the borderline cases. vote is
# kept and derived so nothing downstream (export, the model examples) breaks.
RATING_LABELS = [(1, "Not close"), (2, "Weak"), (3, "Borderline"),
                 (4, "Good"), (5, "Exactly right")]
RATING_TO_VOTE = {1: "down", 2: "down", 3: "", 4: "up", 5: "up"}
RATING_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.0, 4: 0.6, 5: 1.0}
RATING_VERDICT = {1: "wrong", 2: "weak", 3: "borderline", 4: "good", 5: "ideal"}


class JobState(Base):
    """Per-user, per-posting state that outlives any single search run.

    Keyed by (user, dedup_key) so save / dismiss / applied stick to a posting
    even as new runs re-surface it. This is the state the Matches surface reads
    to draw a card as saved, hide a dismissed one, or move an applied one to
    Applications.
    """
    __tablename__ = "job_states"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_jobstate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(120), index=True)

    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    dismiss_reason: Mapped[str] = mapped_column(String(40), default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Applied | Replied | Interviewing | Rejected | Offer | Withdrawn
    application_status: Mapped[str] = mapped_column(String(16), default="")
    # Set when a posting has been included in a digest, so it is never repeated.
    digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 onupdate=utcnow)


class Document(Base):
    """A generated CV or cover letter. Counts against the free allowance."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_result_id: Mapped[int] = mapped_column(ForeignKey("job_results.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8))  # cv | cl
    content: Mapped[str] = mapped_column(Text)
    # For cover letters: a short "why this tone" note shown above the draft.
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    """Server-side sessions: logout and 'sign out everywhere' actually work."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @classmethod
    def issue(cls, user_id: int, days: int) -> "Session":
        return cls(
            token=secrets.token_urlsafe(48),
            user_id=user_id,
            expires_at=utcnow() + timedelta(days=days),
        )

    @property
    def is_valid(self) -> bool:
        expires = aware(self.expires_at)
        return bool(expires and expires > utcnow())


class PageView(Base):
    """Minimal analytics. Stores no IP and no user id.

    `visitor` is a one-way daily-rotating hash (a salt that changes every day,
    combined with the caller's IP and user-agent, then SHA-256'd). It lets us
    count *distinct* visitors within a day without ever storing an IP or being
    able to follow anyone across days. See services/analytics.py.
    """

    __tablename__ = "page_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(255), index=True)
    referrer: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str] = mapped_column(String(8), default="")
    visitor: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
