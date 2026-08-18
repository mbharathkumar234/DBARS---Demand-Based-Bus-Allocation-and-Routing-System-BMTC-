"""The conductor's waybill: sign on, issue tickets, sign off, reconcile.

Three properties drive the design, and each one exists because the alternative
loses or invents money.

IDEMPOTENCY. Buses lose signal constantly and a conductor cannot stop selling
tickets, so issuance is offline-first: the device assigns each sale a UUID and
replays its queue until the server acknowledges. A unique index on
(waybill_id, client_ticket_uuid) means a replayed batch cannot be counted
twice. Revenue that double-counts on a flaky connection is worse than useless.

SERVER-SIDE TOTALS. A waybill's totals are recomputed from its ticket rows on
close and never taken from the client. A client-supplied total in a revenue
document is a fraud vector, and the device is a phone in a bus.

FARE VALUE VS FARE COLLECTED. A Shakti ticket is free to the passenger and not
free to BMTC: the state reimburses it. So every ticket records both what it
would have cost and what was actually taken. Revenue reports use the second;
reimbursement claims use the first. Conflating them misstates both.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.core.shakti import SCHEME_NAME as SHAKTI_SCHEME
from app.db.database import get_db
from app.models.waybill import (
    IssueTicketRequest,
    PassengerType,
    PaymentMode,
    SignOffRequest,
    SignOnRequest,
    WaybillStatus,
)

logger = logging.getLogger("bmtc.services.waybill")

# Passenger types that pay nothing at the point of travel. Their fare VALUE is
# still computed and stored -- for shakti because the state reimburses it, and
# so that a depot can see what concessional travel is costing either way.
ZERO_FARE_TYPES = {PassengerType.SHAKTI}

# Concession multipliers applied to the adult stage fare. Placeholders in the
# same sense as BlockingParameters: BMTC's real concession rules are policy,
# not published data, and these are declared in the API response rather than
# buried so they can be corrected without archaeology.
CONCESSION_MULTIPLIERS = {
    PassengerType.ADULT: 1.0,
    PassengerType.CHILD: 0.5,
    PassengerType.STUDENT: 0.5,
    PassengerType.SENIOR: 0.75,
    PassengerType.SHAKTI: 1.0,      # full value, zero collected
}

SCHEME_BY_TYPE = {PassengerType.SHAKTI: SHAKTI_SCHEME}


class WaybillError(Exception):
    """A refusal the conductor needs to see, not a server fault."""


# Below this, a stop name has not really been recognised and the fare computed
# from it is a guess. get_fare() logs a warning and prices it anyway, which is
# defensible for a commuter e-ticket -- the rider picked both stops from
# autocomplete and can see them on screen. It is not defensible for a cash sale
# on a bus, where a mispriced ticket is money taken at the wrong rate from
# someone with no way to check. Same threshold the SMS channel uses to decide
# when it must not sound confident.
MIN_STOP_CONFIDENCE = 0.55


def price_ticket(
    from_stop: str,
    to_stop: str,
    passengers: list[tuple[PassengerType, int]],
    request: Any,
    is_ac: bool = False,
) -> dict[str, Any]:
    """Price one sale, splitting value from collection.

    Pricing goes through core/fares.py's stage table -- the same authoritative,
    data-driven path the commuter e-ticket uses. A second pricing
    implementation here would drift from that one, and two fare answers for the
    same journey is how a fare system starts lying.
    """
    from app.core.fares import get_fare

    predictor = request.app.state.predictor
    resolved_from, from_score = predictor._resolve_stop_name(from_stop)
    resolved_to, to_score = predictor._resolve_stop_name(to_stop)
    if from_score < MIN_STOP_CONFIDENCE or to_score < MIN_STOP_CONFIDENCE:
        unclear = from_stop if from_score < MIN_STOP_CONFIDENCE else to_stop
        raise WaybillError(
            f"Could not confidently identify the stop {unclear!r}, so this journey has not "
            f"been priced. Closest matches were {resolved_from!r} and {resolved_to!r} -- "
            "re-enter the stop name rather than issuing a ticket at a guessed fare."
        )

    base = get_fare(from_stop, to_stop, request, is_ac)
    if base is None:
        raise WaybillError(f"Could not price {from_stop} to {to_stop}.")

    lines = []
    value_total = 0.0
    collected_total = 0.0
    for passenger_type, count in passengers:
        multiplier = CONCESSION_MULTIPLIERS.get(passenger_type, 1.0)
        unit_value = round(float(base) * multiplier, 2)
        line_value = round(unit_value * count, 2)
        # The scheme covers ordinary services only -- an AC (Vajra) or airport
        # journey is chargeable for everyone. Enforced through the same shared
        # rule the app's e-ticket uses, so a passenger cannot be told her AC
        # journey is free in the app and then charged for it on the bus.
        is_zero_fare = passenger_type in ZERO_FARE_TYPES and not is_ac
        line_collected = 0.0 if is_zero_fare else line_value
        lines.append({
            "passenger_type": passenger_type.value,
            "count": count,
            "unit_fare_value_inr": unit_value,
            "fare_value_inr": line_value,
            "fare_collected_inr": line_collected,
            "is_zero_fare": is_zero_fare,
            # The scheme is still named on a chargeable AC line: the passenger
            # is a Shakti traveller who happened to board a service the scheme
            # does not cover, and a depot reviewing the waybill needs to see
            # that rather than a bare adult fare.
            "scheme": SCHEME_BY_TYPE.get(passenger_type),
        })
        value_total += line_value
        collected_total += line_collected

    return {
        "adult_stage_fare_inr": round(float(base), 2),
        # Echoed back so the conductor's screen shows which stops were actually
        # priced, not just the text that was typed.
        "resolved_from": resolved_from,
        "resolved_to": resolved_to,
        "lines": lines,
        "fare_value_inr": round(value_total, 2),
        "fare_collected_inr": round(collected_total, 2),
    }


async def open_waybill(conductor_id: str, payload: SignOnRequest) -> dict[str, Any]:
    """Sign on: one open waybill per conductor at a time.

    Refusing a second concurrent waybill is not a technicality. Two open
    waybills means tickets land on whichever one the device happens to name,
    and the cash at the end reconciles against neither.
    """
    async for db in get_db():
        existing = await db.waybills.find_one({"conductor_id": conductor_id, "status": WaybillStatus.OPEN.value})
        if existing:
            raise WaybillError(
                f"You already have an open waybill ({existing['waybill_id']}) on route "
                f"{existing['route_number']}. Sign off from it before starting another."
            )

        now = datetime.now(timezone.utc)
        document = {
            "waybill_id": f"WB-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
            "conductor_id": conductor_id,
            "driver_id": payload.driver_id,
            "bus_reg": payload.bus_reg.strip().upper(),
            "depot": payload.depot.strip(),
            "route_number": payload.route_number.strip(),
            "direction_id": payload.direction_id,
            "duty_date": now.date().isoformat(),
            "status": WaybillStatus.OPEN.value,
            "sign_on_at": now,
            "sign_off_at": None,
            "opening_km": payload.opening_km,
            "closing_km": None,
            "opening_ticket_serial": payload.opening_ticket_serial,
            "closing_ticket_serial": None,
            "totals": _empty_totals(),
            "reconciliation": None,
        }
        await db.waybills.insert_one(document)
        logger.info("Waybill %s opened by %s on %s", document["waybill_id"], conductor_id, document["route_number"])
        return _serialize(document)
    return {}


def _empty_totals() -> dict[str, Any]:
    return {
        "tickets_issued": 0,
        "passengers": 0,
        "cash_amount": 0.0,
        "digital_amount": 0.0,
        "pass_boardings": 0,
        "shakti_boardings": 0,
        "shakti_claim_value": 0.0,
        "fare_value_total": 0.0,
        "fare_collected_total": 0.0,
    }


async def get_open_waybill(conductor_id: str) -> dict[str, Any] | None:
    async for db in get_db():
        document = await db.waybills.find_one(
            {"conductor_id": conductor_id, "status": WaybillStatus.OPEN.value}
        )
        return _serialize(document) if document else None
    return None


async def issue_tickets(
    conductor_id: str, tickets: list[IssueTicketRequest], request: Any
) -> dict[str, Any]:
    """Record a batch of onboard sales, idempotently.

    Returns a per-item outcome rather than a single status, so the device knows
    exactly which entries to drop from its offline queue. Clearing the queue on
    a partial success is how offline sales get lost.
    """
    accepted, duplicates, rejected = [], [], []

    async for db in get_db():
        for ticket in tickets:
            waybill = await db.waybills.find_one({"waybill_id": ticket.waybill_id})
            if waybill is None:
                rejected.append({"client_ticket_uuid": ticket.client_ticket_uuid, "reason": "Unknown waybill."})
                continue
            if waybill["conductor_id"] != conductor_id:
                rejected.append({
                    "client_ticket_uuid": ticket.client_ticket_uuid,
                    "reason": "That waybill belongs to another conductor.",
                })
                continue
            if waybill["status"] != WaybillStatus.OPEN.value:
                # Late arrivals from the offline queue after sign-off are the
                # normal case here, not an attack. They are refused because a
                # closed waybill has already been reconciled against counted
                # cash, and the conductor is told so plainly.
                rejected.append({
                    "client_ticket_uuid": ticket.client_ticket_uuid,
                    "reason": f"Waybill {ticket.waybill_id} is already {waybill['status']}.",
                })
                continue

            try:
                pricing = price_ticket(
                    ticket.from_stop,
                    ticket.to_stop,
                    [(item.passenger_type, item.count) for item in ticket.passengers],
                    request,
                    ticket.is_ac,
                )
            except WaybillError as exc:
                rejected.append({"client_ticket_uuid": ticket.client_ticket_uuid, "reason": str(exc)})
                continue

            passengers = sum(item.count for item in ticket.passengers)
            # Counted from the PRICED lines, not the request, and only where the
            # line actually came out zero-fare. A Shakti passenger on an AC
            # service pays like everyone else, so there is nothing to claim for
            # her -- counting her anyway would inflate the claim to the state.
            scheme_lines = [
                line for line in pricing["lines"]
                if line["scheme"] == SHAKTI_SCHEME and line["is_zero_fare"]
            ]
            shakti = sum(line["count"] for line in scheme_lines)
            shakti_value = sum(line["fare_value_inr"] for line in scheme_lines)
            document = {
                "ticket_id": f"CT-{uuid.uuid4().hex[:12].upper()}",
                "client_ticket_uuid": ticket.client_ticket_uuid,
                "waybill_id": ticket.waybill_id,
                "conductor_id": conductor_id,
                "route_number": waybill["route_number"],
                "from_stop": ticket.from_stop.strip(),
                "to_stop": ticket.to_stop.strip(),
                "is_ac": ticket.is_ac,
                "payment_mode": ticket.payment_mode.value,
                "passengers": passengers,
                # No passenger identity is stored anywhere on this document,
                # including for scheme travel. A reimbursement claim needs a
                # count and a value, not a record of who travelled -- the same
                # minimal-collection principle set out in analytics_service.py.
                "lines": pricing["lines"],
                "fare_value_inr": pricing["fare_value_inr"],
                "fare_collected_inr": pricing["fare_collected_inr"],
                "shakti_boardings": shakti,
                "shakti_claim_value": round(shakti_value, 2),
                "issued_at": ticket.issued_at or datetime.now(timezone.utc),
                "synced_at": datetime.now(timezone.utc),
            }
            try:
                await db.conductor_tickets.insert_one(document)
            except DuplicateKeyError:
                # The device replayed a sale the server already has. This is
                # the offline queue working correctly, not an error.
                duplicates.append({"client_ticket_uuid": ticket.client_ticket_uuid})
                continue
            accepted.append({
                "client_ticket_uuid": ticket.client_ticket_uuid,
                "ticket_id": document["ticket_id"],
                "fare_value_inr": document["fare_value_inr"],
                "fare_collected_inr": document["fare_collected_inr"],
            })

        return {
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
            "counts": {
                "accepted": len(accepted),
                "duplicates": len(duplicates),
                "rejected": len(rejected),
            },
        }
    return {"accepted": [], "duplicates": [], "rejected": [], "counts": {}}


async def recompute_totals(db: Any, waybill_id: str) -> dict[str, Any]:
    """Derive a waybill's totals from its ticket rows.

    Never accepts totals from the client. The device is a phone in a bus, and a
    client-supplied figure in a revenue document is a fraud vector.
    """
    totals = _empty_totals()
    cursor = db.conductor_tickets.find({"waybill_id": waybill_id})
    async for ticket in cursor:
        totals["tickets_issued"] += 1
        totals["passengers"] += ticket.get("passengers", 0)
        totals["fare_value_total"] += ticket.get("fare_value_inr", 0.0)
        totals["fare_collected_total"] += ticket.get("fare_collected_inr", 0.0)
        totals["shakti_boardings"] += ticket.get("shakti_boardings", 0)
        totals["shakti_claim_value"] += ticket.get("shakti_claim_value", 0.0)

        mode = ticket.get("payment_mode")
        collected = ticket.get("fare_collected_inr", 0.0)
        if mode == PaymentMode.CASH.value:
            totals["cash_amount"] += collected
        elif mode == PaymentMode.UPI.value:
            totals["digital_amount"] += collected
        elif mode == PaymentMode.PASS.value:
            totals["pass_boardings"] += ticket.get("passengers", 0)

    for key, value in totals.items():
        if isinstance(value, float):
            totals[key] = round(value, 2)
    return totals


async def close_waybill(conductor_id: str, payload: SignOffRequest) -> dict[str, Any]:
    """Sign off: recompute totals, compare declared cash against expected.

    The variance is reported, never auto-resolved. A system that quietly
    adjusts a cash figure to make it balance has destroyed the only signal the
    depot had.
    """
    async for db in get_db():
        waybill = await db.waybills.find_one({"waybill_id": payload.waybill_id})
        if waybill is None:
            raise WaybillError(f"No waybill {payload.waybill_id}.")
        if waybill["conductor_id"] != conductor_id:
            raise WaybillError("That waybill belongs to another conductor.")
        if waybill["status"] != WaybillStatus.OPEN.value:
            raise WaybillError(f"Waybill {payload.waybill_id} is already {waybill['status']}.")
        if payload.closing_km < waybill["opening_km"]:
            raise WaybillError(
                f"Closing odometer ({payload.closing_km}) is below the opening reading "
                f"({waybill['opening_km']})."
            )

        totals = await recompute_totals(db, payload.waybill_id)
        expected_cash = totals["cash_amount"]
        variance = round(payload.declared_cash - expected_cash, 2)
        now = datetime.now(timezone.utc)

        reconciliation = {
            "declared_cash": payload.declared_cash,
            "expected_cash": expected_cash,
            "variance": variance,
            "variance_flagged": abs(variance) >= 1.0,
            "note": payload.note,
            "remitted_at": now,
        }
        await db.waybills.update_one(
            {"waybill_id": payload.waybill_id},
            {"$set": {
                "status": WaybillStatus.CLOSED.value,
                "sign_off_at": now,
                "closing_km": payload.closing_km,
                "closing_ticket_serial": payload.closing_ticket_serial,
                "totals": totals,
                "reconciliation": reconciliation,
                "distance_km": round(payload.closing_km - waybill["opening_km"], 1),
            }},
        )
        document = await db.waybills.find_one({"waybill_id": payload.waybill_id})
        logger.info(
            "Waybill %s closed: %s tickets, %.2f collected, variance %.2f",
            payload.waybill_id, totals["tickets_issued"], expected_cash, variance,
        )
        return _serialize(document)
    return {}


async def list_waybills(
    *, depot: str = "", duty_date: str = "", status: str = "", limit: int = 200
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if depot:
        query["depot"] = depot
    if duty_date:
        query["duty_date"] = duty_date
    if status:
        query["status"] = status

    async for db in get_db():
        cursor = db.waybills.find(query).sort("sign_on_at", -1).limit(limit)
        return [_serialize(document) async for document in cursor]
    return []


async def shakti_claim(*, date_from: str = "", date_to: str = "", depot: str = "") -> dict[str, Any]:
    """Per-depot, per-day Shakti boardings and claim value.

    This is what the office files with the state. It sums fare_value_inr, never
    fare_collected_inr -- the passenger paid nothing, which is exactly why
    there is something to claim.
    """
    match: dict[str, Any] = {}
    if depot:
        match["depot"] = depot
    if date_from or date_to:
        window: dict[str, Any] = {}
        if date_from:
            window["$gte"] = date_from
        if date_to:
            window["$lte"] = date_to
        match["duty_date"] = window

    async for db in get_db():
        pipeline: list[dict[str, Any]] = []
        if match:
            pipeline.append({"$match": match})
        pipeline += [
            {"$group": {
                "_id": {"depot": "$depot", "duty_date": "$duty_date"},
                "boardings": {"$sum": "$totals.shakti_boardings"},
                "claim_value_inr": {"$sum": "$totals.shakti_claim_value"},
                "waybills": {"$sum": 1},
            }},
            {"$sort": {"_id.duty_date": -1}},
        ]
        rows = [row async for row in db.waybills.aggregate(pipeline)]

        breakdown = [
            {
                "depot": row["_id"].get("depot") or "unassigned",
                "duty_date": row["_id"].get("duty_date"),
                "boardings": row["boardings"],
                "claim_value_inr": round(row["claim_value_inr"], 2),
                "waybills": row["waybills"],
            }
            for row in rows
        ]

        # App-issued Shakti e-tickets are a second, separate source of the same
        # entitlement. Omitting them would understate the claim by however many
        # passengers used the app instead of buying from the conductor -- and
        # that share is precisely what this project is trying to grow. They are
        # reported alongside rather than merged in: an e-ticket has no waybill
        # and no depot, so folding it into a per-depot row would attribute it
        # to a depot that did not issue it.
        app_rows = [
            row async for row in db.tickets.aggregate([
                {"$match": {"scheme": SHAKTI_SCHEME, **_ticket_date_match(date_from, date_to)}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$issue_time"}},
                    "boardings": {"$sum": 1},
                    "claim_value_inr": {"$sum": "$fare_value_inr"},
                }},
                {"$sort": {"_id": -1}},
            ])
        ]
        app_breakdown = [
            {
                "date": row["_id"],
                "boardings": row["boardings"],
                "claim_value_inr": round(row["claim_value_inr"] or 0, 2),
            }
            for row in app_rows
        ]

        conductor_boardings = sum(entry["boardings"] for entry in breakdown)
        conductor_value = round(sum(entry["claim_value_inr"] for entry in breakdown), 2)
        app_boardings = sum(entry["boardings"] for entry in app_breakdown)
        app_value = round(sum(entry["claim_value_inr"] for entry in app_breakdown), 2)

        return {
            "status": "ok",
            "period": {"from": date_from or None, "to": date_to or None},
            "depot": depot or None,
            "totals": {
                "boardings": conductor_boardings + app_boardings,
                "claim_value_inr": round(conductor_value + app_value, 2),
            },
            "by_source": {
                "conductor_issued": {"boardings": conductor_boardings, "claim_value_inr": conductor_value},
                "app_issued": {"boardings": app_boardings, "claim_value_inr": app_value},
            },
            "breakdown": breakdown,
            "app_breakdown": app_breakdown,
            "basis": (
                "Sum of fare_value_inr on zero-fare Shakti tickets: what the journey would "
                "have cost had it been paid for. Revenue reports use fare_collected_inr, "
                "which is zero for these tickets."
            ),
            "privacy_note": (
                "Boardings are counted, never attributed. No passenger identity or gender is "
                "recorded on a scheme ticket."
            ),
            "verification_caveat": (
                "App-issued entitlement is taken from the gender recorded at registration. "
                "DBARS does not verify residency or government ID, which the real scheme "
                "requires and a conductor checks. Treat app_issued as a modelled figure until "
                "that check exists."
            ),
        }
    return {"status": "unavailable", "breakdown": []}


def _ticket_date_match(date_from: str, date_to: str) -> dict[str, Any]:
    """E-tickets carry an issue_time, not a duty_date, so the same YYYY-MM-DD
    window has to be applied as a datetime range."""
    if not (date_from or date_to):
        return {}
    window: dict[str, Any] = {}
    if date_from:
        window["$gte"] = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    if date_to:
        # Inclusive of the whole closing day, which is what a reader of
        # "from 1st to 7th" means.
        window["$lt"] = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return {"issue_time": window}


async def revenue_reconciliation(*, date_from: str = "", date_to: str = "", depot: str = "") -> dict[str, Any]:
    """Cash vs digital vs pass vs scheme, per depot per day."""
    match: dict[str, Any] = {"status": {"$in": [WaybillStatus.CLOSED.value, WaybillStatus.RECONCILED.value]}}
    if depot:
        match["depot"] = depot
    if date_from or date_to:
        window: dict[str, Any] = {}
        if date_from:
            window["$gte"] = date_from
        if date_to:
            window["$lte"] = date_to
        match["duty_date"] = window

    async for db in get_db():
        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": {"depot": "$depot", "duty_date": "$duty_date"},
                "cash": {"$sum": "$totals.cash_amount"},
                "digital": {"$sum": "$totals.digital_amount"},
                "pass_boardings": {"$sum": "$totals.pass_boardings"},
                "shakti_claim": {"$sum": "$totals.shakti_claim_value"},
                "tickets": {"$sum": "$totals.tickets_issued"},
                "declared_cash": {"$sum": "$reconciliation.declared_cash"},
                "variance": {"$sum": "$reconciliation.variance"},
                "waybills": {"$sum": 1},
            }},
            {"$sort": {"_id.duty_date": -1}},
        ]
        rows = [row async for row in db.waybills.aggregate(pipeline)]
        breakdown = [
            {
                "depot": row["_id"].get("depot") or "unassigned",
                "duty_date": row["_id"].get("duty_date"),
                "cash_inr": round(row["cash"], 2),
                "digital_inr": round(row["digital"], 2),
                "declared_cash_inr": round(row["declared_cash"] or 0, 2),
                "variance_inr": round(row["variance"] or 0, 2),
                "pass_boardings": row["pass_boardings"],
                "shakti_claim_inr": round(row["shakti_claim"], 2),
                "tickets": row["tickets"],
                "waybills": row["waybills"],
            }
            for row in rows
        ]
        return {
            "status": "ok",
            "breakdown": breakdown,
            "totals": {
                "cash_inr": round(sum(e["cash_inr"] for e in breakdown), 2),
                "digital_inr": round(sum(e["digital_inr"] for e in breakdown), 2),
                "variance_inr": round(sum(e["variance_inr"] for e in breakdown), 2),
                "shakti_claim_inr": round(sum(e["shakti_claim_inr"] for e in breakdown), 2),
            },
            "note": (
                "Shakti claim value is shown alongside revenue, not inside it: it is money "
                "owed by the state, not money taken on the bus."
            ),
        }
    return {"status": "unavailable", "breakdown": []}


def _serialize(document: dict[str, Any] | None) -> dict[str, Any]:
    if not document:
        return {}
    document = dict(document)
    document.pop("_id", None)
    for field in ("sign_on_at", "sign_off_at"):
        if document.get(field):
            document[field] = document[field].isoformat()
    reconciliation = document.get("reconciliation")
    if reconciliation and reconciliation.get("remitted_at"):
        reconciliation = dict(reconciliation)
        reconciliation["remitted_at"] = reconciliation["remitted_at"].isoformat()
        document["reconciliation"] = reconciliation
    return document
