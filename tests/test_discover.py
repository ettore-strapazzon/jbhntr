"""Tests for company discovery: seed loading and the companies.yaml writer.

The LLM suggestion step and live board probing are not exercised here (they
need an API key and network); the logic around them is.
"""

from jobhunter.config import load_companies, load_seeds
from jobhunter.discover import _slugify, write_companies_yaml


def _v(name, ats, token, jobs=5, why=""):
    return {"name": name, "ats": ats, "token": token, "jobs": jobs, "why": why}


def _c(name):
    return {"name": name, "slug": name.lower(), "domain": "", "why": ""}


def test_suggest_merges_web_and_model_knowledge(monkeypatch):
    """Web research and model knowledge are UNIONED (deduped), so an empty
    extraction no longer drops the whole round — the fix for '[C] extract -> 0'
    silently discarding everything."""
    from jobhunter import discover as dm
    from jobhunter import llm
    from jobhunter.config import Profile, Settings

    monkeypatch.setattr(dm, "research", lambda *a, **k: "notes naming companies")
    monkeypatch.setattr(dm, "extract_companies", lambda *a, **k: [_c("WebCo"), _c("Shared")])

    class FakeClient:
        supports_web_search = True
        def json(self, **kw):
            return {"companies": [_c("Shared"), _c("ModelCo")]}
        def text(self, **kw):
            return "notes"
    monkeypatch.setattr(llm, "get_client", lambda s: FakeClient())

    out = dm.suggest(Profile(), Settings(), 5, exemplars=[], exclude=[], web_search=True)
    assert sorted(c["name"] for c in out) == ["ModelCo", "Shared", "WebCo"]   # Shared once

    # Even when web extraction returns nothing, model knowledge still carries.
    monkeypatch.setattr(dm, "extract_companies", lambda *a, **k: [])
    out2 = dm.suggest(Profile(), Settings(), 5, exemplars=[], exclude=[], web_search=True)
    assert sorted(c["name"] for c in out2) == ["ModelCo", "Shared"]


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


# ----------------------------- Exa (Lane C) ---------------------------- #
import contextlib


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _fake_exa_http(payload=None, status=200, capture=None, boom=False):
    """A stand-in for sources.base.http_client whose .post yields `payload`."""
    class _Client:
        def post(self, url, headers=None, json=None):
            if capture is not None:
                capture.update(url=url, headers=headers, json=json)
            if boom:
                raise RuntimeError("network down")
            return _FakeResp(payload or {}, status)

    @contextlib.contextmanager
    def _cm(*a, **k):
        yield _Client()
    return _cm


def _exa_settings(**kw):
    from jobhunter.config import Settings
    return Settings(exa_api_key="k", **kw)


def test_exa_find_similar_maps_results(monkeypatch, tmp_path):
    from jobhunter.sources import exa
    monkeypatch.setattr(exa, "USAGE_FILE", tmp_path / "u.json")
    payload = {"results": [
        {"url": "https://satispay.com", "title": "Satispay | Mobile payments"},
        {"url": "https://scalapay.com/", "title": "Scalapay - Buy now, pay later"},
    ]}
    monkeypatch.setattr(exa, "http_client", _fake_exa_http(payload))
    out = exa.find_similar(_exa_settings(), "https://stripe.com", n=10)
    assert [c["domain"] for c in out] == ["satispay.com", "scalapay.com"]
    assert out[0]["name"] == "Satispay"          # title cleaned to the company part
    assert out[0]["slug"] == "satispay"
    assert all(c["source_hint"] == "exa" for c in out)


def test_exa_excludes_domains_client_and_server_side(monkeypatch, tmp_path):
    from jobhunter.sources import exa
    monkeypatch.setattr(exa, "USAGE_FILE", tmp_path / "u.json")
    cap: dict = {}
    payload = {"results": [{"url": "https://a.com", "title": "A"},
                           {"url": "https://b.com", "title": "B"}]}
    monkeypatch.setattr(exa, "http_client", _fake_exa_http(payload, capture=cap))
    out = exa.find_similar(_exa_settings(), "https://seed.com", exclude_domains=["a.com"])
    assert [c["domain"] for c in out] == ["b.com"]        # a.com filtered locally
    assert "a.com" in cap["json"]["excludeDomains"]       # and asked of Exa
    assert cap["headers"]["x-api-key"] == "k"             # key sent as header


def test_exa_fails_soft_on_network_error(monkeypatch, tmp_path):
    from jobhunter.sources import exa
    monkeypatch.setattr(exa, "USAGE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(exa, "http_client", _fake_exa_http(boom=True))
    assert exa.find_similar(_exa_settings(), "https://x.com") == []


def test_exa_disabled_without_key():
    from jobhunter.config import Settings
    from jobhunter.sources import exa
    assert exa.is_configured(Settings()) is False
    assert exa.find_similar(Settings(), "https://x.com") == []


def test_exa_monthly_budget_blocks_further_calls(monkeypatch, tmp_path):
    from jobhunter.sources import exa
    monkeypatch.setattr(exa, "USAGE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(exa, "http_client", _fake_exa_http({"results": []}))
    s = _exa_settings(exa_monthly_budget_usd=exa.COST_PER_SEARCH_USD)  # room for one
    exa.find_similar(s, "https://x.com")
    assert exa._searches_this_month() == 1
    exa.find_similar(s, "https://y.com")           # budget reached -> short-circuit
    assert exa._searches_this_month() == 1         # second call was never billed


def test_suggest_uses_exa_and_skips_llm_when_enough(monkeypatch):
    from jobhunter import discover as dm
    from jobhunter.config import Profile, Settings
    from jobhunter.sources import exa as exa_mod

    monkeypatch.setattr(exa_mod, "is_configured", lambda s: True)
    monkeypatch.setattr(dm, "_exa_candidates",
                        lambda *a, **k: [_c("ExaCo1"), _c("ExaCo2"), _c("ExaCo3")])

    def _boom(*a, **k):
        raise AssertionError("the LLM round must be skipped when Exa is enough")
    monkeypatch.setattr(dm, "research", _boom)

    out = dm.suggest(Profile(), Settings(), 4, exemplars=[], exclude=[],
                     web_search=True, seed_domains=["stripe.com"])
    assert sorted(c["name"] for c in out) == ["ExaCo1", "ExaCo2", "ExaCo3"]
    assert all(c["source_hint"] == "exa" for c in out)


def test_suggest_falls_back_to_llm_when_exa_thin(monkeypatch):
    from jobhunter import discover as dm
    from jobhunter import llm
    from jobhunter.config import Profile, Settings
    from jobhunter.sources import exa as exa_mod

    monkeypatch.setattr(exa_mod, "is_configured", lambda s: True)
    monkeypatch.setattr(dm, "_exa_candidates", lambda *a, **k: [_c("ExaCo")])
    monkeypatch.setattr(dm, "research", lambda *a, **k: "notes")
    monkeypatch.setattr(dm, "extract_companies", lambda *a, **k: [_c("WebCo")])

    class FakeClient:
        supports_web_search = True
        def json(self, **kw): return {"companies": [_c("ModelCo")]}
        def text(self, **kw): return "notes"
    monkeypatch.setattr(llm, "get_client", lambda s: FakeClient())

    out = dm.suggest(Profile(), Settings(), 6, exemplars=[], exclude=[],
                     web_search=True, seed_domains=["stripe.com"])
    # n=6 needs >=3 fresh from Exa; only 1 -> LLM round runs too, unioned.
    assert sorted(c["name"] for c in out) == ["ExaCo", "ModelCo", "WebCo"]
    hints = {c["name"]: c["source_hint"] for c in out}
    assert hints["ExaCo"] == "exa" and hints["WebCo"] == "llm" and hints["ModelCo"] == "llm"
