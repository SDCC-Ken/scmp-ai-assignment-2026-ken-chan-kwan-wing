"""Local Ollama provider (``POST {ollama_base_url}/api/chat``, structured outputs).

Same contract as the Gemini provider: the model only classifies and extracts; its reply is
mapped to ``AgentTurn`` and validated (one corrective retry, then ``LLMOutputError``). Small
local models drop fields under nested/nullable schemas, so the wire format is a FLAT schema
(``""`` = unknown, ``target_request_id`` 0 = none, amount as text) and the prompt carries a
deterministic calendar table plus backend-resolved dates and type hints (see ``prompts``).

Attachments are handled in two steps: ``OLLAMA_VISION_MODEL`` only transcribes each file
(PDFs are rendered to PNG pages, transparent PNGs flattened onto white; Ollama cannot read
PDFs and drops alpha), then ``OLLAMA_MODEL`` extracts the fields from the OCR text together
with the user's message. Small vision models read text well but hallucinate under a
constrained JSON schema. Errors are fixed safe strings: no request bodies, image bytes, OCR
text or file names are ever put in a message or a log line.

The first call to a model may load it into memory (tens of seconds), so a model that has not
answered yet in this process gets a longer timeout (``COLD_TIMEOUT``); ``keep_alive`` then keeps
it loaded.
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings
from app.llm.base import LLMError, LLMOutputError
from app.llm.dates import claim_dates, drop_unstated_dates, leave_dates
from app.llm.pdf_images import MAX_PAGES, flatten_png_alpha, pdf_to_png_pages
from app.llm.prompts import (
    CORRECTION_TEMPLATE,
    OLLAMA_VISION_PROMPT,
    build_ollama_system_prompt,
    build_ollama_user_prompt,
    resolve_relative_dates,
    vague_date_phrases,
)
from app.llm.schemas import AgentTurn, AttachmentInput, Intent, LLMContext
from app.llm.structured import (
    ATTACHMENT_MIME_TYPES,
    InvalidOutput,
    build_flat_schema,
    correct_currency,
    drop_invented_leave_type,
    parse_flat_turn,
    with_unreadable_documents,
)

logger = logging.getLogger(__name__)

NUM_CTX = 8192
NUM_PREDICT = 1500
KEEP_ALIVE = "30m"
COLD_TIMEOUT = 240.0  # seconds allowed for the first call to a model (it may need loading)
OCR_NUM_PREDICT = 900
MIN_OCR_CHARS = 15  # fewer letters/digits than this: nothing readable
_NO_TEXT = re.compile(
    r"\b(no (visible |readable )?(lines of )?text|unreadable|cannot read|can't read|blank)\b",
    re.IGNORECASE,
)


def _drop_unstated_dates(turn: AgentTurn, message: str, context: LLMContext) -> AgentTurn:
    """Text turns only: a small model fills today's date when the user gave none ("Claim HKD
    180 for a taxi" -> receipt_date = today). A date the message never mentions is dropped, so
    the backend asks for it. Values the draft already holds are not "invented" and stay."""
    if turn.documents:
        return turn
    known = leave_dates(context.current_leave) | claim_dates(context.current_claim)
    leave, dropped_leave = drop_unstated_dates(turn.leave, message, known)
    claim, dropped_claim = drop_unstated_dates(turn.claim, message, known)
    if not (dropped_leave or dropped_claim):
        return turn
    return turn.model_copy(update={"leave": leave, "claim": claim})


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = settings.ollama_model
        self.last_model = self.model  # the model used by the most recent call (text or vision)
        self.vision_model = settings.ollama_vision_model
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._timeout = settings.ollama_timeout_seconds
        self._client = client
        self._transport = transport
        self._warm: set[str] = set()  # models that have answered at least once

    # -- images ----------------------------------------------------------------------------
    @staticmethod
    def _page_images(attachment: AttachmentInput) -> list[str]:
        """Base64 page images of one attachment (PDF pages rendered, PNG alpha flattened)."""
        if attachment.content_type == "application/pdf":
            pages = pdf_to_png_pages(attachment.data, max_pages=MAX_PAGES)
        elif attachment.content_type == "image/png":
            pages = [flatten_png_alpha(attachment.data)]
        else:
            pages = [attachment.data]
        return [base64.b64encode(page).decode("ascii") for page in pages]

    def _transcribe(self, attachment: AttachmentInput) -> str:
        """Free-text OCR of one attachment by the vision model ("" when nothing is readable).

        Small vision models read text well but hallucinate under a constrained JSON schema, so
        the vision model only transcribes; the text model then extracts the fields."""
        body = {
            "model": self.vision_model,
            "stream": False,
            "think": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": OCR_NUM_PREDICT},
            "messages": [
                {
                    "role": "user",
                    "content": OLLAMA_VISION_PROMPT,
                    "images": self._page_images(attachment),
                }
            ],
        }
        text = self._post_chat(body, self.vision_model)
        text = text.strip() if isinstance(text, str) else ""
        letters = sum(ch.isalnum() for ch in text)
        if letters < MIN_OCR_CHARS or (letters < 80 and _NO_TEXT.search(text)):
            return ""
        return text

    # -- transport -------------------------------------------------------------------------
    def _post_chat(self, body: dict[str, Any], model: str) -> Any:
        url = f"{self._base_url}/api/chat"
        timeout = self._timeout if model in self._warm else max(self._timeout, COLD_TIMEOUT)
        try:
            if self._client is not None:
                response = self._client.post(url, json=body, timeout=timeout)
            else:
                with httpx.Client(
                    timeout=httpx.Timeout(timeout), transport=self._transport
                ) as client:
                    response = client.post(url, json=body)
        except httpx.TimeoutException:
            logger.warning("Ollama request timed out (model %s)", model)
            raise LLMError("Ollama request timed out") from None
        except httpx.ConnectError:
            logger.warning("Ollama is not reachable at %s", self._base_url)
            raise LLMError(f"Ollama is not reachable at {self._base_url}") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            logger.warning("Ollama request failed: network error")
            raise LLMError("Ollama request failed") from None
        status = response.status_code
        if status == 404:
            logger.warning("Ollama model %s not found", model)
            raise LLMError(f"Model {model} is not installed (ollama pull {model})")
        if status != 200:
            logger.warning("Ollama returned HTTP %d", status)
            raise LLMError(f"Ollama returned HTTP {status}")
        try:
            payload = response.json()
            content = payload["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise LLMError("Ollama returned an invalid response") from None
        self._warm.add(model)
        return content if isinstance(content, str) else None

    # -- main entry ------------------------------------------------------------------------
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
        model = self.model
        self.last_model = model
        documents: list[tuple[int, str]] = []
        if attachments:
            self.last_model = f"{self.vision_model} + {model}"
            for index, attachment in enumerate(attachments):
                text = self._transcribe(attachment)
                if text:
                    documents.append((index, text))
            if not documents and not user_message.strip():
                return with_unreadable_documents(
                    AgentTurn(intent=Intent.UNCLEAR, rationale="No readable text in the file"),
                    len(attachments),
                )
        positions = [index for index, _ in documents]
        sources = [text for _, text in documents]
        prompt = build_ollama_user_prompt(user_message, context, documents)
        system = build_ollama_system_prompt(bool(documents))
        schema = build_flat_schema(len(documents))
        vague = (vague_date_phrases(user_message) or [""])[0]
        has_values = bool(re.search(r"\d", user_message)) or bool(
            resolve_relative_dates(user_message, context.today)
        )
        problem = ""
        for attempt in (1, 2):
            text = (
                prompt
                if attempt == 1
                else f"{prompt}\n\n{CORRECTION_TEMPLATE.format(problem=problem)}"
            )
            body = {
                "model": model,
                "stream": False,
                "think": False,  # thinking models (gemma4, qwen3, ...) would spend the budget
                "format": schema,
                "keep_alive": KEEP_ALIVE,
                "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
            }
            content = self._post_chat(body, model)
            try:
                turn = parse_flat_turn(
                    content, positions, len(attachments), vague, has_values, sources
                )
                turn = drop_invented_leave_type(correct_currency(turn, user_message), user_message)
                return _drop_unstated_dates(turn, user_message, context)
            except InvalidOutput as invalid:
                problem = invalid.problem
                logger.warning("Ollama output invalid (attempt %d): %s", attempt, problem)
        raise LLMOutputError("Ollama returned an invalid structured response")
