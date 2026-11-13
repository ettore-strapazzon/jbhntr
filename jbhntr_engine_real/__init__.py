"""jbhntr_engine_real — the REAL engine backend behind the ``jbhntr_engine`` façade.

PRIVATE (open-core split). After step 4 this package + ``jobhunter/`` ship as
the private ``jbhntr-engine`` dist (see ``scripts/build_engine_wheel.py``); the
public repo keeps only ``jbhntr_engine`` (contract + selector) and
``jbhntr_engine_demo``. The shell never imports this module directly — it asks
``jbhntr_engine`` for a name and the selector resolves it here.

Every callable below delegates to its engine module **at call time**, so a
monkeypatch on ``jobhunter.<module>.<fn>`` (the engine's own tests and the
shell's tests both do this) is honoured exactly as before the façade existed.
Private engine helpers the shell used to reach into (``_slugify``,
``_is_generic_remote``, ``keyed._careerjet``…, ``FETCHERS``) get stable public
façade names here and stay private inside the engine.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from jobhunter import candidate as _candidate
from jobhunter import criteria as _criteria
from jobhunter import dedup as _dedup
from jobhunter import discover as _discover
from jobhunter import embeddings, geo, llm  # capability namespaces (re-exported)
from jobhunter import generator as _generator
from jobhunter import matcher as _matcher
from jobhunter import seeds as _seeds
from jobhunter import sources as _sources
from jobhunter import tags as _tags
from jobhunter.sources import agency_hints as _agency
from jobhunter.sources import ats as _ats
from jobhunter.sources import base as _base
from jobhunter.sources import boards as _boards
from jobhunter.sources import browser_sniff as _browser
from jobhunter.sources import careers_scrape as _careers
from jobhunter.sources import keyed as _keyed

from . import llm_tasks as _tasks
from . import panel as _panel
from . import recover as _recover
from . import vision as _vision

ENGINE_KIND = "real"


def _late(module: Any, attr: str) -> Callable:
    """A function that looks ``module.attr`` up on every call (patch-friendly)."""
    target = getattr(module, attr)

    @functools.wraps(target)
    def call(*args, **kwargs):
        return getattr(module, attr)(*args, **kwargs)

    return call


# --- candidate / criteria / scoring / generation ---------------------------- #
derive_candidate = _late(_candidate, "derive")
derive_company_profile = _late(_candidate, "derive_company_profile")
derive_criteria = _late(_criteria, "derive")
Matcher = _matcher.Matcher
PROMPT_VERSION = _matcher.PROMPT_VERSION
Generator = _generator.Generator

# --- filtering + tagging ----------------------------------------------------- #
prefilter = _late(_dedup, "prefilter")
cap_per_company = _late(_dedup, "cap_per_company")
is_generic_remote = _late(_dedup, "_is_generic_remote")
deterministic_tags = _late(_tags, "deterministic_tags")
remote_mode = _late(_tags, "remote_mode")

# --- seeds + sources --------------------------------------------------------- #
resolve_seeds = _late(_seeds, "resolve")
collect_all_sources = _late(_sources, "collect_all")
AGGREGATORS = _sources.AGGREGATORS                  # name -> fetch(profile, settings)
BOARD_NAMES = tuple(_boards.BOARDS)
fetch_boards = _late(_boards, "fetch")
KEYED_PROVIDERS: dict[str, Callable] = {
    name: _late(_keyed, attr) for name, attr in (
        ("careerjet", "_careerjet"), ("reed", "_reed"), ("web3career", "_web3career"),
        ("usajobs", "_usajobs"), ("jsearch", "_jsearch"), ("serpapi", "_serpapi"),
        ("francetravail", "_francetravail"), ("jobtech", "_jobtech"),
        ("bundesagentur", "_bundesagentur"),
    )
}
KEYED_MAX_TERMS = _keyed.MAX_TERMS
http_client = _late(_base, "http_client")
strip_html = _late(_base, "strip_html")

# --- company ATS boards ------------------------------------------------------ #
ATS_FETCHERS = _ats.FETCHERS                        # ats -> fetch(token, name)
parse_ats_job = _late(_ats, "parse_ats_job")
board_location_index = _late(_ats, "board_location_index")
enrich_description = _late(_ats, "enrich_description")

# --- company discovery ------------------------------------------------------- #
discover_companies = _late(_discover, "discover")
discover_suggest = _late(_discover, "suggest")
discover_research = _late(_discover, "research")
discover_extract_companies = _late(_discover, "extract_companies")
verify_company = _late(_discover, "verify")
company_slug = _late(_discover, "_slugify")

# --- careers pages, staffing agencies, rendered portals ---------------------- #
scrape_careers = _late(_careers, "scrape_careers")
AGENCY_HINTS = _agency.AGENCY_HINTS
agency_hint_for = _late(_agency, "hint_for")
agency_domain_for = _late(_agency, "domain_for")
agency_is_ignored = _late(_agency, "is_ignored")
browser_configured = _late(_browser, "is_configured")
browser_fetch_portal = _late(_browser, "fetch_portal")
browser_debug_portal = _late(_browser, "debug_portal")

# --- engine-side helpers carved out of web/app/services ---------------------- #
recover_apply_url = _late(_recover, "recover_apply_url")
panel_deliberate = _late(_panel, "deliberate")
vision_style = _late(_vision, "vision_style")
resolve_countries = _late(_tasks, "resolve_countries")
translate_terms = _late(_tasks, "translate_terms")
extract_posting = _late(_tasks, "extract_posting")
