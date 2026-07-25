"""Tests for the derived candidate profile and the (now optional) keyword gate."""

from jobhunter import candidate as C
from jobhunter.config import Materials, Profile
from jobhunter.dedup import prefilter
from jobhunter.matcher import _system_prompt, _triage_system_prompt
from jobhunter.models import JobPosting


def _job(title="Chief of Staff", desc="Own cross-functional priorities", company="Acme",
         location="Milan"):
    return JobPosting(source="s", title=title, description=desc, company=company,
                      location=location)


# --------------------------- no hard keyword gate --------------------------- #
def test_prefilter_keeps_jobs_when_no_keywords_configured():
    """The default profile must not drop jobs on wording."""
    p = Profile(raw={"locations": ["Milan"]})
    # None of these contain a 'must' word — all must survive.
    assert prefilter(_job(title="Strategic Projects Lead"), p) is True
    assert prefilter(_job(title="Head of Special Projects"), p) is True
    assert prefilter(_job(title="Business Operations Manager"), p) is True


def test_synonym_wording_is_not_dropped_by_default():
    """A backend role advertised only as 'server-side' must survive."""
    p = Profile(raw={"locations": ["Milan"]})
    job = _job(title="Server-side Engineer", desc="Django services at scale")
    assert prefilter(job, p) is True


def test_keyword_gate_still_available_when_explicitly_set():
    p = Profile(raw={"locations": ["Milan"], "keywords_must": ["python"]})
    assert prefilter(_job(desc="we use python"), p) is True
    assert prefilter(_job(desc="we use ruby"), p) is False


# ------------------------------- Candidate ---------------------------------- #
def test_candidate_empty_by_default():
    assert C.Candidate().is_empty() is True


def test_candidate_prompt_block_includes_all_signals():
    c = C.Candidate(
        headline="Operator who scales startups",
        target_roles=["Chief of Staff", "Head of Strategy"],
        skills=["strategy", "ops"],
        domains=["fintech"],
        seniority="director",
        avoid=["frontend engineering"],
    )
    block = c.as_prompt_block()
    assert "Chief of Staff" in block
    assert "Clearly NOT a fit: frontend engineering" in block
    assert "Seniority: director" in block
    assert c.is_empty() is False


def test_fingerprint_changes_when_materials_change():
    p = Profile(raw={"objective": "x"})
    a = C._fingerprint(p, Materials(base_cv="one"))
    b = C._fingerprint(p, Materials(base_cv="two"))
    assert a != b


def test_fingerprint_changes_when_objective_changes():
    m = Materials(base_cv="same")
    a = C._fingerprint(Profile(raw={"objective": "x"}), m)
    b = C._fingerprint(Profile(raw={"objective": "y"}), m)
    assert a != b


def test_derive_without_api_key_returns_empty(tmp_path, monkeypatch):
    from jobhunter.config import Settings

    monkeypatch.setattr(C, "CACHE_PATH", tmp_path / "cand.json")
    got = C.derive(Profile(raw={}), Materials(), Settings(anthropic_api_key=""))
    assert got.is_empty()


# ------------------------------ triage prompt -------------------------------- #
def test_triage_prompt_prefers_derived_profile_over_keywords():
    p = Profile(raw={"keywords_nice": ["excel"]})
    c = C.Candidate(headline="Operator", target_roles=["Chief of Staff"], skills=["ops"])
    prompt = _triage_system_prompt(p, c)
    assert "Chief of Staff" in prompt
    assert "Relevant skills: excel" not in prompt  # derived block wins


def test_triage_prompt_falls_back_to_keywords_when_no_derived_profile():
    p = Profile(raw={"keywords_nice": ["excel"]})
    prompt = _triage_system_prompt(p, C.Candidate())
    assert "Relevant skills: excel" in prompt


def test_triage_prompt_instructs_semantic_matching():
    prompt = _triage_system_prompt(Profile(raw={}), None)
    assert "meaning, not keywords" in prompt


# --------------------------- company profile ---------------------------- #
def _company_profile():
    return C.CompanyProfile(
        headline="European fintech and crypto scaleups",
        stage="Series B-D",
        size="50-500 employees",
        sectors=["fintech", "crypto"],
        geographies=["Italy", "EU"],
        traits=["VC-backed", "EU-regulated"],
        anti_traits=["legacy banks", "bootstrapped lifestyle businesses"],
    )


def test_company_profile_empty_by_default():
    assert C.CompanyProfile().is_empty() is True
    assert _company_profile().is_empty() is False


def test_company_profile_prompt_block_includes_traits_and_anti_traits():
    block = _company_profile().as_prompt_block()
    assert "Series B-D" in block
    assert "Shared traits: VC-backed; EU-regulated" in block
    assert "Rules out: legacy banks" in block


def test_company_profile_reaches_the_scoring_prompt():
    prompt = _system_prompt(
        Profile(raw={}), Materials(), [], _company_profile()
    )
    assert "kind of company the candidate wants" in prompt
    assert "legacy banks" in prompt


def test_company_profile_reaches_the_triage_prompt():
    prompt = _triage_system_prompt(
        Profile(raw={}), C.Candidate(), _company_profile()
    )
    assert "Preferred kind of company" in prompt
    assert "European fintech and crypto scaleups" in prompt


def test_prompts_omit_company_section_when_no_seeds():
    """No seeds must not leave an empty, confusing section in the prompt."""
    assert "kind of company" not in _system_prompt(
        Profile(raw={}), Materials(), [], C.CompanyProfile()
    )
    assert "Preferred kind of company" not in _triage_system_prompt(
        Profile(raw={}), C.Candidate(), C.CompanyProfile()
    )


def test_derive_company_profile_no_seeds_returns_empty():
    from jobhunter.config import Settings

    assert C.derive_company_profile([], Settings()).is_empty()


def test_derive_company_profile_without_api_key_returns_empty(tmp_path, monkeypatch):
    from jobhunter.config import Settings

    monkeypatch.setattr(C, "COMPANY_CACHE_PATH", tmp_path / "cp.json")
    got = C.derive_company_profile(["Acme (acme.com)"], Settings(anthropic_api_key=""))
    assert got.is_empty()


def test_salary_rule_tells_model_undisclosed_is_neutral():
    prompt = _system_prompt(
        Profile(raw={"salary_floor_eur": 90000}), Materials(), []
    )
    assert "NEUTRAL" in prompt
    assert "explicitly stated AND falls below the floor" in prompt
