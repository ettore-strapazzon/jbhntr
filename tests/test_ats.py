"""Tests for ATS (company career page) detection and company-list loading."""

import pytest

from jobhunter.config import load_companies
from jobhunter.sources.ats import FETCHERS, detect


def test_detect_reads_the_board_out_of_an_embedded_careers_page(monkeypatch):
    """Most companies host careers on their own domain and embed the board.

    URL parsing alone wrote off 23 of 30 seed companies, Kraken included.
    """
    import jobhunter.sources.ats as A

    monkeypatch.setattr(
        A, "_sniff",
        lambda url: "https://jobs.ashbyhq.com/kraken" if "careers" in url else "",
    )
    assert detect("https://www.kraken.com/careers") == ("ashby", "kraken")


def test_detect_handles_the_greenhouse_embed_form(monkeypatch):
    """Greenhouse embeds carry the token in the query string, not the path."""
    import jobhunter.sources.ats as A

    monkeypatch.setattr(
        A, "_sniff",
        lambda url: "https://boards.greenhouse.io/embed/job_board?for=acme",
    )
    assert detect("https://acme.com/careers") == ("greenhouse", "acme")


def test_detect_does_not_touch_the_network_when_the_url_is_enough(monkeypatch):
    import jobhunter.sources.ats as A

    def boom(url):
        raise AssertionError("should not have fetched")

    monkeypatch.setattr(A, "_sniff", boom)
    assert detect("https://boards.greenhouse.io/acme") == ("greenhouse", "acme")


def test_detect_probe_can_be_disabled(monkeypatch):
    import jobhunter.sources.ats as A

    monkeypatch.setattr(A, "_sniff", lambda url: "https://jobs.lever.co/x")
    assert detect("https://acme.com/careers", probe=False) == ("", "")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://boards.greenhouse.io/figma", ("greenhouse", "figma")),
        ("https://job-boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://jobs.lever.co/plaid", ("lever", "plaid")),
        ("https://jobs.lever.co/plaid/", ("lever", "plaid")),
        ("https://jobs.ashbyhq.com/linear", ("ashby", "linear")),
        ("https://acme.recruitee.com", ("recruitee", "acme")),
        ("https://apply.workable.com/nomadic", ("workable", "nomadic")),
        ("https://jobs.smartrecruiters.com/Visa", ("smartrecruiters", "Visa")),
        ("https://acme.jobs.personio.de", ("personio", "acme")),
        (
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
            ("workday", "nvidia:wd5:NVIDIAExternalCareerSite"),
        ),
        (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
            ("workday", "nvidia:wd5:NVIDIAExternalCareerSite"),
        ),
        ("https://skedulo.bamboohr.com/careers", ("bamboohr", "skedulo")),
    ],
)
def test_detect_known_ats_urls(url, expected):
    assert detect(url) == expected


def test_workday_token_roundtrip():
    from jobhunter.sources.ats import _split_workday_token

    assert _split_workday_token("nvidia:wd5:Site") == ("nvidia", "wd5", "Site")
    assert _split_workday_token("broken") == ("", "", "")


def test_workday_fetcher_rejects_malformed_token():
    from jobhunter.sources.ats import _workday

    with pytest.raises(ValueError):
        _workday("X", "not-a-valid-token")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/careers",
        "https://acme.com/jobs",
        "not-a-url",
        "",
    ],
)
def test_detect_returns_empty_for_unknown(url):
    # probe=False keeps this a pure URL-parsing check — otherwise it would make
    # a live network call to each made-up domain and hang.
    assert detect(url, probe=False) == ("", "")


def test_every_detectable_ats_has_a_fetcher():
    """Detection must never return a platform we can't actually fetch."""
    for url in [
        "https://boards.greenhouse.io/x",
        "https://jobs.lever.co/x",
        "https://jobs.ashbyhq.com/x",
        "https://x.recruitee.com",
        "https://apply.workable.com/x",
        "https://jobs.smartrecruiters.com/x",
        "https://x.jobs.personio.de",
        "https://x.wd1.myworkdayjobs.com/Careers",
        "https://x.bamboohr.com/careers",
    ]:
        ats, _ = detect(url)
        assert ats in FETCHERS, f"{ats} detected but has no fetcher"


def test_load_companies_missing_file_returns_empty(tmp_path):
    assert load_companies(tmp_path / "nope.yaml") == []


def test_load_companies_accepts_strings_and_dicts(tmp_path):
    p = tmp_path / "companies.yaml"
    p.write_text(
        "companies:\n"
        "  - https://jobs.lever.co/acme\n"
        "  - name: Beta\n"
        "    ats: greenhouse\n"
        "    token: beta\n",
        encoding="utf-8",
    )
    got = load_companies(p)
    assert got == [
        {"careers_url": "https://jobs.lever.co/acme"},
        {"name": "Beta", "ats": "greenhouse", "token": "beta"},
    ]


def test_load_companies_empty_list(tmp_path):
    p = tmp_path / "companies.yaml"
    p.write_text("companies: []\n", encoding="utf-8")
    assert load_companies(p) == []
