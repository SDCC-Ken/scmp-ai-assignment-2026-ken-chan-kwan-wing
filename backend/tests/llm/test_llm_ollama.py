"""OllamaProvider against httpx.MockTransport (no network, real pypdfium2 for PDFs)."""

import base64
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMError, LLMOutputError
from app.llm.ollama import COLD_TIMEOUT, OllamaProvider
from app.llm.schemas import AttachmentInput, DocType, Intent, LLMContext
from app.llm.structured import build_flat_schema
from tests.llm.test_pdf_images import make_pdf

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
SECRET_EMAIL = "amy.lau.private@example.test"
FILENAME = "amy-lau-private-note.pdf"
SENTINEL = b"SENTINEL-DOC-BYTES-1234"
OCR_SECRET = "OCR-SECRET-TEXT-9876"
BASE = "http://ollama.test:11434"
TEXT_MODEL, VISION_MODEL = "text-model:1b", "vision-model:1b"


def settings(**kw: Any) -> Settings:
    values: dict[str, Any] = {
        "ollama_base_url": BASE + "/",
        "ollama_model": TEXT_MODEL,
        "ollama_vision_model": VISION_MODEL,
        "ollama_timeout_seconds": 30,
    }
    values.update(kw)
    return Settings(_env_file=None, **values)


def ctx(**kw: Any) -> LLMContext:
    base: dict[str, Any] = {
        "today": date(2026, 9, 25),
        "weekday": "Friday",
        "user_display_name": "Amy Lau",
    }
    base.update(kw)
    return LLMContext(**base)


def flat(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "intent": "help",
        "request_type": "",
        "leave_type": "",
        "start_date": "",
        "end_date": "",
        "start_day_part": "",
        "end_day_part": "",
        "claim_type": "",
        "amount": "",
        "currency": "",
        "receipt_date": "",
        "target_request_id": 0,
        "confidence": 0.8,
    }
    data.update(kw)
    return data


def reply(content: Any) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(200, json={"message": {"role": "assistant", "content": text}})


class Server:
    """Scripted Ollama: outcomes are popped per request (Response, Exception or JSON-able)."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.timeouts.append(request.extensions["timeout"]["read"])
        outcome = self.outcomes.pop(0) if self.outcomes else flat()
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        return reply(outcome)

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def provider(server: Server, **kw: Any) -> OllamaProvider:
    return OllamaProvider(settings(**kw), transport=httpx.MockTransport(server))


def att(
    i: int = 1, mime: str = "image/jpeg", data: bytes = SENTINEL, name: str = FILENAME
) -> AttachmentInput:
    return AttachmentInput(id=i, filename=name, content_type=mime, data=data + bytes([i]))


# ---------------------------------------------------------------- request shape --------------
def test_text_turn_request_shape() -> None:
    server = Server(flat(intent="create_leave", leave_type="annual", start_date="2026-10-05"))
    turn = provider(server).analyse("annual leave on 5 Oct", ctx())
    assert turn.intent == Intent.CREATE_LEAVE
    assert len(server.requests) == 1
    request = server.requests[0]
    assert str(request.url) == f"{BASE}/api/chat"  # trailing slash of the base URL stripped
    assert request.method == "POST"
    body = server.body()
    assert body["model"] == TEXT_MODEL
    assert body["stream"] is False and body["think"] is False
    assert body["format"] == build_flat_schema(0)
    assert body["options"]["temperature"] == 0
    assert body["keep_alive"]
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert all("images" not in m for m in body["messages"])
    assert "2026-09-28 (next Monday)" in body["messages"][1]["content"]  # calendar table


def test_prompt_has_no_email_display_name_filename_or_bytes() -> None:
    server = Server(flat(), {**flat(), "documents": []})
    provider(server).analyse("hello", ctx(user_display_name=SECRET_EMAIL))
    raw = server.requests[0].content.decode()
    assert SECRET_EMAIL not in raw and "@" not in raw


def test_state_from_context_reaches_the_prompt() -> None:
    server = Server(flat(intent="provide_details", end_date="2026-10-05"))
    provider(server).analyse(
        "just one day",
        ctx(
            active_request_type="leave",
            awaiting="end_date",
            pending_card_action="create",
            current_leave={"leave_type": "annual", "start_date": date(2026, 10, 5)},
        ),
    )
    user = server.body()["messages"][1]["content"]
    assert "assistant is awaiting=end_date" in user
    assert '"start_date":"2026-10-05"' in user and "open confirmation card=create" in user


def test_flat_reply_is_mapped_and_post_processed() -> None:
    server = Server(
        flat(
            intent="create_claim",
            request_type="claim",
            claim_type="meal",
            amount="65.5",
            currency="USD",
            receipt_date="2026-09-22",
        )
    )
    turn = provider(server).analyse("lunch $65.5 on 2026-09-22", ctx())
    assert turn.claim is not None
    assert (turn.claim.amount, turn.claim.currency) == (65.5, "HKD")  # bare $ is not USD


def test_invented_leave_type_is_dropped() -> None:
    server = Server(
        flat(
            intent="create_leave",
            leave_type="annual",
            start_date="2026-09-28",
            end_date="2026-09-28",
        )
    )
    turn = provider(server).analyse("I want to take next Monday off", ctx())
    assert turn.leave is not None and turn.leave.leave_type is None


def test_vague_date_note_comes_from_the_backend() -> None:
    server = Server(flat(intent="create_leave"))
    turn = provider(server).analyse("time off next week", ctx())
    assert turn.ambiguities == ["Date is not specific: next week"]


def test_last_model_tracks_text_and_vision() -> None:
    server = Server(flat(), "no visible text", flat())
    p = provider(server)
    assert p.model == TEXT_MODEL and p.last_model == TEXT_MODEL
    p.analyse("hi", ctx())
    assert p.last_model == TEXT_MODEL
    p.analyse("hi", ctx(), [att()])
    assert VISION_MODEL in p.last_model and TEXT_MODEL in p.last_model


# ---------------------------------------------------------------- attachments ---------------
SICK_OCR = (
    "MEDICAL CERTIFICATE Date of issue: 24 September 2026 Amy Lau is unfit for work from "
    "24 September 2026 to 25 September 2026 (2 days)"
)
SICK_DOC = {
    "doc_type": "sick_note",
    "person_name": "Amy Lau",
    "provider_name": "Sample Family Clinic",
    "issue_date": "2026-09-24",
    "rest_start_date": "2026-09-24",
    "rest_end_date": "2026-09-25",
    "days_advised": "2",
    "receipt_date": "",
    "total_amount": "",
    "currency": "",
    "suggested_claim_type": "",
    "unreadable_fields": [],
}


def test_image_attachment_uses_vision_model_then_text_model() -> None:
    server = Server(SICK_OCR, flat(intent="unclear", documents=[SICK_DOC]))
    turn = provider(server).analyse("", ctx(), [att(mime="image/jpeg")])
    vision, text = server.body(0), server.body(1)
    assert vision["model"] == VISION_MODEL and text["model"] == TEXT_MODEL
    assert "format" not in vision and vision["options"]["temperature"] == 0
    assert base64.b64decode(vision["messages"][0]["images"][0]) == SENTINEL + bytes([1])
    assert all("images" not in m for m in text["messages"])  # images go only to the vision call
    assert text["format"] == build_flat_schema(1)
    assert "<document index=0>" in text["messages"][1]["content"]
    assert turn.intent == Intent.CREATE_LEAVE
    assert turn.leave is not None and turn.leave.leave_type.value == "sick"  # type: ignore[union-attr]
    assert (turn.leave.start_date, turn.leave.end_date) == (date(2026, 9, 24), date(2026, 9, 25))
    (doc,) = turn.documents
    assert doc.doc_type == DocType.SICK_NOTE and doc.readable


def test_no_filename_email_or_raw_bytes_in_prompts() -> None:
    server = Server(SICK_OCR, flat(documents=[SICK_DOC]))
    provider(server).analyse("please file this", ctx(user_display_name=SECRET_EMAIL), [att()])
    for request in server.requests:
        raw = request.content.decode()
        assert FILENAME not in raw and SECRET_EMAIL not in raw
        for message in json.loads(raw)["messages"]:
            assert FILENAME not in message["content"]
            assert SENTINEL.decode() not in message["content"]


def test_pdf_is_rendered_to_png_pages_with_a_three_page_cap() -> None:
    server = Server(SICK_OCR, flat(documents=[SICK_DOC]))
    pdf = att(mime="application/pdf", data=make_pdf(5))
    provider(server).analyse("", ctx(), [pdf])
    images = server.body(0)["messages"][0]["images"]
    assert len(images) == 3
    for image in images:
        assert base64.b64decode(image).startswith(b"\x89PNG\r\n\x1a\n")


def test_sample_sick_note_pdf_goes_through_real_pdfium() -> None:
    server = Server(SICK_OCR, flat(documents=[SICK_DOC]))
    sample = AttachmentInput(
        id=1,
        filename="sick-note-sample.pdf",
        content_type="application/pdf",
        data=(SAMPLES / "sick-note-sample.pdf").read_bytes(),
    )
    provider(server).analyse("", ctx(), [sample])
    images = server.body(0)["messages"][0]["images"]
    assert len(images) == 1 and base64.b64decode(images[0]).startswith(b"\x89PNG")


def test_transparent_png_is_flattened_before_sending() -> None:
    data = (SAMPLES / "receipt-sample.png").read_bytes()
    server = Server("Sample Noodle House total 83.60", flat())
    png = AttachmentInput(id=1, filename="r.png", content_type="image/png", data=data)
    provider(server).analyse("claim", ctx(), [png])
    sent = base64.b64decode(server.body(0)["messages"][0]["images"][0])
    assert sent != data and sent[25] == 2  # PNG colour type 2: RGB, no alpha


def test_unreadable_file_without_text_skips_the_text_model() -> None:
    server = Server("There are no visible lines of text in the image.")
    turn = provider(server).analyse("", ctx(), [att()])
    assert len(server.requests) == 1  # only the vision call
    assert turn.intent == Intent.UNCLEAR
    assert [(d.doc_type, d.readable) for d in turn.documents] == [(DocType.UNREADABLE, False)]


def test_unreadable_file_with_text_still_analyses_the_text() -> None:
    server = Server(
        "...", flat(intent="create_claim", request_type="claim", amount="50", currency="HKD")
    )
    turn = provider(server).analyse("claim HKD 50 for a taxi", ctx(), [att()])
    assert len(server.requests) == 2
    assert server.body(1)["format"] == build_flat_schema(0)  # no documents section
    assert turn.claim is not None and turn.claim.amount == 50.0
    assert turn.documents[0].doc_type == DocType.UNREADABLE


def test_two_attachments_first_unreadable_keeps_positions() -> None:
    server = Server("blank", SICK_OCR, flat(documents=[SICK_DOC]))
    turn = provider(server).analyse("", ctx(), [att(1), att(2)])
    assert len(server.requests) == 3
    assert "<document index=1>" in server.body(2)["messages"][1]["content"]
    assert [d.doc_type for d in turn.documents] == [DocType.UNREADABLE, DocType.SICK_NOTE]
    assert [d.index for d in turn.documents] == [0, 1]


def test_attachment_validation() -> None:
    server = Server()
    p = provider(server)
    with pytest.raises(LLMError, match="Unsupported attachment type"):
        p.analyse("x", ctx(), [att(mime="text/plain")])
    with pytest.raises(LLMError, match="Too many attachments"):
        p.analyse("x", ctx(), [att(i) for i in range(1, 5)])
    assert server.requests == []


def test_corrupt_pdf_is_a_safe_llm_error() -> None:
    server = Server()
    with pytest.raises(LLMError, match="Could not read the PDF"):
        provider(server).analyse("", ctx(), [att(mime="application/pdf", data=b"not a pdf")])
    assert server.requests == []


# ---------------------------------------------------------------- retry -------------------------
def test_invalid_json_is_retried_once_with_a_correction() -> None:
    server = Server("this is not json", flat(intent="help"))
    turn = provider(server).analyse("hi", ctx())
    assert turn.intent == Intent.HELP and len(server.requests) == 2
    first = server.body(0)["messages"][1]["content"]
    second = server.body(1)["messages"][1]["content"]
    assert "not valid" not in first and "not valid JSON" in second


def test_invalid_field_is_retried_naming_only_the_field() -> None:
    server = Server(flat(intent="create_leave", start_date="next monday"), flat(intent="help"))
    provider(server).analyse("hi", ctx())
    assert "leave.start_date" in server.body(1)["messages"][1]["content"]


def test_two_invalid_replies_raise_llm_output_error(caplog: pytest.LogCaptureFixture) -> None:
    server = Server("nope", '{"intent": "approve_everything"}')
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMOutputError) as info:
        provider(server).analyse("SECRET-USER-TEXT", ctx())
    assert len(server.requests) == 2
    assert str(info.value) == "Ollama returned an invalid structured response"
    assert "SECRET-USER-TEXT" not in caplog.text and "approve_everything" not in caplog.text


# ---------------------------------------------------------------- errors --------------------
@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (httpx.ConnectError("boom to secret-host"), f"Ollama is not reachable at {BASE}"),
        (httpx.ReadTimeout("slow"), "Ollama request timed out"),
        (httpx.RemoteProtocolError("weird"), "Ollama request failed"),
        (httpx.Response(404, json={"error": "model not found SECRET-BODY"}), TEXT_MODEL),
        (httpx.Response(500, text="internal SECRET-BODY"), "Ollama returned HTTP 500"),
        (httpx.Response(503, text="busy"), "Ollama returned HTTP 503"),
        (httpx.Response(200, text="<html>not json</html>"), "invalid response"),
        (httpx.Response(200, json={"unexpected": True}), "invalid response"),
    ],
)
def test_transport_errors_map_to_safe_llm_errors(
    outcome: Any, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    server = Server(outcome)
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMError) as info:
        provider(server).analyse("SECRET-USER-TEXT", ctx())
    assert not isinstance(info.value, LLMOutputError)
    assert message in str(info.value)
    for secret in ("SECRET-BODY", "SECRET-USER-TEXT", "secret-host", "boom"):
        assert secret not in str(info.value) and secret not in caplog.text
    assert len(server.requests) == 1  # transport failures are not retried here


def test_missing_model_message_names_the_pull_command() -> None:
    server = Server(httpx.Response(404, json={"error": "x"}))
    with pytest.raises(LLMError, match=f"ollama pull {TEXT_MODEL}"):
        provider(server).analyse("hi", ctx())


def test_missing_vision_model_names_the_vision_model() -> None:
    server = Server(httpx.Response(404, json={"error": "x"}))
    with pytest.raises(LLMError, match=VISION_MODEL):
        provider(server).analyse("", ctx(), [att()])


def test_null_content_is_an_invalid_output() -> None:
    server = Server({"message": {"content": None}}, {"message": {"content": None}})
    server.outcomes = [
        httpx.Response(200, json={"message": {"content": None}}),
        httpx.Response(200, json={"message": {"content": None}}),
    ]
    with pytest.raises(LLMOutputError):
        provider(server).analyse("hi", ctx())


def test_logs_never_contain_bytes_ocr_text_or_filenames(caplog: pytest.LogCaptureFixture) -> None:
    server = Server(OCR_SECRET, "not json", "still not json")
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMOutputError):
        provider(server).analyse("USER-TEXT", ctx(), [att()])
    assert OCR_SECRET not in caplog.text and FILENAME not in caplog.text
    assert SENTINEL.decode() not in caplog.text and "USER-TEXT" not in caplog.text


# ---------------------------------------------------------------- timeouts ------------------
def test_first_call_to_a_model_gets_the_cold_timeout_then_the_configured_one() -> None:
    server = Server(flat(), flat(), "some ocr text long enough to count", flat(), flat())
    p = provider(server, ollama_timeout_seconds=30)
    p.analyse("hi", ctx())
    p.analyse("hi again", ctx())
    assert server.timeouts[:2] == [COLD_TIMEOUT, 30]
    p.analyse("", ctx(), [att()])  # the vision model is still cold
    assert server.timeouts[2:4] == [COLD_TIMEOUT, 30]


def test_a_long_configured_timeout_is_never_shortened() -> None:
    server = Server(flat())
    provider(server, ollama_timeout_seconds=600).analyse("hi", ctx())
    assert server.timeouts == [600]


def test_failed_first_call_keeps_the_model_cold() -> None:
    server = Server(httpx.ReadTimeout("slow"), flat())
    p = provider(server, ollama_timeout_seconds=30)
    with pytest.raises(LLMError):
        p.analyse("hi", ctx())
    p.analyse("hi", ctx())
    assert server.timeouts == [COLD_TIMEOUT, COLD_TIMEOUT]


def test_injected_client_is_used() -> None:
    server = Server(flat())
    client = httpx.Client(transport=httpx.MockTransport(server))
    OllamaProvider(settings(), client=client).analyse("hi", ctx())
    assert len(server.requests) == 1
