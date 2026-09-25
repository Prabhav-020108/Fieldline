"""
Tests for the Phase 8c offline-capable RBAC helper: a valid token returns
its role, and every failure mode falls back to "technician" -- least
privilege -- rather than raising.

    uv run pytest tests/test_role_cache.py -v
"""

from datetime import datetime, timedelta, timezone

from jose import jwt

from role_cache import verify_role_token

SECRET = "test-secret-do-not-use-in-real-life"
ALGORITHM = "HS256"


def _make_token(
    *,
    company_id="site-demo",
    role="dispatcher",
    expires_in_minutes=15,
    token_type="call_role",
    secret=SECRET,
):
    payload = {
        "company_id": company_id,
        "role": role,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def test_valid_token_returns_its_role():
    token = _make_token(role="supervisor")
    assert verify_role_token(token, SECRET, "site-demo") == "supervisor"


def test_missing_token_is_least_privilege():
    assert verify_role_token(None, SECRET, "site-demo") == "technician"
    assert verify_role_token("", SECRET, "site-demo") == "technician"


def test_expired_token_is_least_privilege():
    token = _make_token(expires_in_minutes=-5)
    assert verify_role_token(token, SECRET, "site-demo") == "technician"


def test_wrong_company_is_least_privilege():
    token = _make_token(company_id="acme-elevator")
    assert verify_role_token(token, SECRET, "site-demo") == "technician"


def test_tampered_signature_is_least_privilege():
    token = _make_token(role="dispatcher")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert verify_role_token(tampered, SECRET, "site-demo") == "technician"


def test_wrong_secret_is_least_privilege():
    token = _make_token(secret="a-completely-different-secret")
    assert verify_role_token(token, SECRET, "site-demo") == "technician"


def test_wrong_token_type_is_least_privilege():
    token = _make_token(token_type="session")
    assert verify_role_token(token, SECRET, "site-demo") == "technician"
