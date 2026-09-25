"""ReqresSubmissionAdapter against httpx.MockTransport: no network."""

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.integrations.base import ClaimSubmissionPayload, LeaveSubmissionPayload
from app.integrations.reqres import ReqresSubmissionAdapter

KEY = "reqres-test-key-do-not-leak"
URL = "https://reqres.in/api/users"

LEAVE = LeaveSubmissionPayload(
    employee_email="eve.holt@reqres.in",
    leave_type="annual",
    start_date=date(2026, 10, 5),
    end_date=date(2026, 10, 7),
)
CLAIM = ClaimSubmissionPayload(
    employee_email="eve.holt@reqres.in",
    claim_type="travel",
    amount=Decimal("120.50"),
    receipt_date=date(2026, 9, 20),
)


def make_adapter(handler: Any, api_key: str = KEY, **kw: Any) -> ReqresSubmissionAdapter:
    settings = Settings(_env_file=None, reqres_api_key=api_key, **kw)
    return ReqresSubmissionAdapter(settings, transport=httpx.MockTransport(handler))


class Recorder:
    def __init__(self, response: httpx.Response | Exception | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(
            201, json={"id": "531", "createdAt": "2026-09-25T04:00:00.000Z"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_leave_request_shape_and_success_mapping() -> None:
    rec = Recorder(
        httpx.Response(
            201,
            json={
                "id": "531",
                "createdAt": "2026-09-25T04:00:00.000Z",
                "email": "eve.holt@reqres.in",
                "leave_type": "Annual",
                "_meta": {"secret": "ignored"},
            },
        )
    )
    result = make_adapter(rec).submit_leave(LEAVE)
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == URL
    assert req.headers["x-api-key"] == KEY
    assert req.headers["content-type"] == "application/json"
    body = json.loads(req.content)
    assert body == {
        "email": "eve.holt@reqres.in",
        "leave_type": "Annual",
        "start_date": "2026-10-05",
        "end_date": "2026-10-07",
    }
    assert body == LEAVE.to_wire() and len(body) == 4
    assert result.ok and result.http_status == 201
    assert result.external_reference_id == "531"
    assert result.response_summary == {"id": "531", "createdAt": "2026-09-25T04:00:00.000Z"}
    assert result.error_message is None
    assert "_meta" not in result.model_dump_json() and KEY not in result.model_dump_json()


def test_claim_request_shape_amount_is_json_number() -> None:
    rec = Recorder()
    result = make_adapter(rec).submit_claim(CLAIM)
    req = rec.requests[0]
    body = json.loads(req.content)
    assert body == {
        "email": "eve.holt@reqres.in",
        "claim_type": "Travel",
        "amount": 120.5,
        "receipt_date": "2026-09-20",
    }
    assert len(body) == 4 and isinstance(body["amount"], float)
    assert b'"amount":120.5' in req.content.replace(b" ", b"")
    assert result.ok and result.external_reference_id == "531"


def test_integer_reference_id_is_stringified_and_bool_is_rejected() -> None:
    ok = make_adapter(Recorder(httpx.Response(201, json={"id": 23}))).submit_leave(LEAVE)
    assert ok.ok and ok.external_reference_id == "23" and ok.response_summary == {"id": 23}
    bad = make_adapter(Recorder(httpx.Response(201, json={"id": True}))).submit_leave(LEAVE)
    assert not bad.ok


def test_no_key_still_sends_request_without_header() -> None:
    rec = Recorder()
    result = make_adapter(rec, api_key="").submit_leave(LEAVE)
    assert len(rec.requests) == 1
    assert "x-api-key" not in rec.requests[0].headers
    assert result.ok


def test_custom_base_url_and_timeout_are_used() -> None:
    rec = Recorder()
    make_adapter(rec, reqres_base_url="https://mock.example.test/api/users").submit_claim(CLAIM)
    assert str(rec.requests[0].url) == "https://mock.example.test/api/users"


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "ReqRes rejected the request (HTTP 401)"),
        (403, "ReqRes rejected the request (HTTP 403)"),
        (429, "ReqRes rate limited the request"),
        (400, "ReqRes returned HTTP 400"),
        (404, "ReqRes returned HTTP 404"),
        (500, "ReqRes returned HTTP 500"),
        (503, "ReqRes returned HTTP 503"),
        (302, "ReqRes returned HTTP 302"),
    ],
)
def test_http_error_mapping(status: int, message: str) -> None:
    body = {"error": f"leaky {KEY} body"}
    rec = Recorder(httpx.Response(status, json=body, headers={"set-cookie": "s=1"}))
    result = make_adapter(rec).submit_leave(LEAVE)
    assert not result.ok
    assert result.http_status == status
    assert result.error_message == message
    assert result.external_reference_id is None and result.response_summary == {}
    assert len(rec.requests) == 1  # never retried
    dumped = result.model_dump_json()
    assert KEY not in dumped and "leaky" not in dumped


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.ConnectTimeout(f"t {KEY}"), "ReqRes request timed out"),
        (httpx.ReadTimeout(f"t {KEY}"), "ReqRes request timed out"),
        (httpx.ConnectError(f"c {KEY}"), "Could not reach ReqRes"),
        (httpx.ReadError(f"r {KEY}"), "Could not reach ReqRes"),
    ],
)
def test_timeout_and_network_errors(
    exc: Exception, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rec = Recorder(exc)
    result = make_adapter(rec).submit_claim(CLAIM)
    assert not result.ok and result.http_status is None
    assert result.error_message == message
    assert len(rec.requests) == 1
    assert KEY not in caplog.text and KEY not in result.model_dump_json()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, content=b"<html>oops</html>"),
        httpx.Response(200, content=b""),
        httpx.Response(201, json=["not", "an", "object"]),
        httpx.Response(201, json={"createdAt": "x"}),
        httpx.Response(201, json={"id": ""}),
        httpx.Response(201, json={"id": {"nested": 1}}),
    ],
)
def test_invalid_or_unexpected_success_body_is_a_failure(response: httpx.Response) -> None:
    result = make_adapter(Recorder(response)).submit_leave(LEAVE)
    assert not result.ok and result.http_status is None
    assert result.error_message
    assert "oops" not in result.model_dump_json()


def test_secrets_and_payload_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    make_adapter(Recorder()).submit_leave(LEAVE)
    make_adapter(Recorder()).submit_claim(CLAIM)
    make_adapter(Recorder(httpx.Response(401, json={}))).submit_leave(LEAVE)
    make_adapter(Recorder(httpx.ReadTimeout("x"))).submit_claim(CLAIM)
    logged = caplog.text
    assert KEY not in logged
    assert "eve.holt@reqres.in" not in logged
    assert "120.5" not in logged
    assert "HTTP 201" in logged  # ids/status codes are fine


def test_non_finite_amount_is_rejected_without_request() -> None:
    rec = Recorder()
    nan_claim = ClaimSubmissionPayload.model_construct(
        employee_email="eve.holt@reqres.in",
        claim_type="travel",
        amount=Decimal("NaN"),
        receipt_date=date(2026, 9, 20),
    )
    result = make_adapter(rec).submit_claim(nan_claim)
    assert not result.ok and not rec.requests


def test_injected_client_is_used() -> None:
    rec = Recorder()
    client = httpx.Client(transport=httpx.MockTransport(rec))
    adapter = ReqresSubmissionAdapter(Settings(_env_file=None, reqres_api_key=KEY), client=client)
    assert adapter.submit_leave(LEAVE).ok
    assert len(rec.requests) == 1
    assert adapter.provider == "reqres"
