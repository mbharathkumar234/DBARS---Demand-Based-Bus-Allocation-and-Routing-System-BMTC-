from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.auth import get_current_user
from app.models.schemas import CreateTripShareRequest, SaveTrustedContactsRequest
from app.services.safety_service import (
    create_trip_share,
    get_shared_trip,
    get_trusted_contacts,
    save_trusted_contacts,
)

router = APIRouter(prefix="/safety", tags=["safety"])


@router.get("/contacts")
async def list_trusted_contacts(user: dict = Depends(get_current_user)) -> dict:
    contacts = await get_trusted_contacts(user["sub"])
    return {"contacts": contacts}


@router.put("/contacts")
async def update_trusted_contacts(
    payload: SaveTrustedContactsRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    try:
        contacts = await save_trusted_contacts(
            user["sub"], [c.model_dump() for c in payload.contacts]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "contacts": contacts}


@router.post("/share-trip")
async def share_trip(
    payload: CreateTripShareRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Create a shareable record of a PLANNED trip -- see
    safety_service.py's create_trip_share docstring for why this is
    explicitly not, and must never become, a live-location claim."""
    share = await create_trip_share(
        user_id=user["sub"],
        current_stop=payload.current_stop,
        destination=payload.destination,
        bus_number=payload.bus_number,
        matched_current_stop=payload.matched_current_stop,
        matched_destination=payload.matched_destination,
    )
    return {"status": "ok", **share}


@router.get("/trip/{code}")
async def view_shared_trip(code: str) -> dict:
    """Public (no login required) -- this is what a trusted contact opens.
    Deliberately does not require the viewer to have an account, since the
    person checking on someone may not be a registered app user."""
    trip = await get_shared_trip(code)
    if not trip:
        raise HTTPException(status_code=404, detail="This trip link has expired or doesn't exist.")
    return trip