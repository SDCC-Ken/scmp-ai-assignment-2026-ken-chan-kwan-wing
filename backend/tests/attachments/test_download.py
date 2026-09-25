"""GET /api/attachments/{id}: headers and the authorization matrix."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Attachment, ClaimRequest, LeaveRequest
from app.db.session import Database
from app.domain.enums import RequestStatus, RequestType
from app.services.attachments import link_to_request
from tests.attachments.conftest import CATHY, FINANCE, HR
from tests.attachments.helpers import PDF, PNG, upload_ok
from tests.chat.helpers import Chat
from tests.conftest import ORIGIN, get_user

NOT_FOUND = {"detail": "Attachment not found"}


def owner_id(db: Database) -> int:
    return get_user(db, CATHY).id


def link(db: Database, attachment_id: int, rtype: RequestType, request_id: int) -> None:
    with db.session_factory() as s:
        assert link_to_request(s, [attachment_id], rtype, request_id, owner_id(db)) == 1
        s.commit()


def request_with_status(
    db: Database, rtype: RequestType, status: RequestStatus, approver: str | None = None
) -> int:
    """A seeded request in ``status``, assigned to the fixture approver (Helen for leave, Eva for
    claims) so that the Phase 3 "assigned approver" rule is what the tests exercise."""
    model = LeaveRequest if rtype == RequestType.LEAVE else ClaimRequest
    approver = approver or (HR if rtype == RequestType.LEAVE else FINANCE)
    with db.session_factory() as s:
        row = s.scalars(select(model).where(model.status == status)).first()
        assert row is not None, f"the seed has no {rtype} in {status}"
        row.approver_user_id = get_user(db, approver).id
        s.commit()
        return row.id


@pytest.fixture
def file_id(cathy: TestClient, chat: Chat) -> int:
    return upload_ok(cathy, chat.id, PNG + b"body", filename="Receipt Ünï.png")["id"]


def test_owner_gets_the_file_with_the_safe_headers(cathy: TestClient, file_id: int) -> None:
    response = cathy.get(f"/api/attachments/{file_id}")
    assert response.status_code == 200
    assert response.content == PNG + b"body"
    h = response.headers
    assert h["content-type"] == "image/png"
    assert h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "private, no-store"
    assert h["content-security-policy"] == "sandbox"
    disposition = h["content-disposition"]
    assert disposition.startswith("inline; filename=\"Receipt n.png\"; filename*=UTF-8''")
    assert "Receipt%20%C3%9Cn%C3%AF.png" in disposition
    assert disposition.isascii()


def test_content_type_comes_from_the_stored_type_not_the_client(
    cathy: TestClient, chat: Chat
) -> None:
    pdf = upload_ok(cathy, chat.id, PDF, filename="note.png", content_type="application/x-pdf")
    response = cathy.get(f"/api/attachments/{pdf['id']}")
    assert response.headers["content-type"] == "application/pdf"


def test_cors_headers_allow_the_web_app_origin_with_credentials(
    cathy: TestClient, file_id: int
) -> None:
    response = cathy.get(f"/api/attachments/{file_id}", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    other = cathy.get(f"/api/attachments/{file_id}", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_unauthenticated_is_401(anon: TestClient, file_id: int) -> None:
    assert anon.get(f"/api/attachments/{file_id}").status_code == 401
    assert anon.get("/api/attachments/999999").status_code == 401


def test_unlinked_file_is_private_to_its_owner(
    amy: TestClient, hr: TestClient, finance: TestClient, file_id: int
) -> None:
    for other in (amy, hr, finance):
        response = other.get(f"/api/attachments/{file_id}")
        assert response.status_code == 404 and response.json() == NOT_FOUND


def test_unknown_id_has_the_same_body_as_a_refusal(
    cathy: TestClient, amy: TestClient, file_id: int
) -> None:
    unknown = cathy.get("/api/attachments/999999")
    refused = amy.get(f"/api/attachments/{file_id}")
    assert (unknown.status_code, unknown.json()) == (refused.status_code, refused.json())
    assert (unknown.status_code, unknown.json()) == (404, NOT_FOUND)
    assert dict(unknown.headers).keys() == dict(refused.headers).keys()


def test_authorization_matrix_for_a_leave_linked_file(
    cathy: TestClient,
    amy: TestClient,
    hr: TestClient,
    finance: TestClient,
    anon: TestClient,
    seeded: Database,
    file_id: int,
) -> None:
    leave_id = request_with_status(seeded, RequestType.LEAVE, RequestStatus.PENDING_APPROVAL)
    link(seeded, file_id, RequestType.LEAVE, leave_id)
    url = f"/api/attachments/{file_id}"
    assert cathy.get(url).status_code == 200  # owner
    assert hr.get(url).status_code == 200  # HR reviews leave
    assert finance.get(url).status_code == 404  # Finance does not
    assert amy.get(url).status_code == 404  # another employee
    assert anon.get(url).status_code == 401


def test_authorization_matrix_for_a_claim_linked_file(
    cathy: TestClient,
    amy: TestClient,
    hr: TestClient,
    finance: TestClient,
    seeded: Database,
    file_id: int,
) -> None:
    claim_id = request_with_status(seeded, RequestType.CLAIM, RequestStatus.PENDING_APPROVAL)
    link(seeded, file_id, RequestType.CLAIM, claim_id)
    url = f"/api/attachments/{file_id}"
    assert cathy.get(url).status_code == 200
    assert finance.get(url).status_code == 200  # Finance reviews claims
    assert hr.get(url).status_code == 404  # HR does not
    assert amy.get(url).status_code == 404


@pytest.mark.parametrize("status", [RequestStatus.APPROVED, RequestStatus.REJECTED])
def test_approvers_keep_access_after_a_decision(
    hr: TestClient, seeded: Database, file_id: int, status: RequestStatus
) -> None:
    link(seeded, file_id, RequestType.LEAVE, request_with_status(seeded, RequestType.LEAVE, status))
    assert hr.get(f"/api/attachments/{file_id}").status_code == 200


@pytest.mark.parametrize(
    "status",
    [RequestStatus.DRAFT, RequestStatus.SUBMISSION_FAILED, RequestStatus.CANCELLED],
)
def test_approvers_cannot_open_files_of_requests_that_were_never_submitted_or_were_cancelled(
    hr: TestClient, cathy: TestClient, seeded: Database, file_id: int, status: RequestStatus
) -> None:
    leave_id = request_with_status(seeded, RequestType.LEAVE, RequestStatus.PENDING_APPROVAL)
    with seeded.session_factory() as s:
        leave = s.get(LeaveRequest, leave_id)
        assert leave is not None
        leave.status = status
        s.commit()
    link(seeded, file_id, RequestType.LEAVE, leave_id)
    assert hr.get(f"/api/attachments/{file_id}").status_code == 404
    assert cathy.get(f"/api/attachments/{file_id}").status_code == 200  # the owner still can


def test_a_link_to_a_missing_request_grants_nothing(
    hr: TestClient, seeded: Database, file_id: int
) -> None:
    link(seeded, file_id, RequestType.LEAVE, 987654)
    assert hr.get(f"/api/attachments/{file_id}").status_code == 404


def test_missing_file_on_disk_is_404_and_logs_without_paths(
    cathy: TestClient,
    seeded: Database,
    upload_dir: Path,
    file_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with seeded.session_factory() as s:
        row = s.get(Attachment, file_id)
        assert row is not None
        stored = upload_dir / row.storage_path
    stored.unlink()
    with caplog.at_level("WARNING"):
        response = cathy.get(f"/api/attachments/{file_id}")
    assert response.status_code == 404 and response.json() == NOT_FOUND
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("missing on disk" in m for m in warnings)
    assert not any(str(upload_dir) in m or "Receipt" in m for m in warnings)


def test_link_to_request_rules(
    cathy: TestClient, amy: TestClient, chat: Chat, seeded: Database
) -> None:
    from tests.chat.helpers import Chat as ChatWrapper

    mine = upload_ok(cathy, chat.id)["id"]
    theirs = upload_ok(amy, ChatWrapper(amy).id)["id"]
    me = owner_id(seeded)
    with seeded.session_factory() as s:
        # ignores ids that are not the owner's and unknown ids
        assert link_to_request(s, [mine, theirs, 4242], RequestType.CLAIM, 1, me) == 1
        s.commit()
        assert link_to_request(s, [mine], RequestType.CLAIM, 1, me) == 1  # idempotent
        # an already linked file is not moved to another request
        assert link_to_request(s, [mine], RequestType.LEAVE, 2, me) == 0
        s.commit()
        row = s.get(Attachment, mine)
        other = s.get(Attachment, theirs)
        assert row is not None and other is not None
        assert (row.request_type, row.request_id) == (RequestType.CLAIM, 1)
        assert (other.request_type, other.request_id) == (None, None)
        assert link_to_request(s, [], RequestType.CLAIM, 1, me) == 0


def test_an_approver_of_the_right_role_who_is_not_assigned_cannot_open_the_file(
    cathy: TestClient, hr: TestClient, chat: Chat, seeded: Database, file_id: int
) -> None:
    """Phase 3: the assignment matters, not just the role (Helen is HR but not this approver)."""
    rid = request_with_status(seeded, RequestType.LEAVE, RequestStatus.APPROVED)
    link(seeded, file_id, RequestType.LEAVE, rid)
    assert hr.get(f"/api/attachments/{file_id}").status_code == 200  # Helen is the assigned one
    with seeded.session_factory() as s:
        s.get(LeaveRequest, rid).approver_user_id = get_user(seeded, "ben.chow@example.com").id
        s.commit()
    assert hr.get(f"/api/attachments/{file_id}").status_code == 404
    assert cathy.get(f"/api/attachments/{file_id}").status_code == 200  # the owner always can
