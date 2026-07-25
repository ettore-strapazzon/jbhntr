"""Tests for seed parsing (name vs website) and the web-search fallback."""

import pytest

from jobhunter import discover as D
from jobhunter import seeds as S


# ------------------------------- parsing ------------------------------- #
@pytest.mark.parametrize(
    "raw, name, domain",
    [
        ("https://satispay.com", "Satispay", "satispay.com"),
        ("http://satispay.com/", "Satispay", "satispay.com"),
        ("satispay.com", "Satispay", "satispay.com"),
        ("www.back-market.com", "Back Market", "back-market.com"),
        ("https://linear.app/", "Linear", "linear.app"),
        ("https://sub.example.co.uk", "Sub", "sub.example.co.uk"),
    ],
)
def test_website_seeds_are_parsed(raw, name, domain):
    s = S.parse(raw)
    assert (s.name, s.domain) == (name, domain)


@pytest.mark.parametrize("raw", ["Stripe", "Back Market", "1Komma5"])
def test_plain_names_stay_names(raw):
    s = S.parse(raw)
    assert s.name == raw
    assert s.domain == ""


def test_slug_prefers_domain_over_name():
    assert S.parse("https://back-market.com").slug() == "backmarket"
    assert S.parse("Back Market").slug() == "backmarket"


def test_label_includes_domain_and_blurb():
    s = S.parse("satispay.com")
    assert s.label() == "Satispay (satispay.com)"
    s.blurb = "payments app"
    assert s.label() == "Satispay (satispay.com) — payments app"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("https://x.com", True),
        ("x.com", True),
        ("sub.x.co.uk", True),
        ("Stripe", False),
        ("Back Market", False),
        ("", False),
    ],
)
def test_looks_like_url(text, expected):
    assert S.looks_like_url(text) is expected


def test_resolve_without_enrichment_does_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        S, "_scrape_blurb", lambda d: pytest.fail("should not fetch")
    )
    out = S.resolve(["https://example.com", "Stripe"], enrich=False)
    assert [s.name for s in out] == ["Example", "Stripe"]


def test_resolve_skips_blank_seeds():
    assert S.resolve(["", "  ", "Stripe"], enrich=False)[0].name == "Stripe"


# --------------------------- search fallback --------------------------- #
class _FakeLLM:
    """Stand-in LLM client returning a fixed company list."""

    def __init__(self, payload, supports_web_search=True):
        self.payload = payload
        self.supports_web_search = supports_web_search
        self.json_calls = 0

    def json(self, **kw):
        self.json_calls += 1
        return self.payload

    def text(self, **kw):  # pragma: no cover - not used in these tests
        return ""


def test_suggest_falls_back_to_knowledge_when_search_fails(monkeypatch):
    """A web-search failure must never abort discovery."""
    calls = {}

    def boom(*a, **k):
        calls["research"] = True
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(D, "research", boom)
    fake = _FakeLLM({"companies": [
        {"name": "Acme", "slug": "acme", "domain": "acme.com", "why": "fits"}
    ]})
    monkeypatch.setattr(D.llm, "get_client", lambda s: fake)

    from jobhunter.config import Profile, Settings

    got = D.suggest(Profile(raw={}), Settings(), 5, [], [], web_search=True)
    assert calls == {"research": True}      # search was attempted...
    assert fake.json_calls == 1             # ...then the knowledge path ran
    assert got[0]["name"] == "Acme"


def test_suggest_skips_search_when_disabled(monkeypatch):
    monkeypatch.setattr(
        D, "research", lambda *a, **k: pytest.fail("should not research")
    )
    monkeypatch.setattr(D.llm, "get_client", lambda s: _FakeLLM({"companies": []}))

    from jobhunter.config import Profile, Settings

    assert D.suggest(Profile(raw={}), Settings(), 5, [], [], web_search=False) == []


def test_suggest_skips_search_when_provider_cannot_search(monkeypatch):
    """Providers without web search fall back silently, not fatally."""
    monkeypatch.setattr(
        D, "research", lambda *a, **k: pytest.fail("provider cannot search")
    )
    fake = _FakeLLM({"companies": []}, supports_web_search=False)
    monkeypatch.setattr(D.llm, "get_client", lambda s: fake)

    from jobhunter.config import Profile, Settings

    assert D.suggest(Profile(raw={}), Settings(), 5, [], [], web_search=True) == []
    assert fake.json_calls == 1
