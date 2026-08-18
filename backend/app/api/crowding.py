from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.auth import get_current_user
from app.models.schemas import CrowdReportRequest
from app.services.crowding_service import get_route_crowding, submit_crowd_report

router = APIRouter(prefix="/crowding", tags=["crowding"])


@router.post("/report")
async def report_crowding(
    payload: CrowdReportRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Submit a real crowding report for a route. Requires login so the
    cooldown/anti-spam check in crowding_service has a real identity to
    key off of -- an anonymous endpoint here would have no way to limit
    one person flooding a route with reports."""
    try:
        report = await submit_crowd_report(
            user_id=user["sub"],
            route_number=payload.route_number,
            crowding_level=payload.crowding_level,
            stop_name=payload.stop_name,
            bus_number=payload.bus_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "report": {k: v for k, v in report.items() if k != "_id"}}


@router.get("/route/{route_number}")
async def route_crowding(route_number: str) -> dict:
    """Real, recent commuter-reported crowding for a route. Returns an
    honest 'insufficient_data' status rather than a fabricated number
    when there aren't enough recent reports -- see crowding_service.py."""
    return await get_route_crowding(route_number)