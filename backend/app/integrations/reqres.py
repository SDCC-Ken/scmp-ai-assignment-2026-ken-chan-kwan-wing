"""ReqRes submission adapter: ``POST https://reqres.in/api/users`` (the hosted mock API).

This is the integration the assignment requires. The body is exactly ``payload.to_wire()``.
ReqRes currently needs no API key: ``x-api-key`` is sent only when REQRES_API_KEY is set. The
key, headers and raw response bodies never appear in results, logs or errors. No automatic
retries: POST is not idempotent, the user retries explicitly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.integrations.base import (
    ClaimSubmissionPayload,
    LeaveSubmissionPayload,
    SubmissionResult,
)

logger = logging.getLogger(__name__)


def _fail(message: str, http_status: int | None = None) -> SubmissionResult:
    return SubmissionResult(ok=False, http_status=http_status, error_message=message)


class ReqresSubmissionAdapter:
    provider = "reqres"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = settings.reqres_base_url
        self._api_key = settings.reqres_api_key.get_secret_value().strip()
        self._timeout = settings.submission_timeout_seconds
        self._transport = transport
        self._client = client

    def submit_leave(self, payload: LeaveSubmissionPayload) -> SubmissionResult:
        return self._post("leave", payload.to_wire())

    def submit_claim(self, payload: ClaimSubmissionPayload) -> SubmissionResult:
        if not payload.amount.is_finite():
            return _fail("Claim amount is not a valid number")
        return self._post("claim", payload.to_wire())

    # -- internals -------------------------------------------------------------------------
    def _post(self, kind: str, body: dict[str, Any]) -> SubmissionResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        try:
            if self._client is not None:
                response = self._client.post(self._url, json=body, headers=headers)
            else:
                timeout = httpx.Timeout(self._timeout)
                with httpx.Client(timeout=timeout, transport=self._transport) as client:
                    response = client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException:
            logger.warning("ReqRes %s submission timed out", kind)
            return _fail("ReqRes request timed out")
        except (httpx.HTTPError, httpx.InvalidURL):
            # Deliberately not logging the exception text: it may echo request details.
            logger.warning("ReqRes %s submission failed: network error", kind)
            return _fail("Could not reach ReqRes")
        return self._map_response(kind, response)

    @staticmethod
    def _map_response(kind: str, response: httpx.Response) -> SubmissionResult:
        status = response.status_code
        logger.info("ReqRes %s submission -> HTTP %d", kind, status)
        if status in (401, 403):
            return _fail(f"ReqRes rejected the request (HTTP {status})", status)
        if status == 429:
            return _fail("ReqRes rate limited the request", status)
        if not 200 <= status < 300:
            return _fail(f"ReqRes returned HTTP {status}", status)
        try:
            data = response.json()
        except ValueError:
            return _fail("ReqRes returned an invalid response")
        ref = data.get("id") if isinstance(data, dict) else None
        if isinstance(ref, bool) or not isinstance(ref, str | int) or ref == "":
            return _fail("ReqRes returned an unexpected response")
        summary: dict[str, Any] = {"id": ref}
        created = data.get("createdAt")
        if isinstance(created, str):
            summary["createdAt"] = created[:64]
        return SubmissionResult(
            ok=True,
            http_status=status,
            external_reference_id=str(ref),
            response_summary=summary,
        )
