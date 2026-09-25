import socket
from typing import Any

import pytest

from app.config import Settings
from app.llm.factory import build_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.fallback import FallbackLLMProvider
from app.llm.gemini import GeminiProvider
from app.llm.ollama import OllamaProvider


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def test_gemini_provider_without_key_builds_without_error() -> None:
    provider = build_llm_provider(settings(llm_provider="gemini", gemini_api_key=""))
    assert isinstance(provider, GeminiProvider)
    assert (provider.name, provider.model) == ("gemini", "gemini-3.8-flash")


def test_fake_provider() -> None:
    provider = build_llm_provider(settings(llm_provider="fake"))
    assert isinstance(provider, FakeLLMProvider)
    assert (provider.name, provider.model) == ("fake", "fake-rules-v1")


def test_provider_name_is_case_insensitive() -> None:
    assert isinstance(build_llm_provider(settings(llm_provider=" FAKE ")), FakeLLMProvider)


def test_unknown_provider_is_a_config_error() -> None:
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        build_llm_provider(settings(llm_provider="openai"))


def test_ollama_provider_uses_configured_models() -> None:
    provider = build_llm_provider(
        settings(llm_provider="ollama", ollama_model="m-text", ollama_vision_model="m-vision")
    )
    assert isinstance(provider, OllamaProvider)
    assert (provider.name, provider.model, provider.vision_model) == (
        "ollama",
        "m-text",
        "m-vision",
    )


@pytest.mark.parametrize(
    ("primary", "fallback", "primary_type", "fallback_type"),
    [
        ("gemini", "ollama", GeminiProvider, OllamaProvider),
        ("ollama", "gemini", OllamaProvider, GeminiProvider),
        ("gemini", "fake", GeminiProvider, FakeLLMProvider),
        ("fake", "ollama", FakeLLMProvider, OllamaProvider),
        ("ollama", "fake", OllamaProvider, FakeLLMProvider),
        (" GEMINI ", " Ollama ", GeminiProvider, OllamaProvider),
    ],
)
def test_primary_and_fallback_combinations(
    primary: str, fallback: str, primary_type: type, fallback_type: type
) -> None:
    provider = build_llm_provider(
        settings(
            llm_provider=primary,
            llm_fallback_provider=fallback,
            llm_fallback_cooldown_seconds=42,
        )
    )
    assert isinstance(provider, FallbackLLMProvider)
    assert isinstance(provider._primary, primary_type)
    assert isinstance(provider._fallback, fallback_type)
    assert provider._cooldown == 42
    assert provider.last_served_by.startswith(provider._primary.name + ":")


@pytest.mark.parametrize("name", ["gemini", "ollama", "fake", "OLLAMA"])
def test_same_primary_and_fallback_returns_the_plain_primary(name: str) -> None:
    provider = build_llm_provider(settings(llm_provider=name, llm_fallback_provider=name))
    assert not isinstance(provider, FallbackLLMProvider)
    assert provider.name == name.lower()


@pytest.mark.parametrize("empty", ["", "   "])
def test_no_fallback_configured(empty: str) -> None:
    provider = build_llm_provider(settings(llm_provider="ollama", llm_fallback_provider=empty))
    assert isinstance(provider, OllamaProvider)


def test_unknown_fallback_is_a_config_error() -> None:
    with pytest.raises(ValueError, match="LLM_FALLBACK_PROVIDER"):
        build_llm_provider(settings(llm_provider="gemini", llm_fallback_provider="claude"))


def test_error_message_lists_supported_providers() -> None:
    with pytest.raises(ValueError, match="gemini, ollama, fake"):
        build_llm_provider(settings(llm_provider="nope"))


def test_construction_does_no_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access while building providers")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    for primary, fallback in (("gemini", "ollama"), ("ollama", "gemini"), ("ollama", "")):
        build_llm_provider(
            settings(
                llm_provider=primary,
                llm_fallback_provider=fallback,
                gemini_api_key="k-not-used",
                ollama_base_url="http://ollama.invalid:11434",
            )
        )
