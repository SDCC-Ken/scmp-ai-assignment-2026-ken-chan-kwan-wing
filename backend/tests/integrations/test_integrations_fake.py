from datetime import date
from decimal import Decimal

from app.integrations.base import ClaimSubmissionPayload, LeaveSubmissionPayload
from app.integrations.fake import FakeSubmissionAdapter

LEAVE = LeaveSubmissionPayload(
    employee_email="a@example.test",
    leave_type="sick",
    start_date=date(2026, 10, 5),
    end_date=date(2026, 10, 5),
)
CLAIM = ClaimSubmissionPayload(
    employee_email="a@example.test",
    claim_type="meal",
    amount=Decimal("88"),
    receipt_date=date(2026, 9, 20),
)


def test_records_payload_and_wire_body_and_returns_sequential_ids() -> None:
    fake = FakeSubmissionAdapter()
    first = fake.submit_leave(LEAVE)
    second = fake.submit_claim(CLAIM)
    assert fake.provider == "fake"
    assert (first.ok, first.external_reference_id) == (True, "fake-1")
    assert (second.ok, second.external_reference_id) == (True, "fake-2")
    assert [c.kind for c in fake.calls] == ["leave", "claim"]
    assert fake.calls[0].payload == LEAVE
    assert fake.calls[0].body == {
        "email": "a@example.test",
        "leave_type": "Sick",
        "start_date": "2026-10-05",
        "end_date": "2026-10-05",
    }
    assert fake.calls[1].body["amount"] == 88.0


def test_fail_with_is_persistent_until_succeed() -> None:
    fake = FakeSubmissionAdapter()
    fake.fail_with(500, "boom")
    for _ in range(2):
        result = fake.submit_leave(LEAVE)
        assert (result.ok, result.http_status, result.error_message) == (False, 500, "boom")
    fake.succeed()
    assert fake.submit_leave(LEAVE).ok
    assert len(fake.calls) == 3  # failed attempts are recorded too


def test_fail_next_counts_down() -> None:
    fake = FakeSubmissionAdapter()
    fake.fail_next(2)
    assert [fake.submit_claim(CLAIM).ok for _ in range(3)] == [False, False, True]
    assert fake.calls[-1].payload == CLAIM


def test_raise_timeout_returns_a_timeout_failure_once() -> None:
    fake = FakeSubmissionAdapter()
    fake.raise_timeout()
    timed_out = fake.submit_leave(LEAVE)
    assert not timed_out.ok and timed_out.http_status is None
    assert "timed out" in (timed_out.error_message or "")
    assert fake.submit_leave(LEAVE).ok
