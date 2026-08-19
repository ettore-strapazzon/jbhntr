"""Load user configuration: profile.yaml, materials/, and environment settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

# Project root = parent of the jobhunter package directory.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
MATERIALS_DIR = CONFIG_DIR / "materials"
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


# --------------------------------------------------------------------------- #
# Materials text extraction
# --------------------------------------------------------------------------- #
def _read_text_file(path: Path) -> str:
    """Best-effort text extraction from a materials file."""
    suffix = path.suffix.lower()
    try:
        if suffix in {".md", ".txt"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix == ".docx":
            from docx import Document

            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception as exc:  # pragma: no cover - defensive
        return f"[could not read {path.name}: {exc}]"
    return ""


@dataclass
class Materials:
    """Extracted text of the user's documents."""

    base_cv: str = ""  # concatenated CV text (first *.cv.* / cv.* file wins as primary)
    base_cv_path: Optional[Path] = None
    cover_letters: str = ""
    linkedin_export: str = ""
    about_me: str = ""

    def combined_context(self) -> str:
        """A single blob describing the candidate, for the matcher prompt."""
        parts = []
        if self.about_me:
            parts.append("## About me\n" + self.about_me)
        if self.base_cv:
            parts.append("## CV\n" + self.base_cv)
        if self.linkedin_export:
            parts.append("## LinkedIn\n" + self.linkedin_export)
        if self.cover_letters:
            parts.append("## Past cover letters\n" + self.cover_letters)
        return "\n\n".join(parts).strip()


def load_materials(materials_dir: Path = MATERIALS_DIR) -> Materials:
    """Read every document in config/materials/ and classify by filename."""
    m = Materials()
    if not materials_dir.exists():
        return m

    for path in sorted(materials_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name == "about_me.example.md":
            continue
        name = path.name.lower()
        text = _read_text_file(path)
        if not text.strip():
            continue

        if "about" in name:
            m.about_me += text + "\n"
        elif "linkedin" in name:
            m.linkedin_export += text + "\n"
        elif "cover" in name or name.startswith("cl") or "cover_letter" in name:
            m.cover_letters += text + "\n"
        elif "cv" in name or "resume" in name:
            m.base_cv += text + "\n"
            if m.base_cv_path is None:
                m.base_cv_path = path
        else:
            # Unclassified: treat as extra CV context.
            m.base_cv += text + "\n"
    return m


# --------------------------------------------------------------------------- #
# Profile (profile.yaml)
# --------------------------------------------------------------------------- #
@dataclass
class Profile:
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def objective(self) -> str:
        return str(self.raw.get("objective", "")).strip()

    @property
    def seniority(self) -> list[str]:
        return [str(x).lower() for x in self.raw.get("seniority", [])]

    @property
    def company_type(self) -> list[str]:
        return [str(x).lower() for x in self.raw.get("company_type", [])]

    @property
    def verticals(self) -> list[str]:
        return [str(x).lower() for x in self.raw.get("verticals", [])]

    @property
    def locations(self) -> list[str]:
        return [str(x) for x in self.raw.get("locations", [])]

    @property
    def job_type(self) -> list[str]:
        return [str(x).lower() for x in self.raw.get("job_type", [])]

    @property
    def keywords_must(self) -> list[str]:
        return [str(x).lower() for x in self.raw.get("keywords_must", [])]

    @property
    def keywords_nice(self) -> list[str]:
        return [str(x).lower() for x in self.raw.get("keywords_nice", [])]

    @property
    def salary_floor_eur(self) -> Optional[int]:
        val = self.raw.get("salary_floor_eur")
        return int(val) if val else None

    @property
    def top_n_tailored(self) -> int:
        return int(self.raw.get("top_n_tailored", 5))

    @property
    def keep_tier_max(self) -> int:
        # Tiers are 1 (Excellent) … 5 (No); keep down to "Possible" by default.
        return int(self.raw.get("keep_tier_max", 3))

    @property
    def criteria_count(self) -> int:
        """Roughly how many criteria/tags to derive (half become must-haves)."""
        return int(self.raw.get("criteria_count", 20))

    @property
    def min_must(self) -> int:
        """Must-have criteria a discovered company has to meet."""
        return int(self.raw.get("discovery_min_must", 1))

    @property
    def min_nice(self) -> int:
        """Nice-to-have criteria a discovered company has to meet."""
        return int(self.raw.get("discovery_min_nice", 1))

    @property
    def two_stage_triage(self) -> bool:
        """Cheap title-only pass before full scoring. Keeps big runs affordable."""
        return bool(self.raw.get("two_stage_triage", True))

    @property
    def discovery_web_search(self) -> bool:
        """Let company discovery research the live web (funding news, PR, press)."""
        return bool(self.raw.get("discovery_web_search", True))

    @property
    def sources(self) -> dict[str, Any]:
        return self.raw.get("sources", {}) or {}

    @property
    def aggregators(self) -> list[str]:
        return [str(x).lower() for x in self.sources.get("aggregators", [])]

    @property
    def search_terms(self) -> list[str]:
        return [str(x) for x in self.sources.get("search_terms", [])]

    @property
    def linkedin_search_urls(self) -> list[str]:
        return [str(x) for x in self.sources.get("linkedin_search_urls", [])]

    @property
    def boards(self) -> list[str]:
        """Niche/vertical job boards from the built-in registry."""
        return [str(x).lower() for x in self.sources.get("boards", [])]

    @property
    def custom_rss(self) -> list[dict[str, Any]]:
        """Any other RSS job feed: {url, name, title_format}."""
        out: list[dict[str, Any]] = []
        for item in self.sources.get("custom_rss", []) or []:
            if isinstance(item, str):
                out.append({"url": item, "name": item})
            elif isinstance(item, dict):
                out.append(item)
        return out

    @property
    def custom_sites(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in self.sources.get("custom_sites", []) or []:
            if isinstance(item, str):
                out.append({"url": item, "name": item})
            elif isinstance(item, dict):
                out.append(item)
        return out


def load_profile(path: Path = CONFIG_DIR / "profile.yaml") -> Profile:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Copy the sample and fill it in.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Profile(raw=data)


def load_companies(path: Path = CONFIG_DIR / "companies.yaml") -> list[dict[str, Any]]:
    """Companies whose career pages (ATS boards) we poll. Empty if not configured."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[dict[str, Any]] = []
    for item in data.get("companies", []) or []:
        if isinstance(item, str):
            out.append({"careers_url": item})
        elif isinstance(item, dict):
            out.append(item)
    return out


def load_seeds(path: Path = CONFIG_DIR / "companies.yaml") -> list[str]:
    """Company names you admire, used to steer discovery toward similar ones.

    Seeds do not need a job board — they're pure examples of 'more like this'.
    """
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(s).strip() for s in (data.get("seeds") or []) if str(s).strip()]


# --------------------------------------------------------------------------- #
# Environment settings
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    anthropic_api_key: str = ""
    scoring_model: str = "claude-haiku-4-5"
    generation_model: str = "claude-sonnet-5"
    # Model used for live web research in company discovery. A general chat model
    # with an ':online' suffix often just emits tool-call markup instead of
    # searching; a purpose-built search model (e.g. perplexity/sonar) returns clean
    # cited results. Empty -> fall back to the scoring model + ':online'.
    research_model: str = ""

    # Which AI provider to use: "anthropic" (default) or "openai_compatible"
    # (OpenRouter, OpenAI, Mistral, Groq, DeepSeek, Ollama, ...).
    llm_provider: str = "anthropic"
    llm_base_url: str = ""
    llm_api_key: str = ""

    # ---- Embeddings (optional; provider-agnostic OpenAI-compatible endpoint).
    # Activates only when a base URL + key are set. Works with OpenAI, Jina,
    # Voyage, DeepInfra, or a local server. See jobhunter/embeddings.py.
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "gb"
    adzuna_pages: int = 3        # result pages per (country, term) — 50 jobs each

    # ---- Optional aggregator APIs (each activates when its key is set) ----
    careerjet_affid: str = ""
    careerjet_locale: str = "en_GB"       # e.g. it_IT for Italy
    careerjet_referer: str = "http://localhost"
    jooble_key: str = ""
    reed_key: str = ""
    findwork_key: str = ""
    web3career_key: str = ""
    usajobs_key: str = ""
    usajobs_email: str = ""               # registered email, sent as User-Agent
    serpapi_key: str = ""
    serpapi_max_terms: int = 4            # searches = terms x locations
    serpapi_max_locations: int = 2
    jsearch_key: str = ""
    # France Travail (ex-Pôle Emploi) gov API — OAuth client credentials.
    france_travail_id: str = ""
    france_travail_secret: str = ""
    # Sweden JobTech — keyless; a flag so it can be switched off.
    jobtech_enabled: bool = True

    google_sa_file: str = "service_account.json"
    google_sheet_id: str = ""
    google_drive_folder_id: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        def g(key: str, default: str = "") -> str:
            return os.environ.get(key, default)

        provider = g("LLM_PROVIDER", "anthropic").lower()
        # Model names differ per provider, so only default them for Anthropic.
        anthropic_default = provider in ("anthropic", "")
        return cls(
            anthropic_api_key=g("ANTHROPIC_API_KEY"),
            scoring_model=g(
                "JOBHUNTER_SCORING_MODEL",
                "claude-haiku-4-5" if anthropic_default else "",
            ),
            generation_model=g(
                "JOBHUNTER_GENERATION_MODEL",
                "claude-sonnet-5" if anthropic_default else "",
            ),
            research_model=g("DISCOVERY_RESEARCH_MODEL", ""),
            llm_provider=provider,
            llm_base_url=g("LLM_BASE_URL"),
            llm_api_key=g("LLM_API_KEY") or g("OPENROUTER_API_KEY"),
            embedding_base_url=g("EMBEDDING_BASE_URL"),
            embedding_api_key=g("EMBEDDING_API_KEY"),
            embedding_model=g("EMBEDDING_MODEL", "text-embedding-3-small"),
            adzuna_app_id=g("ADZUNA_APP_ID"),
            adzuna_app_key=g("ADZUNA_APP_KEY"),
            adzuna_country=g("ADZUNA_COUNTRY", "gb"),
            adzuna_pages=int(g("ADZUNA_PAGES", "3") or "3"),
            careerjet_affid=g("CAREERJET_AFFID"),
            careerjet_locale=g("CAREERJET_LOCALE", "en_GB"),
            careerjet_referer=g("CAREERJET_REFERER", "http://localhost"),
            jooble_key=g("JOOBLE_API_KEY"),
            reed_key=g("REED_API_KEY"),
            findwork_key=g("FINDWORK_API_KEY"),
            web3career_key=g("WEB3CAREER_API_KEY"),
            usajobs_key=g("USAJOBS_KEY"),
            usajobs_email=g("USAJOBS_EMAIL"),
            serpapi_key=g("SERPAPI_KEY"),
            serpapi_max_terms=int(g("SERPAPI_MAX_TERMS", "4") or "4"),
            serpapi_max_locations=int(g("SERPAPI_MAX_LOCATIONS", "2") or "2"),
            jsearch_key=g("JSEARCH_API_KEY"),
            france_travail_id=g("FRANCE_TRAVAIL_ID"),
            france_travail_secret=g("FRANCE_TRAVAIL_SECRET"),
            jobtech_enabled=(g("JOBTECH_ENABLED", "true").lower() in ("1", "true", "yes")),
            google_sa_file=g("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"),
            google_sheet_id=g("GOOGLE_SHEET_ID"),
            google_drive_folder_id=g("GOOGLE_DRIVE_FOLDER_ID"),
            smtp_host=g("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(g("SMTP_PORT", "587") or "587"),
            smtp_user=g("SMTP_USER"),
            smtp_password=g("SMTP_PASSWORD"),
            email_from=g("EMAIL_FROM") or g("SMTP_USER"),
            email_to=g("EMAIL_TO"),
        )

    def service_account_path(self) -> Path:
        p = Path(self.google_sa_file)
        return p if p.is_absolute() else ROOT / p
