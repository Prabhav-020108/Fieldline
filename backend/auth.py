"""
Auth for the FieldLine dispatch backend -- JWT login (OAuth2 password
flow), role-based access control, and (Phase 8c) short-lived call-role
tokens for offline-capable RBAC in the voice agent.

fieldline_jwt_secret (from settings.py) MUST be byte-for-byte identical
to the same variable in agent/.env.local -- it's what lets
agent/src/role_cache.py verify a call-role token this file mints, using
nothing but local cryptography, even with the network fully off.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from settings import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 hours -- a full shift
CALL_ROLE_TOKEN_EXPIRE_MINUTES = 15    # Phase 8c -- short-lived, single-call scope


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(*, username: str, role: str, company_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "role": role,
        "company_id": company_id,
        "exp": expire,
        "type": "session",
    }
    return jwt.encode(payload, settings.fieldline_jwt_secret, algorithm=ALGORITHM)


def create_call_role_token(*, company_id: str, role: str) -> str:
    """Phase 8c: a much shorter-lived token whose only job is telling the
    LiveKit agent which role is on this call. Kept deliberately separate
    from the dashboard session token above -- if this one leaks (it rides
    along in LiveKit participant metadata) or its window runs out, the
    dashboard session itself is unaffected."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=CALL_ROLE_TOKEN_EXPIRE_MINUTES)
    payload = {
        "company_id": company_id,
        "role": role,
        "exp": expire,
        "type": "call_role",
    }
    return jwt.encode(payload, settings.fieldline_jwt_secret, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.fieldline_jwt_secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    payload = _decode_token(token)
    username = payload.get("sub")
    role = payload.get("role")
    company_id = payload.get("company_id")
    if not username or not role or not company_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    return {"username": username, "role": role, "company_id": company_id}


def require_role(*allowed_roles: str):
    def _dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action needs one of these roles: {', '.join(allowed_roles)}.",
            )
        return user
    return _dependency


def require_same_company(user: dict, company_id: str) -> None:
    if user["company_id"] != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this company's data.",
        )
