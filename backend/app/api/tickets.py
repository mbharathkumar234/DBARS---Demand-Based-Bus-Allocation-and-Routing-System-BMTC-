from datetime import datetime, timezone, timedelta
import secrets
import string
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from app.auth.auth import (
    UserRole,
    create_ticket_token,
    decode_ticket_token,
    get_current_user,
    require_role,
)
from app.db.database import get_db
from app.models.tickets import (
    TicketPurchaseRequest, 
    TicketResponse, 
    VerifyTicketRequest, 
    VerifyTicketResponse
)
from app.core.fares import get_fare
from app.core.shakti import (
    DISCLOSURE as SHAKTI_DISCLOSURE,
    SCHEME_NAME,
    is_shakti_eligible,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

# Expiry for tickets in seconds (e.g. 2 hours)
TICKET_EXPIRY_SECONDS = 2 * 60 * 60

from fastapi import Request

@router.get("/fare")
async def get_estimated_fare(source: str, destination: str, request: Request, is_ac: bool = False):
    """Gets the fare between two stops"""
    fare = get_fare(source, destination, request, is_ac)
    if fare is None:
        raise HTTPException(status_code=404, detail="Fare not found for this route")
    return {"fare": fare}

async def _account_gender(db, user_id: str) -> str | None:
    """Read the passenger's gender from their account, never from the token.

    A bearer token travels through logs, proxies and browser storage; a
    sensitive attribute does not belong in one. The cost is a single indexed
    lookup per purchase, which is the right trade.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        oid = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None
    account = await db.users.find_one({"_id": oid}, {"gender": 1})
    return (account or {}).get("gender")


@router.post("/purchase", response_model=TicketResponse)
async def purchase_ticket(
    payload: TicketPurchaseRequest,
    req: Request,
    user: dict = Depends(get_current_user)
):
    """Issue a ticket, priced server-side, free where the Shakti scheme applies.

    A Shakti ticket is issued exactly like any other -- same QR token, same
    six-character short code, same expiry -- because a conductor must be able
    to verify it with the same scan and the same glance. What differs is only
    the money: the passenger pays nothing, and the fare the journey WOULD have
    cost is recorded as the amount BMTC claims back from the state.

    Keeping fare_value_inr and fare_collected_inr as separate fields is the
    whole point. Revenue reporting uses what was collected; the reimbursement
    claim uses what it was worth. A single fare_amount field cannot express
    both, and collapsing them misstates one or the other.
    """
    fare = get_fare(payload.source_stop, payload.destination_stop, req, payload.is_ac)
    if fare is None:
        raise HTTPException(status_code=422, detail="Could not price this journey.")

    async for db in get_db():
        gender = await _account_gender(db, user.get("sub", ""))
        # Same rule the conductor's onboard sale uses -- see app/core/shakti.py.
        # Two implementations would eventually disagree, and a passenger told
        # by the app that her journey is free and then charged on the bus has
        # been failed by the software twice.
        free_travel, ineligible_reason = is_shakti_eligible(gender, is_ac=payload.is_ac)

        fare_value = round(float(fare), 2)
        fare_collected = 0.0 if free_travel else fare_value

        ticket_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=TICKET_EXPIRY_SECONDS)

        # Generate a unique 6-character alphanumeric short code for quick
        # visual verification (displayed in large text under the QR code).
        _alphabet = string.ascii_uppercase + string.digits
        short_code = ''.join(secrets.choice(_alphabet) for _ in range(6))

        # QR token payload. create_ticket_token stamps the ticket type and
        # signs with the ticket-domain key -- see app/auth/auth.py.
        # Identical for a Shakti ticket: the scheme changes who pays, not what
        # a valid ticket looks like.
        qr_token = create_ticket_token(
            {
                "ticket_id": ticket_id,
                "source": payload.source_stop,
                "destination": payload.destination_stop,
            },
            TICKET_EXPIRY_SECONDS,
        )

        ticket_doc = {
            "ticket_id": ticket_id,
            "user_id": user.get("sub"),
            "source_stop": payload.source_stop,
            "destination_stop": payload.destination_stop,
            # What the passenger actually pays. Zero on a scheme ticket.
            "fare_amount": fare_collected,
            "fare_value_inr": fare_value,
            "fare_collected_inr": fare_collected,
            "is_zero_fare": free_travel,
            "scheme": SCHEME_NAME if free_travel else None,
            # No gender is stored on the ticket. The scheme needs a count and a
            # value to claim against, not a record of who travelled -- the same
            # minimal-collection principle set out in analytics_service.py.
            "issue_time": now,
            "expiry_time": expiry,
            "status": "ISSUED",
            "qr_token": qr_token,
            "short_code": short_code
        }

        # Insert into DB
        await db.tickets.insert_one(ticket_doc)

        # Transaction log. A scheme ticket still gets one, for a zero amount:
        # a missing transaction would look like a failed purchase, and the
        # ledger should show that a journey happened and nothing was charged.
        transaction_doc = {
            "transaction_id": str(uuid.uuid4()),
            "ticket_id": ticket_id,
            "user_id": user.get("sub"),
            "amount": fare_collected,
            "status": "SUCCESS",
            "scheme": SCHEME_NAME if free_travel else None,
            "timestamp": now
        }
        await db.transactions.insert_one(transaction_doc)

        response = TicketResponse(**ticket_doc)
        response.scheme_note = SHAKTI_DISCLOSURE if free_travel else ineligible_reason
        return response

@router.get("/active", response_model=TicketResponse)
async def get_active_ticket(user: dict = Depends(get_current_user)):
    """Fetches the currently active (ISSUED and not expired) ticket for the user."""
    async for db in get_db():
        now = datetime.now(timezone.utc)
        ticket = await db.tickets.find_one({
            "user_id": user.get("sub"),
            "status": "ISSUED",
            "expiry_time": {"$gt": now}
        }, sort=[("issue_time", -1)])
        
        if not ticket:
            raise HTTPException(status_code=404, detail="No active ticket found")
            
        return TicketResponse(**ticket)

@router.get("/history", response_model=List[TicketResponse])
async def get_ticket_history(user: dict = Depends(get_current_user)):
    """Fetches all tickets for the user."""
    async for db in get_db():
        cursor = db.tickets.find({"user_id": user.get("sub")}).sort("issue_time", -1)
        tickets = await cursor.to_list(length=100)
        return [TicketResponse(**t) for t in tickets]

@router.post("/verify", response_model=VerifyTicketResponse)
async def verify_ticket(
    request: VerifyTicketRequest, 
    conductor: dict = Depends(require_role(UserRole.CONDUCTOR, UserRole.ADMIN, UserRole.DEPOT_MANAGER))
):
    """
    Verifies a scanned QR token. (Conductors/Admins only)
    """
    # 1. Decode token
    try:
        # Verifies the ticket-domain signature AND the ticket type together --
        # a session/refresh token signed with the auth key cannot satisfy this.
        payload = decode_ticket_token(request.qr_token)
    except HTTPException as e:
        return VerifyTicketResponse(success=False, message=str(e.detail))
    except Exception as e:
        return VerifyTicketResponse(success=False, message=str(e))


    ticket_id = payload.get("ticket_id")
    
    async for db in get_db():
        now = datetime.now(timezone.utc)

        # 2. Claim the ticket ATOMICALLY.
        #
        # This was previously find_one() -> inspect status -> update_one(), with
        # `await` points in between. Two conductors scanning the same QR at the
        # same moment both read status "ISSUED" before either wrote "USED", so
        # both were told SUCCESS -- one ticket, two rides, every time. Verified
        # against a live instance: 2 of 2 concurrent scans were accepted.
        #
        # find_one_and_update with the status in the FILTER makes the read and
        # the write a single atomic document operation, so exactly one caller
        # can ever transition ISSUED -> USED. The loser matches nothing here and
        # falls through to the diagnostic read below, which reports why.
        claimed = await db.tickets.find_one_and_update(
            {"ticket_id": ticket_id, "status": "ISSUED", "expiry_time": {"$gt": now}},
            {"$set": {"status": "USED", "used_at": now}},
        )

        if claimed:
            result = "SUCCESS"
        else:
            # Did not win the claim. Work out the honest reason.
            ticket = await db.tickets.find_one({"ticket_id": ticket_id})
            if not ticket:
                return VerifyTicketResponse(
                    success=False, message="Ticket not found in database", ticket_id=ticket_id
                )

            expiry = ticket["expiry_time"]
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            if ticket["status"] == "USED":
                result = "ALREADY_USED"
            elif ticket["status"] == "CANCELLED":
                result = "CANCELLED"
            elif expiry < now:
                result = "EXPIRED"
                if ticket["status"] == "ISSUED":
                    await db.tickets.update_one(
                        {"ticket_id": ticket_id, "status": "ISSUED"},
                        {"$set": {"status": "EXPIRED"}},
                    )
            else:
                result = ticket["status"]


        # 3. Log verification
        log_doc = {
            "log_id": str(uuid.uuid4()),
            "ticket_id": ticket_id,
            "conductor_id": conductor.get("sub"),
            "scan_time": now,
            "result": result
        }
        await db.verification_logs.insert_one(log_doc)
        
        success = (result == "SUCCESS")
        message = "Verification successful" if success else f"Verification failed: {result}"
        
        return VerifyTicketResponse(
            success=success, 
            message=message, 
            ticket_id=ticket_id,
            status=result
        )
