"""IN-19: two clicks on the same inbox card at the same moment have exactly one winner.

Needs a real file database (two connections); see tests/approvals/test_concurrency.py.
"""

import threading
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditEvent, LeaveRequest, Notification
from app.db.session import Database
from app.domain.enums import RequestStatus
from app.main import create_app
from tests.conftest import CSRF_HEADERS, login, make_settings
from tests.inbox.conftest import CATHY, start_inbox
from tests.inbox.helpers import act, inbox_cards


def _run_pair(a, b) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    barrier = threading.Barrier(2)
    results: dict[str, Any] = {}

    def run(name: str, fn) -> None:  # type: ignore[no-untyped-def]
        barrier.wait()
        results[name] = fn()

    threads = [
        threading.Thread(target=run, args=("a", a)),
        threading.Thread(target=run, args=("b", b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_a_double_click_on_approve_has_exactly_one_winner(file_db: Database) -> None:
    """The card is claimed with a compare-and-swap: the loser gets 409 and writes nothing."""
    app = create_app(make_settings(), database=file_db)
    with (
        TestClient(app, headers=CSRF_HEADERS) as one,
        TestClient(app, headers=CSRF_HEADERS) as two,
    ):
        login(one, CATHY)
        login(two, CATHY)
        body = start_inbox(one)
        conv_id, card_id = body["conversation"]["id"], inbox_cards(body)[0]["card_id"]
        results = _run_pair(
            lambda: act(one, conv_id, card_id, "approve", confirmed=True, note="a").status_code,
            lambda: act(two, conv_id, card_id, "reject", confirmed=True, note="b").status_code,
        )
        assert sorted(results.values()) == [200, 409], results
    with file_db.session_factory() as s:
        row = s.get(LeaveRequest, 1)
        assert row.status in (RequestStatus.APPROVED, RequestStatus.REJECTED)
        winner = "a" if row.reviewer_note == "a" else "b"
        assert results[winner] == 200
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == 1,
                AuditEvent.entity_type == "leave_request",
                AuditEvent.event_type.in_(["request.approved", "request.rejected"]),
            )
        ).all()
        assert len(events) == 1 and events[0].metadata_json["via"] == "inbox"
        notices = s.scalars(
            select(Notification).where(
                Notification.request_id == 1,
                Notification.event_type.in_(["request.approved", "request.rejected"]),
            )
        ).all()
        assert len(notices) == 1


def test_two_conversations_for_the_same_request_have_one_winner(file_db: Database) -> None:
    """Two inbox snapshots (two tabs) show the same request; the second decision finds it
    handled: its card becomes stale (200) and no second audit row is written."""
    app = create_app(make_settings(), database=file_db)
    with (
        TestClient(app, headers=CSRF_HEADERS) as one,
        TestClient(app, headers=CSRF_HEADERS) as two,
    ):
        login(one, CATHY)
        login(two, CATHY)
        first, second = start_inbox(one), start_inbox(two)
        results = _run_pair(
            lambda: act(
                one,
                first["conversation"]["id"],
                inbox_cards(first)[0]["card_id"],
                "approve",
                confirmed=True,
            ),
            lambda: act(
                two,
                second["conversation"]["id"],
                inbox_cards(second)[0]["card_id"],
                "approve",
                confirmed=True,
            ),
        )
    responses = list(results.values())
    assert [r.status_code for r in responses] == [200, 200]
    bodies = [r.json()["assistant_messages"][0]["content"] for r in responses]
    assert sorted(bodies) == [
        "That request was already handled.",
        "You approved leave request #1 from Amy Lau.",
    ]
    with file_db.session_factory() as s:
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == 1,
                AuditEvent.entity_type == "leave_request",
                AuditEvent.event_type == "request.approved",
            )
        ).all()
        assert len(events) == 1
        amy_notices = s.scalars(
            select(Notification).where(
                Notification.request_id == 1, Notification.event_type == "request.approved"
            )
        ).all()
        assert len(amy_notices) == 1
