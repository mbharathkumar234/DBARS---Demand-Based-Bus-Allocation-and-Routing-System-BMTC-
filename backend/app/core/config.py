from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", str(BACKEND_DIR.parent)))

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "DBARS — Demand Based Bus Allocation & Routing System"
    app_version: str = "1.0.0"
    dataset_path: Path = Path(os.getenv("DATASET_PATH", WORKSPACE_DIR / "dataset" / "routes_cleaned.csv"))
    stop_coordinates_path: Path = Path(os.getenv("STOP_COORDINATES_PATH", WORKSPACE_DIR / "dataset" / "stops_cleaned.csv"))
    metro_dataset_path: Path = Path(os.getenv("METRO_DATASET_PATH", WORKSPACE_DIR / "dataset" / "bengaluru_metro_network.csv"))
    fares_dataset_path: Path = Path(os.getenv("FARES_DATASET_PATH", WORKSPACE_DIR / "dataset" / "fares.json"))
    metro_pdf_path: Path = Path(os.getenv("METRO_PDF_PATH", WORKSPACE_DIR / "dataset" / "Metro_Map_2025_-_Bengaluru_City.pdf"))
    depot_dataset_path: Path = Path(os.getenv("DEPOT_DATASET_PATH", WORKSPACE_DIR / "dataset" / "BMTC_depot_place_zone.xlsx"))
    artifact_dir: Path = Path(os.getenv("ARTIFACT_DIR", BACKEND_DIR / "artifacts"))
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")
    # Signs e-ticket QR tokens. Deliberately separate from JWT_SECRET_KEY so a
    # ticket token can never be a valid session credential even if the type
    # check below it were ever bypassed -- two independent barriers, not one.
    # Falls back to JWT_SECRET_KEY only when unset, so existing deployments
    # keep working; see app/auth/auth.py.
    ticket_signing_key: str = os.getenv("TICKET_SIGNING_KEY", "")
    pass_verification_secret: str = os.getenv("PASS_VERIFICATION_SECRET", "")
    # Signs travel-pass tokens. A third domain, separate from both the session
    # key and the ticket key, because a pass is a long-lived bearer credential
    # verified OFFLINE on a device in a bus -- the key most likely to end up
    # cached somewhere it should not be.
    pass_signing_key: str = os.getenv("PASS_SIGNING_KEY", "")
    # Demo mode for the conductor scanner: accepts unsigned pass ids so a
    # presentation works before any real pass has been issued. Every response
    # is labelled demo_mode=true, and it defaults OFF.
    demo_pass_mode: bool = os.getenv("DEMO_PASS_MODE", "false").strip().lower() == "true"
    # Twilio's account auth token, used to verify the X-Twilio-Signature on
    # inbound SMS webhooks. Unset means POST /sms/webhook refuses to process
    # anything -- see app/api/sms.py. Use POST /sms/query to exercise the same
    # pipeline locally without a gateway.
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    google_maps_distance_mode: str = os.getenv("GOOGLE_MAPS_DISTANCE_MODE", "driving")
    google_maps_location_suffix: str = os.getenv("GOOGLE_MAPS_LOCATION_SUFFIX", "Bengaluru, Karnataka, India")
    google_maps_max_remote_lookups: int = int(os.getenv("GOOGLE_MAPS_MAX_REMOTE_LOOKUPS", "24"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    )
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    # ── Vehicle location (AVL) ──────────────────────────────────────────
    # Which adapter supplies vehicle positions: simulated | gtfs_rt |
    # http_json | push. Defaults to the simulator so an unconfigured
    # deployment behaves exactly as before -- and, crucially, keeps declaring
    # itself simulated rather than quietly appearing live.
    tracking_feed: str = os.getenv("TRACKING_FEED", "simulated")
    tracking_feed_url: str = os.getenv("TRACKING_FEED_URL", "")
    # JSON object mapping DBARS observation fields to the upstream API's field
    # names, for http_json. Configuration rather than code, because every ITS
    # vendor invents its own names and none of them are negotiable.
    tracking_feed_field_map: str = os.getenv("TRACKING_FEED_FIELD_MAP", "")
    tracking_poll_seconds: float = float(os.getenv("TRACKING_POLL_SECONDS", "10"))
    # An observation older than this is not shown as a position at all. A
    # stalled feed keeps returning its last payload, and rendering that as
    # current produces a map of buses riders will wait for and that will
    # never come.
    avl_stale_seconds: float = float(os.getenv("AVL_STALE_SECONDS", "120"))
    # Shared secret for POST /avl/ingest, compared with hmac.compare_digest.
    # Unset means the endpoint refuses everything -- an open ingest endpoint
    # would let anyone inject bus positions into the map.
    avl_ingest_key: str = os.getenv("AVL_INGEST_KEY", "")
    # ── GTFS export ─────────────────────────────────────────────────────
    # Namespaces every id in the published feed so a DBARS identifier can
    # never be mistaken for, or collide with, an official BMTC one.
    gtfs_feed_prefix: str = os.getenv("GTFS_FEED_PREFIX", "dbars")
    gtfs_publisher_name: str = os.getenv(
        "GTFS_PUBLISHER_NAME", "DBARS (unofficial, derived from published BMTC data)"
    )
    gtfs_publisher_url: str = os.getenv("GTFS_PUBLISHER_URL", "https://example.org/dbars")
    gtfs_contact_email: str = os.getenv("GTFS_CONTACT_EMAIL", "")
    # Building the feed takes ~11s and ~15MB of output. On by default because
    # a feed that only appears after someone requests it is a feed whose first
    # requester waits; set false for test runs and small dev machines.
    gtfs_build_on_startup: bool = os.getenv("GTFS_BUILD_ON_STARTUP", "true").strip().lower() == "true"
    # GTFS-realtime has no field meaning "this data is simulated", and a
    # consumer ingesting vehicle positions cannot tell the difference. So the
    # vehicle feed is refused outright while positions come from the
    # simulator. This switch exists only for local development and demos, and
    # even then the feed is served on a separate .sim.pb path so that no
    # consumer can be pointed at simulated data by accident.
    gtfs_rt_allow_simulated: bool = os.getenv("GTFS_RT_ALLOW_SIMULATED", "false").strip().lower() == "true"
    # Only set true for a deployment with exactly one trusted reverse proxy
    # in front of this process (e.g. Render's edge, or a properly
    # configured Nginx) -- see rate_limit.py's docstring for why this
    # defaults to false everywhere else.
    trust_proxy_headers: bool = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() == "true"


settings = Settings()