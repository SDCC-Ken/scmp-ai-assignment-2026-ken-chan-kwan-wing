import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import get_current_user, require_roles
from app.db.models import AuditEvent, User
from app.db.session import Database
from app.domain.enums import UserRole
from tests.conftest import TEST_SECRET, auth, login, make_settings

AMY = "amy.lau@example.com"
HR = "daniel.wong@example.com"
FIN = "eva.cheung@example.com"
ISSUER = "scmp-ai-assignment"


def token_for(user_id: int, secret: str = TEST_SECRET, **overrides) -> str:
    """Sign a token; an override of ``None`` drops that claim."""
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "email": AMY,
        "role": "employee",
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "abc",
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm="HS256")


def set_user(db: Database, email: str, **fields) -> None:
    with db.session_factory() as s:
        user = s.scalars(select(User).where(User.email == email)).one()
        for k, v in fields.items():
            setattr(user, k, v)
        s.commit()


def user_id(db: Database, email: str) -> int:
    with db.session_factory() as s:
        return s.scalars(select(User.id).where(User.email == email)).one()


def audit_types(db: Database) -> list[str]:
    with db.session_factory() as s:
        return [e.event_type for e in s.scalars(select(AuditEvent).order_by(AuditEvent.id))]


# ---- mock users --------------------------------------------------------------------------


def test_mock_users_lists_active_users_in_role_order_without_google_subject(
    client: TestClient,
) -> None:
    response = client.get("/api/auth/mock-users")
    assert response.status_code == 200
    users = response.json()
    assert [u["role"] for u in users] == ["employee"] * 3 + ["hr_approver", "finance_approver"]
    assert all(set(u) == {"id", "email", "display_name", "role"} for u in users)
    assert "google_subject" not in response.text and "mock-google-sub" not in response.text


def test_mock_users_hides_inactive(client: TestClient, seeded: Database) -> None:
    set_user(seeded, "ben.chow@example.com", is_active=False)
    emails = [u["email"] for u in client.get("/api/auth/mock-users").json()]
    assert "ben.chow@example.com" not in emails and len(emails) == 4


def test_sso_disabled_returns_404(app_factory) -> None:
    with TestClient(app_factory(mock_sso_enabled=False)) as c:
        assert c.get("/api/auth/mock-users").status_code == 404
        assert c.post("/api/auth/mock-google/login", json={"email": AMY}).status_code == 404


# ---- login -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "role"), [(AMY, "employee"), (HR, "hr_approver"), (FIN, "finance_approver")]
)
def test_login_success_for_each_role(client: TestClient, email: str, role: str) -> None:
    response = client.post("/api/auth/mock-google/login", json={"email": email})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    assert set(body["user"]) == {"id", "email", "display_name", "role"}
    assert body["user"]["email"] == email and body["user"]["role"] == role
    claims = jwt.decode(body["access_token"], TEST_SECRET, algorithms=["HS256"], issuer=ISSUER)
    assert set(claims) == {"sub", "email", "role", "iss", "iat", "exp", "jti"}
    assert claims["sub"] == str(body["user"]["id"]) and claims["role"] == role
    assert claims["exp"] - claims["iat"] == 3600


def test_login_is_case_insensitive(client: TestClient) -> None:
    response = client.post("/api/auth/mock-google/login", json={"email": "  AMY.Lau@Example.COM "})
    assert response.status_code == 200 and response.json()["user"]["email"] == AMY


def test_login_expiry_follows_settings(app_factory) -> None:
    with TestClient(app_factory(jwt_expire_minutes=15)) as c:
        assert (
            c.post("/api/auth/mock-google/login", json={"email": AMY}).json()["expires_in"] == 900
        )


@pytest.mark.parametrize("email", ["nobody@example.com", "not-an-email", "", "a" * 100])
def test_unknown_email_is_401_with_generic_message(client: TestClient, email: str) -> None:
    response = client.post("/api/auth/mock-google/login", json={"email": email})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_login_inactive_user_403(client: TestClient, seeded: Database) -> None:
    set_user(seeded, AMY, is_active=False)
    response = client.post("/api/auth/mock-google/login", json={"email": AMY})
    assert response.status_code == 403
    assert response.json() == {"detail": "Account is inactive"}


def test_login_audit_rows_without_tokens(client: TestClient, seeded: Database) -> None:
    before = len(audit_types(seeded))
    token = login(client, AMY)
    client.post("/api/auth/mock-google/login", json={"email": "ghost@example.com"})
    with seeded.session_factory() as s:
        rows = s.scalars(select(AuditEvent).order_by(AuditEvent.id).offset(before)).all()
    assert [r.event_type for r in rows] == ["auth.login", "auth.login_failed"]
    ok, failed = rows
    assert ok.entity_type == "user" and ok.actor_user_id == ok.entity_id
    assert failed.actor_user_id is None and failed.entity_id is None
    dump = json.dumps([r.metadata_json for r in rows])
    assert token not in dump and "ghost@example.com" not in dump


# ---- /me and logout ----------------------------------------------------------------------


def test_me_returns_current_user(client: TestClient) -> None:
    token = login(client, HR)
    response = client.get("/api/auth/me", headers=auth(token))
    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "email": HR,
        "display_name": "Daniel Wong",
        "role": "hr_approver",
    }


def assert_401(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_without_or_with_garbage_token(client: TestClient) -> None:
    assert_401(client.get("/api/auth/me"))
    assert_401(client.get("/api/auth/me", headers=auth("garbage")))
    assert_401(client.get("/api/auth/me", headers={"Authorization": "Basic abc"}))


def test_expired_token(client: TestClient, seeded: Database) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token = token_for(user_id(seeded, AMY), iat=past, exp=past + timedelta(minutes=5))
    assert_401(client.get("/api/auth/me", headers=auth(token)))


def test_tampered_signature(client: TestClient, seeded: Database) -> None:
    token = login(client, AMY)
    head, payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert_401(client.get("/api/auth/me", headers=auth(f"{head}.{payload}.{flipped}")))
    # a token signed with another secret
    forged = token_for(user_id(seeded, AMY), secret="another-secret-" + "z" * 32)
    assert_401(client.get("/api/auth/me", headers=auth(forged)))


def test_tampered_payload_role(client: TestClient) -> None:
    head, payload, sig = login(client, AMY).split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["role"] = "hr_approver"
    forged_payload = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    assert_401(client.get("/api/auth/me", headers=auth(f"{head}.{forged_payload}.{sig}")))


def test_alg_none_rejected(client: TestClient, seeded: Database) -> None:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": str(user_id(seeded, AMY)), "email": AMY, "role": "employee",
               "iss": ISSUER, "iat": now, "exp": now + 300, "jti": "x"}  # fmt: skip
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(payload)}."
    assert_401(client.get("/api/auth/me", headers=auth(unsigned)))


def test_wrong_algorithm_rejected(client: TestClient, seeded: Database) -> None:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id(seeded, AMY)), "email": AMY, "role": "employee",
              "iss": ISSUER, "iat": now, "exp": now + timedelta(minutes=5), "jti": "x"}  # fmt: skip
    hs512 = jwt.encode(claims, TEST_SECRET, algorithm="HS512")
    assert_401(client.get("/api/auth/me", headers=auth(hs512)))


def test_wrong_issuer_and_missing_claims(client: TestClient, seeded: Database) -> None:
    uid = user_id(seeded, AMY)
    assert_401(client.get("/api/auth/me", headers=auth(token_for(uid, iss="someone-else"))))
    for missing in ("jti", "iat", "exp", "iss", "sub", "role", "email"):
        bad = token_for(uid, **{missing: None})
        assert_401(client.get("/api/auth/me", headers=auth(bad)))


def test_non_numeric_or_unknown_subject(client: TestClient) -> None:
    assert_401(client.get("/api/auth/me", headers=auth(token_for(0, sub="abc"))))
    assert_401(client.get("/api/auth/me", headers=auth(token_for(99999))))


def test_deactivated_user_rejected_with_still_valid_token(
    client: TestClient, seeded: Database
) -> None:
    token = login(client, AMY)
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 200
    set_user(seeded, AMY, is_active=False)
    response = client.get("/api/auth/me", headers=auth(token))
    assert response.status_code == 403 and response.json() == {"detail": "Account is inactive"}


def test_role_demotion_takes_effect_immediately(client: TestClient, seeded: Database) -> None:
    token = login(client, HR)
    assert client.get("/api/auth/me", headers=auth(token)).json()["role"] == "hr_approver"
    set_user(seeded, HR, role=UserRole.EMPLOYEE)
    # the token still claims hr_approver, but the DB role wins
    assert client.get("/api/auth/me", headers=auth(token)).json()["role"] == "employee"


def test_logout_writes_audit_and_returns_204(client: TestClient, seeded: Database) -> None:
    token = login(client, AMY)
    response = client.post("/api/auth/logout", headers=auth(token))
    assert response.status_code == 204 and response.content == b""
    assert audit_types(seeded)[-1] == "auth.logout"
    assert_401(client.post("/api/auth/logout"))


# ---- require_roles -----------------------------------------------------------------------


def _guarded_app(app: FastAPI) -> FastAPI:
    router = APIRouter()

    @router.get("/t/any")
    def any_user(user: User = Depends(get_current_user)) -> dict:
        return {"role": user.role.value}

    @router.get("/t/hr")
    def hr_only(user: User = Depends(require_roles(UserRole.HR_APPROVER))) -> dict:
        return {"ok": True}

    @router.get("/t/approvers")
    def approvers(
        user: User = Depends(require_roles(UserRole.HR_APPROVER, UserRole.FINANCE_APPROVER)),
    ) -> dict:
        return {"ok": True}

    app.include_router(router)
    return app


@pytest.mark.parametrize(
    ("email", "path", "status"),
    [
        (AMY, "/t/any", 200),
        (AMY, "/t/hr", 403),
        (AMY, "/t/approvers", 403),
        (HR, "/t/hr", 200),
        (HR, "/t/approvers", 200),
        (FIN, "/t/hr", 403),
        (FIN, "/t/approvers", 200),
    ],
)
def test_require_roles_matrix(app: FastAPI, email: str, path: str, status: int) -> None:
    with TestClient(_guarded_app(app)) as c:
        token = login(c, email)
        assert c.get(path, headers=auth(token)).status_code == status


def test_require_roles_without_token_is_401(app: FastAPI) -> None:
    with TestClient(_guarded_app(app)) as c:
        assert_401(c.get("/t/hr"))


def test_require_roles_uses_db_role_not_token_claim(app: FastAPI, seeded: Database) -> None:
    with TestClient(_guarded_app(app)) as c:
        token = login(c, HR)
        set_user(seeded, HR, role=UserRole.EMPLOYEE)
        assert c.get("/t/hr", headers=auth(token)).status_code == 403


# ---- CORS / misc -------------------------------------------------------------------------


def test_cors_preflight_allows_authorization_header(client: TestClient) -> None:
    response = client.options(
        "/api/auth/me",
        headers={
            "Origin": "http://localhost:9180",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert response.headers["access-control-allow-origin"] == "http://localhost:9180"


def test_health_still_at_root(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_settings_helper_builds_isolated_settings() -> None:
    assert make_settings().database_url == "sqlite:///:memory:"
