"""CONFIRM flow: stale cards, double clicks, adapter failure + retry, wire payload, no DB lock."""

import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import (
    AuditEvent,
    ClaimRequest,
    ExternalSubmission,
    LeaveRequest,
    Notification,
)
from app.db.session import Database
from app.domain.enums import DayPart, LeaveType, RequestStatus
from app.main import create_app
from app.seed import seed_demo_data
from tests.chat.helpers import (
    AM,
    FULL_LEAVE,
    PM,
    VALID_CLAIM,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    card_of,
    claim_turn,
    d,
    details_leave,
    leave_turn,
    text_of,
    ui_of,
)
from tests.conftest import CSRF_HEADERS, SEED_TODAY, login, make_settings

CATHY = "cathy.ng@example.com"


def count(db: Database, model: type) -> int:
    with db.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


# ---- stale / unknown / double confirm -----------------------------------------------------------
def test_confirm_without_an_open_card_is_409(chat: Chat) -> None:
    """FC-01"""
    resp = chat.act_raw("c_doesnotexist")
    assert resp.status_code == 409
    assert resp.json()["warning_code"] == "stale_card"
    assert chat.act_raw("c_doesnotexist", "discard").status_code == 409


def test_superseded_card_is_409_and_the_new_card_still_works(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-02"""
    llm.push(leave_turn(**FULL_LEAVE))
    old = card_of(chat.say("annual leave 5-7 Oct"))
    llm.push(details_leave(end_date=d("2026-10-08")))
    new = card_of(chat.say("make it the 8th"))
    assert new["card_id"] != old["card_id"]
    states = {
        m["ui"]["card_id"]: m["ui"]["state"]
        for m in chat.detail()["messages"]
        if m["ui"] and m["ui"]["type"] == "confirmation_card"
    }
    assert states == {old["card_id"]: "superseded", new["card_id"]: "open"}
    stale = chat.act_raw(old["card_id"])
    assert stale.status_code == 409 and stale.json()["warning_code"] == "stale_card"
    assert adapter.calls == []
    done = chat.act(new["card_id"])
    assert ui_of(done)["outcome"] == "submitted"
    assert adapter.calls[0][1]["end_date"] == "2026-10-08"


def test_card_from_another_conversation_is_409(
    cathy: TestClient, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """FC-03"""
    first, second = Chat(cathy), Chat(cathy)
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(first.say("annual leave"))
    assert second.act_raw(card["card_id"]).status_code == 409
    assert adapter.calls == []


def test_double_confirm_creates_exactly_one_request_and_one_external_call(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-04"""
    before = count(seeded, LeaveRequest)
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    assert chat.act_raw(card["card_id"]).status_code == 200
    second = chat.act_raw(card["card_id"])
    assert second.status_code == 409 and second.json()["warning_code"] == "stale_card"
    assert count(seeded, LeaveRequest) == before + 1
    assert len(adapter.calls) == 1


@pytest.fixture
def file_db(tmp_path: Path) -> Iterator[Database]:
    """A real SQLite file, so a second connection can prove the database is not locked."""
    db = Database(f"sqlite:///{tmp_path}/chat.db")
    db.init_db()
    with db.session_factory() as s:
        seed_demo_data(s, today=SEED_TODAY)
    yield db
    db.dispose()


def make_file_app(db: Database, llm: ScriptedLLM, adapter: RecordingAdapter) -> FastAPI:
    return create_app(
        make_settings(database_url=db.url),
        database=db,
        llm_provider=llm,
        submission_adapter=adapter,
    )


def test_concurrent_confirms_have_exactly_one_winner(
    file_db: Database, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """FC-05: two clicks racing (compare-and-swap on state_version): one 200, one 409."""
    app = make_file_app(file_db, llm, adapter)
    adapter.on_call = lambda: threading.Event().wait(0.3)  # keep the winner "in flight"
    with TestClient(app, headers=CSRF_HEADERS) as one, TestClient(app, headers=CSRF_HEADERS) as two:
        login(one, CATHY)
        login(two, CATHY)
        chat = Chat(one)
        llm.push(leave_turn(**FULL_LEAVE))
        card = card_of(chat.say("annual leave"))
        before = count(file_db, LeaveRequest)
        barrier = threading.Barrier(2)

        def click(client: TestClient) -> int:
            barrier.wait()
            return client.post(
                f"/api/chat/conversations/{chat.id}/actions",
                json={"card_id": card["card_id"], "action": "confirm"},
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            codes = sorted(pool.map(click, [one, two]))
    assert codes == [200, 409]
    assert count(file_db, LeaveRequest) == before + 1
    assert len(adapter.calls) == 1


def test_database_is_not_locked_during_the_adapter_and_llm_calls(
    file_db: Database, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """FC-06: a second connection can WRITE while the LLM / HTTP call is in flight."""
    path = file_db.engine.url.database
    probes: list[str] = []

    def probe(label: str):
        def run() -> None:
            conn = sqlite3.connect(path, timeout=0.3)
            try:
                conn.execute("UPDATE users SET display_name = display_name WHERE id = 1")
                conn.commit()
                probes.append(f"{label}: writable")
            except sqlite3.OperationalError as exc:  # "database is locked"
                probes.append(f"{label}: {exc}")
            finally:
                conn.close()

        return run

    llm.on_call = probe("llm")
    adapter.on_call = probe("adapter")
    with TestClient(make_file_app(file_db, llm, adapter), headers=CSRF_HEADERS) as client:
        login(client, CATHY)
        chat = Chat(client)
        llm.push(leave_turn(**FULL_LEAVE))
        card = card_of(chat.say("annual leave"))
        chat.act(card["card_id"])
    assert probes == ["llm: writable", "adapter: writable"]


# ---- adapter failure and retry -------------------------------------------------------------------
def test_adapter_failure_saves_submission_failed_then_retry_succeeds(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-07"""
    adapter.fail_next(503, "Service unavailable")
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    failed = chat.act(card["card_id"])

    assert failed["warning_code"] == "submission_failed"
    first, second = failed["assistant_messages"]
    assert first["ui"]["type"] == "result_card" and first["ui"]["outcome"] == "failed"
    assert first["ui"]["status"] == "submission_failed"
    assert "Service unavailable" in first["content"]
    retry = second["ui"]
    assert retry["type"] == "confirmation_card" and retry["action"] == "retry"
    assert retry["confirm_label"] == "Retry" and retry["state"] == "open"
    rid = retry["request_id"]

    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, rid)
        assert row.status == RequestStatus.SUBMISSION_FAILED and row.submitted_at is None
        sub = s.scalars(
            select(ExternalSubmission).where(
                ExternalSubmission.request_id == rid, ExternalSubmission.request_type == "leave"
            )
        ).one()
        assert sub.status.value == "failed" and sub.http_status == 503
        assert sub.error_message == "Service unavailable"
        assert sub.request_payload_json["email"] == CATHY  # what was attempted is on record
        events = [
            (e.event_type, e.from_status, e.to_status)
            for e in s.scalars(
                select(AuditEvent)
                .where(AuditEvent.entity_type == "leave_request", AuditEvent.entity_id == rid)
                .order_by(AuditEvent.id)
            )
        ]
        assert events == [
            ("request.created", None, "draft"),
            ("request.confirmed", None, None),
            ("submission.failed", "draft", "submission_failed"),
        ]
        assert (
            s.scalars(
                select(Notification).where(
                    Notification.request_id == rid, Notification.request_type == "leave"
                )
            ).all()
            == []
        )

    assert chat.detail()["conversation"]["has_pending_card"] is True
    done = chat.act(retry["card_id"])
    assert ui_of(done)["outcome"] == "submitted" and ui_of(done)["status"] == "pending_approval"
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, rid)
        assert row.status == RequestStatus.PENDING_APPROVAL and row.submitted_at is not None
        subs = s.scalars(
            select(ExternalSubmission)
            .where(ExternalSubmission.request_id == rid, ExternalSubmission.request_type == "leave")
            .order_by(ExternalSubmission.id)
        ).all()
        assert [x.status.value for x in subs] == ["failed", "success"]
        notes = s.scalars(
            select(Notification).where(
                Notification.request_id == rid, Notification.request_type == "leave"
            )
        ).all()
        assert len(notes) == 1
        types = [
            e.event_type
            for e in s.scalars(
                select(AuditEvent)
                .where(AuditEvent.entity_type == "leave_request", AuditEvent.entity_id == rid)
                .order_by(AuditEvent.id)
            )
        ]
        assert types[-1] == "submission.succeeded"
    assert len(adapter.calls) == 2 and adapter.calls[0][1] == adapter.calls[1][1]


def test_retry_that_fails_again_offers_another_retry(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-08"""
    adapter.fail_next()
    adapter.fail_next(500, "Internal error")
    llm.push(leave_turn(**FULL_LEAVE))
    failed = chat.act(card_of(chat.say("annual leave"))["card_id"])
    again = chat.act(failed["assistant_messages"][1]["ui"]["card_id"])
    assert again["warning_code"] == "submission_failed"
    retry = again["assistant_messages"][1]["ui"]
    assert retry["action"] == "retry"
    rid = retry["request_id"]
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, rid).status == RequestStatus.SUBMISSION_FAILED
    assert ui_of(chat.act(retry["card_id"]))["outcome"] == "submitted"


def test_adapter_that_raises_is_handled_like_a_failed_submission(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-09"""

    def boom() -> None:
        raise RuntimeError("socket exploded with secret-key-123")

    adapter.on_call = boom
    llm.push(claim_turn(**VALID_CLAIM))
    failed = chat.act(card_of(chat.say("claim"))["card_id"])
    assert failed["warning_code"] == "submission_failed"
    assert "secret-key-123" not in str(failed)
    rid = failed["assistant_messages"][0]["ui"]["request_id"]
    with seeded.session_factory() as s:
        assert s.get(ClaimRequest, rid).status == RequestStatus.SUBMISSION_FAILED


# ---- only the defined fields leave the system ------------------------------------------------
def test_leave_wire_body_contains_only_the_defined_fields(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-10: half-day parts and working days stay in SQLite."""
    llm.push(
        leave_turn(
            leave_type=LeaveType.PERSONAL,
            start_date=d("2026-10-05"),
            end_date=d("2026-10-07"),
            start_day_part=PM,
            end_day_part=AM,
        )
    )
    done = chat.act(card_of(chat.say("personal leave"))["card_id"])
    kind, body = adapter.calls[0]
    assert kind == "leave"
    assert set(body) == {"email", "leave_type", "start_date", "end_date"}
    assert body == {
        "email": CATHY,
        "leave_type": "Personal",
        "start_date": "2026-10-05",
        "end_date": "2026-10-07",
    }
    assert set(adapter.payloads[0].model_dump()) == {
        "employee_email",
        "leave_type",
        "start_date",
        "end_date",
    }
    rid = ui_of(done)["request_id"]
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, rid)
        assert (row.start_day_part, row.end_day_part) == (DayPart.PM, DayPart.AM)
        assert float(row.working_days) == 2.0
        sub = s.scalars(
            select(ExternalSubmission).where(
                ExternalSubmission.request_id == rid, ExternalSubmission.request_type == "leave"
            )
        ).one()
        assert sub.request_payload_json == body  # exactly what was sent


def test_claim_wire_body_contains_only_the_defined_fields(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """FC-11: the currency stays in SQLite."""
    llm.push(claim_turn(**VALID_CLAIM, currency="hkd"))
    done = chat.act(card_of(chat.say("claim"))["card_id"])
    kind, body = adapter.calls[0]
    assert kind == "claim"
    assert set(body) == {"email", "claim_type", "amount", "receipt_date"}
    assert body == {
        "email": CATHY,
        "claim_type": "Travel",
        "amount": 120.0,
        "receipt_date": "2026-09-20",
    }
    assert set(adapter.payloads[0].model_dump()) == {
        "employee_email",
        "claim_type",
        "amount",
        "receipt_date",
    }
    rid = ui_of(done)["request_id"]
    with seeded.session_factory() as s:
        assert s.get(ClaimRequest, rid).currency == "HKD"
        sub = s.scalars(
            select(ExternalSubmission).where(
                ExternalSubmission.request_id == rid, ExternalSubmission.request_type == "claim"
            )
        ).one()
        assert sub.request_payload_json == body


def test_fake_provider_is_never_presented_as_reqres(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """FC-12"""
    llm.push(leave_turn(**FULL_LEAVE))
    done = chat.act(card_of(chat.say("annual leave"))["card_id"])
    assert 'offline "fake" adapter (not ReqRes)' in text_of(done)
    adapter.provider = "reqres"
    llm.push(leave_turn(**FULL_LEAVE))
    done = chat.act(card_of(chat.say("annual leave again"))["card_id"])
    assert "the ReqRes mock API" in text_of(done) and "offline" not in text_of(done)


def test_confirm_shows_a_submit_trace(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """FC-13"""
    llm.push(leave_turn(**FULL_LEAVE))
    done = chat.act(card_of(chat.say("annual leave"))["card_id"])
    trace = done["assistant_messages"][0]["trace"]
    assert [t["step"] for t in trace] == ["submit", "submit", "submit"]
    assert trace[1]["label"].startswith("Sent to")
    assert CATHY not in str(trace)
