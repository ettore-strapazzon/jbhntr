"""Tests for the dedup 'seen' store and the pre-filter."""

import pytest

from jobhunter.config import Profile
from jobhunter.dedup import cap_per_company


def _job(company, i=0, title=None):
    from jobhunter.models import JobPosting

    return JobPosting(source="s", title=title or f"role-{company}-{i}", company=company)


@pytest.mark.parametrize(
    "pref, loc, keep",
    [
        # A country preference matches its cities, keeps unattributable cities,
        # and rejects clearly-other-country locations.
        ("United States", "Austin, TX", True),
        ("United States", "Houston", True),           # unlisted US city
        ("United States", "Milan, Italy", False),     # names Italy
        ("United States", "London", False),           # names UK
        ("Italy", "Milano", True),
        ("Italy", "Berlin", False),                   # earlier leak stays closed
        ("Germany", "Frankfurt", True),
        # Bare short country codes must be caught as whole words (the reported
        # leak: an Italy filter let a "UK" posting through).
        ("Italy", "UK", False),
        ("Italy", "US", False),
        ("Italy", "London, UK", False),
        ("United States", "UK", False),               # names UK
        ("United States", "US", True),                # own code, kept
        ("Italy", "Milan, IT", True),                 # own code (ambiguous short) still via city
        ("United States", "Houston TX US", True),     # own bare code, still kept
        ("Italy", "Houston", True),                   # "us" NOT a word here -> not rejected
    ],
)
def test_prefilter_country_matching(pref, loc, keep):
    from jobhunter.dedup import prefilter
    from jobhunter.models import JobPosting

    p = Profile(raw={"locations": [pref]})
    assert prefilter(JobPosting(source="s", title="x", location=loc), p) is keep


@pytest.mark.parametrize(
    "loc, keep",
    [
        # Reported leaks: US city+state, Hong Kong, a UK town+county, all past an
        # Italy-only filter. Must now be rejected.
        ("Clearwater, FL", False),
        ("Austin, TX", False),
        ("Hong Kong", False),
        ("Liss, Hampshire", False),
        ("Fraserburgh, UK", False),
        ("Dubai", False),
        # Italian cities (incl. ones only just added) must stay.
        ("Milano", True),
        ("Bergamo", True),
        ("Verona", True),
        ("La Spezia", True),          # "la" is NOT a mapped state code (would false-reject)
        ("Italy", True),
        ("", True),                    # blank -> matcher decides
    ],
)
def test_italy_filter_rejects_foreign_cities(loc, keep):
    """Regression for the audit finding: FL / Hong Kong / UK-county postings were
    ranking for an onsite Italy user."""
    from jobhunter.dedup import prefilter
    from jobhunter.models import JobPosting
    p = Profile(raw={"locations": ["Italy"]})
    assert prefilter(JobPosting(source="s", title="x", location=loc), p) is keep


@pytest.mark.parametrize(
    "loc, keep",
    [
        ("Clearwater, FL", True),      # US user keeps US cities+states
        ("Austin, TX", True),
        ("Boston, MA", True),
        ("Houston", True),
        ("Milan, Italy", False),       # ...but not an Italian one
    ],
)
def test_us_filter_keeps_us_states(loc, keep):
    from jobhunter.dedup import prefilter
    from jobhunter.models import JobPosting
    p = Profile(raw={"locations": ["United States"]})
    assert prefilter(JobPosting(source="s", title="x", location=loc), p) is keep


@pytest.mark.parametrize(
    "loc, remote, keep",
    [
        # A global corpus must not leak US jobs into an Italy / Remote-EU search.
        ("Canal Street, Manhattan", False, False),   # US onsite city
        ("Saint Petersburg, FL", True, False),       # US remote city
        ("USA", True, False),                        # US remote
        ("Remote - US", True, False),
        ("Berlin (remote)", True, True),             # EU city, remote -> OK
        ("Remote, Europe", True, True),
        ("Anywhere in the World", True, True),        # location-agnostic remote
        ("Milano, Italy", False, True),
        ("Torino", False, True),                      # target city, onsite
    ],
)
def test_corpus_geo_does_not_leak_foreign_jobs(loc, remote, keep):
    """Regression: cities of another country slipped past the city/remote gate."""
    from jobhunter.dedup import prefilter
    from jobhunter.models import JobPosting

    p = Profile(raw={"locations": ["Milan", "Turin", "Remote-EU", "Remote-Italy"]})
    j = JobPosting(source="s", title="x", location=loc, is_remote=remote)
    assert prefilter(j, p) is keep


def test_cap_per_company_limits_a_prolific_employer():
    """One company posting hundreds of roles must not own the shortlist."""
    jobs = [_job("Tether", i) for i in range(30)] + [_job("Satispay", i) for i in range(4)]
    out = cap_per_company(jobs, limit=10)
    assert sum(1 for j in out if j.company == "Tether") == 10
    assert sum(1 for j in out if j.company == "Satispay") == 4


def test_cap_per_company_keeps_the_best_titles_not_the_first():
    """Blind truncation would discard the one job the candidate wants."""
    jobs = [_job("Tether", i, title=f"Software Engineer {i}") for i in range(9)]
    jobs.append(_job("Tether", 99, title="Chief of Staff"))     # last in source order
    out = cap_per_company(jobs, limit=2, terms=["chief of staff", "head of strategy"])
    assert "Chief of Staff" in [j.title for j in out]
    assert len(out) == 2


def test_cap_per_company_falls_back_to_source_order_without_terms():
    jobs = [_job("Acme", 0), _job("ACME", 1), _job("acme", 2)]
    out = cap_per_company(jobs, limit=2)
    assert [j.title for j in out] == ["role-Acme-0", "role-ACME-1"]


@pytest.mark.parametrize(
    "title, terms, expected",
    [
        ("Chief of Staff", ["chief of staff"], 1.0),          # exact phrase
        ("Senior Chief of Staff, EMEA", ["chief of staff"], 1.0),
        ("Head of Strategy", ["chief of staff", "head of strategy"], 1.0),
        ("Strategy Manager", ["head of strategy"], 0.5),      # partial overlap
        ("Warehouse Picker", ["chief of staff"], 0.0),
        ("Anything", [], 0.0),
        ("", ["chief of staff"], 0.0),
    ],
)
def test_title_relevance_ranks_by_overlap(title, terms, expected):
    from jobhunter.dedup import title_relevance

    assert title_relevance(_job("X", title=title), terms) == expected


def test_cap_per_company_never_drops_unknown_employers():
    """A blank company is not evidence of flooding — keep them all."""
    jobs = [_job("", i) for i in range(25)]
    assert len(cap_per_company(jobs, limit=10)) == 25
from jobhunter.dedup import SeenStore, filter_new_and_relevant, prefilter
from jobhunter.models import JobPosting


def make_profile(**overrides) -> Profile:
    raw = {
        "keywords_must": ["python", "backend"],
        "locations": ["Milan", "Remote-EU"],
    }
    raw.update(overrides)
    return Profile(raw=raw)


def job(title="Backend Engineer", desc="We use python and go", company="Acme",
        location="Milan", url=""):
    return JobPosting(source="s", title=title, description=desc,
                      company=company, location=location, url=url)


# --------------------------- keyword gate --------------------------- #
def test_prefilter_requires_a_must_keyword():
    p = make_profile()
    assert prefilter(job(title="Backend Engineer", desc="python"), p) is True
    assert prefilter(job(title="Sales Manager", desc="quotas and CRM"), p) is False


def test_prefilter_no_must_keywords_configured_passes_keyword_gate():
    p = make_profile(keywords_must=[])
    assert prefilter(job(title="Anything", desc="whatever"), p) is True


# --------------------------- location gate --------------------------- #
def test_target_city_matches():
    p = make_profile()
    assert prefilter(job(location="Milan, Italy"), p) is True


def test_remote_eu_keeps_european_remote():
    p = make_profile()
    assert prefilter(job(location="Europe, remote"), p) is True
    # An on-site Berlin role does NOT satisfy "Remote-EU" — see the regression
    # tests below for why this changed.
    assert prefilter(job(location="Berlin, Germany"), p) is False


def test_remote_eu_drops_wrong_region_remote_even_if_body_says_remote():
    p = make_profile()
    j = job(location="Brazil", desc="fully remote python backend role")
    assert prefilter(j, p) is False


def test_remote_region_does_not_match_onsite_jobs_in_that_region():
    """Regression: 'Remote-EU' must mean a REMOTE job, not any EU job.

    Berlin/Lisbon/London office roles were leaking through a Remote-EU
    preference simply because those countries are in the EU.
    """
    p = make_profile(locations=["Italy", "Remote-EU", "Remote-Italy"])
    for loc in ("Berlin, Germany", "Lisbon, Portugal", "London, UK", "Paris, France"):
        assert prefilter(job(location=loc), p) is False, loc


def test_remote_region_keeps_genuinely_remote_jobs():
    p = make_profile(locations=["Italy", "Remote-EU"])
    assert prefilter(job(location="Remote"), p) is True
    assert prefilter(job(location="Berlin (remote)"), p) is True
    assert prefilter(job(location="Anywhere in the World"), p) is True


def test_remote_only_source_flag_is_respected():
    """Remote boards often say just 'Europe' with no mention of 'remote'."""
    p = make_profile(locations=["Italy", "Remote-EU"])
    j = job(location="Europe, UK, Germany")
    assert prefilter(j, p) is False          # no flag, reads as an on-site list
    j.is_remote = True                        # ...but the source knows better
    assert prefilter(j, p) is True


def test_target_cities_still_match_onsite_jobs():
    """Naming a city means you WILL travel there — on-site is fine."""
    p = make_profile(locations=["Italy", "Remote-EU"])
    assert prefilter(job(location="Milan, Italy"), p) is True
    assert prefilter(job(location="Torino, Italia"), p) is True


def test_looks_remote_uses_flag_or_wording():
    assert JobPosting(source="s", title="X", location="Remote").looks_remote()
    assert JobPosting(source="s", title="X", location="Berlin",
                      is_remote=True).looks_remote()
    assert not JobPosting(source="s", title="X", location="Berlin").looks_remote()


def test_generic_remote_with_no_country_is_kept():
    p = make_profile()
    assert prefilter(job(location="Remote"), p) is True
    assert prefilter(job(location="Worldwide"), p) is True


def test_missing_location_is_kept_for_matcher_to_judge():
    p = make_profile()
    assert prefilter(job(location=""), p) is True


def test_no_locations_configured_skips_location_gate():
    p = make_profile(locations=[])
    assert prefilter(job(location="Mars"), p) is True


# --------------------------- seen store --------------------------- #
def test_seen_store_is_new_then_marked(tmp_path):
    store = SeenStore(db_path=tmp_path / "seen.sqlite")
    j = job(url="https://x.co/jobs/1")
    assert store.is_new(j) is True
    store.mark(j)
    store.commit()
    assert store.is_new(j) is False
    store.close()


def test_filter_dedupes_within_run_and_drops_seen(tmp_path):
    store = SeenStore(db_path=tmp_path / "seen.sqlite")
    p = make_profile()
    j1 = job(url="https://x.co/jobs/1")
    j1_dup = job(url="https://x.co/jobs/1?utm=y")  # same canonical url
    j2 = job(title="Backend Engineer", company="Beta", url="https://x.co/jobs/2")

    out = filter_new_and_relevant([j1, j1_dup, j2], p, store)
    assert len(out) == 2  # duplicate collapsed

    # Mark them, then a second pass yields nothing new.
    for j in out:
        store.mark(j)
    store.commit()
    out2 = filter_new_and_relevant([j1, j2], p, store)
    assert out2 == []
    store.close()
