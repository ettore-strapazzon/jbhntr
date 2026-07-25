"""Tests for company discovery: seed loading and the companies.yaml writer.

The LLM suggestion step and live board probing are not exercised here (they
need an API key and network); the logic around them is.
"""

from jobhunter.config import load_companies, load_seeds
from jobhunter.discover import _slugify, write_companies_yaml


def _v(name, ats, token, jobs=5, why=""):
    return {"name": name, "ats": ats, "token": token, "jobs": jobs, "why": why}


# ------------------------------- writer -------------------------------- #
def test_writes_new_file_with_verified_companies(tmp_path):
    p = tmp_path / "companies.yaml"
    added = write_companies_yaml([_v("Figma", "greenhouse", "figma")], p)
    assert added == 1
    assert load_companies(p) == [
        {"name": "Figma", "ats": "greenhouse", "token": "figma"}
    ]


def test_appends_without_dropping_existing(tmp_path):
    p = tmp_path / "companies.yaml"
    write_companies_yaml([_v("Figma", "greenhouse", "figma")], p)
    added = write_companies_yaml([_v("Linear", "ashby", "linear")], p)
    assert added == 1
    assert {c["token"] for c in load_companies(p)} == {"figma", "linear"}


def test_skips_companies_already_present(tmp_path):
    p = tmp_path / "companies.yaml"
    write_companies_yaml([_v("Figma", "greenhouse", "figma")], p)
    added = write_companies_yaml(
        [_v("Figma", "greenhouse", "figma"), _v("Linear", "ashby", "linear")], p
    )
    assert added == 1  # only Linear is new
    assert len(load_companies(p)) == 2


def test_upgrades_empty_placeholder_list(tmp_path):
    """`companies: []` must become a real list, not produce invalid YAML."""
    p = tmp_path / "companies.yaml"
    p.write_text("# header\ncompanies: []\n", encoding="utf-8")
    write_companies_yaml([_v("Figma", "greenhouse", "figma")], p)
    assert load_companies(p) == [
        {"name": "Figma", "ats": "greenhouse", "token": "figma"}
    ]


def test_writes_into_a_seeds_only_file(tmp_path):
    """A file with seeds but no companies: key must still gain the list."""
    p = tmp_path / "companies.yaml"
    p.write_text("seeds:\n  - Stripe\n", encoding="utf-8")
    write_companies_yaml([_v("Figma", "greenhouse", "figma")], p)
    assert load_seeds(p) == ["Stripe"]
    assert load_companies(p) == [
        {"name": "Figma", "ats": "greenhouse", "token": "figma"}
    ]


def test_why_comment_does_not_corrupt_yaml(tmp_path):
    p = tmp_path / "companies.yaml"
    write_companies_yaml(
        [_v("Figma", "greenhouse", "figma", why="design tool: uses python & go")], p
    )
    assert load_companies(p) == [
        {"name": "Figma", "ats": "greenhouse", "token": "figma"}
    ]


# -------------------------------- seeds -------------------------------- #
def test_load_seeds_missing_file(tmp_path):
    assert load_seeds(tmp_path / "nope.yaml") == []


def test_load_seeds_empty_placeholder(tmp_path):
    p = tmp_path / "companies.yaml"
    p.write_text("seeds: []\ncompanies: []\n", encoding="utf-8")
    assert load_seeds(p) == []


def test_load_seeds_reads_names(tmp_path):
    p = tmp_path / "companies.yaml"
    p.write_text("seeds:\n  - Stripe\n  - Datadog\ncompanies: []\n", encoding="utf-8")
    assert load_seeds(p) == ["Stripe", "Datadog"]


def test_slugify_normalizes_company_names():
    assert _slugify("Back Market") == "backmarket"
    assert _slugify("1Komma5°") == "1komma5"
    assert _slugify("") == ""
