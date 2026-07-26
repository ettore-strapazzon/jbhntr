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
    free_searches: int = int(os.environ.get("FREE_SEARCHES", "3"))
    free_documents: int = int(os.environ.get("FREE_DOCUMENTS", "2"))
    premium_searches_per_day: int = int(os.environ.get("PREMIUM_SEARCHES_PER_DAY", "2"))
    max_upload_bytes: int = 1024 * 1024          # 1 MB, per the spec
    max_feedback_chars: int = 300

    # Free users get the cheap model; premium gets the better one.
    free_scoring_model: str = os.environ.get(
        "FREE_SCORING_MODEL", "google/gemini-2.5-flash-lite"
    )
    premium_scoring_model: str = os.environ.get(
        "PREMIUM_SCORING_MODEL", "anthropic/claude-haiku-4.5"
    )

    # --- profile completeness ---
    # Required before a search may run (see docs/ARCHITECTURE.md).
    required_fields: tuple[str, ...] = (
        "cv", "about_me", "objective", "seniority",
        "company_type", "verticals", "locations", "job_type",
    )
    quality_threshold: int = 70  # below this we nudge "improve your profile"

    # --- email (provider-agnostic SMTP; unset = a safe no-op) ---
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("SMTP_FROM", "") or os.environ.get("SUPPORT_EMAIL", "")
    smtp_tls: bool = _b("SMTP_TLS", "true")
    reset_token_minutes: int = _int("RESET_TOKEN_MINUTES", 60)

    # --- product ---
    payments_enabled: bool = _b("PAYMENTS_ENABLED", "false")
    plausible_domain: str = os.environ.get("PLAUSIBLE_DOMAIN", "")
    support_email: str = os.environ.get("SUPPORT_EMAIL", "support@jbhntr.app")
    company_name: str = os.environ.get("COMPANY_NAME", "JBHNTR")
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
