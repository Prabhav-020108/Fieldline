"""
Auth tests: login, bearer-token checks, the two token types, the call-role
token endpoint, and the login rate limit.

Covers: NFR-05 (API authentication), NFR-06 (rate limiting), and the
backend half of NFR-14 (call-role tokens the voice agent verifies offline).

    uv run pytest tests/test_auth.py -v
"""

import time
from datetime import datetime, timedelta, timezone

from jose import jwt

import auth
import main
from settings import settings

DEMO_PASSWORD = "FieldLine123!"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.fieldline_jwt_secret, algorithms=["HS256"])


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


def test_login_with_correct_credentials_returns_token_role_and_company(client):
    response = client.post(
        "/auth/token", data={"username": "dispatcher.demo", "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "dispatcher"
    assert body["company_id"] == "site-demo"
    assert body["access_token"]


def test_login_with_wrong_password_returns_401(client):
    response = client.post(
        "/auth/token", data={"username": "dispatcher.demo", "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password."


def test_login_with_unknown_user_returns_401(client):
    response = client.post(
        "/auth/token", data={"username": "nobody.here", "password": DEMO_PASSWORD}
    )
    assert response.status_code == 401


def test_token_from_login_works_on_auth_me(client):
    login = client.post(
        "/auth/token", data={"username": "supervisor.acme", "password": DEMO_PASSWORD}
    )
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers=_bearer(token))

    assert me.status_code == 200
    assert me.json() == {
        "username": "supervisor.acme",
        "role": "supervisor",
        "company_id": "acme-elevator",
    }


# --------------------------------------------------------------------------
# Bearer-token validation
# --------------------------------------------------------------------------


def test_auth_me_without_a_token_returns_401(client):
    assert client.get("/auth/me").status_code == 401


def test_auth_me_with_a_garbage_token_returns_401(client):
    response = client.get("/auth/me", headers=_bearer("this-is-not-a-jwt"))
    assert response.status_code == 401


def test_expired_token_is_rejected(client):
    expired = jwt.encode(
        {
            "sub": "tech.demo",
            "role": "technician",
            "company_id": "site-demo",
            "type": "session",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.fieldline_jwt_secret,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers=_bearer(expired)).status_code == 401


def test_token_signed_with_the_wrong_secret_is_rejected(client):
    forged = jwt.encode(
        {
            "sub": "tech.demo",
            "role": "dispatcher",
            "company_id": "site-demo",
            "type": "session",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "some-other-secret",
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers=_bearer(forged)).status_code == 401


def test_token_missing_required_claims_is_rejected(client):
    incomplete = jwt.encode(
        {"sub": "tech.demo", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.fieldline_jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/auth/me", headers=_bearer(incomplete))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token payload."


# --------------------------------------------------------------------------
# auth.py helper functions
# --------------------------------------------------------------------------


def test_password_hash_roundtrip():
    hashed = auth.hash_password("s3cret-Passw0rd!")
    assert hashed != "s3cret-Passw0rd!"
    assert auth.verify_password("s3cret-Passw0rd!", hashed) is True
    assert auth.verify_password("wrong-password", hashed) is False


def test_session_and_call_role_tokens_are_different_kinds_of_token():
    session = _decode(
        auth.create_access_token(username="u", role="dispatcher", company_id="site-demo")
    )
    call_role = _decode(auth.create_call_role_token(company_id="site-demo", role="dispatcher"))

    assert session["type"] == "session"
    assert call_role["type"] == "call_role"
    # A dashboard session lasts hours; a call-role token only 15 minutes.
    assert session["exp"] > call_role["exp"]


# --------------------------------------------------------------------------
# Call-role token endpoint (used by the dashboard before starting a call)
# --------------------------------------------------------------------------


def test_call_role_token_carries_role_company_and_a_15_minute_expiry(client, auth_headers):
    response = client.post(
        "/companies/site-demo/call-role-token", headers=auth_headers("dispatcher")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "dispatcher"

    payload = _decode(body["token"])
    assert payload["type"] == "call_role"
    assert payload["role"] == "dispatcher"
    assert payload["company_id"] == "site-demo"

    seconds_left = payload["exp"] - time.time()
    assert 0 < seconds_left <= 15 * 60 + 5


def test_call_role_token_requires_login(client):
    response = client.post("/companies/site-demo/call-role-token")
    assert response.status_code == 401


def test_call_role_token_cannot_be_minted_for_another_company(client, auth_headers):
    response = client.post(
        "/companies/site-demo/call-role-token",
        headers=auth_headers("dispatcher", company_id="acme-elevator"),
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Rate limiting (NFR-06)
# --------------------------------------------------------------------------


def test_login_endpoint_is_rate_limited(client):
    """The limiter is off in every other test; switch it on just for this one.
    /auth/token allows 20 requests per minute, so 25 quick attempts must end
    in HTTP 429 (Too Many Requests)."""
    main.limiter.enabled = True
    try:
        statuses = [
            client.post(
                "/auth/token", data={"username": "nobody", "password": "wrong"}
            ).status_code
            for _ in range(25)
        ]
    finally:
        main.limiter.enabled = False

    assert statuses[0] == 401  # early attempts are allowed (and simply fail to log in)
    assert statuses[-1] == 429  # later attempts are blocked
