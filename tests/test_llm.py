"""Tests for the provider-agnostic LLM layer."""

import json

import pytest

from jobhunter import llm
from jobhunter.config import Settings


@pytest.fixture(autouse=True)
def _clear_client_cache():
    llm.reset_clients()
    yield
    llm.reset_clients()


def _openrouter_settings(**kw):
    base = dict(
        llm_provider="openai_compatible",
        llm_base_url="https://openrouter.ai/api/v1",
        llm_api_key="sk-or-test",
        scoring_model="anthropic/claude-haiku-4.5",
        generation_model="anthropic/claude-sonnet-4.5",
    )
    base.update(kw)
    return Settings(**base)


# ------------------------------ selection ------------------------------ #
def test_defaults_to_anthropic():
    s = Settings(anthropic_api_key="sk-ant-x")
    assert isinstance(llm.get_client(s), llm.AnthropicClient)


def test_openai_compatible_selected_by_provider():
    assert isinstance(llm.get_client(_openrouter_settings()), llm.OpenAICompatibleClient)


@pytest.mark.parametrize("alias", ["openai", "openrouter", "openai_compatible"])
def test_provider_aliases(alias):
    s = _openrouter_settings(llm_provider=alias)
    assert isinstance(llm.get_client(s), llm.OpenAICompatibleClient)


def test_unknown_provider_raises():
    with pytest.raises(llm.LLMError):
        llm.get_client(Settings(llm_provider="nope"))


def test_missing_api_key_raises_clear_error():
    with pytest.raises(llm.LLMError, match="LLM_API_KEY"):
        llm.get_client(Settings(llm_provider="openai_compatible"))


def test_missing_model_raises_clear_error():
    s = _openrouter_settings(scoring_model="")
    with pytest.raises(llm.LLMError, match="JOBHUNTER_SCORING_MODEL"):
        llm.get_client(s)._model(llm.SCORING)


# --------------------------- is_configured ----------------------------- #
def test_is_configured_anthropic():
    assert llm.is_configured(Settings(anthropic_api_key="k")) is True
    assert llm.is_configured(Settings()) is False


def test_is_configured_openai_compatible():
    assert llm.is_configured(_openrouter_settings()) is True
    assert llm.is_configured(Settings(llm_provider="openai_compatible")) is False


# ---------------------------- web search ------------------------------- #
def test_anthropic_supports_web_search():
    assert llm.get_client(Settings(anthropic_api_key="k")).supports_web_search is True


def test_openrouter_supports_web_search_but_others_do_not():
    assert llm.get_client(_openrouter_settings()).supports_web_search is True
    mistral = _openrouter_settings(llm_base_url="https://api.mistral.ai/v1")
    assert llm.get_client(mistral).supports_web_search is False


def test_online_suffix_added_for_openrouter_search(monkeypatch):
    """OpenRouter exposes live search by suffixing the model with ':online'."""
    used = {}

    class FakeCompletions:
        def create(self, **kw):
            used["model"] = kw["model"]
            class M:
                content = "notes"
            class C:
                message = M()
            class R:
                choices = [C()]
            return R()

    client = llm.get_client(_openrouter_settings())
    client.client.chat.completions = FakeCompletions()

    client.text(user="find companies", web_search=True)
    assert used["model"].endswith(":online")

    client.text(user="hello", web_search=False)
    assert not used["model"].endswith(":online")


# ---------------------------- JSON parsing ----------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Here you go:\n{"a": 1}\nhope that helps',
    ],
)
def test_parse_json_handles_fences_and_prose(raw):
    assert llm._parse_json(raw) == {"a": 1}


def test_parse_json_raises_on_garbage():
    with pytest.raises(Exception):
        llm._parse_json("no json here at all")


def test_openai_json_falls_back_when_schema_unsupported(monkeypatch):
    """Models without strict schema support must still yield parsed JSON."""
    calls = {"n": 0}

    class FakeCompletions:
        def create(self, **kw):
            calls["n"] += 1
            if "response_format" in kw:
                raise RuntimeError("json_schema not supported by this model")
            class M:
                content = '```json\n{"ok": true}\n```'
            class C:
                message = M()
            class R:
                choices = [C()]
            return R()

    client = llm.get_client(_openrouter_settings())
    client.client.chat.completions = FakeCompletions()

    got = client.json(system="s", user="u", schema={"type": "object"})
    assert got == {"ok": True}
    assert calls["n"] == 2  # strict attempt, then loose retry
