"""One LLM interface, two backends.

Nothing in this tool is tied to a specific AI provider — every call is either
"give me JSON matching this schema" or "research this and write it up". This
module hides the provider behind those two methods.

Backends
--------
* ``anthropic``          — the Anthropic API directly (default). Supports
                           prompt caching and native server-side web search.
* ``openai_compatible``  — anything speaking the OpenAI chat-completions API:
                           OpenRouter, OpenAI, Mistral, Groq, DeepSeek,
                           Together, local Ollama, etc. Selected with
                           ``LLM_PROVIDER=openai_compatible`` plus a base URL.

Switching providers is a `.env` change; no code changes anywhere else.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .config import Settings

log = logging.getLogger("jobhunter.llm")

SCORING = "scoring"        # cheap, high-volume (triage, match scoring)
GENERATION = "generation"  # stronger (CV/cover letters, company research)

# Appended to every system prompt so scored reasons and generated documents
# read like a person wrote them (R2). Kept here, at the one point every model
# call passes through.
STYLE_RULES = (
    "Write like a person, not a marketing department. Never use em dashes or "
    "en dashes. Never use the construction 'it is not X, it is Y'. Avoid the "
    "words seamless, effortless, unlock, leverage, empower, elevate, robust, "
    "delve, landscape, journey. No exclamation marks. No emoji. Short "
    "sentences. British spelling."
)


def _styled(system: str) -> str:
    return f"{system}\n\n{STYLE_RULES}"


class LLMError(RuntimeError):
    pass


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences despite instructions."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_json(text: str) -> dict:
    t = _strip_code_fence(text)
    try:
        return json.loads(t)
    except Exception:
        # Last resort: pull the outermost JSON object out of surrounding prose.
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


# --------------------------------------------------------------------------- #
class BaseClient:
    supports_web_search = False

    def json(self, *, system: str, user: str, schema: dict, tier: str = SCORING,
             max_tokens: int = 2000, cache_system: bool = True) -> dict:
        raise NotImplementedError

    def text(self, *, user: str, tier: str = GENERATION, max_tokens: int = 16000,
             web_search: bool = False) -> str:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
class AnthropicClient(BaseClient):
    supports_web_search = True

    WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

    def __init__(self, settings: Settings):
        import anthropic

        self._anthropic = anthropic
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _model(self, tier: str) -> str:
        return (self.settings.generation_model if tier == GENERATION
                else self.settings.scoring_model)

    def json(self, *, system, user, schema, tier=SCORING, max_tokens=2000,
             cache_system=True) -> dict:
        system = _styled(system)
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        resp = self.client.messages.create(
            model=self._model(tier),
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return _parse_json(text)

    def text(self, *, user, tier=GENERATION, max_tokens=16000, web_search=False) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model(tier),
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if web_search:
            kwargs["tools"] = [{**self.WEB_SEARCH_TOOL, "max_uses": 12}]

        messages = kwargs.pop("messages")
        parts: list[str] = []
        for _ in range(5):  # server tools can pause; resume a bounded number of times
            resp = self.client.messages.create(messages=messages, **kwargs)
            for block in resp.content:
                if block.type == "text":
                    parts.append(block.text)
            if resp.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]
        return "\n".join(parts)


# --------------------------------------------------------------------------- #
class OpenAICompatibleClient(BaseClient):
    """Works with OpenRouter, OpenAI, Mistral, Groq, DeepSeek, Ollama, ..."""

    def __init__(self, settings: Settings):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "The 'openai' package is required for LLM_PROVIDER=openai_compatible. "
                "Run: pip install -r requirements.txt"
            ) from exc

        self.settings = settings
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY is not set — required for this provider.")
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or None,
        )
        self._is_openrouter = "openrouter" in (settings.llm_base_url or "")

    @property
    def supports_web_search(self) -> bool:
        # OpenRouter exposes live search by suffixing the model with ':online'.
        return self._is_openrouter

    def _model(self, tier: str) -> str:
        model = (self.settings.generation_model if tier == GENERATION
                 else self.settings.scoring_model)
        if not model:
            raise LLMError(
                f"No {tier} model configured. Set JOBHUNTER_{tier.upper()}_MODEL "
                "in .env to a model your provider offers "
                "(e.g. 'anthropic/claude-sonnet-4.5' on OpenRouter)."
            )
        return model

    def json(self, *, system, user, schema, tier=SCORING, max_tokens=2000,
             cache_system=True) -> dict:
        system = _styled(system)
        model = self._model(tier)
        # The scoring system prompt is identical across every job in a search,
        # so mark it cacheable: on Anthropic (via OpenRouter) this caches the
        # prefix and bills the repeats at a fraction of the input cost. Only
        # Anthropic uses cache_control; other providers get a plain string.
        cacheable = (cache_system and self._is_openrouter
                     and ("claude" in model.lower() or "anthropic" in model.lower()))
        system_content = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if cacheable else system
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user},
        ]

        # Preferred: provider-enforced JSON schema.
        try:
            resp = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "strict": True,
                        "schema": schema,
                    },
                },
            )
            return _parse_json(resp.choices[0].message.content or "")
        except Exception as exc:
            log.debug("Strict JSON schema unsupported/failed (%s); retrying loosely.", exc)

        # Fallback for models without schema support: ask for JSON in the prompt.
        messages[0]["content"] = (
            system
            + "\n\nReply with a single JSON object only — no prose, no code fences. "
            + "It must match this JSON schema:\n"
            + json.dumps(schema)
        )
        resp = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return _parse_json(resp.choices[0].message.content or "")

    def text(self, *, user, tier=GENERATION, max_tokens=16000, web_search=False) -> str:
        model = self._model(tier)
        if web_search and self._is_openrouter and not model.endswith(":online"):
            model += ":online"  # OpenRouter's live-search variant
        resp = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


# --------------------------------------------------------------------------- #
_CLIENTS: dict[str, BaseClient] = {}


def get_client(settings: Settings) -> BaseClient:
    """Return the configured LLM client (cached per provider+key)."""
    provider = (settings.llm_provider or "anthropic").lower()
    cache_key = f"{provider}|{settings.llm_base_url}|{bool(settings.llm_api_key)}"
    if cache_key in _CLIENTS:
        return _CLIENTS[cache_key]

    if provider in ("anthropic", ""):
        client: BaseClient = AnthropicClient(settings)
    elif provider in ("openai_compatible", "openai", "openrouter"):
        client = OpenAICompatibleClient(settings)
    else:
        raise LLMError(
            f"Unknown LLM_PROVIDER {provider!r}. "
            "Use 'anthropic' or 'openai_compatible'."
        )
    _CLIENTS[cache_key] = client
    return client


def reset_clients() -> None:
    """Drop cached clients (used by tests)."""
    _CLIENTS.clear()


def is_configured(settings: Settings) -> bool:
    """True if we have credentials for the selected provider."""
    provider = (settings.llm_provider or "anthropic").lower()
    if provider in ("anthropic", ""):
        return bool(settings.anthropic_api_key)
    return bool(settings.llm_api_key)
