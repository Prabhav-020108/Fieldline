"""
Phase 7: authentication and role-based access control for the FieldLine
dispatch backend.

- Passwords are hashed with bcrypt (the `bcrypt` package directly, not
  passlib -- passlib's bcrypt wrapper has a well-known compatibility bug
  against newer bcrypt releases; calling bcrypt directly sidesteps it).
- Sessions are stateless JWTs (python-jose): the token carries `sub`
  (username), `role`, and `company_id`, so get_current_user() never needs
  to hit the database -- it just verifies the token's signature and
  expiry.
- Three roles:
    technician  -- read data, log job notes
    supervisor  -- + create/edit/delete safety procedures
    dispatcher  -- + reroute jobs, delete jobs/inventory
  See require_role() below and main.py for exactly which endpoints
  require which role.
- Accounts are provisioned by seed_db.py, not a public /auth/register
  endpoint -- an internal ops tool doesn't need public self-signup, and
  adding one would be unnecessary attack surface.

IMPORTANT: this module calls load_dotenv() itself, right here, before
reading FIELDLINE_JWT_SECRET below -- rather than relying on some other
module (e.g. moss_sync.py) to have loaded backend/.env first. auth.py is
imported very early in main.py's import chain, so if it read
os.environ.get() without loading .env itself first, it would always see
an empty environment regardless of what's actually in backend/.env.

SECURITY NOTE: FIELDLINE_JWT_SECRET must be set to a real, random secret
before this is ever exposed outside your own machine (see .env.example).
A fallback dev secret is generated below ONLY so the backend doesn't
refuse to start if you forget to set one locally -- it changes every
restart and is NOT safe for anything beyond localhost testing. Generate a
real one with:

    python -c "import secrets; print(secrets.token_urlsafe(48))"
"""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

logger = logging.getLogger("fieldline.auth")

# Must happen BEFORE reading FIELDLINE_JWT_SECRET below. load_dotenv()
# with no arguments searches the current working directory (and its
# parents) for a file named exactly ".env" -- since the backend is always
# run from inside backend/ (see README's `cd backend` step), this finds
# backend/.env correctly without needing an explicit path.
load_dotenv()

_ENV_SECRET = os.environ.get("FIELDLINE_JWT_SECRET")
if not _ENV_SECRET:
    _ENV_SECRET = secrets.token_urlsafe(32)
    logger.warning(
        "FIELDLINE_JWT_SECRET is not set -- using a random secret "
        "generated for THIS PROCESS ONLY. Every existing token will be "
        "invalidated on restart, and this is not safe beyond local "
        "development. Set FIELDLINE_JWT_SECRET in backend/.env."
    )
SECRET_KEY: str = _ENV_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12  # roughly one working shift

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

VALID_ROLES = ("technician", "supervisor", "dispatcher")


# --- Password hashing ------------------------------------------------------

def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed hash in the DB -- treat as "does not match" rather than 500ing.
        return False


# --- Token issuance + verification -----------------------------------------

def create_access_token(*, username: str, role: str, company_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "role": role, "company_id": company_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    username = payload.get("sub")
    role = payload.get("role")
    company_id = payload.get("company_id")
    if not username or role not in VALID_ROLES or not company_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"username": username, "role": role, "company_id": company_id}


def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """Any authenticated user, regardless of role. Use this (rather than
    require_role()) for actions any logged-in technician/supervisor/
    dispatcher should be able to do, e.g. creating a job."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_token(token)


def require_role(*allowed_roles: str):
    """Dependency factory -- Depends(require_role("supervisor", "dispatcher"))
    restricts an endpoint to only those roles."""

    def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{current_user['role']}' is not authorized for "
                    f"this action (requires one of: {', '.join(allowed_roles)})."
                ),
            )
        return current_user

    return dependency


def require_same_company(current_user: dict, company_id: str) -> None:
    """Extra tenant-isolation check: a valid, correctly-roled token for
    company A must never be usable to mutate company B's data. Call this
    at the top of any protected endpoint, right after the role check."""
    if current_user["company_id"] != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not authorized for this company.",
        )