"""Web-app settings. Separate from the engine's own Settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
load_dotenv(ROOT / ".env")


def _b(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def _int(key: str, default: int) -> int:
    """Env int that tolerates unset or empty ('SMTP_PORT=' in a .env)."""
    raw = (os.environ.get(key) or "").strip()
    return int(raw) if raw.isdigit() else default


def _float(key: str, default: float) -> float:
    raw = (os.environ.get(key) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _csv(key: str, default: str) -> list[str]:
    """Comma-separated env list -> [str], trimmed, empties dropped."""
    raw = os.environ.get(key)
    raw = default if raw is None else raw
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class WebConfig:
    # --- core ---
    secret_key: str = os.environ.get("SECRET_KEY", "")
    file_encryption_key: str = os.environ.get("FILE_ENCRYPTION_KEY", "")
    database_url: str = os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'web.sqlite'}")
    debug: bool = _b("DEBUG", "true")
    base_url: str = os.environ.get("BASE_URL", "http://localhost:8000")

    # --- auth ---
    google_client_id: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    session_days: int = 14

    # --- limits (the levers that protect the AI bill) ---
    # Free is a lifetime allowance; Premium document allowances are per calendar
    # month. All numbers are config-driven so copy never hard-codes them.
    free_searches: int = _int("FREE_SEARCHES", 3)
    free_cvs: int = _int("FREE_CVS", 3)                    # lifetime, per distinct job
    free_cover_letters: int = _int("FREE_COVER_LETTERS", 3)
    premium_cvs_monthly: int = _int("PREMIUM_CVS_MONTHLY", 30)
    premium_cover_letters_monthly: int = _int("PREMIUM_COVER_LETTERS_MONTHLY", 20)
    # Premium runs one automatic search a day; the manual fair-use cap stays too.
    premium_auto_searches_per_day: int = _int("PREMIUM_AUTO_SEARCHES_PER_DAY", 1)
    premium_searches_per_day: int = _int("PREMIUM_SEARCHES_PER_DAY", 2)
    # Premium similar-company discovery: how often it re-runs per user, and how many
    # newly-added seeds count as a material profile change that triggers it early.
    discovery_interval_days: int = _int("DISCOVERY_INTERVAL_DAYS", 7)
    discovery_new_seeds_trigger: int = _int("DISCOVERY_NEW_SEEDS_TRIGGER", 3)
    # How many similar companies to accumulate per user before discovery stops
    # finding new ones. Raised now that live web research surfaces real local firms.
    discover_target: int = _int("DISCOVER_TARGET", 300)
    # Live-web-research model for discovery. A general model + ':online' emits
    # tool-call markup instead of searching; a native search model returns clean
    # results. Must be a model your OpenRouter key can reach.
    discovery_research_model: str = os.environ.get(
        "DISCOVERY_RESEARCH_MODEL", "perplexity/sonar")
    # Corpus search shape. `corpus_topk` = how many geo-matched, cosine-ranked jobs
    # get sent to the paid LLM scorer per search (the "60 to score" number the user
    # sees): the main per-search cost lever. `embed_limit` = how many corpus jobs get
    # embedded per nightly ingest — must exceed the daily ingest rate or the
    # searchable fraction of the corpus shrinks over time. Local fastembed is free
    # and batched (memory-bounded), so this can be large; it only costs CPU time.
    corpus_topk: int = _int("CORPUS_TOPK", 60)
    embed_limit: int = _int("EMBED_LIMIT", 20000)
    # Reaper cadence. A board/aggregator link is re-verified if it hasn't been
    # checked in this many days; lower = expired jobs caught sooner. Link-checking
    # is plain HTTP (no API $), so the only cost is more requests/night and a
    # longer sweep — 2 means the whole checkable corpus cycles every ~48h.
    # (ATS/scraped jobs are never link-checked; they prune on the poll window.)
    reaper_recheck_days: int = _int("REAPER_RECHECK_DAYS", 2)
    reaper_workers: int = _int("REAPER_WORKERS", 24)
    # Description enrichment: fetch the real posting page for jobs an aggregator
    # stored only a snippet for, so work-mode tagging AND match scoring improve.
    # HTTP only (no API $); each job is fetched at most once, so it's a one-time
    # backlog + the day's new thin jobs, not a nightly full re-scan. The cap is
    # about politeness (fetch too fast and hosts block our IP, which also hurts
    # link-checking) — raise it if blocks don't appear; ENRICH_ENABLED is the
    # kill switch if a host starts pushing back.
    enrich_enabled: bool = _b("ENRICH_ENABLED", "true")
    enrich_nightly_limit: int = _int("ENRICH_NIGHTLY_LIMIT", 6000)
    # Corpus company resolution: probe the most common corpus companies for an ATS
    # board (Greenhouse/Lever/Ashby/Personio/Workable/…) so we ingest their FULL-JD
    # openings, which then upgrade the thin aggregator snippets via dedup. HTTP-only
    # ATS probing (no LLM); runs weekly. The cap bounds how many companies we probe
    # per run (politeness to ATS APIs).
    corpus_resolve_enabled: bool = _b("CORPUS_RESOLVE_ENABLED", "true")
    corpus_resolve_limit: int = _int("CORPUS_RESOLVE_LIMIT", 120)
    # Country tagging + ATS location correction per nightly ingest. Like embedding,
    # these must outpace the daily ingest or the untagged backlog grows — and
    # untagged rows can't be geo-filtered, so they hurt in-country recall. Country
    # backfill resolves most locations for free (geo maps); only genuinely
    # unresolvable places cost a (batched) LLM call.
    geo_backfill_limit: int = _int("GEO_BACKFILL_LIMIT", 6000)
    ats_correct_limit: int = _int("ATS_CORRECT_LIMIT", 4000)
    # Recompute stale 'unknown' remote_mode tags (pure function, no LLM — safe to
    # run large). Jobs ingested before geo maps/descriptions filled stay unknown.
    remote_backfill_limit: int = _int("REMOTE_BACKFILL_LIMIT", 20000)
    max_upload_bytes: int = 1024 * 1024          # 1 MB, per the spec
    max_feedback_chars: int = 300

    # Free users get the cheap model; premium gets the better one.
    free_scoring_model: str = os.environ.get(
        "FREE_SCORING_MODEL", "google/gemini-2.5-flash-lite"
    )
    premium_scoring_model: str = os.environ.get(
        "PREMIUM_SCORING_MODEL", "anthropic/claude-haiku-4.5"
    )

    # --- premium multi-model "panel" for CV / cover-letter generation ---
    # Diverse models each draft a version, critique each other, revise, and vote;
    # a synthesiser merges the best once they agree (>= threshold) or rounds run
    # out. Premium-only — free keeps the single-model path. Every knob is env
    # tunable. Set PANEL_MODELS to OpenRouter model IDs your account can reach; a
    # model that errors is simply dropped from the panel for that document.
    panel_enabled: bool = _b("PANEL_ENABLED", "true")
    panel_models: list[str] = field(default_factory=lambda: _csv(
        "PANEL_MODELS",
        "anthropic/claude-3.7-sonnet,openai/gpt-4o,google/gemini-2.0-flash-001"))
    panel_synth_model: str = os.environ.get("PANEL_SYNTH_MODEL", "")  # "" -> first panel model
    panel_rounds: int = _int("PANEL_ROUNDS", 1)         # critique/revise rounds after drafts
    panel_threshold: float = _float("PANEL_THRESHOLD", 0.75)

    # --- profile completeness ---
    # Required before a search may run (see docs/ARCHITECTURE.md).
    required_fields: tuple[str, ...] = (
        "cv", "about_me", "objective", "seniority",
        "company_type", "verticals", "locations", "job_type",
    )
    quality_threshold: int = 70  # below this we nudge "improve your profile"

    # --- email ---
    # Resend HTTP API (port 443, works where cloud hosts block outbound SMTP).
    # Preferred when set; otherwise falls back to SMTP below.
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")
    # Provider-agnostic SMTP; unset = a safe no-op.
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("SMTP_FROM", "") or os.environ.get("SUPPORT_EMAIL", "")
    smtp_tls: bool = _b("SMTP_TLS", "true")
    reset_token_minutes: int = _int("RESET_TOKEN_MINUTES", 60)
    postal_address: str = os.environ.get("POSTAL_ADDRESS", "")   # CAN-SPAM line in the email footer

    # --- operator ---
    # Password for the /admin dashboard (HTTP Basic, any username). Empty = the
    # whole /admin surface 404s, so it is off unless you deliberately set it.
    admin_token: str = os.environ.get("ADMIN_TOKEN", "")

    # --- product ---
    payments_enabled: bool = _b("PAYMENTS_ENABLED", "false")
    plausible_domain: str = os.environ.get("PLAUSIBLE_DOMAIN", "")
    support_email: str = os.environ.get("SUPPORT_EMAIL", "support@jbhntr.app")
    company_name: str = os.environ.get("COMPANY_NAME", "JBHNTR")

    # --- public entity / SEO (stable values templates and schema need) ---
    site_name: str = os.environ.get("SITE_NAME", "JBHNTR")
    founder_name: str = os.environ.get("FOUNDER_NAME", "Ettore Strapazzon")
    og_image_path: str = os.environ.get("OG_IMAGE_PATH", "/static/og-default.png")
    # Public repo, linked in the footer ("built in the open"). Correct the handle
    # if it differs; blank hides the link.
    repo_url: str = os.environ.get("REPO_URL", "https://github.com/ettore-strapazzon/jbhntr")

    # Premium pricing (display only until payments are switched on).
    plans: tuple[dict, ...] = field(default_factory=lambda: (
        {"months": 1, "usd": 30, "label": "1 month"},
        {"months": 2, "usd": 50, "label": "2 months", "note": "save $10"},
        {"months": 3, "usd": 60, "label": "3 months", "note": "best value"},
    ))

    def validate(self) -> list[str]:
        """Problems that must be fixed before running in production."""
        problems = []
        if not self.secret_key or len(self.secret_key) < 32:
            problems.append("SECRET_KEY missing or shorter than 32 chars")
        if not self.file_encryption_key:
            problems.append("FILE_ENCRYPTION_KEY missing (uploads cannot be encrypted)")
        if not self.debug and self.base_url.startswith("http://"):
            problems.append("BASE_URL must be https:// in production")
        return problems


config = WebConfig()
