"""
Phase 8c: offline-capable role-based access control for the FieldLine
voice agent.

The dashboard mints a short-lived (15 minute) JWT right before starting a
call -- see backend/auth.py's create_call_role_token() -- and rides it
along as the connecting participant's metadata (see
dashboard/app/api/livekit-token/route.ts). This module verifies that
token once the agent has connected (see agent.py's entrypoint()) using
nothing but a local HMAC signature check against the same shared secret
the backend used to sign it -- no network call, so it works identically
online or fully offline.

A JWT's own exp claim IS the cache TTL here: minting the token costs a
network round-trip, but *verifying* one is pure local cryptography.
That's what makes this offline-capable rather than just RBAC.

Fails safe on every edge case: a missing, expired, tampered, or
wrong-company token is treated exactly like an anonymous caller --
"technician", the least-privileged role -- never a privileged one, and
never an exception thrown into a tool call.
"""

import logging

from jose import JWTError, jwt

logger = logging.getLogger("fieldline.role_cache")

ALGORITHM = "HS256"
LEAST_PRIVILEGED_ROLE = "technician"


def verify_role_token(token: str | None, secret: str, expected_company_id: str) -> str:
    """Returns the verified role, or "technician" (least privilege) on
    any missing/invalid/expired/wrong-company/wrong-type token. Never
    raises."""
    if not token:
        return LEAST_PRIVILEGED_ROLE

    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        logger.warning("call-role token failed signature/expiry check -- defaulting to least privilege")
        return LEAST_PRIVILEGED_ROLE

    if payload.get("type") != "call_role":
        logger.warning("token is not a call-role token -- defaulting to least privilege")
        return LEAST_PRIVILEGED_ROLE

    if payload.get("company_id") != expected_company_id:
        logger.warning(
            "call-role token was minted for a different company (%r) than this "
            "call belongs to (%r) -- defaulting to least privilege",
            payload.get("company_id"),
            expected_company_id,
        )
        return LEAST_PRIVILEGED_ROLE

    return payload.get("role") or LEAST_PRIVILEGED_ROLE
