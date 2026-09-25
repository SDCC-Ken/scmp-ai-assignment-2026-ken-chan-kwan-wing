"""Two decisions at the same moment: exactly one wins (A-15).

This needs a real file database (two connections). The in-memory test database shares ONE
connection, which cannot interleave two transactions.
"""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditEvent, LeaveRequest, Notification
from app.db.session import Database
from app.domain.enums import RequestStatus, RequestType
from app.main import create_app
from app.seed import seed_demo_data
from app.services import approvals as service
from tests.approvals.conftest import CATHY, decide
from tests.conftest import CSRF_HEADERS, SEED_TODAY, get_user, login, make_settings


@pytest.fixture
def file_db(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'concurrent.db'}")
    database.init_db()
    with database.session_factory() as s:
        seed_demo_data(s, today=SEED_TODAY)
    yield database
    database.dispose()


@pytest.mark.parametrize("second_decision", ["approve", "reject"])
def test_concurrent_decisions_have_exactly_one_winner(
    file_db: Database, second_decision: str
) -> None:
    """A-15: the loser gets 409, one audit row, one requester notification."""
    app = create_app(make_settings(), database=file_db)
    with (
        TestClient(app, headers=CSRF_HEADERS) as one,
        TestClient(app, headers=CSRF_HEADERS) as two,
    ):
        login(one, CATHY)
        login(two, CATHY)
        barrier = threading.Barrier(2)
        results: dict[str, int] = {}

        def run(name: str, client: TestClient, decision: str) -> None:
            barrier.wait()
            results[name] = decide(client, "leave", 1, decision, f"note {name}").status_code

        threads = [
            threading.Thread(target=run, args=("a", one, "approve")),
            threading.Thread(target=run, args=("b", two, second_decision)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert sorted(results.values()) == [200, 409], results

    with file_db.session_factory() as s:
        row = s.get(LeaveRequest, 1)
        assert row.status in (RequestStatus.APPROVED, RequestStatus.REJECTED)
        winner = "a" if row.reviewer_note == "note a" else "b"
        assert results[winner] == 200
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "leave_request",
                AuditEvent.entity_id == 1,
                AuditEvent.event_type.in_(["request.approved", "request.rejected"]),
            )
        ).all()
        assert len(events) == 1 and events[0].to_status == row.status.value
        outcomes = s.scalars(
            select(Notification).where(
                Notification.request_id == 1,
                Notification.event_type.in_(["request.approved", "request.rejected"]),
            )
        ).all()
        assert len(outcomes) == 1


def test_a_decision_that_loses_after_its_status_check_is_a_conflict(
    file_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-15 (deterministic): the request is decided by someone else AFTER our status check but
    before our write. The conditional UPDATE matches no row, so we get a conflict and write
    nothing (no second audit row, no second notification)."""
    cathy = get_user(file_db, CATHY)
    real_context = service.limit_context
    raced = {"done": False}

    def context_then_race(session, req):  # type: ignore[no-untyped-def]
        context = real_context(session, req)
        if not raced["done"]:
            raced["done"] = True
            with file_db.session_factory() as other:
                service.decide(other, cathy, RequestType.LEAVE, 1, "reject", "first")
        return context

    monkeypatch.setattr(service, "limit_context", context_then_race)
    with file_db.session_factory() as session, pytest.raises(service.ApprovalConflict):
        service.decide(session, cathy, RequestType.LEAVE, 1, "approve", "late")

    with file_db.session_factory() as s:
        row = s.get(LeaveRequest, 1)
        assert row.status == RequestStatus.REJECTED and row.reviewer_note == "first"
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "leave_request",
                AuditEvent.entity_id == 1,
                AuditEvent.event_type.in_(["request.approved", "request.rejected"]),
            )
        ).all()
        assert [e.event_type for e in events] == ["request.rejected"]
