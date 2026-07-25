"""Tests for pipeline helpers."""

from jobhunter.config import Materials, Profile, Settings
from jobhunter.matcher import Matcher
from jobhunter.models import JobPosting
from jobhunter.pipeline import _interleave_by_source


def test_score_counts_jobs_it_could_not_judge(monkeypatch, caplog):
    """A run cut short by API errors must not look like 'found nothing'."""
    import jobhunter.llm as llm

    calls = {"n": 0}

    class Client:
        def json(self, **kw):
            calls["n"] += 1
            if calls["n"] % 2:
                raise RuntimeError("402 insufficient credits")
            return {"tier": 3, "tier_label": "Possible", "score": 50,
                    "reasons": "ok", "tags": []}

    monkeypatch.setattr(llm, "get_client", lambda s: Client())
    m = Matcher(Settings())
    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(4)]
    with caplog.at_level("WARNING"):
        out = m.score(jobs, Profile(raw={}), Materials())

    assert len(out) == 2
    assert m.failures == 2
    assert "INCOMPLETE" in caplog.text


def _jobs(source, n):
    return [JobPosting(source=source, title=f"{source}-{i}") for i in range(n)]


def test_interleave_spreads_sources_across_the_prefix():
    """A small --limit must not sample only the first source."""
    jobs = _jobs("adzuna", 5) + _jobs("linkedin", 5) + _jobs("arbeitnow", 5)
    out = _interleave_by_source(jobs)
    # The first 3 must cover all 3 sources, not 3x adzuna.
    assert {j.source for j in out[:3]} == {"adzuna", "linkedin", "arbeitnow"}


def test_interleave_keeps_every_job():
    jobs = _jobs("a", 3) + _jobs("b", 7) + _jobs("c", 1)
    out = _interleave_by_source(jobs)
    assert len(out) == 11
    assert {j.title for j in out} == {j.title for j in jobs}


def test_interleave_handles_uneven_sources():
    """A source running out early must not stall or drop the rest."""
    jobs = _jobs("big", 6) + _jobs("small", 1)
    out = _interleave_by_source(jobs)
    assert len(out) == 7
    assert out[0].source == "big"
    assert out[1].source == "small"
    assert all(j.source == "big" for j in out[2:])


def test_interleave_single_source_is_unchanged():
    jobs = _jobs("only", 4)
    assert [j.title for j in _interleave_by_source(jobs)] == [j.title for j in jobs]


def test_interleave_empty():
    assert _interleave_by_source([]) == []
