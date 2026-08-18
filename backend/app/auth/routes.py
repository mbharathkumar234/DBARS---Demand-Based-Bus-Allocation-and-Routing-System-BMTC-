from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.auth.auth import (
    create_access_token,
    TOKEN_TYPE_REFRESH,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.shakti import Gender, is_shakti_eligible
from app.db.database import get_db

logger = logging.getLogger("bmtc.auth.routes")

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    name: str = Field(..., min_length=2, max_length=100)
    # role intentionally absent -- public signup creates commuters only
    #
    # Gender is collected for exactly one purpose: Shakti scheme eligibility,
    # which is a real entitlement worth real money to the passenger. It is
    # optional, "prefer not to say" is a first-class answer, and it is used
    # nowhere else in this codebase -- not in prediction, not in analytics, not
    # in any dashboard. Collecting a sensitive attribute is only defensible
    # when it does one specific thing for the person it was collected from.
    gender: Gender | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


def _format_user(user_doc: dict[str, Any]) -> dict[str, Any]:
    gender = user_doc.get("gender")
    eligible, _ = is_shakti_eligible(gender)
    return {
        "id": str(user_doc.get("_id", "")),
        "email": user_doc.get("email", ""),
        "name": user_doc.get("name", ""),
        "role": user_doc.get("role", "commuter"),
        "preferred_lang": user_doc.get("preferred_lang", "en"),
        "reliability": user_doc.get("reliability", 1.0),
        "gender": gender,
        # Surfaced so the app can tell a passenger her fare will be zero BEFORE
        # she reaches the payment step, rather than after. Note this is the
        # non-AC answer; an AC journey is chargeable for everyone, and the
        # purchase response says so at the point it applies.
        "shakti_eligible": eligible,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> dict[str, Any]:
    """Public user registration. Always assigns role='commuter'."""
    async for db in get_db():
        existing = await db.users.find_one({"email": payload.email.lower().strip()})
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists.",
            )

        user_doc = {
            "email": payload.email.lower().strip(),
            "name": payload.name.strip(),
            "password_hash": hash_password(payload.password),
            "role": "commuter",  # Enforce commuter role for public registration
            "preferred_lang": "en",
            "reliability": 1.0,
            "is_active": 1,
            "created_at": datetime.now(timezone.utc),
            # Stored as the plain value, or None when not given. "prefer not to
            # say" is recorded as itself rather than as a missing field, so a
            # deliberate non-answer is distinguishable from an older account
            # that was created before this field existed.
            "gender": payload.gender.value if payload.gender else None,
        }

        res = await db.users.insert_one(user_doc)
        user_doc["_id"] = res.inserted_id

        user_id_str = str(res.inserted_id)
        access_token = create_access_token(
            user_id=user_id_str,
            email=user_doc["email"],
            role=user_doc["role"],
            name=user_doc["name"],
        )
        refresh_token = create_refresh_token(user_id=user_id_str)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": _format_user(user_doc),
        }

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database unavailable.",
    )


@router.post("/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    """Authenticate user with email and password."""
    async for db in get_db():
        user = await db.users.find_one({"email": payload.email.lower().strip()})
        if not user or not verify_password(payload.password, user.get("password_hash", "")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not user.get("is_active", 1):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        user_id_str = str(user["_id"])
        access_token = create_access_token(
            user_id=user_id_str,
            email=user["email"],
            role=user.get("role", "commuter"),
            name=user.get("name", ""),
        )
        refresh_token = create_refresh_token(user_id=user_id_str)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": _format_user(user),
        }

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database unavailable.",
    )


@router.get("/me")
async def get_me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return current authenticated user profile."""
    from bson import ObjectId
    from bson.errors import InvalidId

    user_id = current_user.get("sub", "")
    async for db in get_db():
        try:
            oid = ObjectId(user_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid user id in token.")

        user = await db.users.find_one({"_id": oid})
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        return {"user": _format_user(user)}

    # Fallback to token claims if DB unavailable. Gender is deliberately NOT
    # carried in the token -- a bearer credential that travels through logs,
    # proxies and local storage is the wrong place for a sensitive attribute --
    # so it is simply unknown here, and the scheme reports itself unavailable
    # rather than defaulting to "not eligible", which would read as a decision.
    return {
        "user": {
            "id": current_user.get("sub", ""),
            "email": current_user.get("email", ""),
            "name": current_user.get("name", ""),
            "role": current_user.get("role", "commuter"),
            "preferred_lang": "en",
            "reliability": 1.0,
            "gender": None,
            "shakti_eligible": None,
        }
    }


@router.post("/refresh")
async def refresh_token(payload: RefreshTokenRequest) -> dict[str, Any]:
    """Issue a new access token using a valid refresh token."""
    token_payload = decode_token(payload.refresh_token)
    if token_payload.get("type") != TOKEN_TYPE_REFRESH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provided token is not a refresh token.",
        )

    user_id = token_payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload.",
        )

    from bson import ObjectId
    from bson.errors import InvalidId

    async for db in get_db():
        try:
            oid = ObjectId(user_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid user id in token.")

        user = await db.users.find_one({"_id": oid})
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        new_access_token = create_access_token(
            user_id=str(user["_id"]),
            email=user["email"],
            role=user.get("role", "commuter"),
            name=user.get("name", ""),
        )
        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "user": _format_user(user),
        }

    # If DB is down, issue token using claims
    new_access_token = create_access_token(
        user_id=user_id,
        email=token_payload.get("email", ""),
        role=token_payload.get("role", "commuter"),
        name=token_payload.get("name", ""),
    )
    return {"access_token": new_access_token, "token_type": "bearer"}