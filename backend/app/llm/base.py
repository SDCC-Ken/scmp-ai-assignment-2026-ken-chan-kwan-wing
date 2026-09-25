"""Provider interface so Gemini can be replaced without touching business workflows."""

from collections.abc import Sequence
from typing import Protocol

from app.llm.schemas import AgentTurn, AttachmentInput, LLMContext


class LLMError(Exception):
    """The provider is unavailable, timed out, is misconfigured or was refused."""


class LLMOutputError(LLMError):
    """The provider answered but the structured output was invalid, even after a retry."""


class LLMProvider(Protocol):
    name: str  # e.g. "gemini" | "fake" | "scripted"
    model: str  # e.g. "gemini-3.8-flash"

    def analyse(
        self,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput] = (),
    ) -> AgentTurn:
        """Classify the message (and any attached images/PDFs) and extract fields.
        Raises LLMError / LLMOutputError."""
        ...
