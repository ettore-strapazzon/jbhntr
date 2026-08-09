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
    # An operator "reset usage" sets this to now; the premium daily fair-use cap
    # only counts searches started after it, so a reset also clears the daily cap.
    usage_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    tos_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    digest: Mapped[str] = mapped_column(String(8), default="daily")   # daily | weekly | off (R13.4)
    # Set when a free user asks for premium while checkout is "coming soon" —
    # the flag the operator upgrades from manually (F-13).
    premium_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Premium similar-company discovery: when it last ran for this user, and the
    # profile signals it ran against — so a material change (>=3 new seeds, or any
    # new vertical / company type / market) can trigger a fresh run before the cadence.
    last_discovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    discovery_seeds: Mapped[list] = mapped_column(JSON, default=list)
    discovery_verticals: Mapped[list] = mapped_column(JSON, default=list)
    discovery_company_types: Mapped[list] = mapped_column(JSON, default=list)
    discovery_countries: Mapped[list] = mapped_column(JSON, default=list)

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
        """None means no per-account search cap (premium; fair-use only)."""
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
    # Target roles the engine derived from the objective + CV (not typed by the
    # user). Stored so the shared corpus can be built around what people actually
    # want, not only the titles they happened to type. Refreshed each search.
    derived_roles: Mapped[list] = mapped_column(JSON, default=list)
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
    # "unverified" when the apply link couldn't be verified (captcha/bot-wall) and
    # no live alternative was found — the card warns it may no longer be available.
    link_status: Mapped[str] = mapped_column(String(16), default="")

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

    # True once we've settled this job's country — either the deterministic tagger
    # placed it, or (for a location the maps couldn't resolve) a one-time LLM
    # lookup ran. Stops the nightly backfill re-asking about the same posting.
    geo_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    # True once we've checked whether this posting links to a known ATS and, if so,
    # corrected its location/remote from that source (aggregators mislabel these).
    ats_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Freshness — used by the TTL/re-crawl that must precede any corpus-as-source use.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # When the reaper last verified the URL was still live (None = never checked).
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # "" = ok/verified. "unverified" = the apply link is behind a captcha/bot-wall
    # we couldn't read and couldn't recover, so we can't confirm it's still live.
    link_status: Mapped[str] = mapped_column(String(16), default="")
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

    `visitor` is a one-way persistent hash (a secret non-rotating salt combined
    with the caller's IP and user-agent, then SHA-256'd). It lets us count
    *distinct* devices over time without ever storing an IP. See
    services/analytics.py.
    """

    __tablename__ = "page_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(255), index=True)
    referrer: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str] = mapped_column(String(8), default="")
    visitor: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ProductEvent(Base):
    """Server-side funnel/activation events (PROOF-003). One row per action, e.g.
    signup_completed, scan_completed, match_rated. Deliberately carries no CV
    text, objective text, job-description text, IP or email — only a controlled
    event name, an optional user id, and a small allowlisted properties bag.
    """

    __tablename__ = "product_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None)
    name: Mapped[str] = mapped_column(String(48), index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# Whole-product survey shown during the alpha (distinct from per-match Feedback).
# Each question is a 1-5 scale; label is what the tester reads.
SITE_FEEDBACK_QUESTIONS = [
    ("q_useful", "JBHNTR could be useful to me"),
    ("q_easy", "It is easy to use and understand"),
    ("q_look", "I like how it looks and feels"),
    ("q_pay", "I would pay for Premium if I were job-hunting"),
]


class CorpusStat(Base):
    """One row per nightly maintenance run: corpus size and the day's churn, so
    'how many jobs live in the corpus, and how many are added / deprecated per
    day' is answerable over time (the reaper deletes rows, so past churn is only
    knowable if recorded here). Written by services/cron.nightly()."""

    __tablename__ = "corpus_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    total: Mapped[int] = mapped_column(Integer, default=0)          # corpus size after the run
    added: Mapped[int] = mapped_column(Integer, default=0)          # new postings ingested
    updated: Mapped[int] = mapped_column(Integer, default=0)        # refreshed (still live)
    ttl_deleted: Mapped[int] = mapped_column(Integer, default=0)    # pruned: unseen too long
    gone_deleted: Mapped[int] = mapped_column(Integer, default=0)   # pruned: link 404/410/dead
    checked: Mapped[int] = mapped_column(Integer, default=0)        # link-checks this run
    embedded: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OpsLog(Base):
    """One row per operator background job (discovery, embed, maintenance, deep
    clean). These run fire-and-forget in a thread, so without this the operator
    can't tell whether a button did anything, was skipped, or errored. `detail`
    holds a compact human-readable outcome. Read on the /admin dashboard."""

    __tablename__ = "ops_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default="", index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SiteFeedback(Base):
    """Alpha/testing feedback on the product as a whole: four 1-5 ratings plus
    open comments. Separate from the per-match `Feedback`. Anonymous-friendly —
    user_id is nullable so a logged-out tester can still leave feedback.
    """

    __tablename__ = "site_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None)
    # Four 1-5 ratings; None when the tester skipped that question.
    q_useful: Mapped[int | None] = mapped_column(Integer, default=None)
    q_easy: Mapped[int | None] = mapped_column(Integer, default=None)
    q_look: Mapped[int | None] = mapped_column(Integer, default=None)
    q_pay: Mapped[int | None] = mapped_column(Integer, default=None)
    # Open text.
    likes: Mapped[str] = mapped_column(Text, default="")
    dislikes: Mapped[str] = mapped_column(Text, default="")
    broken: Mapped[str] = mapped_column(Text, default="")
    other: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(String(255), default="")   # where they were
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
