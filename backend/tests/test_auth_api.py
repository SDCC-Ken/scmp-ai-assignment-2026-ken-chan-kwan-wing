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
from tests.conftest import (
    COOKIE_NAME,
    CSRF_HEADERS,
    ORIGIN,
    TEST_SECRET,
    auth,
    login,
    make_settings,
)

USER_KEYS = {
    "id",
    "email",
    "display_name",
    "role",
    "department",
    "job_title",
    "can_request",
    "approves",
}

AMY = "amy.lau@example.com"
HR = "cathy.ng@example.com"  # an hr_approver (she also files her own leave)
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
    assert [u["role"] for u in users] == (
        ["employee"] * 3 + ["hr_approver"] * 2 + ["finance_approver"]
    )
    assert [u["display_name"] for u in users] == [
        "Amy Lau",
        "Ben Chow",
        "Daniel Wong",
        "Cathy Ng",
        "Helen Yeung",
        "Eva Cheung",
    ]
    assert all(set(u) == USER_KEYS for u in users)
    assert "google_subject" not in response.text and "mock-google-sub" not in response.text


def test_mock_users_hides_inactive(client: TestClient, seeded: Database) -> None:
    set_user(seeded, "ben.chow@example.com", is_active=False)
    emails = [u["email"] for u in client.get("/api/auth/mock-users").json()]
    assert "ben.chow@example.com" not in emails and len(emails) == 5


def test_sso_disabled_returns_404(app_factory) -> None:
    with TestClient(app_factory(mock_sso_enabled=False), headers=CSRF_HEADERS) as c:
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
    assert set(body) == {"expires_in", "user"}  # the JWT is never in the body
    assert "access_token" not in response.text and "token" not in body
    assert body["expires_in"] == 3600
    assert set(body["user"]) == USER_KEYS
    assert body["user"]["email"] == email and body["user"]["role"] == role
    token = client.cookies.get(COOKIE_NAME)
    assert token and token not in response.text
    claims = jwt.decode(token, TEST_SECRET, algorithms=["HS256"], issuer=ISSUER)
    assert set(claims) == {"sub", "email", "role", "iss", "iat", "exp", "jti"}
    assert claims["sub"] == str(body["user"]["id"]) and claims["role"] == role
    assert claims["exp"] - claims["iat"] == 3600


def test_login_is_case_insensitive(client: TestClient) -> None:
    response = client.post("/api/auth/mock-google/login", json={"email": "  AMY.Lau@Example.COM "})
    assert response.status_code == 200 and response.json()["user"]["email"] == AMY


def test_login_expiry_follows_settings(app_factory) -> None:
    with TestClient(app_factory(jwt_expire_minutes=15), headers=CSRF_HEADERS) as c:
        response = c.post("/api/auth/mock-google/login", json={"email": AMY})
        assert response.json()["expires_in"] == 900
        assert "Max-Age=900" in response.headers["set-cookie"]


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
        "display_name": "Cathy Ng",
        "role": "hr_approver",
        "department": {"id": response.json()["department"]["id"], "name": "HR"},
        "job_title": "HR Business Partner (IT)",
        "can_request": True,
        "approves": "leave",
    }


def assert_401(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def set_cookie_attrs(response) -> dict[str, str]:
    """Parse the (single) Set-Cookie header into {lowercased attribute: value}."""
    headers = response.headers.get_list("set-cookie")
    assert len(headers) == 1, headers
    name_value, *attrs = [part.strip() for part in headers[0].split(";")]
    name, _, value = name_value.partition("=")
    parsed = {"name": name, "value": value}
    for attr in attrs:
        key, _, val = attr.partition("=")
        parsed[key.lower()] = val
    return parsed


def assert_cookie_cleared(response) -> None:
    attrs = set_cookie_attrs(response)
    assert attrs["name"] == COOKIE_NAME and attrs["value"] in ("", '""')
    assert attrs["max-age"] == "0" and "1970" in attrs["expires"]
    assert attrs["path"] == "/" and attrs["samesite"] == "Lax" and "httponly" in attrs
    assert "domain" not in attrs


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


def test_logout_writes_audit_clears_cookie_and_returns_204(
    client: TestClient, seeded: Database
) -> None:
    login(client, AMY)
    before = audit_types(seeded)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204 and response.content == b""
    assert audit_types(seeded) == [*before, "auth.logout"]
    assert_cookie_cleared(response)
    assert client.cookies.get(COOKIE_NAME) is None
    assert_401(client.get("/api/auth/me"))


def test_logout_with_bearer_token_writes_audit(raw_client: TestClient, seeded: Database) -> None:
    token = login(raw_client, AMY)
    raw_client.cookies.clear()
    before = audit_types(seeded)
    response = raw_client.post("/api/auth/logout", headers={**auth(token), **CSRF_HEADERS})
    assert response.status_code == 204 and audit_types(seeded) == [*before, "auth.logout"]


@pytest.mark.parametrize("cookie", [None, "garbage"])
def test_logout_without_valid_cookie_is_idempotent(
    client: TestClient, seeded: Database, cookie: str | None
) -> None:
    if cookie:
        client.cookies.set(COOKIE_NAME, cookie)
    before = audit_types(seeded)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert_cookie_cleared(response)
    assert audit_types(seeded) == before  # no user, no audit row


def test_logout_for_deactivated_user_still_clears_cookie(
    client: TestClient, seeded: Database
) -> None:
    login(client, AMY)
    set_user(seeded, AMY, is_active=False)
    before = audit_types(seeded)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204 and audit_types(seeded) == before
    assert_cookie_cleared(response)


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


# ---- cookie delivery ---------------------------------------------------------------------


def test_login_sets_httponly_samesite_lax_cookie(client: TestClient) -> None:
    response = client.post("/api/auth/mock-google/login", json={"email": AMY})
    attrs = set_cookie_attrs(response)
    assert attrs["name"] == COOKIE_NAME and len(attrs["value"]) > 20
    assert "httponly" in attrs
    assert attrs["samesite"] == "Lax"
    assert attrs["path"] == "/"
    assert attrs["max-age"] == "3600"
    assert "secure" not in attrs
    assert "domain" not in attrs  # host-only cookie


def test_cookie_secure_when_configured(app_factory) -> None:
    with TestClient(app_factory(auth_cookie_secure=True), headers=CSRF_HEADERS) as c:
        response = c.post("/api/auth/mock-google/login", json={"email": AMY})
        assert "secure" in set_cookie_attrs(response)
        assert "secure" in set_cookie_attrs(c.post("/api/auth/logout"))


def test_cookie_secure_in_production(app_factory) -> None:
    prod = app_factory(app_env="production", jwt_secret_key="p" * 40)
    with TestClient(prod, headers=CSRF_HEADERS) as c:
        response = c.post("/api/auth/mock-google/login", json={"email": AMY})
        attrs = set_cookie_attrs(response)
        assert "secure" in attrs and "httponly" in attrs and attrs["samesite"] == "Lax"


def test_custom_cookie_name(app_factory) -> None:
    with TestClient(app_factory(auth_cookie_name="custom_sid"), headers=CSRF_HEADERS) as c:
        response = c.post("/api/auth/mock-google/login", json={"email": AMY})
        assert set_cookie_attrs(response)["name"] == "custom_sid"
        assert c.get("/api/auth/me").status_code == 200


def test_me_works_with_only_the_cookie(client: TestClient) -> None:
    login(client, HR)
    response = client.get("/api/auth/me")  # no Authorization header
    assert response.status_code == 200 and response.json()["email"] == HR


def test_bearer_still_works_without_cookie(client: TestClient) -> None:
    token = login(client, AMY)
    client.cookies.clear()
    response = client.get("/api/auth/me", headers=auth(token))
    assert response.status_code == 200 and response.json()["email"] == AMY


def test_authorization_header_wins_over_cookie(client: TestClient) -> None:
    login(client, AMY)  # cookie: Amy
    hr_token = login(client.__class__(client.app, headers=CSRF_HEADERS), HR)
    assert client.get("/api/auth/me").json()["email"] == AMY
    assert client.get("/api/auth/me", headers=auth(hr_token)).json()["email"] == HR
    # an invalid header is not rescued by a valid cookie
    assert_401(client.get("/api/auth/me", headers=auth("garbage")))


def test_tampered_cookie_rejected(client: TestClient) -> None:
    token = login(client, AMY)
    head, payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    client.cookies.set(COOKIE_NAME, f"{head}.{payload}.{flipped}")
    assert_401(client.get("/api/auth/me"))


def test_expired_cookie_rejected(client: TestClient, seeded: Database) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    client.cookies.set(
        COOKIE_NAME, token_for(user_id(seeded, AMY), iat=past, exp=past + timedelta(minutes=5))
    )
    assert_401(client.get("/api/auth/me"))


def test_wrong_issuer_cookie_rejected(client: TestClient, seeded: Database) -> None:
    client.cookies.set(COOKIE_NAME, token_for(user_id(seeded, AMY), iss="someone-else"))
    assert_401(client.get("/api/auth/me"))


def test_deactivated_user_with_valid_cookie_is_403(client: TestClient, seeded: Database) -> None:
    login(client, AMY)
    assert client.get("/api/auth/me").status_code == 200
    set_user(seeded, AMY, is_active=False)
    response = client.get("/api/auth/me")
    assert response.status_code == 403 and response.json() == {"detail": "Account is inactive"}


def test_role_demotion_is_immediate_with_cookie(client: TestClient, seeded: Database) -> None:
    login(client, HR)
    assert client.get("/api/auth/me").json()["role"] == "hr_approver"
    set_user(seeded, HR, role=UserRole.EMPLOYEE)
    assert client.get("/api/auth/me").json()["role"] == "employee"


# ---- CSRF --------------------------------------------------------------------------------


def test_post_without_csrf_header_is_403(raw_client: TestClient) -> None:
    for path, body in [
        ("/api/auth/mock-google/login", {"email": AMY}),
        ("/api/auth/logout", None),
        ("/api/does-not-exist", None),
    ]:
        response = raw_client.post(path, json=body)
        assert response.status_code == 403, path
        assert response.json() == {"detail": "CSRF check failed"}
    assert raw_client.cookies.get(COOKIE_NAME) is None


@pytest.mark.parametrize("value", ["", "fetch", "true"])
def test_post_with_wrong_csrf_header_value_is_403(raw_client: TestClient, value: str) -> None:
    response = raw_client.post(
        "/api/auth/mock-google/login", json={"email": AMY}, headers={"X-Requested-With": value}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_unsafe_methods_require_csrf_header(raw_client: TestClient, method: str) -> None:
    response = raw_client.request(method, "/api/auth/me")
    assert response.status_code == 403 and response.json() == {"detail": "CSRF check failed"}
    # with the header the CSRF layer passes (the route itself answers 405/401, not 403 CSRF)
    passed = raw_client.request(method, "/api/auth/me", headers=CSRF_HEADERS)
    assert passed.json() != {"detail": "CSRF check failed"}


def test_post_with_disallowed_origin_is_403(raw_client: TestClient) -> None:
    response = raw_client.post(
        "/api/auth/mock-google/login",
        json={"email": AMY},
        headers={**CSRF_HEADERS, "Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF check failed"}
    assert "access-control-allow-origin" not in response.headers
    assert raw_client.cookies.get(COOKIE_NAME) is None


def test_post_with_allowed_origin_and_header_succeeds(raw_client: TestClient) -> None:
    response = raw_client.post(
        "/api/auth/mock-google/login",
        json={"email": AMY},
        headers={**CSRF_HEADERS, "Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_csrf_403_from_allowed_origin_carries_cors_headers(raw_client: TestClient) -> None:
    response = raw_client.post(
        "/api/auth/logout", headers={"Origin": ORIGIN}
    )  # allowed origin, missing header
    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_get_and_head_without_header_are_fine(raw_client: TestClient) -> None:
    assert raw_client.get("/api/auth/mock-users").status_code == 200
    assert raw_client.get("/health").status_code == 200
    assert raw_client.head("/api/auth/mock-users").status_code != 403
    assert (
        raw_client.get(
            "/api/auth/mock-users", headers={"Origin": "http://evil.example"}
        ).status_code
        == 200
    )


def test_post_outside_api_is_not_csrf_checked(raw_client: TestClient) -> None:
    assert raw_client.post("/health").status_code == 405  # plain router answer, not CSRF 403


def test_cors_preflight_for_post_with_csrf_header(raw_client: TestClient) -> None:
    response = raw_client.options(
        "/api/auth/mock-google/login",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-requested-with",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-requested-with" in allowed and "content-type" in allowed
    assert "authorization" in allowed


def test_cors_disallowed_origin_gets_no_allow_origin(raw_client: TestClient) -> None:
    evil = "http://evil.example"
    preflight = raw_client.options(
        "/api/auth/mock-google/login",
        headers={
            "Origin": evil,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-requested-with",
        },
    )
    assert "access-control-allow-origin" not in preflight.headers
    simple = raw_client.get("/api/auth/mock-users", headers={"Origin": evil})
    assert "access-control-allow-origin" not in simple.headers
