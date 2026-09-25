"""User shape (department, title, can_request, approves), requester gate, /api/me/balances."""

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import REQUESTER_FORBIDDEN_DETAIL
from app.db.models import User
from app.db.session import Database
from tests.conftest import SEED_TODAY, auth, get_user, login
from tests.inbox.helpers import strip_capabilities

AMY = "amy.lau@example.com"
BEN = "ben.chow@example.com"
CATHY = "cathy.ng@example.com"
DANIEL = "daniel.wong@example.com"
HELEN = "helen.yeung@example.com"
EVA = "eva.cheung@example.com"

# email -> (department, role, job title, can_request, approves)
EXPECTED = {
    AMY: ("IT", "employee", "Software Engineer", True, None),
    BEN: ("IT", "employee", "Software Engineer", True, None),
    CATHY: ("HR", "hr_approver", "HR Business Partner (IT)", True, "leave"),
    DANIEL: ("HR", "employee", "HR Officer", True, None),
    HELEN: ("HR", "hr_approver", "HR Manager", False, "leave"),
    EVA: ("Finance", "finance_approver", "Finance Manager", False, "claim"),
}


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.me.today_hk", lambda: SEED_TODAY)


# ---- the UserPublic shape --------------------------------------------------------------------


@pytest.mark.parametrize("email", list(EXPECTED))
def test_login_and_me_carry_the_organisation_fields(client: TestClient, email: str) -> None:
    dept, role, title, can_request, approves = EXPECTED[email]
    login_body = client.post("/api/auth/mock-google/login", json={"email": email}).json()["user"]
    me = client.get("/api/auth/me").json()
    assert login_body == me
    assert me["email"] == email and me["role"] == role and me["job_title"] == title
    assert me["department"]["name"] == dept and isinstance(me["department"]["id"], int)
    assert me["can_request"] is can_request and me["approves"] == approves
    assert set(me) == {
        "id",
        "email",
        "display_name",
        "role",
        "department",
        "job_title",
        "can_request",
        "approves",
    }
    assert "google_subject" not in str(me)


def test_mock_users_carry_the_same_shape_in_the_documented_order(client: TestClient) -> None:
    users = client.get("/api/auth/mock-users").json()
    assert [u["email"] for u in users] == [AMY, BEN, DANIEL, CATHY, HELEN, EVA]
    for u in users:
        dept, role, title, can_request, approves = EXPECTED[u["email"]]
        assert (u["department"]["name"], u["role"], u["job_title"]) == (dept, role, title)
        assert (u["can_request"], u["approves"]) == (can_request, approves)


def test_a_user_without_a_department_serialises_as_null(
    client: TestClient, seeded: Database
) -> None:
    with seeded.session_factory() as s:
        user = s.query(User).filter_by(email=AMY).one()
        user.department_id, user.job_title = None, None
        s.commit()
    login(client, AMY)
    me = client.get("/api/auth/me").json()
    assert me["department"] is None and me["job_title"] is None


def test_can_request_follows_the_configured_approvers_live(
    client: TestClient, seeded: Database
) -> None:
    login(client, AMY)
    assert client.get("/api/auth/me").json()["can_request"] is True
    with seeded.session_factory() as s:
        user = s.query(User).filter_by(email=AMY).one()
        user.leave_approver_user_id = None
        s.commit()
    assert client.get("/api/auth/me").json()["can_request"] is True  # the claim approver remains
    with seeded.session_factory() as s:
        user = s.query(User).filter_by(email=AMY).one()
        user.claim_approver_user_id = None
        s.commit()
    assert client.get("/api/auth/me").json()["can_request"] is False


# ---- require_requester on the chat --------------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "status"),
    [(AMY, 200), (BEN, 200), (CATHY, 200), (DANIEL, 200), (HELEN, 200), (EVA, 200)],
)
def test_requester_matrix_on_the_chat(client: TestClient, email: str, status: int) -> None:
    """Everybody in the seed may use the chat: requesters file, Helen and Eva use the bell
    inbox (they decide a queue). A user with neither capability is refused (next test)."""
    token = login(client, email)
    response = client.get("/api/chat/conversations", headers=auth(token))
    assert response.status_code == status, response.text
    if status == 403:
        assert response.json() == {"detail": REQUESTER_FORBIDDEN_DETAIL}
        assert "no approver is configured" in response.json()["detail"]


@pytest.mark.parametrize("email", [AMY, HELEN, EVA])
def test_a_user_with_neither_capability_gets_403_on_the_chat(
    client: TestClient, seeded: Database, email: str
) -> None:
    token = login(client, email)
    strip_capabilities(seeded, email)
    response = client.get("/api/chat/conversations", headers=auth(token))
    assert response.status_code == 403
    assert response.json() == {"detail": REQUESTER_FORBIDDEN_DETAIL}
    assert "no approver is configured" in response.json()["detail"]


def test_unauthenticated_chat_is_401(client: TestClient) -> None:
    assert client.get("/api/chat/conversations").status_code == 401


def test_the_gate_reads_the_database_not_the_token(client: TestClient, seeded: Database) -> None:
    token = login(client, AMY)
    with seeded.session_factory() as s:
        user = s.query(User).filter_by(email=AMY).one()
        user.leave_approver_user_id = user.claim_approver_user_id = None
        s.commit()
    assert client.get("/api/chat/conversations", headers=auth(token)).status_code == 403


def test_an_approver_who_can_request_may_create_a_conversation(client: TestClient) -> None:
    login(client, CATHY)
    assert client.post("/api/chat/conversations").status_code == 201


# ---- GET /api/me/balances --------------------------------------------------------------------


def test_balances_for_a_requester(client: TestClient) -> None:
    login(client, DANIEL)
    response = client.get("/api/me/balances")
    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    annual, sick = body["leave"]
    # Daniel: 10 approved working days (history), 6 pending (the over-the-balance showcase)
    assert annual == {
        "leave_type": "annual",
        "entitled_days": 15.0,
        "approved_days": 10.0,
        "pending_days": 6.0,
        "remaining_days": 5.0,
    }
    assert sick == {
        "leave_type": "sick",
        "entitled_days": 12.0,
        "approved_days": 0.0,
        "pending_days": 0.0,
        "remaining_days": 12.0,
    }


def test_balance_numbers_are_json_numbers_in_half_day_steps(client: TestClient) -> None:
    login(client, AMY)
    body = client.get("/api/me/balances").json()
    assert [line["leave_type"] for line in body["leave"]] == ["annual", "sick"]
    for line in body["leave"]:
        for key in ("entitled_days", "approved_days", "pending_days", "remaining_days"):
            assert isinstance(line[key], float) and (line[key] * 2) % 1 == 0
        assert line["remaining_days"] == line["entitled_days"] - line["approved_days"]
    assert body["leave"][0]["pending_days"] > 0  # Amy has a pending annual leave


def test_ben_has_more_annual_days(client: TestClient) -> None:
    login(client, BEN)
    annual = client.get("/api/me/balances").json()["leave"][0]
    assert annual["entitled_days"] == 18.0


@pytest.mark.parametrize("email", [HELEN, EVA])
def test_balances_are_403_for_users_who_cannot_request(client: TestClient, email: str) -> None:
    login(client, email)
    response = client.get("/api/me/balances")
    assert response.status_code == 403
    assert response.json() == {"detail": REQUESTER_FORBIDDEN_DETAIL}


def test_balances_need_a_session(client: TestClient) -> None:
    assert client.get("/api/me/balances").status_code == 401


def test_a_requester_without_entitlements_gets_an_empty_list(
    client: TestClient, seeded: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.routes.me.today_hk", lambda: SEED_TODAY.replace(year=2030))
    login(client, AMY)
    assert client.get("/api/me/balances").json() == {"year": 2030, "leave": []}


def test_the_balance_follows_approved_leave(client: TestClient, seeded: Database) -> None:
    from app.db.models import LeaveRequest
    from app.domain.enums import RequestStatus

    login(client, DANIEL)
    before = client.get("/api/me/balances").json()["leave"][0]
    with seeded.session_factory() as s:
        pending = (
            s.query(LeaveRequest)
            .join(User, User.id == LeaveRequest.employee_id)
            .filter(User.email == DANIEL, LeaveRequest.status == RequestStatus.PENDING_APPROVAL)
            .one()
        )
        pending.status = RequestStatus.APPROVED
        pending.reviewed_by_user_id = pending.approver_user_id
        pending.reviewed_at = pending.submitted_at
        s.commit()
    after = client.get("/api/me/balances").json()["leave"][0]
    assert after["approved_days"] == before["approved_days"] + before["pending_days"]
    assert (
        after["pending_days"] == 0.0 and after["remaining_days"] == -1.0
    )  # 15 - 16: never blocked
    assert get_user(seeded, DANIEL).can_request
