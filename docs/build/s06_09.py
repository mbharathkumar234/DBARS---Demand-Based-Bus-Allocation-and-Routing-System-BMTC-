# -*- coding: utf-8 -*-
"""Sections 6-9: Directory structure, file map, entry point, execution traces."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_6(doc):
    h(doc, 1, "6. Project Directory Structure")
    para(doc, "Reconstructed from the repository. Only folders that exist are listed. Build outputs "
              "and dependency folders (node_modules, .venv, dist, __pycache__) are excluded from "
              "version control by .gitignore and are not shown.")
    code(doc,
         "dbars/\n"
         "|\n"
         "+-- backend/                     Python API and computation engines\n"
         "|   +-- app/\n"
         "|   |   +-- main.py              APPLICATION ENTRY POINT (create_app, lifespan)\n"
         "|   |   +-- api/                 HTTP endpoints, one module per subject area\n"
         "|   |   |   +-- routes.py        predict, autocomplete, metrics, all depot planning\n"
         "|   |   |   +-- votes.py         demand voting and aggregation\n"
         "|   |   |   +-- tickets.py       e-ticket purchase and verification\n"
         "|   |   |   +-- conductor.py     waybills, onboard sales, passes, revenue, audit\n"
         "|   |   |   +-- tracking.py      vehicle positions, ETA, favourites, AVL ingest\n"
         "|   |   |   +-- gtfs.py          GTFS static and realtime endpoints\n"
         "|   |   |   +-- admin.py         admin dashboards and user management\n"
         "|   |   |   +-- alerts.py  crowding.py  metro.py  safety.py  sms.py\n"
         "|   |   +-- auth/                authentication and authorisation\n"
         "|   |   |   +-- auth.py          tokens, hashing, roles, dependencies\n"
         "|   |   |   +-- routes.py        register, login, me, refresh\n"
         "|   |   +-- core/                cross-cutting configuration and rules\n"
         "|   |   |   +-- config.py        every environment variable, in one frozen dataclass\n"
         "|   |   |   +-- fares.py         BMTC stage fare calculation\n"
         "|   |   |   +-- shakti.py        the single shared Shakti eligibility rule\n"
         "|   |   |   +-- rate_limit.py    per-IP sliding-window middleware\n"
         "|   |   +-- db/\n"
         "|   |   |   +-- database.py      Motor client, index creation, graceful degradation\n"
         "|   |   |   +-- seed.py          demo data seeding\n"
         "|   |   +-- ml/                  THE ENGINES - pure computation, no database\n"
         "|   |   |   +-- predictor.py     route search  (1,600+ lines - the biggest file)\n"
         "|   |   |   +-- blocking.py      vehicle blocking: fleet size and dead kilometres\n"
         "|   |   |   +-- crew.py          crew duty scheduling\n"
         "|   |   |   +-- distance.py      stop coordinate resolution and distance\n"
         "|   |   |   +-- route_geometry.py  anchored stop-sequence resolution (shared)\n"
         "|   |   |   +-- data_loader.py   CSV -> RouteRecord\n"
         "|   |   |   +-- text.py  tfidf.py  stop_registry.py\n"
         "|   |   +-- gtfs/                open-data export\n"
         "|   |   |   +-- builder.py       GTFS static feed builder (streaming)\n"
         "|   |   |   +-- realtime.py      GTFS-Realtime protobuf feeds\n"
         "|   |   +-- tracking/            vehicle location layer\n"
         "|   |   |   +-- base.py          VehicleFeed protocol, VehicleObservation\n"
         "|   |   |   +-- adapters.py      simulated / gtfs_rt / http_json / push\n"
         "|   |   |   +-- store.py         current state with staleness rules\n"
         "|   |   |   +-- ingest.py        the polling loop and health reporting\n"
         "|   |   |   +-- matcher.py       projection, trip matching, ETA\n"
         "|   |   +-- services/            business logic and all database access\n"
         "|   |   +-- models/              pydantic request/response schemas\n"
         "|   +-- tests/                   161 tests across 15 files\n"
         "|   +-- artifacts/               generated: metrics.json, gtfs/ (gitignored)\n"
         "|   +-- scripts/                 blocking_report.py, offline analysis\n"
         "|   +-- train.py                 standalone training entry point\n"
         "|   +-- requirements.txt  Dockerfile  pytest.ini  conftest.py\n"
         "|\n"
         "+-- frontend/                    React single-page application\n"
         "|   +-- src/\n"
         "|   |   +-- main.tsx             React mount point\n"
         "|   |   +-- App.tsx              router, providers, role-gated routes\n"
         "|   |   +-- pages/               one file per screen (13 pages)\n"
         "|   |   +-- components/          reusable panels (17 components)\n"
         "|   |   +-- contexts/            AuthContext, LanguageContext\n"
         "|   |   +-- lib/                 apiClient.ts, offlineQueue.ts\n"
         "|   |   +-- services/            api.ts, ticketApi.ts\n"
         "|   |   +-- hooks/  utils/  types/  i18n/  styles.css\n"
         "|   +-- android/                 Capacitor Android shell\n"
         "|   +-- public/                  static assets\n"
         "|   +-- package.json  vite.config.ts  tailwind.config.ts  Dockerfile\n"
         "|\n"
         "+-- dataset/                     THE SOURCE OF TRUTH\n"
         "|   +-- routes_cleaned.csv       6,737 route-directions (5.6 MB)\n"
         "|   +-- stops_cleaned.csv        9,507 stop rows, 4,883 unique names\n"
         "|   +-- bengaluru_metro_network.csv\n"
         "|   +-- fares.json / fares.csv   stage fare table with confidence notes\n"
         "|   +-- BMTC_depot_place_zone.xlsx   the depot list\n"
         "|   +-- Metro_Map_2025_-_Bengaluru_City.pdf\n"
         "|\n"
         "+-- deployment/                  nginx.conf, render.yaml\n"
         "+-- docs/                        implementation-plan.md, resume-entry.md, this document\n"
         "+-- .github/workflows/ci.yml     continuous integration\n"
         "+-- docker-compose.yml  vercel.json  README.md  .gitignore",
         caption="Figure 6.1 - Complete project structure.")

    h(doc, 2, "6.2 Why the folders are split this way")
    table(doc, ["Folder", "Purpose", "Depends on"], [
        ["backend/app/api/", "Translate HTTP into function calls. No business rules live here.", "auth, services, ml"],
        ["backend/app/auth/", "Decide who the caller is and what role they hold.", "core, db"],
        ["backend/app/core/", "Configuration and rules shared by everything.", "nothing in the app"],
        ["backend/app/db/", "Own the MongoDB connection and index definitions.", "nothing in the app"],
        ["backend/app/ml/", "Compute answers from the dataset. Never imports services or api.", "dataset files only"],
        ["backend/app/gtfs/", "Turn the dataset into standard open-data formats.", "ml"],
        ["backend/app/tracking/", "Ingest and interpret vehicle positions.", "ml, core"],
        ["backend/app/services/", "Business logic, and the only layer that reads and writes MongoDB.", "db, ml, core"],
        ["backend/app/models/", "Define the shape of requests and responses.", "nothing"],
        ["frontend/src/pages/", "One file per screen the user can navigate to.", "components, contexts, lib"],
        ["frontend/src/components/", "Reusable panels used by several pages.", "lib, contexts"],
        ["frontend/src/lib/", "Cross-cutting client utilities: HTTP wrapper, offline queue.", "nothing"],
    ], widths=[1.6, 3.7, 1.5])
    callout(doc, "The dependency rule that keeps the design honest",
            "Dependencies point in one direction only: api -> services -> db, and api -> ml -> dataset. "
            "The ml folder never imports from services or api. That is what makes the engines "
            "unit-testable without a database and without an HTTP server, and it is why 161 tests can "
            "run in CI with no MongoDB container. INFERRED from the import graph; CONFIRMED by the "
            "CI workflow, which runs pytest with no database service defined.")
    page_break(doc)


def section_7(doc):
    h(doc, 1, "7. File-by-File Codebase Map")
    para(doc, "Files analysed in depth are listed first. Section 39 states which files were treated "
              "as lower priority.")

    h(doc, 2, "7.1 Backend - entry point, core and data")
    table(doc, ["File", "Lang", "Purpose", "Important elements", "Called by", "Calls"], [
        ["app/main.py", "Py", "Entry point: builds the app,\nruns startup and shutdown", "create_app(),\nlifespan(),\n_seed_default_admin()", "uvicorn,\ntests", "all routers,\ninit_db,\npredictor.train"],
        ["core/config.py", "Py", "Every environment variable in\none frozen dataclass", "Settings, settings", "everything", "os.getenv,\ndotenv"],
        ["core/fares.py", "Py", "BMTC stage fare from distance", "get_fare(),\ncalculate_stage_fare(),\n_load_fare_table()", "tickets.py,\nwaybill_service", "predictor,\ndistance"],
        ["core/shakti.py", "Py", "The single shared Shakti\neligibility rule", "Gender,\nis_shakti_eligible(),\nDISCLOSURE", "tickets.py,\nwaybill_service,\nauth/routes", "nothing"],
        ["core/rate_limit.py", "Py", "Per-IP sliding-window limiter", "RateLimitMiddleware,\nEXEMPT_PATH_PREFIXES", "main.py", "nothing"],
        ["db/database.py", "Py", "Mongo client, indexes, and\ngraceful degradation", "init_db(), get_db(),\ndb_available()", "every service", "motor"],
    ], widths=[1.15, 0.35, 1.4, 1.5, 0.95, 1.05])

    h(doc, 2, "7.2 Backend - the engines (app/ml, app/gtfs, app/tracking)")
    table(doc, ["File", "Lang", "Purpose", "Important elements", "Called by", "Calls"], [
        ["ml/predictor.py", "Py", "THE core engine: route search,\nranking, transfers, benchmarks", "BMTCBusPredictor,\npredict(),\n_find_transfer_suggestions(),\n_interchange_is_walkable()", "api/routes,\nvotes, sms,\ntickets", "distance,\ndata_loader,\nroute_geometry"],
        ["ml/blocking.py", "Py", "Vehicle blocking: minimum fleet\nand dead kilometres", "BlockingEngine,\nBlockingParameters,\nchain_blocks(),\nconcurrency_lower_bound()", "blocking_\nservice,\ncrew_service", "distance,\ndata_loader"],
        ["ml/crew.py", "Py", "Crew duties cut from vehicle\nblocks", "CrewParameters,\ncut_block_into_pieces(),\ncombine_pieces_into_duties()", "crew_service", "blocking"],
        ["ml/distance.py", "Py", "Stop name -> coordinate, and\ndistance between stops", "GoogleMapsDistanceService,\nStopRecord,\nresolve_stop_record()", "predictor,\nblocking,\ngtfs", "httpx\n(optional)"],
        ["ml/route_geometry.py", "Py", "Anchored resolution of an\nordered stop list", "resolve_stop_sequence(),\nresolve_route_geometry()", "predictor,\ngtfs builder,\nvehicle_service", "distance"],
        ["ml/data_loader.py", "Py", "CSV -> RouteRecord objects", "RouteRecord,\nload_routes(),\ndataset_profile()", "predictor,\nblocking, gtfs", "csv, text"],
        ["ml/text.py", "Py", "Stop name normalisation, fuzzy\nmatching, mojibake repair", "normalize_text(),\nfuzzy_ratio(),\nrepair_route_text()", "everywhere", "difflib"],
        ["gtfs/builder.py", "Py", "Streams the GTFS static feed\ninto a zip", "GtfsFeedBuilder,\nGtfsParameters,\nGtfsBuildReport", "gtfs_service", "route_geometry,\nblocking"],
        ["gtfs/realtime.py", "Py", "GTFS-Realtime protobuf feeds", "build_service_alerts_feed(),\nbuild_vehicle_positions_feed()", "api/gtfs", "gtfs_realtime\n_pb2"],
        ["tracking/base.py", "Py", "The feed interface every\nadapter implements", "VehicleFeed (Protocol),\nVehicleObservation", "adapters,\nstore, ingest", "nothing"],
        ["tracking/adapters.py", "Py", "Four vehicle feed adapters", "SimulatedFeed,\nGtfsRealtimeFeed,\nHttpJsonFeed,\nPushIngestFeed, build_feed()", "ingest", "httpx,\nprotobuf"],
        ["tracking/store.py", "Py", "Latest position per vehicle,\nwith staleness", "VehicleStateStore,\nfresh(), apply()", "ingest,\nvehicle_service", "nothing"],
        ["tracking/ingest.py", "Py", "The polling loop and honest\nsource reporting", "VehicleIngestService,\nsource_report()", "main.py,\napi/tracking", "adapters,\nstore"],
        ["tracking/matcher.py", "Py", "Projection, trip matching,\nroute-following ETA", "project_onto_polyline(),\nmatch_trip(),\nestimate_arrival()", "vehicle_\nservice", "blocking"],
    ], widths=[1.2, 0.32, 1.35, 1.65, 0.85, 1.03])

    h(doc, 2, "7.3 Backend - API layer")
    table(doc, ["File", "Purpose", "Important endpoints / elements"], [
        ["api/routes.py", "The largest router: prediction plus all depot planning", "predict(), autocomplete(), metrics(), health(), train(),\ndepot_blocking_plan(), depot_crew_plan(),\ndepot_crew_scenario(), rank_dispatch_recommendations()"],
        ["api/votes.py", "Demand voting", "create_vote(), my_votes(), vote_allocation(),\nvote_aggregate()"],
        ["api/tickets.py", "Commuter e-tickets", "get_estimated_fare(), purchase_ticket(),\nget_active_ticket(), verify_ticket(), _account_gender()"],
        ["api/conductor.py", "The money workflows", "sign_on(), sync_tickets(), sign_off(), verify_pass(),\nissue_travel_pass(), shakti_claim_report(),\nrevenue_report(), audit_log()"],
        ["api/tracking.py", "Vehicle positions and AVL ingest", "get_all_buses(), get_bus(), get_eta(),\ningest_positions(), favourites CRUD"],
        ["api/gtfs.py", "Open data", "feed_info(), static_feed(), rebuild_feed(),\nservice_alerts_protobuf(), vehicle_positions_protobuf()"],
        ["api/admin.py", "Administration", "admin_dashboard(), list_users(), create_user_by_admin(),\ntoggle_user_active(), vote_analytics(), fraud_alerts()"],
        ["api/alerts.py", "Service disruptions", "list_active_alerts(), create_service_alert(),\nresolve_service_alert()"],
        ["api/crowding.py", "Crowdsourced occupancy", "report_crowding(), route_crowding()"],
        ["api/metro.py", "Metro data", "get_metro_stations(), get_nearest_metro_stations(),\nget_metro_map_pdf()"],
        ["api/safety.py", "Personal safety", "list/update trusted contacts, share_trip(),\nview_shared_trip()"],
        ["api/sms.py", "Low-bandwidth channel", "sms_webhook() (Twilio-signed), sms_query_test()"],
        ["auth/routes.py", "Identity", "register(), login(), get_me(), refresh_token()"],
        ["auth/auth.py", "Security primitives", "hash_password(), verify_password(), create_token(),\ndecode_token(), get_current_user(), require_role(),\nUserRole"],
    ], widths=[1.3, 2.0, 3.5])

    h(doc, 2, "7.4 Backend - service layer (all database access)")
    table(doc, ["File", "Purpose", "Key functions"], [
        ["services/vote_service.py", "Voting rules and aggregation", "VoteFraudDetector.check(), submit_vote(),\nget_vote_aggregation(), get_pair_demand()"],
        ["services/waybill_service.py", "The conductor money path", "price_ticket(), open_waybill(), issue_tickets(),\nrecompute_totals(), close_waybill(), shakti_claim(),\nrevenue_reconciliation()"],
        ["services/pass_service.py", "Travel passes", "issue_pass(), revoke_pass(), revocation_list(),\nverify_pass_token(), demo_verify()"],
        ["services/blocking_service.py", "Serves the fleet plan, cached", "compute_plan(), run_scenario(),\nBlockingPlanService.get_plan()"],
        ["services/crew_service.py", "Serves the crew plan, cached", "compute_crew_plan(), CrewPlanService.get_plan(),\nrun_scenario()"],
        ["services/gtfs_service.py", "Builds and caches the feed", "GtfsFeedService.ensure_built(), published_ids(),\nfeed_info()"],
        ["services/vehicle_service.py", "Vehicle queries and ETA", "describe_vehicles(), vehicle_trip_status(),\nestimate_eta(), RouteGeometryCache"],
        ["services/tracking_service.py", "The bus simulator", "BusSimulator.tick(), initialize_buses()"],
        ["services/crowding_service.py", "Crowd reports", "submit_crowd_report(), get_route_crowding()"],
        ["services/alerts_service.py", "Service alerts", "create_alert(), get_active_alerts(), resolve_alert()"],
        ["services/safety_service.py", "Trusted contacts, trip shares", "save_trusted_contacts(), create_trip_share(),\nget_shared_trip()"],
        ["services/sms_service.py", "SMS parsing and formatting", "parse_sms_query(), format_sms_reply(),\nformat_low_confidence_reply()"],
        ["services/metro_service.py", "Metro station lookup", "metro_service singleton, nearest-station search"],
        ["services/analytics_service.py", "Privacy-minimal usage logging", "log_event(), get_pilot_metrics()"],
        ["services/audit_service.py", "Accountability record", "record(), recent()"],
    ], widths=[1.6, 2.1, 3.1])

    h(doc, 2, "7.5 Frontend")
    table(doc, ["File", "Purpose", "Important elements"], [
        ["src/main.tsx", "Mounts React into #root", "ReactDOM.createRoot"],
        ["src/App.tsx", "Router, providers, role gating", "ProtectedRoute, DashboardRouter, 13 routes"],
        ["contexts/AuthContext.tsx", "Auth state for the whole app", "login(), register(), logout(), isAdmin, isDepot,\nisConductor, User type"],
        ["contexts/LanguageContext.tsx", "Four-language switching", "t() with dot-path lookup and English fallback"],
        ["lib/apiClient.ts", "Single source of the backend URL", "API_BASE_URL, apiFetch() - converts TypeError into\na readable network message"],
        ["lib/offlineQueue.ts", "Offline conductor sales", "enqueue(), flush(), pendingCount(), newTicketId()"],
        ["pages/PredictPage.tsx", "Journey search (861 lines)", "handleSubmit, RouteStopsPanel, alerts, RouteMap"],
        ["pages/VotePage.tsx", "Demand voting (697 lines)", "vote submission, aggregate display"],
        ["pages/Tickets.tsx", "E-ticket purchase and display", "QR rendering, Shakti pre-purchase notice"],
        ["pages/ConductorDuty.tsx", "Conductor working day", "signOn(), issueTicket(), syncNow(), signOff()"],
        ["pages/LiveTracking.tsx", "Vehicle map", "marker colouring by occupancy, detail panel"],
        ["pages/DepotDashboard.tsx", "Operations screen", "hosts BlockingPanel, ScenarioConsole, CrewPanel"],
        ["components/RouteMap.tsx", "Route map with per-leg colouring", "MapBehaviour (invalidateSize, zoom handlers),\ncreatePortal for full screen"],
        ["components/BlockingPanel.tsx", "Fleet plan UI", "depot selector, proposals, approve/reject"],
        ["components/CrewPanel.tsx", "Crew plan UI", "duty metrics, crew rule scenario console"],
        ["components/ScenarioConsole.tsx", "Timetable what-if UI", "headway / add / remove trips"],
        ["components/AutocompleteInput.tsx", "Stop name suggestions", "debounced GET /autocomplete"],
    ], widths=[1.7, 2.0, 3.1])
    page_break(doc)


def section_8(doc):
    h(doc, 1, "8. Application Entry Point")
    para(doc, "Knowing exactly where and how the application starts is a standard viva question. "
              "For DBARS the answer has two halves: how the process is launched, and what happens "
              "inside lifespan() before the first request is served.")

    h(doc, 2, "8.1 How the process is launched")
    code(doc,
         "  Development:   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000\n"
         "  Docker:        the backend image runs the same uvicorn command\n"
         "  Tests:         with TestClient(app) - which runs the full lifespan too\n"
         "\n"
         "  'app.main:app'  means: import the module app.main, take the object named app.\n"
         "  That object is created on the last line of main.py:   app = create_app()",
         caption="Figure 8.1 - Launch paths.")

    h(doc, 2, "8.2 create_app() - assembling the application")
    para(doc, "This function builds the FastAPI object but does not start anything. Order matters "
              "in two places, and both are deliberate.")
    numbered(doc, [
        "FastAPI(...) is constructed with the title, version, description and - critically - the lifespan function.",
        "RateLimitMiddleware is added FIRST, then CORSMiddleware. In Starlette the middleware added last sits outermost, so CORS wraps rate limiting. That ordering means a rejected 429 response still carries CORS headers, so the browser can read the error instead of reporting an opaque network failure.",
        "app.state.predictor = BMTCBusPredictor(...) creates the engine object, but does not train it yet.",
        "Fourteen routers are attached with app.include_router(...).",
        "The assembled app is returned.",
    ])
    evidence(doc, "backend/app/main.py -> create_app()")

    h(doc, 2, "8.3 lifespan() - the startup sequence, in order")
    para(doc, "lifespan is an async context manager. Everything before the yield runs once at "
              "startup; everything after it runs once at shutdown.")
    code(doc,
         "  STARTUP\n"
         "  1. Verify the four required dataset files exist.\n"
         "     A missing file raises FileNotFoundError and REFUSES to start. Deliberate:\n"
         "     an app with no timetable cannot answer anything, so failing loudly at boot\n"
         "     is better than failing mysteriously on every request.\n"
         "\n"
         "  2. app.state.predictor.train()\n"
         "     Loads routes_cleaned.csv, builds every index, and either reads cached metrics\n"
         "     from artifacts/metrics.json or re-evaluates the models. About 7 seconds.\n"
         "     This is BLOCKING - the server does not accept traffic until it finishes.\n"
         "\n"
         "  3. Fire-and-forget: _warm_blocking_plan()\n"
         "     The fleet plan takes ~25 s. Warming it in the background means the first depot\n"
         "     manager to open the dashboard does not wait. Held on app.state, NOT in a local\n"
         "     variable, because asyncio keeps only a weak reference to running tasks - a task\n"
         "     with no strong reference can be garbage collected mid-flight.\n"
         "\n"
         "  4. Fire-and-forget: _warm_gtfs_feed()   (if GTFS_BUILD_ON_STARTUP is true)\n"
         "     Adopts a feed a previous run left on disk, or builds a new one in ~11 s.\n"
         "\n"
         "  5. await vehicle_ingest.start(predictor=...)\n"
         "     Builds the adapter named by TRACKING_FEED and starts the polling loop.\n"
         "\n"
         "  6. await init_db()\n"
         "     Creates every MongoDB index. If Mongo is unreachable this logs a warning and\n"
         "     returns - it does NOT raise. Route prediction is already working by this point.\n"
         "\n"
         "  7. _seed_default_admin()  only when SEED_DEFAULT_ADMIN=true, and it refuses to seed\n"
         "     the password 'admin123' when ENV=production.\n"
         "\n"
         "  yield   <-- the application now serves requests\n"
         "\n"
         "  SHUTDOWN\n"
         "  8. await vehicle_ingest.stop()      cancel the poll loop, close the HTTP client\n"
         "  9. Cancel the two warm-up tasks if still running\n"
         " 10. await close_db()                 close the Mongo connection pool",
         caption="Figure 8.2 - The full startup and shutdown sequence.")
    callout(doc, "The ordering decision that defines this project",
            "Step 2 (train the predictor) runs BEFORE step 6 (connect to MongoDB), and step 6 cannot "
            "abort startup. That single ordering choice is what makes the core feature independent of "
            "the database. Reverse those two steps and an unreachable Mongo would take the whole "
            "application down with it. CONFIRMED: main.py, and the init_db() docstring explaining "
            "that this exact failure used to happen.")

    h(doc, 2, "8.4 Configuration loading")
    para(doc, "core/config.py runs at import time, before anything else. It calls load_dotenv() twice - "
              "once for backend/.env and once for a workspace-level .env - then builds a single frozen "
              "Settings dataclass. Frozen means immutable: no code can change configuration at runtime, "
              "so behaviour cannot silently drift between requests.")
    evidence(doc, "backend/app/core/config.py")
    page_break(doc)


def section_9(doc):
    h(doc, 1, "9. Complete Request / Execution Traces")
    para(doc, "Each trace below names the real file, function and line-level behaviour at every step. "
              "These are the traces to rehearse before a viva.")

    h(doc, 2, "9.1 Trace 1 - POST /predict (the core feature)")
    table(doc, ["#", "Where", "What happens"], [
        ["1", "PredictPage.tsx -> handleSubmit", "Reads the two stop names from React state; guards against\nempty or identical stops"],
        ["2", "services/api.ts -> planRoute", "Builds the JSON body; expands candidate stop-name splits"],
        ["3", "lib/apiClient.ts -> apiFetch", "Prefixes API_BASE_URL; catches TypeError and rethrows it\nas \"Can't reach the server\""],
        ["4", "network", "POST /predict with a JSON body"],
        ["5", "CORSMiddleware", "Confirms the browser origin is allowed"],
        ["6", "RateLimitMiddleware", "Per-IP deque; over 120/minute returns 429"],
        ["7", "FastAPI router", "Matches the path to predict() in api/routes.py"],
        ["8", "PredictRequest (pydantic)", "Validates lengths and types; a bad body is 422 before any\nlogic runs"],
        ["9", "api/routes.py -> predict()", "Calls asyncio.to_thread(predictor.predict, ...) so ~1 s of\nCPU does not block the event loop"],
        ["10", "predictor._resolve_stop_name", "Fuzzy-matches each typed name to a real stop, returning a\nconfidence score"],
        ["11", "predictor._find_transfer_\nsuggestions", "Candidate generation from stop_to_route_indices and\nstop_pair_to_segments; direct routes first, then one-transfer\nchains"],
        ["12", "predictor._interchange_is_\nwalkable", "Rejects any transfer whose two stops are more than 1.2 km\napart - the Avalahalli problem"],
        ["13", "predictor._make_transfer_leg", "Per leg: stop path, distance, trip counts, EV estimate,\nmetro interchange"],
        ["14", "predictor._reanchor_legs", "Re-resolves the whole journey as ONE anchored sequence so\nthe interchange lands on a single physical place"],
        ["15", "api/routes.py", "Adds metro enrichment; logs a predict_query usage event\n(fire-and-forget)"],
        ["16", "FastAPI", "Serialises the dict to JSON"],
        ["17", "PredictPage.tsx", "setResult(...) triggers a re-render"],
        ["18", "components/RouteMap.tsx", "Draws one coloured polyline per leg, with markers for board,\nchange and alight"],
    ], widths=[0.3, 1.9, 4.6])

    h(doc, 2, "9.2 Trace 2 - POST /conductor/tickets/sync (offline sales)")
    table(doc, ["#", "Where", "What happens"], [
        ["1", "ConductorDuty.tsx ->\nissueTicket", "Writes the sale into localStorage FIRST, with a\nclient-generated UUID"],
        ["2", "lib/offlineQueue.ts -> flush", "Sends the whole queue as one batch"],
        ["3", "api/conductor.py ->\nsync_tickets", "require_role(CONDUCTOR, ADMIN)"],
        ["4", "waybill_service.issue_tickets", "For each ticket: check the waybill exists, belongs to this\nconductor, and is still OPEN"],
        ["5", "waybill_service.price_ticket", "Confidence gate at 0.55 - refuses to price an unrecognised\nstop rather than guessing a cash fare"],
        ["6", "core/fares.py -> get_fare", "The SAME pricing path the commuter e-ticket uses"],
        ["7", "MongoDB insert", "Unique index (waybill_id, client_ticket_uuid). A replay raises\nDuplicateKeyError, caught and reported as 'duplicate'"],
        ["8", "response", "Per-item accepted / duplicates / rejected lists"],
        ["9", "lib/offlineQueue.ts", "Clears ONLY the items the server acknowledged; anything else\nstays queued"],
    ], widths=[0.3, 1.9, 4.6])
    callout(doc, "Why per-item results matter",
            "If the client cleared its whole queue on a 200 response, any ticket the server rejected "
            "would be silently lost - and a lost cash sale is indistinguishable afterwards from one "
            "that never happened. Returning per-item outcomes is what makes the offline queue safe. "
            "CONFIRMED: services/waybill_service.py -> issue_tickets(); frontend/src/lib/offlineQueue.ts.")

    h(doc, 2, "9.3 Trace 3 - GET /gtfs-rt/vehicle-positions.pb (the honesty gate)")
    table(doc, ["#", "Where", "What happens"], [
        ["1", "api/gtfs.py ->\nvehicle_positions_protobuf", "Calls _vehicle_positions_response(allow_simulated=False)"],
        ["2", "tracking/ingest.py ->\nsource_report()", "Reports the active adapter and its is_live flag"],
        ["3", "the gate", "If not is_live -> HTTP 503 with an explanation of why"],
        ["4", "tracking/store.py -> fresh()", "Only observations newer than AVL_STALE_SECONDS"],
        ["5", "gtfs/realtime.py ->\nbuild_vehicle_positions_feed", "Builds the protobuf; vehicle.timestamp is the SOURCE\nobservation time, never the time of republication"],
        ["6", "response", "application/x-protobuf, with X-Feed-Is-Live in the headers"],
    ], widths=[0.3, 1.9, 4.6])
    para(doc, "With the default configuration this endpoint returns 503, and that is correct behaviour, "
              "not a bug. GTFS-Realtime has no field meaning \"this data is simulated\", so a consumer "
              "ingesting the feed could not tell the difference. Publishing simulator output here would "
              "be indistinguishable from claiming BMTC's fleet is being tracked.")
    page_break(doc)
