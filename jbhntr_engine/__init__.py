"""jbhntr_engine — THE façade between the public shell and the matching engine.

Open-core split, REPO_SPLIT_EXECUTION_PLAN §4 (steps 1-3, in-repo). The shell
(``web/``) may import engine functionality ONLY as top-level names of this
package: ``from jbhntr_engine import Matcher``. Never a submodule, never
``jobhunter.*``, never ``jbhntr_engine_real``/``jbhntr_engine_demo`` directly.
``tests/test_engine_boundary.py`` enforces this.

Two kinds of names live here:

* **Contract** (public, defined in this package, importable without any engine):
  the wire types (``JobPosting``, ``MatchResult``, ``RankedJob``, tier helpers)
  and the engine config objects (``Settings``, ``Profile``, ``Materials``).
* **Backend API** (``BACKEND_API`` below): resolved lazily, on first use, from
  whichever engine backend is selected —

  - ``jbhntr_engine_real`` — the private engine (sources, prompts, ranking,
    ingestion, discovery). Ships in the private ``jbhntr-engine`` dist after
    step 4; in this repo it wraps ``jobhunter/``.
  - ``jbhntr_engine_demo`` — the public, deterministic demo engine: canned
    postings, keyword scoring, no network, no prompts.

Selection (``JBHNTR_ENGINE`` env var, default ``auto``):

  ``auto`` → the real engine if it imports, else the demo engine **with a
  recorded fallback reason** (a silent fallback is exactly what the boot guard
  refuses in production); ``real`` → the real engine or a loud ImportError;
  ``demo`` → the demo engine (dev / tests / the public repo).

``ENGINE_KIND`` is taken from the backend module that actually loaded — it is
not read from the environment, so an env var can't make a demo build claim to
be real. Production needs no new env var: ``auto`` resolves to the real engine.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from .settings import Materials, Profile, Settings, load_companies
from .types import TIER_LABELS, JobPosting, MatchResult, RankedJob, tier_for_score

log = logging.getLogger("jbhntr.engine")

ENGINE_ENV_VAR = "JBHNTR_ENGINE"
_MODES = ("auto", "real", "demo")
_REAL_MODULE = "jbhntr_engine_real"
_DEMO_MODULE = "jbhntr_engine_demo"

# The contract both backends implement. Adding a name here is a contract change:
# add it to BOTH backends (tests/test_engine_boundary.py checks parity).
BACKEND_API: tuple[str, ...] = (
    "ENGINE_KIND",
    # capability namespaces (the shell uses only the attributes listed in
    # NAMESPACE_API — the boundary test checks the shell stays inside them)
    "llm", "geo", "embeddings",
    # candidate / criteria / scoring / generation
    "derive_candidate", "derive_company_profile", "derive_criteria",
    "Matcher", "PROMPT_VERSION", "Generator",
    # filtering + tagging
    "prefilter", "cap_per_company", "is_generic_remote",
    "deterministic_tags", "remote_mode",
    # seeds + sources
    "resolve_seeds", "collect_all_sources", "AGGREGATORS",
    "BOARD_NAMES", "fetch_boards", "KEYED_PROVIDERS", "KEYED_MAX_TERMS",
    "http_client", "strip_html",
    # company ATS boards
    "ATS_FETCHERS", "parse_ats_job", "board_location_index", "enrich_description",
    # company discovery
    "discover_companies", "discover_suggest", "discover_research",
    "discover_extract_companies", "verify_company", "company_slug",
    # careers pages, staffing agencies, rendered portals
    "scrape_careers", "AGENCY_HINTS", "agency_hint_for", "agency_domain_for",
    "agency_is_ignored", "browser_configured", "browser_fetch_portal",
    "browser_debug_portal",
    # engine-side helpers carved out of web/app/services (step 1 placement)
    "recover_apply_url", "panel_deliberate", "vision_style",
    "resolve_countries", "translate_terms", "extract_posting",
)

# Attributes the shell may use on the capability namespaces.
NAMESPACE_API: dict[str, tuple[str, ...]] = {
    "llm": ("SCORING", "GENERATION", "get_client", "is_configured"),
    "geo": ("country_of",),
    "embeddings": ("is_configured", "model_name", "embed", "embed_one", "cosine"),
}

__all__ = [
    "JobPosting", "MatchResult", "RankedJob", "TIER_LABELS", "tier_for_score",
    "Settings", "Profile", "Materials", "load_companies",
    "ENGINE_ENV_VAR", "ENGINE_SELECTED_BY", "ENGINE_FALLBACK_REASON",
    "engine_problems", "selected_mode",
    *BACKEND_API,
]

_backend: Any = None
ENGINE_SELECTED_BY = ""        # "auto" | "config" — set when the backend resolves
ENGINE_FALLBACK_REASON = ""    # non-empty only for an auto fallback to demo


def selected_mode(environ: dict | None = None) -> str:
    """The configured mode (auto|real|demo). An unknown value is a loud error."""
    raw = ((environ if environ is not None else os.environ).get(ENGINE_ENV_VAR) or "auto")
    mode = raw.strip().lower() or "auto"
    if mode not in _MODES:
        raise ValueError(f"{ENGINE_ENV_VAR}={raw!r} is not one of {', '.join(_MODES)}")
    return mode


def _resolve(environ: dict | None = None):
    """Import the selected backend. Returns (module, selected_by, fallback_reason)."""
    mode = selected_mode(environ)
    if mode == "demo":
        return importlib.import_module(_DEMO_MODULE), "config", ""
    if mode == "real":
        return importlib.import_module(_REAL_MODULE), "config", ""
    try:
        return importlib.import_module(_REAL_MODULE), "auto", ""
    except ImportError as exc:
        reason = f"{type(exc).__name__}: {exc}"
        log.warning("Real engine not importable (%s) — falling back to the DEMO engine. "
                    "Production refuses to boot like this.", reason)
        return importlib.import_module(_DEMO_MODULE), "auto", reason


def _load():
    global _backend, ENGINE_SELECTED_BY, ENGINE_FALLBACK_REASON
    if _backend is None:
        mod, by, reason = _resolve()
        ENGINE_SELECTED_BY, ENGINE_FALLBACK_REASON = by, reason
        _backend = mod
    return _backend


def __getattr__(name: str) -> Any:   # PEP 562: lazy backend resolution
    if name in BACKEND_API:
        value = getattr(_load(), name)
        # Cache the binding. Callables in the real backend delegate to the engine
        # module at call time, so test monkeypatches on jobhunter.* still apply.
        globals()[name] = value
        return value
    raise AttributeError(f"module 'jbhntr_engine' has no attribute {name!r}")


def engine_problems() -> list[str]:
    """Boot-guard input: problems that must block a production boot.

    Empty when the real engine is active. Any non-real engine (an explicit demo
    or an auto fallback) is a problem — the web lifespan and the cron entrypoint
    raise on it when ``DEBUG`` is off, and only log it in dev/tests. A backend
    that fails to import at all is reported here too, not swallowed.
    """
    try:
        backend = _load()
    except Exception as exc:  # explicit `real` that can't import, bad mode value
        return [f"engine failed to load ({type(exc).__name__}: {exc})"]
    kind = getattr(backend, "ENGINE_KIND", "")
    if kind == "real":
        return []
    why = (f"silent fallback — {ENGINE_FALLBACK_REASON}" if ENGINE_FALLBACK_REASON
           else f"{ENGINE_ENV_VAR}={selected_mode()}")
    return [f"engine is {kind or 'unknown'!r}, not 'real' ({why}); "
            "production requires the private engine"]
