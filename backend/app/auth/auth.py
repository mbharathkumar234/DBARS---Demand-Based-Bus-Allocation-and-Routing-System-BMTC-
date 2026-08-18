
from __future__ import annotations
 
import hashlib
import hmac
import json
import logging
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from enum import Enum
from functools import wraps
from typing import Any
 
from fastapi import Depends, HTTPException, Request, status
 
from app.core.config import settings
 
logger = logging.getLogger("bmtc.auth")
 
# ── Secret key ──
#
# Previously this was a fixed literal committed to source control:
# SECRET_KEY = "bmtc-ai-predictor-secret-change-in-production-2024"
#
# Anyone who has ever seen this codebase -- this zip, a public repo, a
# code review, a fork -- already knows that exact string. With it, they
# can forge a validly-signed JWT for ANY user, including admin and
# depot_manager roles, without ever needing a password. A secret that's
# readable in source control is not a secret.
#
# Now: read JWT_SECRET_KEY from the environment (via .env / Settings --
# the same mechanism already used for GOOGLE_MAPS_API_KEY and every other
# secret-shaped value in this project; see app/core/config.py). If it
# isn't set, generate a random, process-local secret instead of falling
# back to another fixed value -- that keeps a plain local run working out
# of the box, while guaranteeing no fixed, guessable secret is ever baked
# into the code or version control again. The trade-off is that tokens
# issued before a restart stop validating after one, and that a
# multi-worker deployment without JWT_SECRET_KEY set would have each
# worker signing with a different secret; that's the correct, safe
# failure mode for an unconfigured environment, and it's exactly why a
# clear warning is logged below rather than letting this pass silently.
if settings.jwt_secret_key:
    SECRET_KEY = settings.jwt_secret_key
else:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET_KEY is not set. Generated a random, process-local secret instead "
        "of using a fixed one: every issued token will stop validating on the next "
        "restart, and tokens signed by one worker process will be rejected by "
        "another. Set JWT_SECRET_KEY in your environment or .env file before "
        "deploying, or before running with more than one worker."
    )
 
# E-ticket QR tokens are signed with their own key so that a ticket can never
# double as a session credential. If TICKET_SIGNING_KEY isn't set we derive a
# distinct key from SECRET_KEY rather than reusing it verbatim -- still
# separate domains, still zero configuration required to run locally.
if settings.ticket_signing_key:
    TICKET_SECRET_KEY = settings.ticket_signing_key
else:
    TICKET_SECRET_KEY = hashlib.sha256(f"ticket-domain:{SECRET_KEY}".encode()).hexdigest()

# Travel passes get a third domain key, on the same reasoning that separated
# ticket signing from session signing: a pass is a long-lived bearer credential
# a conductor verifies OFFLINE, so its signing key is the one most likely to
# end up cached on a device in a bus. Keeping it distinct means a compromised
# pass key cannot mint sessions or e-tickets.
if settings.pass_signing_key:
    PASS_SECRET_KEY = settings.pass_signing_key
else:
    PASS_SECRET_KEY = hashlib.sha256(f"pass-domain:{SECRET_KEY}".encode()).hexdigest()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24  # 24 hours for demo convenience
REFRESH_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7  # 7 days

# Token `type` values. These are the single source of truth -- api/tickets.py
# and auth/routes.py import them rather than repeating string literals.
#
# They exist as constants because they were previously duplicated as bare
# strings across three files and drifted: tickets.py minted tokens typed
# "qr_ticket" while get_current_user rejected "ticket", so the guard was dead
# code and a ticket QR token authenticated successfully as a user session.
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_TICKET = "qr_ticket"
TOKEN_TYPE_PASS = "travel_pass"

# A pass is valid for a season, not a session. The expiry is carried in the
# token itself so a conductor's device can check it with no network at all.
PASS_TOKEN_MAX_SECONDS = 60 * 60 * 24 * 400
 
 
class UserRole(str, Enum):
    COMMUTER = "commuter"
    ADMIN = "admin"
    DEPOT_MANAGER = "depot_manager"
    CONDUCTOR = "conductor"
    # Drivers were absent from this system entirely -- no role, no surface,
    # invisible to every dashboard -- while being half of every crew duty the
    # scheduler counts. The role exists now so a waybill can name the driver on
    # the bus, which is the first thing a depot asks of a duty record.
    DRIVER = "driver"
 
 
# ── Password hashing (bcrypt-compatible using hashlib for zero extra deps) ──
 
def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 (stdlib, no bcrypt needed)."""
    import os
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + ":" + dk.hex()
 
 
def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a PBKDF2-SHA256 hash."""
    try:
        salt_hex, dk_hex = password_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False
 
 
# ── JWT implementation (pure stdlib, no PyJWT needed) ──
 
def _b64_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()
 
 
def _b64_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    return urlsafe_b64decode(data + "=" * padding)
 
 
def _sign(payload: str, secret: str) -> str:
    return _b64_encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    )
 
 
def create_token(
    data: dict[str, Any],
    expires_seconds: int = ACCESS_TOKEN_EXPIRE_SECONDS,
    secret: str | None = None,
) -> str:
    """Create a JWT token, signed with SECRET_KEY unless `secret` overrides it."""
    header = _b64_encode(json.dumps({"alg": ALGORITHM, "typ": "JWT"}).encode())
    payload_data = {**data, "exp": int(time.time()) + expires_seconds, "iat": int(time.time())}
    payload = _b64_encode(json.dumps(payload_data).encode())
    signature = _sign(f"{header}.{payload}", secret or SECRET_KEY)
    return f"{header}.{payload}.{signature}"


def create_ticket_token(data: dict[str, Any], expires_seconds: int) -> str:
    """Mint an e-ticket QR token: ticket-domain key, ticket-domain type."""
    return create_token({**data, "type": TOKEN_TYPE_TICKET}, expires_seconds, secret=TICKET_SECRET_KEY)


def decode_ticket_token(token: str) -> dict[str, Any]:
    """Verify an e-ticket QR token. Rejects anything not typed as a ticket."""
    payload = decode_token(token, secret=TICKET_SECRET_KEY)
    if payload.get("type") != TOKEN_TYPE_TICKET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a ticket token.")
    return payload


def create_pass_token(data: dict[str, Any], expires_seconds: int) -> str:
    """Mint a travel-pass token: pass-domain key, pass-domain type.

    This is what a conductor's scanner verifies, and it is designed to be
    verifiable with no network: the signature proves the pass was issued by
    BMTC, and the expiry inside it proves it is still in season. Only
    revocation -- a lost or refunded pass -- needs a list synced from the
    server, and that list is small because it holds only the revoked ids.
    """
    return create_token(
        {**data, "type": TOKEN_TYPE_PASS},
        min(expires_seconds, PASS_TOKEN_MAX_SECONDS),
        secret=PASS_SECRET_KEY,
    )


def decode_pass_token(token: str) -> dict[str, Any]:
    """Verify a travel-pass token. Rejects anything not typed as a pass."""
    payload = decode_token(token, secret=PASS_SECRET_KEY)
    if payload.get("type") != TOKEN_TYPE_PASS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a pass token.")
    return payload


def decode_token(token: str, secret: str | None = None) -> dict[str, Any]:
    """Decode and verify a JWT token. Raises HTTPException on failure."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token format")
        header_b64, payload_b64, signature = parts
        expected_sig = _sign(f"{header_b64}.{payload_b64}", secret or SECRET_KEY)
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            raise ValueError("Token expired")
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
 
 
def create_access_token(user_id: str | int, email: str, role: str, name: str) -> str:
    return create_token({
        "sub": str(user_id),
        "email": email,
        "role": role,
        "name": name,
        "type": TOKEN_TYPE_ACCESS,
    })


def create_refresh_token(user_id: str | int) -> str:
    return create_token({"sub": str(user_id), "type": TOKEN_TYPE_REFRESH}, REFRESH_TOKEN_EXPIRE_SECONDS)
 
 
# ── FastAPI dependencies ──
 
async def get_current_user(request: Request) -> dict[str, Any]:
    """Extract and validate the current user from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[7:]
    payload = decode_token(token)
    # Allow-list, not deny-list. A deny-list is what let this through before:
    # it named "refresh" and "ticket" explicitly, but tickets are actually
    # typed "qr_ticket", so ticket tokens sailed past the guard. Anything that
    # is not positively an access token is rejected here, so a new token type
    # added elsewhere can never silently become a session credential.
    if payload.get("type", TOKEN_TYPE_ACCESS) != TOKEN_TYPE_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token cannot be used for access.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
 
 
def require_role(*roles: UserRole):
    """Dependency that checks the user has one of the specified roles."""
    async def role_checker(user: dict = Depends(get_current_user)) -> dict:
        user_role = user.get("role", "")
        if user_role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(r.value for r in roles)}",
            )
        return user
    return role_checker
 
