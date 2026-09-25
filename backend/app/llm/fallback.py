"""Automatic fallback between two LLM providers (e.g. Gemini -> local Ollama).

On an ``LLMError`` (including ``LLMOutputError``) from the primary, the same call goes to the
fallback and the primary is skipped for ``cooldown_seconds`` so users do not wait for repeated
slow failures. Afterwards the primary is tried again. The fallback is only called when needed.
``last_served_by`` / ``name`` / ``model`` describe which provider answered last (for the trace).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence

from app.llm.base import LLMError, LLMOutputError, LLMProvider
from app.llm.schemas import AgentTurn, AttachmentInput, LLMContext

logger = logging.getLogger(__name__)


def _short(error: Exception) -> str:
    text = " ".join(str(error).split()) or type(error).__name__
    return text[:120]


def _label(provider: LLMProvider) -> str:
    model = getattr(provider, "last_model", None) or provider.model
    return f"{provider.name}:{model}"


class FallbackLLMProvider:
    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        cooldown_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._cooldown_until: float | None = None
        self._primary_reason = ""  # why the primary is currently skipped
        self._on_fallback = False
        self._last: LLMProvider = primary
        self.last_served_by: str = _label(primary)

    @property
    def name(self) -> str:
        return self._last.name

    @property
    def model(self) -> str:
        return getattr(self._last, "last_model", None) or self._last.model

    # -- helpers ---------------------------------------------------------------------------
    def _in_cooldown(self) -> bool:
        with self._lock:
            until = self._cooldown_until
            if until is None:
                return False
            if self._clock() < until:
                return True
            self._cooldown_until = None  # expired: try the primary again
            return False

    def _served(self, provider: LLMProvider, reason: str | None) -> None:
        with self._lock:
            self._last = provider
            label = _label(provider)
            if reason is None:
                self.last_served_by = label
                if self._on_fallback:
                    logger.info("LLM primary %s recovered; switching back", label)
                    self._on_fallback = False
            else:
                self.last_served_by = f"{label} (fallback: primary failed - {reason})"

    def _call_fallback(
        self,
        reason: str,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput],
    ) -> AgentTurn:
        try:
            turn = self._fallback.analyse(user_message, context, attachments)
        except LLMError as exc:
            message = f"The AI service is unavailable (primary: {reason}; fallback: {_short(exc)})"
            raise (LLMOutputError if isinstance(exc, LLMOutputError) else LLMError)(
                message
            ) from None
        self._served(self._fallback, reason)
        return turn

    # -- LLMProvider -----------------------------------------------------------------------
    def analyse(
        self,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput] = (),
    ) -> AgentTurn:
        if self._in_cooldown():
            return self._call_fallback(
                f"cooling down after: {self._primary_reason}", user_message, context, attachments
            )
        try:
            turn = self._primary.analyse(user_message, context, attachments)
        except LLMError as exc:
            reason = _short(exc)
            with self._lock:
                self._primary_reason = reason
                if self._cooldown > 0:
                    self._cooldown_until = self._clock() + self._cooldown
                first_switch = not self._on_fallback
                self._on_fallback = True
            if first_switch:
                logger.warning(
                    "LLM primary %s failed (%s); using fallback %s",
                    self._primary.name,
                    reason,
                    self._fallback.name,
                )
            return self._call_fallback(reason, user_message, context, attachments)
        self._served(self._primary, None)
        return turn
