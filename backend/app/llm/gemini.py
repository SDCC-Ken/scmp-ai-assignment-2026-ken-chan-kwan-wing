"""Google Gemini provider (structured JSON output, validated by ``AgentTurn``).

The model only classifies and extracts. Its reply is parsed as JSON, normalised defensively
(length limits) and validated with ``AgentTurn.model_validate``; one corrective retry is made
before ``LLMOutputError``. Error messages are fixed, safe strings: the API key, request bodies
and raw SDK exceptions are never surfaced or logged.

SDK notes (google-genai 2.x): ``ThinkingConfig(thinking_level=ThinkingLevel.LOW)`` and
``response_mime_type="application/json"`` with ``response_json_schema=<dict>``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.llm.base import LLMError, LLMOutputError
from app.llm.prompts import CORRECTION_TEMPLATE, SYSTEM_PROMPT, build_user_prompt
from app.llm.schemas import AgentTurn, AttachmentInput, LLMContext
from app.llm.structured import (  # noqa: F401  (re-exported for callers and tests)
    ATTACHMENT_MIME_TYPES,
    RESPONSE_SCHEMA,
    InvalidOutput,
    WireTurn,
    _WireDocument,
    align_documents,
    parse_turn,
)

logger = logging.getLogger(__name__)

TOTAL_TIMEOUT_SECONDS = 20.0
ATTACHMENT_TIMEOUT_SECONDS = 40.0  # reading a PDF/photo takes longer than a text turn
MAX_OUTPUT_TOKENS = 3072


class _ModelsAPI(Protocol):
    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any: ...


class GeminiClient(Protocol):
    """The slice of ``google.genai.Client`` we use (also implemented by test doubles)."""

    models: _ModelsAPI


def _thinking_level(name: str) -> Any:
    from google.genai import types

    # ThinkingLevel is a lenient enum (unknown strings pass through), so check membership.
    key = name.strip().upper()
    if key in types.ThinkingLevel.__members__ and key != "THINKING_LEVEL_UNSPECIFIED":
        return types.ThinkingLevel[key]
    logger.warning("Unknown GEMINI_THINKING_LEVEL %r; using LOW", name)
    return types.ThinkingLevel.LOW


def _map_sdk_error(exc: Exception) -> LLMError:
    """Translate any SDK/transport failure to a fixed, key-free message."""
    code = getattr(exc, "code", None)
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("Gemini request timed out")
    if isinstance(exc, httpx.HTTPError):
        return LLMError("Could not reach Gemini")
    if code in (401, 403):
        return LLMError("Gemini rejected the API key or access")
    if code == 404:
        return LLMError("Gemini model not found or unsupported")
    if code == 429:
        return LLMError("Gemini quota or rate limit reached")
    if isinstance(code, int) and code >= 500:
        return LLMError("Gemini service error")
    if isinstance(code, int):
        return LLMError(f"Gemini rejected the request (HTTP {code})")
    return LLMError("Gemini request failed")


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        client: GeminiClient | None = None,
        timeout_seconds: float = TOTAL_TIMEOUT_SECONDS,
        unavailable_retry_delay: float = 1.5,
        media_resolution: str | None = "medium",
        attachment_timeout_seconds: float = ATTACHMENT_TIMEOUT_SECONDS,
    ) -> None:
        self.model = settings.gemini_model
        self._api_key = settings.gemini_api_key.get_secret_value().strip()
        self._thinking_level = settings.gemini_thinking_level
        self._timeout_seconds = timeout_seconds
        self._retry_delay = unavailable_retry_delay
        self._media_resolution = media_resolution  # "low" | "medium" | "high" | None (default)
        self._attachment_timeout = attachment_timeout_seconds
        self._client: GeminiClient | None = client

    # -- client ----------------------------------------------------------------------------
    def _get_client(self) -> GeminiClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise LLMError("Gemini is not configured")
        try:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        except Exception:
            raise LLMError("Gemini client could not be created") from None
        return self._client

    def _media_resolution_level(self) -> Any:
        from google.genai import types

        key = f"MEDIA_RESOLUTION_{(self._media_resolution or '').strip().upper()}"
        if key in types.MediaResolution.__members__ and not key.endswith("UNSPECIFIED"):
            return types.MediaResolution[key]
        return None

    def _config(self, remaining_seconds: float, with_attachments: bool = False) -> Any:
        from google.genai import types

        extra: dict[str, Any] = {}
        if with_attachments and (level := self._media_resolution_level()) is not None:
            extra["media_resolution"] = level
        return types.GenerateContentConfig(
            **extra,
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=RESPONSE_SCHEMA,
            thinking_config=types.ThinkingConfig(
                thinking_level=_thinking_level(self._thinking_level)
            ),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            http_options=types.HttpOptions(timeout=max(1000, int(remaining_seconds * 1000))),
        )

    # -- main entry ------------------------------------------------------------------------
    def _build_parts(
        self, prompt: str, attachments: Sequence[AttachmentInput], correction: str | None
    ) -> Any:
        """Plain text when there are no files; otherwise text part(s) then one part per file."""
        text = prompt if correction is None else f"{prompt}\n\n{correction}"
        if not attachments:
            return text
        from google.genai import types

        parts = [types.Part.from_text(text=text)]
        parts += [types.Part.from_bytes(data=a.data, mime_type=a.content_type) for a in attachments]
        return parts

    def analyse(
        self,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput] = (),
    ) -> AgentTurn:
        for attachment in attachments:
            if attachment.content_type not in ATTACHMENT_MIME_TYPES:
                raise LLMError("Unsupported attachment type")
        if len(attachments) > 3:
            raise LLMError("Too many attachments")
        client = self._get_client()
        prompt = build_user_prompt(user_message, context, [a.content_type for a in attachments])
        budget = self._attachment_timeout if attachments else self._timeout_seconds
        deadline = time.monotonic() + budget
        contents: Any = self._build_parts(prompt, attachments, None)
        problem = ""
        unavailable_retried = False
        attempt = 0
        while attempt < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMError("Gemini request timed out")
            if attempt == 1:
                correction = CORRECTION_TEMPLATE.format(problem=problem)
                contents = self._build_parts(prompt, attachments, correction)
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=self._config(remaining, bool(attachments)),
                )
            except LLMError:
                raise
            except Exception as exc:
                error = _map_sdk_error(exc)
                logger.warning("Gemini call failed: %s (%s)", error, type(exc).__name__)
                # 503 "high demand" is transient: one short retry inside the time budget.
                if getattr(exc, "code", None) == 503 and not unavailable_retried:
                    unavailable_retried = True
                    if deadline - time.monotonic() > self._retry_delay + 1:
                        time.sleep(self._retry_delay)
                        continue
                raise error from None
            attempt += 1
            try:
                turn = parse_turn(getattr(response, "text", None), len(attachments))
                return align_documents(turn, len(attachments))
            except InvalidOutput as invalid:
                problem = invalid.problem
                logger.warning("Gemini output invalid (attempt %d): %s", attempt, problem)
        raise LLMOutputError("Gemini returned an invalid structured response")
