from __future__ import annotations

import asyncio
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services.metro_service import metro_service

router = APIRouter(prefix="/metro", tags=["metro"])


@router.get("/stations")
async def get_metro_stations() -> dict:
    """Return all Bengaluru Namma Metro stations with lines and coordinates."""
    stations = metro_service.get_all_stations()
    grouped = metro_service.get_stations_grouped_by_line()
    return {
        "status": "ok",
        "total_stations": len(stations),
        "lines": list(grouped.keys()),
        "stations": stations,
        "grouped_by_line": grouped,
    }


@router.get("/nearest")
async def get_nearest_metro_stations(
    request: Request,
    stop_name: str | None = Query(None, description="Bus stop name or landmark"),
    lat: float | None = Query(None, description="Latitude"),
    lon: float | None = Query(None, description="Longitude"),
    limit: int = Query(3, ge=1, le=10, description="Number of nearest metro stations to return"),
) -> dict:
    """Find the nearest Namma Metro stations to a given bus stop or coordinate."""
    predictor = getattr(request.app.state, "predictor", None)
    distance_service = predictor.distance_service if predictor else None

    if not stop_name and (lat is None or lon is None):
        raise HTTPException(
            status_code=400,
            detail="Either 'stop_name' or latitude/longitude coordinates must be provided.",
        )

    nearest = metro_service.find_nearest_stations(
        stop_name=stop_name,
        lat=lat,
        lon=lon,
        limit=limit,
        distance_service=distance_service,
    )

    # "40 min walk" is a distance restated in minutes, not advice. Attach the
    # bus that actually reaches each station, for the closest couple.
    #
    # In a worker thread because this calls predict(), which is CPU-bound and
    # takes a second or two -- running it inline would stall every other
    # request on the event loop for that long.
    if stop_name and predictor is not None:
        from app.services.metro_bus_link import attach_bus_connections

        nearest = await asyncio.to_thread(attach_bus_connections, nearest, stop_name, predictor)

    return {
        "status": "ok",
        "query_stop": stop_name,
        "query_coordinates": {"lat": lat, "lon": lon} if lat and lon else None,
        "count": len(nearest),
        "nearest_metro_stations": nearest,
    }


@router.get("/map-pdf")
async def get_metro_map_pdf():
    """Serve the Bengaluru Metro Map 2025 PDF file."""
    pdf_path = settings.metro_pdf_path
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Metro map PDF file not found")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename="Metro_Map_2025_-_Bengaluru_City.pdf",
    )
