"""Deterministic job tags (no AI) used by the shared corpus."""

import pytest

from jobhunter.models import JobPosting
from jobhunter.tags import deterministic_tags, remote_mode, salary_range


def _job(**kw):
    return JobPosting(source="s", title=kw.pop("title", "x"), **kw)


@pytest.mark.parametrize(
    "kw, expected",
    [
        ({"title": "Engineer (Hybrid)"}, "hybrid"),
        ({"description": "This is a hybrid role, 2 days in office"}, "hybrid"),
        ({"is_remote": True}, "remote"),
        ({"location": "Remote - EU"}, "remote"),
        ({"description": "Fully remote, work from home"}, "remote"),
        ({"location": "Milan, Italy", "description": "on-site role"}, "onsite"),
        # A posting naming a real place with no remote/hybrid signal is inferred
        # on-site (was "unknown" — most of the corpus).
        ({"location": "Milan, Italy"}, "onsite"),
        ({"location": ""}, "unknown"),                 # no place at all -> unknown
        # Hybrid wins even when the ad also says remote.
        ({"description": "hybrid / remote flexible"}, "hybrid"),
    ],
)
def test_remote_mode(kw, expected):
    assert remote_mode(_job(**kw)) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("50000-70000", (50000, 70000)),
        ("$90k - $120k", (90000, 120000)),
        ("€45.000", (45000, 45000)),
        ("", (None, None)),
        ("competitive", (None, None)),
        ("Req 2024, id 4501", (None, None)),   # stray numbers below the floor / noise
        ("120000", (120000, 120000)),
    ],
)
def test_salary_range(text, expected):
    assert salary_range(_job(salary_text=text)) == expected


def test_deterministic_tags_shape():
    j = _job(title="Chief of Staff", location="Austin, TX, US",
             salary_text="150000-200000", is_remote=False)
    t = deterministic_tags(j)
    assert t["countries"] == ["us"]
    assert t["remote_mode"] == "onsite"       # names Austin -> inferred on-site
    assert t["salary_min"] == 150000 and t["salary_max"] == 200000
    assert t["has_salary"] is True


def test_deterministic_tags_undisclosed_salary_is_neutral():
    t = deterministic_tags(_job(location="Milan, Italy"))
    assert t["countries"] == ["it"]
    assert t["has_salary"] is False
    assert t["salary_min"] is None
