"""Bounded live smoke test for the ReqRes adapter (NOT collected by pytest).

    RUN_LIVE_REQRES=1 uv run python scripts/live_reqres_smoke.py

Makes exactly TWO real POSTs to the hosted mock API (one leave, one claim) using the
fictional email from the assignment spec, through ``ReqresSubmissionAdapter``. Prints only
status codes, reference ids and the wire bodies (fictional). Never prints settings or keys.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.integrations.base import ClaimSubmissionPayload, LeaveSubmissionPayload  # noqa: E402
from app.integrations.reqres import ReqresSubmissionAdapter  # noqa: E402

EMAIL = "eve.holt@reqres.in"  # fictional, from the assignment spec


def main() -> int:
    if os.environ.get("RUN_LIVE_REQRES") != "1":
        print("Refusing to run: set RUN_LIVE_REQRES=1 to allow two live ReqRes POSTs.")
        return 2
    settings = Settings()
    adapter = ReqresSubmissionAdapter(settings)
    has_key = bool(settings.reqres_api_key.get_secret_value())
    print(f"url={settings.reqres_base_url} key_configured={has_key}")
    leave = LeaveSubmissionPayload(
        employee_email=EMAIL,
        leave_type="annual",
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 7),
    )
    claim = ClaimSubmissionPayload(
        employee_email=EMAIL,
        claim_type="travel",
        amount=Decimal("120.50"),
        receipt_date=date(2026, 9, 20),
    )
    ok = True
    for kind, payload, submit in (
        ("leave", leave, adapter.submit_leave),
        ("claim", claim, adapter.submit_claim),
    ):
        result = submit(payload)
        ok &= result.ok
        print(f"{kind}: body={payload.to_wire()}")
        print(
            f"  -> ok={result.ok} http={result.http_status} ref={result.external_reference_id} "
            f"summary={result.response_summary} error={result.error_message}"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
