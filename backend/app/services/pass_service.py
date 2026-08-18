"""Travel passes: issued signed, verified offline, revoked by list.

Replaces a stub that decided validity from the pass id's own text:

    is_valid = not (pass_id.endswith("FAIL") or pass_id.endswith("EXPIRED") or "FAKE" in pass_id)

...while computing an HMAC that was never consulted and returning a hardcoded
passenger name. It also claimed "Offline Local Cryptographic Scan" and padded
its own response time to make the claim look measured.

The real thing is genuinely simpler. A pass is a signed token carrying its own
id, type, holder and expiry. A conductor's device verifies the signature and
the expiry with no network at all -- that is what offline verification means --
and the only thing it needs from the server is the revocation list, which is
small because it holds nothing but the ids of passes that were lost or
refunded.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.auth.auth import create_pass_token, decode_pass_token
from app.core.config import settings
from app.db.database import db_available, get_db

logger = logging.getLogger("bmtc.services.pass")


async def issue_pass(
    *, holder_name: str, pass_type: str, valid_days: int, route_permission: str,
    issued_by: str, user_id: str | None = None,
) -> dict[str, Any]:
    """Mint a signed pass and record it so it can later be revoked."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=valid_days)
    pass_id = f"BP-{now:%Y%m}-{uuid.uuid4().hex[:8].upper()}"

    token = create_pass_token(
        {
            "pass_id": pass_id,
            "holder_name": holder_name,
            "pass_type": pass_type,
            "route_permission": route_permission,
        },
        expires_seconds=valid_days * 86400,
    )

    document = {
        "pass_id": pass_id,
        "holder_name": holder_name,
        "pass_type": pass_type,
        "route_permission": route_permission,
        "user_id": user_id,
        "issued_by": issued_by,
        "issued_at": now,
        "expires_at": expires_at,
        "status": "active",
        "revoked_at": None,
        "revoked_reason": None,
    }
    if db_available():
        async for db in get_db():
            await db.travel_passes.insert_one(document)
            break

    logger.info("Pass %s issued (%s, %s days)", pass_id, pass_type, valid_days)
    return {
        "pass_id": pass_id,
        "token": token,
        "holder_name": holder_name,
        "pass_type": pass_type,
        "valid_until": expires_at.date().isoformat(),
        "route_permission": route_permission,
    }


async def revoke_pass(pass_id: str, reason: str, revoked_by: str) -> bool:
    async for db in get_db():
        result = await db.travel_passes.update_one(
            {"pass_id": pass_id, "status": "active"},
            {"$set": {
                "status": "revoked",
                "revoked_at": datetime.now(timezone.utc),
                "revoked_reason": reason,
                "revoked_by": revoked_by,
            }},
        )
        return result.modified_count > 0
    return False


async def revocation_list() -> dict[str, Any]:
    """The only thing a conductor's device needs from the network.

    Deliberately just ids and nothing else: it is cached on a shared device in
    a bus, so it must not carry holder names or any other personal data. Passes
    whose natural expiry has already passed are omitted -- the token's own
    expiry already rejects those, so listing them would grow the file forever
    for no benefit.
    """
    now = datetime.now(timezone.utc)
    ids: list[str] = []
    if db_available():
        async for db in get_db():
            cursor = db.travel_passes.find(
                {"status": "revoked", "expires_at": {"$gt": now}}, {"pass_id": 1}
            )
            ids = [row["pass_id"] async for row in cursor]
            break
    return {
        "status": "ok",
        "generated_at": now.isoformat(),
        "count": len(ids),
        "revoked_pass_ids": sorted(ids),
        "note": (
            "Cache this on the scanner. Signature and expiry are checked on the device "
            "with no network; this list is the only part that needs syncing."
        ),
    }


async def verify_pass_token(
    token: str, *, conductor_id: str | None = None, route_id: str | None = None,
    offline_mode: bool = False,
) -> dict[str, Any]:
    """Verify a scanned pass.

    The signature check is the decision. Revocation is consulted only when a
    database is reachable, and the response says which of the two checks
    actually ran -- a conductor operating from a cached list deserves to know
    that a pass revoked in the last few minutes might not be reflected yet.
    """
    now = datetime.now(timezone.utc)
    try:
        payload = decode_pass_token(token)
    except Exception as exc:                       # HTTPException from decode
        detail = getattr(exc, "detail", str(exc))
        return {
            "status": "INVALID",
            "reason": str(detail),
            "verification_mode": "offline signature check",
            "checked_revocation": False,
            "scanned_by": conductor_id,
            "route_id": route_id,
            "timestamp": now.isoformat(),
        }

    pass_id = payload.get("pass_id", "")
    result = {
        "status": "VALID",
        "pass_id": pass_id,
        "holder_name": payload.get("holder_name"),
        "pass_type": payload.get("pass_type"),
        "route_permission": payload.get("route_permission"),
        "valid_until": datetime.fromtimestamp(payload["exp"], tz=timezone.utc).date().isoformat(),
        # Signature and expiry were both verified without touching the network.
        # That is the real claim the old stub only asserted.
        "verification_mode": "offline signature check" if offline_mode else "signature check",
        "checked_revocation": False,
        "scanned_by": conductor_id,
        "route_id": route_id,
        "timestamp": now.isoformat(),
    }

    if db_available():
        async for db in get_db():
            record = await db.travel_passes.find_one({"pass_id": pass_id})
            result["checked_revocation"] = True
            if record and record.get("status") == "revoked":
                result["status"] = "INVALID"
                result["reason"] = f"Pass revoked: {record.get('revoked_reason') or 'no reason recorded'}"
            break
    elif not offline_mode:
        result["revocation_note"] = (
            "Revocation could not be checked -- the pass register is unreachable. The "
            "signature and expiry above are still verified."
        )

    return result


def demo_verify(pass_id: str, *, conductor_id: str | None, route_id: str | None) -> dict[str, Any]:
    """Accept an unsigned pass id, for demonstrations before any pass exists.

    Off by default (DEMO_PASS_MODE) and every response carries demo_mode=true,
    so a demo result can never be mistaken for a real verification. This exists
    because removing the stub would otherwise break the ability to show the
    scanner working at all before passes have been issued.
    """
    return {
        "status": "VALID",
        "pass_id": pass_id.strip().upper(),
        "holder_name": None,
        "pass_type": "Demonstration pass",
        "route_permission": "Demonstration only",
        "valid_until": None,
        "verification_mode": "DEMO -- no signature was checked",
        "checked_revocation": False,
        "demo_mode": True,
        "scanned_by": conductor_id,
        "route_id": route_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def demo_mode_enabled() -> bool:
    return settings.demo_pass_mode
