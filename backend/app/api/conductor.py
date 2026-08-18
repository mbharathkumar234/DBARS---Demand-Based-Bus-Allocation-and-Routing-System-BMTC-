"""The conductor's working day, and the depot/office views built on it.

This is the one part of DBARS that touches money, which is why every write here
is audited, every total is recomputed server-side, and every offline sale is
idempotent. It is also the reason this is the feature most likely to get a
transport corporation to adopt the system: it is the workflow they actually
feel.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth.auth import UserRole, get_current_user, require_role
from app.models.waybill import (
    IssuePassRequest,
    IssueTicketRequest,
    SignOffRequest,
    SignOnRequest,
    SyncTicketsRequest,
    VerifyPassTokenRequest,
)
from app.services import audit_service, pass_service
from app.services.waybill_service import (
    WaybillError,
    close_waybill,
    get_open_waybill,
    issue_tickets,
    list_waybills,
    open_waybill,
    revenue_reconciliation,
    shakti_claim,
)

logger = logging.getLogger("bmtc.api.conductor")

router = APIRouter(prefix="/conductor", tags=["conductor"])
depot_router = APIRouter(prefix="/depot", tags=["depot"])
office_router = APIRouter(prefix="/admin", tags=["admin"])

_conductor = require_role(UserRole.CONDUCTOR, UserRole.ADMIN)
_supervisor = require_role(UserRole.DEPOT_MANAGER, UserRole.ADMIN)


# ── the conductor's day ─────────────────────────────────────────────────────

@router.post("/sign-on", status_code=201)
async def sign_on(payload: SignOnRequest, user: dict = Depends(_conductor)) -> dict:
    """Start a duty and open a waybill.

    Refuses a second concurrent waybill: two open waybills means tickets land
    on whichever the device happens to name, and the cash at the end
    reconciles against neither.
    """
    try:
        waybill = await open_waybill(user["sub"], payload)
    except WaybillError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await audit_service.record(
        "waybill.sign_on", user["sub"], subject=waybill["waybill_id"],
        metadata={"route": payload.route_number, "bus": payload.bus_reg},
    )
    return {"status": "ok", "waybill": waybill}


@router.get("/waybill")
async def current_waybill(user: dict = Depends(_conductor)) -> dict:
    """The conductor's open waybill, if any. The device calls this on launch to
    recover state after being killed mid-shift."""
    waybill = await get_open_waybill(user["sub"])
    return {"status": "ok" if waybill else "none", "waybill": waybill}


@router.post("/tickets/issue")
async def issue_ticket(
    payload: IssueTicketRequest, request: Request, user: dict = Depends(_conductor)
) -> dict:
    """Issue one ticket, online.

    Shares its whole implementation with the offline sync path below, so the
    two can never price a journey differently.
    """
    result = await issue_tickets(user["sub"], [payload], request)
    if result["rejected"]:
        raise HTTPException(status_code=422, detail=result["rejected"][0]["reason"])
    if result["duplicates"]:
        return {"status": "duplicate", "note": "This sale was already recorded.", **result}
    return {"status": "ok", **result}


@router.post("/tickets/sync")
async def sync_tickets(
    payload: SyncTicketsRequest, request: Request, user: dict = Depends(_conductor)
) -> dict:
    """Drain the device's offline queue.

    Returns a per-item outcome rather than one overall status. The device must
    clear only what the server acknowledged -- clearing the queue on a partial
    success is exactly how offline sales get lost, and a lost sale is
    indistinguishable afterwards from one that was never made.
    """
    result = await issue_tickets(user["sub"], payload.tickets, request)
    await audit_service.record(
        "waybill.tickets_synced", user["sub"],
        subject=payload.tickets[0].waybill_id,
        metadata=result["counts"],
    )
    return {"status": "ok", **result}


@router.post("/sign-off")
async def sign_off(payload: SignOffRequest, user: dict = Depends(_conductor)) -> dict:
    """End the duty: recompute totals, compare declared cash against expected.

    The variance is reported, never auto-resolved. A system that quietly
    adjusts a cash figure so the books balance has destroyed the only signal
    the depot had.
    """
    try:
        waybill = await close_waybill(user["sub"], payload)
    except WaybillError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await audit_service.record(
        "waybill.sign_off", user["sub"], subject=waybill["waybill_id"],
        metadata={
            "declared_cash": payload.declared_cash,
            "expected_cash": waybill["reconciliation"]["expected_cash"],
            "variance": waybill["reconciliation"]["variance"],
        },
    )
    return {"status": "ok", "waybill": waybill}


# ── passes ──────────────────────────────────────────────────────────────────

@router.post("/verify-pass")
async def verify_pass(payload: VerifyPassTokenRequest) -> dict:
    """Verify a scanned travel pass.

    Signature and expiry are checked with no network -- that is what offline
    verification means, and it is what the previous version of this endpoint
    only claimed while actually deciding validity from whether the pass id
    happened to end in "FAIL".
    """
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=422, detail="No pass token supplied.")

    # A bare pass id (not a signed token) is only acceptable in demo mode, and
    # the response says so in every field a caller might read.
    if "." not in token:
        if not pass_service.demo_mode_enabled():
            raise HTTPException(
                status_code=422,
                detail=(
                    "That is a pass id, not a signed pass token. Scan the QR code from an "
                    "issued pass, or set DEMO_PASS_MODE=true to accept bare ids for a "
                    "demonstration."
                ),
            )
        return pass_service.demo_verify(
            token, conductor_id=payload.conductor_id, route_id=payload.route_id
        )

    return await pass_service.verify_pass_token(
        token,
        conductor_id=payload.conductor_id,
        route_id=payload.route_id,
        offline_mode=payload.offline_mode,
    )


@router.get("/pass-revocations")
async def pass_revocations(user: dict = Depends(_conductor)) -> dict:
    """The revocation list a scanner caches for offline use."""
    return await pass_service.revocation_list()


@depot_router.post("/passes", status_code=201)
async def issue_travel_pass(payload: IssuePassRequest, user: dict = Depends(_supervisor)) -> dict:
    """Issue a real signed pass. The token is the QR code's contents."""
    issued = await pass_service.issue_pass(
        holder_name=payload.holder_name,
        pass_type=payload.pass_type,
        valid_days=payload.valid_days,
        route_permission=payload.route_permission,
        issued_by=user["sub"],
        user_id=payload.user_id,
    )
    await audit_service.record(
        "pass.issued", user["sub"], subject=issued["pass_id"],
        metadata={"pass_type": payload.pass_type, "valid_days": payload.valid_days},
    )
    return {"status": "ok", "pass": issued}


@depot_router.post("/passes/{pass_id}/revoke")
async def revoke_travel_pass(
    pass_id: str, reason: str = Query("", max_length=200), user: dict = Depends(_supervisor)
) -> dict:
    revoked = await pass_service.revoke_pass(pass_id, reason, user["sub"])
    if not revoked:
        raise HTTPException(status_code=404, detail=f"No active pass {pass_id}.")
    await audit_service.record("pass.revoked", user["sub"], subject=pass_id, metadata={"reason": reason})
    return {"status": "ok", "pass_id": pass_id}


# ── depot and office views ──────────────────────────────────────────────────

@depot_router.get("/waybills")
async def depot_waybills(
    duty_date: str = Query("", max_length=10, description="YYYY-MM-DD"),
    depot: str = Query("", max_length=120),
    status: str = Query("", max_length=20),
    user: dict = Depends(_supervisor),
) -> dict:
    """Waybills for a depot and day: open, closed, and cash variances.

    The two things a depot manager looks for here are a waybill still open long
    after the duty should have ended, and a variance -- both surfaced rather
    than left to be noticed.
    """
    waybills = await list_waybills(depot=depot, duty_date=duty_date, status=status)
    flagged = [
        entry for entry in waybills
        if (entry.get("reconciliation") or {}).get("variance_flagged")
    ]
    return {
        "status": "ok",
        "count": len(waybills),
        "open": sum(1 for entry in waybills if entry["status"] == "open"),
        "variances_flagged": len(flagged),
        "waybills": waybills,
    }


@office_router.get("/shakti/claim")
async def shakti_claim_report(
    date_from: str = Query("", max_length=10),
    date_to: str = Query("", max_length=10),
    depot: str = Query("", max_length=120),
    user: dict = Depends(_supervisor),
) -> dict:
    """Shakti boardings and claim value, per depot per day.

    What the office files with the state. Sums what the journeys WOULD have
    cost, because the passenger paid nothing -- which is precisely why there is
    something to claim.
    """
    return await shakti_claim(date_from=date_from, date_to=date_to, depot=depot)


@office_router.get("/revenue/reconciliation")
async def revenue_report(
    date_from: str = Query("", max_length=10),
    date_to: str = Query("", max_length=10),
    depot: str = Query("", max_length=120),
    user: dict = Depends(_supervisor),
) -> dict:
    """Cash vs digital vs pass vs scheme, with declared-versus-expected variance."""
    return await revenue_reconciliation(date_from=date_from, date_to=date_to, depot=depot)


@office_router.get("/audit")
async def audit_log(
    limit: int = Query(100, ge=1, le=500),
    action: str = Query("", max_length=40),
    user: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Who did what, when. Admin only."""
    return {"status": "ok", "events": await audit_service.recent(limit=limit, action=action)}
