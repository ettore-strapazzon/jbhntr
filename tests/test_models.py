"""Tests for the core data models."""

from jobhunter.models import JobPosting, MatchResult, RankedJob


def test_two_directional_score_fields():
    from jobhunter.matcher import MATCH_SCHEMA
    req = MATCH_SCHEMA["required"]
    assert "fit_role" in req and "fit_candidate" in req
    m = MatchResult(tier=1, score=90, fit_role=95, fit_candidate=88, reasons="x")
    assert m.fit_role == 95 and m.fit_candidate == 88
    # older cached/LLM output without them defaults to 0 (falls back to one bar)
    assert MatchResult(tier=3, score=50, reasons="x").fit_role == 0


def test_null_string_fields_are_coerced_not_rejected():
    """A feed sending an explicit null (Findwork's `role`) must not crash."""
    j = JobPosting(source="api:findwork", title=None, company=None,
                   location=None, description=None, url=None, salary_text=None)
    assert j.title == "" and j.company == "" and j.location == ""
    assert j.description == "" and j.url == "" and j.salary_text == ""


def test_same_job_from_different_sources_collapses():
    """The same role posted to 3 boards is ONE job, despite 3 different URLs."""
    linkedin = JobPosting(source="linkedin", title="Chief of Staff", company="Acme",
                          location="Milan, Lombardy, Italy",
                          url="https://linkedin.com/jobs/view/1")
    adzuna = JobPosting(source="adzuna", title="Chief of Staff", company="Acme",
                        location="Milano, Provincia di Milano",
                        url="https://adzuna.it/details/999")
    own_board = JobPosting(source="ats:lever:Acme", title="chief of staff  ",
                           company="ACME", location="Milan",
                           url="https://jobs.lever.co/acme/abc")
    assert linkedin.dedup_key() == adzuna.dedup_key() == own_board.dedup_key()
    assert linkedin.dedup_key().startswith("ct:")


def test_different_roles_at_same_company_stay_separate():
    a = JobPosting(source="s", title="Chief of Staff", company="Acme")
    b = JobPosting(source="s", title="Head of Strategy", company="Acme")
    assert a.dedup_key() != b.dedup_key()


def test_same_title_at_different_companies_stays_separate():
    a = JobPosting(source="s", title="Chief of Staff", company="Acme")
    b = JobPosting(source="s", title="Chief of Staff", company="Beta")
    assert a.dedup_key() != b.dedup_key()


def test_missing_company_falls_back_to_url():
    """Without a company, identical titles must not merge into one job."""
    a = JobPosting(source="s", title="Chief of Staff", url="https://x.co/1")
    b = JobPosting(source="s", title="Chief of Staff", url="https://x.co/2")
    assert a.dedup_key() != b.dedup_key()
    assert a.dedup_key().startswith("url:")


def test_short_id_is_stable_and_short():
    j = JobPosting(source="s", title="Chief of Staff", company="Acme")
    assert j.short_id() == j.short_id()
    assert len(j.short_id()) == 8
    # Same job from another source shares the id, which is what makes
    # `python -m jobhunter.apply <id>` unambiguous.
    other = JobPosting(source="other", title="Chief of Staff", company="Acme")
    assert j.short_id() == other.short_id()


def test_match_result_and_ranked_roundtrip():
    m = MatchResult(tier=1, score=88, reasons="fits well", role="Backend Eng")
    r = RankedJob(job=JobPosting(source="s", title="X"), match=m)
    assert r.match.tier == 1
    assert r.tailored is False
    assert r.cv_link == ""
    assert r.documents == {}


def test_five_tiers_are_labelled():
    from jobhunter.models import TIER_LABELS

    assert set(TIER_LABELS) == {1, 2, 3, 4, 5}
    assert MatchResult(tier=1, score=90, reasons="x").tier_label == "Excellent"
    assert MatchResult(tier=5, score=5, reasons="x").tier_label == "No"


def test_match_result_carries_tags():
    m = MatchResult(tier=2, score=70, reasons="x", tags=["fintech", "founder-adjacent"])
    assert m.tags == ["fintech", "founder-adjacent"]
    assert MatchResult(tier=2, score=70, reasons="x").tags == []
