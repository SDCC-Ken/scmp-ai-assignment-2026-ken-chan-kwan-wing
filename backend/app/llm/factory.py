"""Build the configured LLM provider (optionally wrapped with an automatic fallback)."""

from app.config import Settings
from app.llm.base import LLMProvider

SUPPORTED = ("gemini", "ollama", "fake")


def _build_one(name: str, settings: Settings, setting_label: str) -> LLMProvider:
    """No network I/O happens here; a missing key or a stopped Ollama only fails at analyse."""
    key = name.strip().lower()
    if key == "gemini":
        from app.llm.gemini import GeminiProvider

        return GeminiProvider(settings)
    if key == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider(settings)
    if key == "fake":
        from app.llm.fake import FakeLLMProvider

        return FakeLLMProvider()
    raise ValueError(f"Unsupported {setting_label} {name!r}; use one of: {', '.join(SUPPORTED)}")


def build_llm_provider(settings: Settings) -> LLMProvider:
    primary = _build_one(settings.llm_provider, settings, "LLM_PROVIDER")
    fallback_name = settings.llm_fallback_provider.strip().lower()
    if not fallback_name:
        return primary
    fallback = _build_one(fallback_name, settings, "LLM_FALLBACK_PROVIDER")
    if fallback_name == settings.llm_provider.strip().lower():
        return primary  # same provider: a fallback would only repeat the failure
    from app.llm.fallback import FallbackLLMProvider

    return FallbackLLMProvider(
        primary, fallback, cooldown_seconds=settings.llm_fallback_cooldown_seconds
    )
