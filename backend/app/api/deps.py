"""Provider dependencies backed by ``app.state`` (built lazily, overridable in tests)."""

import logging

from fastapi import Request

from app.chat.fallbacks import UnavailableAdapter, UnavailableLLM
from app.integrations.base import SubmissionAdapter
from app.integrations.factory import build_submission_adapter
from app.llm.base import LLMProvider
from app.llm.factory import build_llm_provider

logger = logging.getLogger(__name__)


def get_llm_provider(request: Request) -> LLMProvider:
    """The LLM provider: the one passed to ``create_app`` or built once from the settings.

    A construction failure (for example a missing API key) is logged and replaced with a
    provider that raises ``LLMError``, so the chat degrades gracefully instead of crashing.
    """
    state = request.app.state
    if state.llm_provider is None:
        with state.provider_lock:
            if state.llm_provider is None:
                try:
                    state.llm_provider = build_llm_provider(state.settings)
                except Exception:
                    logger.exception("Could not build the LLM provider; chat will report it")
                    state.llm_provider = UnavailableLLM()
    return state.llm_provider


def get_submission_adapter(request: Request) -> SubmissionAdapter:
    state = request.app.state
    if state.submission_adapter is None:
        with state.provider_lock:
            if state.submission_adapter is None:
                try:
                    state.submission_adapter = build_submission_adapter(state.settings)
                except Exception:
                    logger.exception("Could not build the submission adapter")
                    state.submission_adapter = UnavailableAdapter()
    return state.submission_adapter
