"""Tests for the key-gated aggregator APIs.

The live calls can't be tested without keys; what matters here is that the
module stays inert until a key exists, activates the right provider when one
does, and never lets a provider failure break a run.
"""

import pytest

from jobhunter.config import Profile, Settings
from jobhunter.sources import keyed


@pytest.mark.parametrize(
    "locations, expected",
    [
        # A country subsumes its cities and covers remote-from-there, so it
        # must outrank a city when only a couple of searches are billed.
        (["Milan", "Turin", "Remote-EU", "Remote-Italy"], ["Italy", "Milan", "Turin"]),
        (["Remote-EU"], []),                 # names no searchable country
        (["Remote-Anywhere", "Remote-Worldwide"], []),
        (["Milan"], ["Milan"]),
        (["Remote-Italy", "Italy"], ["Italy"]),   # de-duplicated
        ([], []),
    ],
)
def test_cities_prefers_countries_and_drops_generic_remote(locations, expected):
    from jobhunter.sources.keyed import _cities

    assert _cities(Profile(raw={"locations": locations})) == expected


def test_no_keys_means_no_providers_and_no_calls():
    s = Settings()
    assert keyed.configured(s) == []
    assert keyed.fetch(Profile(raw={}), s) == []


@pytest.mark.parametrize(
    "attr, expected",
    [
        ("careerjet_affid", "careerjet"),
        ("jooble_key", "jooble"),
        ("reed_key", "reed"),
        ("findwork_key", "findwork"),
        ("web3career_key", "web3career"),
        ("serpapi_key", "serpapi"),
        ("jsearch_key", "jsearch"),
    ],
)
def test_each_key_activates_its_provider(attr, expected):
    assert keyed.configured(Settings(**{attr: "k"})) == [expected]


def test_multiple_keys_activate_in_order():
    s = Settings(jooble_key="a", serpapi_key="b", reed_key="c")
    assert keyed.configured(s) == ["jooble", "reed", "serpapi"]


def test_a_failing_provider_does_not_break_the_run(monkeypatch):
    def boom(profile, settings):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(keyed, "PROVIDERS", [("jooble_key", boom)])
    # Must return cleanly rather than propagating.
    assert keyed.fetch(Profile(raw={}), Settings(jooble_key="k")) == []


def test_only_keyed_providers_are_called(monkeypatch):
    called = []

    def a(p, s):
        called.append("a")
        return []

    def b(p, s):
        called.append("b")
        return []

    monkeypatch.setattr(keyed, "PROVIDERS", [("jooble_key", a), ("reed_key", b)])
    keyed.fetch(Profile(raw={}), Settings(jooble_key="k"))
    assert called == ["a"]


# --------------------------- query construction -------------------------- #
def test_cities_skips_remote_tokens():
    p = Profile(raw={"locations": ["Remote-EU", "Milan", "Remote-US", "Turin"]})
    assert keyed._cities(p) == ["Milan", "Turin"]


def test_terms_are_capped_to_bound_cost():
    p = Profile(raw={"sources": {"search_terms": [f"t{i}" for i in range(20)]}})
    assert len(keyed._terms(p)) == keyed.MAX_TERMS


def test_terms_fall_back_when_none_configured():
    assert keyed._terms(Profile(raw={})) == ["chief of staff"]


def test_serpapi_search_count_is_bounded_by_settings():
    """SerpApi bills per search, so terms x locations must stay capped."""
    s = Settings(serpapi_key="k", serpapi_max_terms=3, serpapi_max_locations=2)
    p = Profile(raw={
        "locations": ["Milan", "Turin", "Genoa", "Remote-EU"],
        "sources": {"search_terms": ["a", "b", "c", "d", "e"]},
    })
    expected = min(len(keyed._terms(p)), s.serpapi_max_terms) * min(
        len(keyed._cities(p)), s.serpapi_max_locations
    )
    assert expected == 6  # 3 terms x 2 locations, not 5 x 4
