from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class TicketPurchaseRequest(BaseModel):
    source_stop: str = Field(..., description="The source stop name")
    destination_stop: str = Field(..., description="The destination stop name")
    is_ac: bool = Field(False, description="Whether the journey is AC service")
    fare_amount: Optional[float] = Field(None, description="Optional client fare estimate (ignored, recomputed server-side)")

class TicketResponse(BaseModel):
    ticket_id: str
    user_id: str
    source_stop: str
    destination_stop: str
    fare_amount: float
    """What the passenger actually paid. Zero on a scheme ticket."""

    issue_time: datetime
    expiry_time: datetime
    status: str
    qr_token: str
    short_code: str

    # Scheme fields. All optional with defaults, because tickets issued before
    # the Shakti flow existed are still in the database and must keep
    # deserialising through this same model -- a required field here would
    # break every historical ticket in /api/tickets/history.
    fare_value_inr: Optional[float] = None
    """What the journey would have cost. On a Shakti ticket this is the amount
    BMTC claims back from the state, and it is the reason a zero-fare ticket
    still has to carry a price."""

    fare_collected_inr: Optional[float] = None
    is_zero_fare: bool = False
    scheme: Optional[str] = None
    scheme_note: Optional[str] = None
    """Shown to the passenger: either the scheme disclosure, or the reason a
    free ticket was not issued when they might have expected one."""

class VerifyTicketRequest(BaseModel):
    qr_token: str = Field(..., description="The JWT token from the QR code")

class VerifyTicketResponse(BaseModel):
    success: bool
    message: str
    ticket_id: Optional[str] = None
    status: Optional[str] = None
