from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as predict_router
from app.api.votes import router as votes_router
from app.api.admin import router as admin_router
from app.api.tracking import router as tracking_router, avl_router
from app.api.tickets import router as tickets_router
from app.api.metro import router as metro_router
from app.api.crowding import router as crowding_router
from app.api.alerts import router as alerts_router
from app.api.gtfs import router as gtfs_router, realtime_router as gtfs_realtime_router
from app.api.conductor import (
    router as conductor_router,
    depot_router as conductor_depot_router,
    office_router as conductor_office_router,
)
from app.api.sms import router as sms_router
from app.api.safety import router as safety_router
# The AI layer is an optional add-on, so its import is guarded. It pulls in
# langchain, faiss and sentence-transformers; if any of them is missing or
# broken, DBARS must still start. The deterministic core -- route prediction,
# ticketing, GTFS -- does not depend on this and must never be taken down by
# it. Same principle as init_db() below, which also cannot raise.
try:
    from app.ai.api.routes import router as ai_router
except Exception as _ai_import_error:  # pragma: no cover - depends on env
    ai_router = None
    _AI_IMPORT_ERROR = _ai_import_error
else:
    _AI_IMPORT_ERROR = None
from app.auth.routes import router as auth_router
from app.core.config import settings
from app.core.rate_limit import RateLimitMiddleware
from app.db.database import db_available, init_db
from app.ml.predictor import BMTCBusPredictor


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("bmtc-predictor")


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify dataset files exist
    for name, path in [
        ("dataset_path", settings.dataset_path),
        ("stop_coordinates_path", settings.stop_coordinates_path),
        ("metro_dataset_path", settings.metro_dataset_path),
        ("fares_dataset_path", settings.fares_dataset_path),
    ]:
        if not path.exists():
            logger.error("Required dataset file missing: %s (%s)", name, path)
            raise FileNotFoundError(f"Dataset file '{name}' not found at {path}")

    logger.info("Training BMTC predictor from %s", settings.dataset_path)
    app.state.predictor.train()
    logger.info("Predictor is locked and loaded with %s routes", app.state.predictor.profile.get("rows", 0))

    # Hand the trained predictor to the AI tool layer. Its accessor falls back
    # to building its own if nobody injects one, and nobody did: the first chat
    # request paid ~7s to train a second full copy and held ~900MB of duplicate
    # index for the life of the process. Guarded like the router import, so an
    # unavailable AI layer still cannot affect startup.
    try:
        from app.ai.tools import set_shared_predictor
        set_shared_predictor(app.state.predictor)
        logger.info("AI tool layer is sharing the trained predictor")
    except Exception:
        logger.debug("AI layer unavailable; skipping predictor injection")

    # Warm the vehicle-blocking plan in the background. It takes ~25s to
    # compute, and whoever opens the depot dashboard first would otherwise sit
    # watching a spinner for that long. Fire-and-forget rather than awaited, so
    # a failure here can never stop the app from starting -- the endpoint
    # recomputes on demand if this did not finish.
    async def _warm_blocking_plan() -> None:
        from app.services.blocking_service import blocking_plan_service
        try:
            plan = await blocking_plan_service.get_plan()
            logger.info(
                "Blocking plan ready: %s buses scheduled, %s interlined across %s depots",
                plan["network"]["buses_scheduled"],
                plan["network"]["buses_interlined"],
                len(plan["depots"]),
            )
        except Exception:
            logger.exception("Could not precompute the blocking plan; it will be built on first request")

        # Crew duties, warmed in the same task so it runs after the blocking
        # context exists and reuses it rather than rebuilding it. Asking the
        # copilot "what is the crew-to-bus ratio?" on a cold process otherwise
        # paid ~5.6s to rebuild the context plus ~7.6s to schedule the crew --
        # the 10-15s wait a user reported. Failure here is logged and ignored,
        # exactly like the blocking plan above.
        try:
            from app.services.crew_service import crew_plan_service
            crew = await crew_plan_service.get_plan()
            logger.info(
                "Crew plan ready: %s duties at a crew-to-bus ratio of %s",
                crew["network"].get("duties"),
                crew["network"].get("crew_to_bus_ratio"),
            )
        except Exception:
            logger.exception("Could not precompute the crew plan; it will be built on first request")

    # Held in app.state, not a local: asyncio keeps only a weak reference to
    # running tasks, so a task with no strong reference can be garbage
    # collected mid-flight and silently never finish.
    app.state.blocking_warm_task = asyncio.create_task(_warm_blocking_plan())

    # Same treatment for the GTFS feed: ~11s to build, and whoever requests
    # GET /gtfs/static.zip first would otherwise wait the whole time. Adopts a
    # feed a previous run left on disk instead of rebuilding it.
    async def _warm_gtfs_feed() -> None:
        from app.services.gtfs_service import gtfs_feed_service
        try:
            report = await gtfs_feed_service.ensure_built()
            logger.info(
                "GTFS feed ready: version %s, %s routes, %s trips, %s stop_times",
                report.feed_version, report.routes, report.trips, report.stop_times,
            )
        except Exception:
            logger.exception("Could not prebuild the GTFS feed; it will be built on first request")

    if settings.gtfs_build_on_startup:
        app.state.gtfs_warm_task = asyncio.create_task(_warm_gtfs_feed())

    # Vehicle positions. Which adapter this starts is TRACKING_FEED; the
    # default is still the simulator, and it still declares itself simulated.
    from app.tracking.ingest import vehicle_ingest
    await vehicle_ingest.start(predictor=app.state.predictor)

    await init_db()
    if db_available():
        logger.info("MongoDB connection established and database initialized")
        await _seed_default_admin()
    else:
        logger.warning(
            "Starting without MongoDB: account, voting, ticketing, and admin/depot "
            "features are unavailable until it is reachable. Route prediction is unaffected."
        )
    try:
        yield
    finally:
        from app.tracking.ingest import vehicle_ingest
        await vehicle_ingest.stop()
        for task_name in ("blocking_warm_task", "gtfs_warm_task"):
            warm_task = getattr(app.state, task_name, None)
            if warm_task and not warm_task.done():
                warm_task.cancel()
        from app.db.database import close_db
        await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="DBARS API — Demand Based Bus Allocation & Routing System. Powering bus route predictions, commuter voting, demand-driven bus allocation, and live tracking.",
        lifespan=lifespan,
    )
    # Register RateLimitMiddleware first so CORSMiddleware registered second is outermost
    app.add_middleware(
        RateLimitMiddleware,
        max_requests_per_minute=settings.rate_limit_per_minute,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials="*" not in settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)

    # Register all routers
    app.include_router(predict_router)
    app.include_router(auth_router)
    app.include_router(votes_router)
    app.include_router(admin_router)
    app.include_router(tracking_router)
    app.include_router(tickets_router)
    app.include_router(metro_router)
    app.include_router(crowding_router)
    app.include_router(alerts_router)
    app.include_router(sms_router)
    app.include_router(safety_router)
    app.include_router(gtfs_router)
    app.include_router(gtfs_realtime_router)
    app.include_router(avl_router)
    app.include_router(conductor_router)
    app.include_router(conductor_depot_router)
    app.include_router(conductor_office_router)
    if ai_router is not None:
        app.include_router(ai_router)
    else:
        logger.warning(
            "AI Intelligence Layer disabled: %s. Route prediction and all "
            "deterministic features are unaffected.", _AI_IMPORT_ERROR,
        )

    return app


async def _seed_default_admin() -> None:
    """Bootstrap a default admin and depot account if explicitly enabled."""
    import os
    if os.getenv("SEED_DEFAULT_ADMIN", "false").strip().lower() != "true":
        return

    admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    depot_password = os.getenv("DEFAULT_DEPOT_PASSWORD", "depot123")
    env_name = os.getenv("ENV", os.getenv("APP_ENV", "development")).lower()
    if env_name == "production" and admin_password == "admin123":
        raise ValueError("Cannot seed default admin with default password 'admin123' in production!")

    from app.auth.auth import hash_password
    from app.db.database import get_db
    from datetime import datetime, timezone

    async for db in get_db():
        existing_admins = await db.users.count_documents({"role": "admin"})
        if existing_admins == 0:
            await db.users.insert_many([
                {
                    "email": "admin@bmtc.ai",
                    "name": "BMTC Admin",
                    "password_hash": hash_password(admin_password),
                    "role": "admin",
                    "preferred_lang": "en",
                    "reliability": 1.0,
                    "is_active": 1,
                    "created_at": datetime.now(timezone.utc)
                },
                {
                    "email": "depot@bmtc.ai",
                    "name": "Depot Manager",
                    "password_hash": hash_password(depot_password),
                    "role": "depot_manager",
                    "preferred_lang": "en",
                    "reliability": 1.0,
                    "is_active": 1,
                    "created_at": datetime.now(timezone.utc)
                }
            ])
            logger.info("Created fallback admin accounts (admin@bmtc.ai, depot@bmtc.ai)")


app = create_app()