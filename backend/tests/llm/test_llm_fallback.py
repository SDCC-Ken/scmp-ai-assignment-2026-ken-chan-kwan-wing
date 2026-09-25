"""FallbackLLMProvider with stub providers and an injected clock (no network, no sleeping)."""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from app.llm.base import LLMError, LLMOutputError
from app.llm.fallback import FallbackLLMProvider
from app.llm.schemas import AgentTurn, AttachmentInput, Intent, LLMContext

CTX = LLMContext(today=date(2026, 9, 25), weekday="Friday", user_display_name="Amy Lau")


class Stub:
    def __init__(self, name: str, model: str, *outcomes: Any) -> None:
        self.name, self.model = name, model
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, Sequence[AttachmentInput]]] = []

    def analyse(
        self, user_message: str, context: LLMContext, attachments: Sequence[AttachmentInput] = ()
    ) -> AgentTurn:
        self.calls.append((user_message, attachments))
        outcome = self.outcomes.pop(0) if self.outcomes else AgentTurn(intent=Intent.HELP)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def turn(intent: Intent = Intent.HELP) -> AgentTurn:
    return AgentTurn(intent=intent)


def make(primary: Stub, fallback: Stub, cooldown: float = 300) -> tuple[FallbackLLMProvider, Clock]:
    clock = Clock()
    return FallbackLLMProvider(primary, fallback, cooldown_seconds=cooldown, clock=clock), clock


def test_primary_success_leaves_the_fallback_untouched() -> None:
    primary, fallback = Stub("gemini", "g-model", turn(Intent.CHECK_STATUS)), Stub("ollama", "o")
    provider, _ = make(primary, fallback)
    assert provider.analyse("hi", CTX).intent == Intent.CHECK_STATUS
    assert fallback.calls == []
    assert provider.last_served_by == "gemini:g-model"
    assert (provider.name, provider.model) == ("gemini", "g-model")


def test_primary_llm_error_uses_the_fallback_and_records_it() -> None:
    primary = Stub("gemini", "g-model", LLMError("quota exhausted\nmulti line"))
    fallback = Stub("ollama", "o-model", turn(Intent.CREATE_LEAVE))
    provider, _ = make(primary, fallback)
    assert provider.analyse("leave", CTX).intent == Intent.CREATE_LEAVE
    assert len(primary.calls) == len(fallback.calls) == 1
    assert provider.last_served_by.startswith("ollama:o-model (fallback: primary failed - ")
    assert "quota exhausted multi line" in provider.last_served_by
    assert (provider.name, provider.model) == ("ollama", "o-model")


def test_llm_output_error_also_falls_back() -> None:
    primary = Stub("gemini", "g", LLMOutputError("invalid structured response"))
    fallback = Stub("ollama", "o", turn(Intent.HELP))
    provider, _ = make(primary, fallback)
    assert provider.analyse("hi", CTX).intent == Intent.HELP
    assert len(fallback.calls) == 1


def test_cooldown_skips_the_primary_until_the_clock_passes() -> None:
    primary = Stub("gemini", "g", LLMError("down"), turn(Intent.CHECK_STATUS))
    fallback = Stub("ollama", "o")
    provider, clock = make(primary, fallback, cooldown=300)
    provider.analyse("1", CTX)  # primary fails, fallback answers, cooldown starts
    clock.now += 299
    provider.analyse("2", CTX)  # still cooling down: primary not called
    provider.analyse("3", CTX)
    assert len(primary.calls) == 1 and len(fallback.calls) == 3
    assert "cooling down after: down" in provider.last_served_by
    clock.now += 2  # 301 s after the failure
    assert provider.analyse("4", CTX).intent == Intent.CHECK_STATUS  # primary retried, recovered
    assert len(primary.calls) == 2 and len(fallback.calls) == 3
    assert provider.last_served_by == "gemini:g"
    provider.analyse("5", CTX)
    assert len(primary.calls) == 3  # no lingering cooldown after recovery


def test_failed_retry_starts_a_new_cooldown() -> None:
    primary = Stub("gemini", "g", LLMError("down"), LLMError("still down"))
    fallback = Stub("ollama", "o")
    provider, clock = make(primary, fallback, cooldown=60)
    provider.analyse("1", CTX)
    clock.now += 61
    provider.analyse("2", CTX)  # retried and failed again
    provider.analyse("3", CTX)  # cooling down again
    assert len(primary.calls) == 2 and len(fallback.calls) == 3


def test_zero_cooldown_retries_the_primary_every_time() -> None:
    primary = Stub("gemini", "g", LLMError("a"), LLMError("b"), turn(Intent.HELP))
    provider, _ = make(primary, Stub("ollama", "o"), cooldown=0)
    for text in ("1", "2", "3"):
        provider.analyse(text, CTX)
    assert len(primary.calls) == 3


def test_both_failing_raises_a_combined_llm_error() -> None:
    primary = Stub("gemini", "g", LLMError("primary broke"))
    fallback = Stub("ollama", "o", LLMError("fallback broke"))
    provider, _ = make(primary, fallback)
    with pytest.raises(LLMError) as info:
        provider.analyse("hi", CTX)
    message = str(info.value)
    assert "primary broke" in message and "fallback broke" in message
    assert not isinstance(info.value, LLMOutputError)


def test_fallback_output_error_stays_an_output_error() -> None:
    provider, _ = make(
        Stub("gemini", "g", LLMError("down")), Stub("ollama", "o", LLMOutputError("bad json"))
    )
    with pytest.raises(LLMOutputError):
        provider.analyse("hi", CTX)


def test_error_messages_are_bounded_and_single_line() -> None:
    long_error = LLMError("x" * 500 + "\nsecondline")
    provider, _ = make(Stub("gemini", "g", long_error), Stub("ollama", "o", LLMError("y" * 500)))
    with pytest.raises(LLMError) as info:
        provider.analyse("hi", CTX)
    assert "\n" not in str(info.value) and len(str(info.value)) < 400


def test_attachments_and_message_are_forwarded_to_both() -> None:
    files = [AttachmentInput(id=1, filename="a.png", content_type="image/png", data=b"\x89PNG")]
    primary, fallback = Stub("gemini", "g", LLMError("down")), Stub("ollama", "o")
    provider, _ = make(primary, fallback)
    provider.analyse("claim this", CTX, files)
    assert primary.calls == [("claim this", files)]
    assert fallback.calls == [("claim this", files)]


def test_last_model_of_the_serving_provider_is_reported() -> None:
    fallback = Stub("ollama", "text-model")
    fallback.last_model = "vision-model + text-model"  # type: ignore[attr-defined]
    provider, _ = make(Stub("gemini", "g", LLMError("down")), fallback)
    provider.analyse("hi", CTX)
    assert provider.model == "vision-model + text-model"
    assert provider.last_served_by.startswith("ollama:vision-model + text-model (fallback")


def test_switch_and_recovery_are_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    primary = Stub("gemini", "g", LLMError("down"), turn(Intent.HELP))
    provider, clock = make(primary, Stub("ollama", "o"), cooldown=10)
    with caplog.at_level(logging.INFO, logger="app.llm.fallback"):
        provider.analyse("1", CTX)
        provider.analyse("2", CTX)  # cooling down: no second warning
        clock.now += 11
        provider.analyse("3", CTX)
    messages = [r.getMessage() for r in caplog.records]
    assert sum("using fallback" in m for m in messages) == 1
    assert sum("recovered" in m for m in messages) == 1
    assert "Amy" not in caplog.text


def test_only_llm_errors_trigger_the_fallback() -> None:
    primary = Stub("gemini", "g", RuntimeError("programming error"))
    fallback = Stub("ollama", "o")
    provider, _ = make(primary, fallback)
    with pytest.raises(RuntimeError):
        provider.analyse("hi", CTX)
    assert fallback.calls == []
