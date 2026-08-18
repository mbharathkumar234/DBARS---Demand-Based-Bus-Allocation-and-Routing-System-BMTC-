from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.auth import UserRole, get_current_user, require_role
from app.models.schemas import ServiceAlertRequest
from app.services.alerts_service import create_alert, get_active_alerts, resolve_alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_active_alerts(route_number: str | None = None, stop_name: str | None = None) -> dict:
    """Public: list currently-active service disruption alerts, optionally
    filtered to a specific route or stop. An empty list is a normal,
    honest answer meaning no known disruptions -- not an error state."""
    alerts = await get_active_alerts(route_number=route_number, stop_name=stop_name)
    return {"status": "ok", "count": len(alerts), "alerts": alerts}


@router.post("")
async def create_service_alert(
    payload: ServiceAlertRequest,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Create a real service alert. Restricted to admin/depot_manager --
    this is moderated, human-reported content (see alerts_service.py's
    docstring for why), and an unrestricted public endpoint here would let
    anyone post a fake disruption that commuters might actually act on."""
    try:
        alert = await create_alert(
            created_by_user_id=user["sub"],
            title=payload.title,
            description=payload.description,
            severity=payload.severity,
            affected_routes=payload.affected_routes,
            affected_stops=payload.affected_stops,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "alert": alert}


@router.patch("/{alert_id}/resolve")
async def resolve_service_alert(
    alert_id: str,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    alert = await resolve_alert(alert_id, resolved_by_user_id=user["sub"])
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    return {"status": "ok", "alert": alert}