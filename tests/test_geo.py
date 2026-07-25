"""Per-user geo derivation — the public product serves every country."""

import pytest

from jobhunter import geo
from jobhunter.config import Profile


def _p(locations):
    return Profile(raw={"locations": locations})


@pytest.mark.parametrize(
    "locations, expected",
    [
        # Regression: Adzuna country was a global env default, so US users got
        # Italian jobs. It must follow the profile.
        (["New York", "Remote-US"], ["us"]),
        (["Milan", "Turin", "Remote-EU", "Remote-Italy"], ["it"]),
        (["London", "Remote-UK"], ["gb"]),
        (["Remote-US", "Remote-EU", "Berlin"], ["us", "de"]),   # order preserved
        (["United States"], ["us"]),
        (["Milan, Italy"], ["it"]),                              # "City, Country"
        (["Remote-Anywhere"], []),                               # nothing resolvable
        (["Atlantis"], []),                                      # unknown → skipped
        ([], []),
    ],
)
def test_countries_follow_the_profile(locations, expected):
    assert geo.countries(_p(locations)) == expected


def test_countries_are_capped():
    locs = ["New York", "London", "Berlin", "Paris", "Madrid"]
    assert geo.countries(_p(locs), limit=2) == ["us", "gb"]


def test_countries_only_returns_adzuna_supported():
    # Every returned code must be a real Adzuna endpoint.
    for loc in ["New York", "Tokyo", "Lagos", "Milan"]:
        for code in geo.countries(_p([loc])):
            assert code in geo.ADZUNA_COUNTRIES


@pytest.mark.parametrize(
    "locations, expected",
    [
        (["New York"], "en_US"),
        (["Milan"], "it_IT"),
        (["Berlin"], "de_DE"),
        (["Paris"], "fr_FR"),
        (["London"], "en_GB"),
        (["Remote-Anywhere"], "en_GB"),      # falls back to default
    ],
)
def test_careerjet_locale_follows_country(locations, expected):
    assert geo.careerjet_locale(_p(locations)) == expected


@pytest.mark.parametrize(
    "token, loc, present",
    [
        ("United States", "austin, tx", True),      # a US city is an alias
        ("United States", "houston", False),         # unlisted city: no alias
        ("Italy", "milano", True),
        ("us", "houston", False),                    # short code never an alias
        ("Germany", "berlin", True),
    ],
)
def test_match_aliases_avoids_short_substring_traps(token, loc, present):
    aliases = geo.match_aliases(token)
    assert any(a in loc for a in aliases) is present
    assert "us" not in aliases and "uk" not in aliases   # never bare codes


@pytest.mark.parametrize(
    "loc, token, expected",
    [
        ("milan, italy", "United States", True),     # names Italy
        ("london", "United States", True),           # names UK
        ("houston", "United States", False),         # names no other country
        ("berlin", "Italy", True),                   # names Germany
        ("remote", "Italy", False),
    ],
)
def test_names_other_country(loc, token, expected):
    assert geo.names_other_country(loc, token) is expected


def test_usajobs_skips_non_us_searches():
    """USAJOBS must not burn a call for a user with no US intent."""
    from jobhunter.config import Settings
    from jobhunter.sources.keyed import _usajobs

    s = Settings(usajobs_key="x", usajobs_email="a@b.com")
    # No US in the profile → returns immediately without a network call.
    assert _usajobs(_p(["Milan", "Remote-EU"]), s) == []
