"""Request/response shapes for the conductor's working day.

The waybill is the conductor's real daily paperwork: sign on, take a bus, issue
tickets, sign off, remit cash. Modelling it is what makes this system touch the
one thing a transport corporation actually feels, which is money.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class PassengerType(str, Enum):
    ADULT = "adult"
    CHILD = "child"
    STUDENT = "student"
    SENIOR = "senior"
    SHAKTI = "shakti"
    """Free travel for women under the Karnataka Shakti scheme. Zero fare to
    the passenger, NOT zero value to BMTC -- the state reimburses it, and the
    claim is only as good as the count. See waybill_service.price_ticket."""


class PaymentMode(str, Enum):
    CASH = "cash"
    UPI = "upi"
    PASS = "pass"
    FREE = "free"
    """Used for scheme travel where nothing changes hands."""


class WaybillStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    RECONCILED = "reconciled"


class SignOnRequest(BaseModel):
    route_number: str = Field(..., min_length=1, max_length=50, examples=["500-D"])
    direction_id: int | None = Field(None, ge=0, le=1)
    bus_reg: str = Field(..., min_length=3, max_length=20, examples=["KA01F1234"])
    depot: str = Field("", max_length=120)
    driver_id: str | None = Field(None, max_length=64)
    opening_km: float = Field(..., ge=0, le=3_000_000)
    opening_ticket_serial: str = Field("", max_length=40)


class PassengerCount(BaseModel):
    passenger_type: PassengerType
    count: int = Field(..., ge=1, le=60)


class IssueTicketRequest(BaseModel):
    """One onboard ticket sale.

    `client_ticket_uuid` is generated on the device, not the server, and is the
    whole basis of safe offline operation: it lets the same sale be retried any
    number of times without being counted twice.
    """

    waybill_id: str = Field(..., min_length=1, max_length=64)
    client_ticket_uuid: str = Field(..., min_length=8, max_length=64)
    from_stop: str = Field(..., min_length=1, max_length=150)
    to_stop: str = Field(..., min_length=1, max_length=150)
    passengers: list[PassengerCount] = Field(..., min_length=1, max_length=10)
    payment_mode: PaymentMode = PaymentMode.CASH
    is_ac: bool = False
    issued_at: datetime | None = Field(
        None, description="When the device issued it. Preserved so an offline batch keeps its real times."
    )

    @field_validator("passengers")
    @classmethod
    def _no_duplicate_types(cls, value: list[PassengerCount]) -> list[PassengerCount]:
        seen = [item.passenger_type for item in value]
        if len(seen) != len(set(seen)):
            raise ValueError("Each passenger type may appear only once; use the count field.")
        return value


class SyncTicketsRequest(BaseModel):
    """A batch drained from the device's offline queue."""

    tickets: list[IssueTicketRequest] = Field(..., min_length=1, max_length=500)


class SignOffRequest(BaseModel):
    waybill_id: str = Field(..., min_length=1, max_length=64)
    closing_km: float = Field(..., ge=0, le=3_000_000)
    closing_ticket_serial: str = Field("", max_length=40)
    declared_cash: float = Field(..., ge=0, le=1_000_000)
    note: str | None = Field(None, max_length=300)


class IssuePassRequest(BaseModel):
    """Issue a real signed travel pass. Admin/depot only."""

    holder_name: str = Field(..., min_length=1, max_length=120)
    pass_type: str = Field(..., min_length=1, max_length=60, examples=["Student Monthly"])
    valid_days: int = Field(30, ge=1, le=400)
    route_permission: str = Field("All BMTC Non-AC & Ordinary Routes", max_length=200)
    user_id: str | None = Field(None, max_length=64)


class VerifyPassTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=4000, description="The signed token from the QR code")
    conductor_id: str | None = Field(None, max_length=64)
    route_id: str | None = Field(None, max_length=50)
    offline_mode: bool = False
