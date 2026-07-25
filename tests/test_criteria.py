"""Tests for the criteria/tag vocabulary and the board registry."""

import pytest

from jobhunter.config import Profile, Settings
from jobhunter.criteria import Criteria, derive
from jobhunter.sources import boards


def _criteria():
    return Criteria(
        must_have=[
            {"tag": "ceo-adjacent", "description": "Works with the CEO"},
            {"tag": "post-pmf", "description": "Has product-market fit"},
        ],
        nice_have=[
            {"tag": "italy-based", "description": "Based in Italy"},
            {"tag": "crypto-native", "description": "Crypto company"},
        ],
    )


def test_all_tags_and_must_tags():
    c = _criteria()
    assert c.all_tags() == ["ceo-adjacent", "post-pmf", "italy-based", "crypto-native"]
    assert c.must_tags() == {"ceo-adjacent", "post-pmf"}


def test_prompt_block_lists_both_groups():
    block = _criteria().as_prompt_block()
    assert "MUST-HAVE criteria:" in block
    assert "[ceo-adjacent] Works with the CEO" in block
    assert "NICE-TO-HAVE criteria:" in block


@pytest.mark.parametrize(
    "tags, min_must, min_nice, expected",
    [
        (["ceo-adjacent", "italy-based"], 1, 1, True),   # 1 must + 1 nice
        (["ceo-adjacent"], 1, 1, False),                  # no nice
        (["italy-based"], 1, 1, False),                   # no must
        (["ceo-adjacent", "post-pmf", "italy-based"], 2, 1, True),
        (["ceo-adjacent", "italy-based"], 2, 1, False),   # only 1 must
        ([], 0, 0, True),                                 # bar disabled
        (["unknown-tag", "ceo-adjacent", "crypto-native"], 1, 1, True),
    ],
)
def test_qualifies_threshold_rule(tags, min_must, min_nice, expected):
    assert _criteria().qualifies(tags, min_must, min_nice) is expected


def test_empty_criteria():
    assert Criteria().is_empty() is True
    assert _criteria().is_empty() is False


def test_derive_without_api_key_returns_empty(tmp_path, monkeypatch):
    import jobhunter.criteria as C

    monkeypatch.setattr(C, "CACHE_PATH", tmp_path / "criteria.json")
    assert derive(Profile(raw={}), [], Settings()).is_empty()


# ------------------------------- boards --------------------------------- #
def test_every_board_has_required_config():
    for name, cfg in boards.BOARDS.items():
        assert cfg["type"] in ("rss", "json"), name
        assert cfg["url"].startswith("https://"), name
        assert cfg.get("vertical"), name
        if cfg["type"] == "json":
            assert "map" in cfg and "title" in cfg["map"], name


@pytest.mark.parametrize(
    "raw, fmt, title, company",
    [
        ("Senior DeFi BD at Re7 Capital", "role_at_company", "Senior DeFi BD", "Re7 Capital"),
        ("Coinbase: Product Marketing Manager", "company_colon_role",
         "Product Marketing Manager", "Coinbase"),
        ("Plain Title", "role_at_company", "Plain Title", ""),
        ("Plain Title", None, "Plain Title", ""),
        # "at" inside the role must not split early — we take the LAST " at ".
        ("Engineer at Scale at Acme", "role_at_company", "Engineer at Scale", "Acme"),
    ],
)
def test_split_title(raw, fmt, title, company):
    assert boards._split_title(raw, fmt) == (title, company)


def test_unavailable_boards_are_documented():
    """Blocked boards stay listed with a reason so they aren't re-added."""
    assert "cryptojobslist.com" in boards.UNAVAILABLE
    assert all(reason for reason in boards.UNAVAILABLE.values())


@pytest.mark.parametrize(
    "description, expected",
    [
        ("This is a full-time position that is 100% remote with no geographical "
         "restrictions.", "Remote, Worldwide"),
        ("We are fully remote across Europe.", "Remote"),
        ("Our team is based in Milan and we are growing.", "Milan"),
        ("A great opportunity for a motivated person.", ""),
        ("", ""),
    ],
)
def test_location_inferred_from_description(description, expected):
    """Regression: feeds with no location field bypassed the location filter."""
    assert boards._location_from_description(description) == expected


def test_geography_specific_board_has_a_default_location():
    """Berlin Startup Jobs listings are Berlin even though the feed omits it."""
    assert boards.BOARDS["berlinstartupjobs"]["default_location"] == "Berlin, Germany"


# ------------------------------- adzuna --------------------------------- #
@pytest.mark.parametrize(
    "locations, expected",
    [
        # Regression: "Italy" on the country-scoped /it/ endpoint returned zero.
        (["Italy", "Remote-EU", "Remote-Italy"], ""),
        # Wants remote as well, so pinning to Milan would drop Remote-Italy jobs.
        (["Milan", "Turin", "Remote-EU"], ""),
        (["Milan", "Turin"], ""),          # two cities: can't express, search wide
        (["Milan"], "Milan"),              # unambiguous: narrow
        (["Italy", "Milan"], "Milan"),
        (["Remote-Italy"], ""),
        ([], ""),
        (["Europe"], ""),
    ],
)
def test_adzuna_where_narrows_only_when_unambiguous(locations, expected):
    from jobhunter.sources import adzuna

    assert adzuna._where(Profile(raw={"locations": locations}), "it") == expected


def test_unknown_board_is_skipped_not_fatal(caplog):
    p = Profile(raw={"sources": {"boards": ["does-not-exist"]}})
    assert boards.fetch(p, Settings()) == []


# --------------------------- json field digging -------------------------- #
def test_dig_reads_nested_fields():
    obj = {"company": {"name": "Acme"}, "refs": {"landing_page": "https://x"}}
    assert boards._dig(obj, "company.name") == "Acme"
    assert boards._dig(obj, "refs.landing_page") == "https://x"
    assert boards._dig(obj, "missing.path") == ""
    assert boards._dig(obj, "company.missing") == ""


@pytest.mark.parametrize(
    "job, mapping, expected",
    [
        ({"jobGeo": "Italy"}, {"location": "jobGeo"}, "Italy"),
        ({"locs": ["Europe", "UK"]}, {"location_list": "locs"}, "Europe, UK"),
        ({"locations": [{"name": "Milan, Italy"}]},
         {"location_list_of_dicts": "locations"}, "Milan, Italy"),
        ({"arbeitsort": {"ort": "Berlin", "region": "Berlin"}},
         {"location_nested": "arbeitsort"}, "Berlin, Berlin"),
        ({}, {"location": "nope"}, ""),
    ],
)
def test_location_normalisation_across_shapes(job, mapping, expected):
    assert boards._location_from(job, mapping) == expected


def test_query_placeholders_expand_from_profile(monkeypatch):
    """{search}/{location} must be filled from the profile, not left literal."""
    seen = []

    def fake_fetch_one(name, cfg):
        seen.append(cfg["url"])
        return []

    monkeypatch.setattr(boards, "_fetch_one", fake_fetch_one)
    p = Profile(raw={
        "locations": ["Remote-EU", "Milan"],
        "sources": {"search_terms": ["chief of staff", "head of strategy"]},
    })
    boards._fetch_with_queries(
        "x", {"type": "json", "url": "https://api/?q={search}&l={location}"}, p
    )
    assert seen == [
        "https://api/?q=chief%20of%20staff&l=Milan",   # skips the Remote- token
        "https://api/?q=head%20of%20strategy&l=Milan",
    ]


def test_board_without_placeholders_is_fetched_once(monkeypatch):
    calls = []
    monkeypatch.setattr(boards, "_fetch_one", lambda n, c: calls.append(c["url"]) or [])
    boards._fetch_with_queries(
        "x", {"type": "rss", "url": "https://api/feed"}, Profile(raw={})
    )
    assert calls == ["https://api/feed"]
