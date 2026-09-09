# -*- coding: utf-8 -*-
"""Sections 2-3: Technology Stack, Architecture."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_2(doc):
    h(doc, 1, "2. Technology Stack")
    para(doc, "Every technology below was identified by reading the dependency files and source of "
              "this project, not assumed in advance. Unfamiliar terms are defined in plain language "
              "in the glossary in Section 31.")

    h(doc, 2, "2.1 Backend")
    table(doc, ["Layer", "Technology", "Purpose", "Why it is used here", "Evidence"], [
        ["Language", "Python 3.12", "Backend logic", "Strong CSV and data handling; the routing and\nblocking maths is easiest to express here", "ci.yml"],
        ["Web framework", "FastAPI 0.115.6", "Serves the 82 REST\nendpoints", "Async by default, automatic OpenAPI docs, and\nrequest validation straight from type hints", "requirements.txt"],
        ["Server", "Uvicorn 0.34", "ASGI server running\nFastAPI", "Standard production runner for async Python", "requirements.txt"],
        ["Validation", "Pydantic 2.10.4", "Request/response\nmodels", "Rejects malformed input before it can reach\nbusiness logic", "models/schemas.py"],
        ["DB driver", "Motor 3.6", "Async MongoDB client", "Non-blocking database access, so one slow query\ndoes not stall the event loop", "db/database.py"],
        ["Config", "python-dotenv 1.0.1", "Loads .env files", "Keeps secrets out of source code", "core/config.py"],
        ["HTTP client", "httpx 0.28.1", "Outbound HTTP calls", "Async client used for Google Maps and AVL feeds", "ml/distance.py"],
        ["Open data", "gtfs-realtime-\nbindings 2.2.0", "GTFS-RT protobuf", "Official Google protobuf schema for transit\nrealtime data", "gtfs/realtime.py"],
        ["Spreadsheets", "openpyxl 3.1", "Reads the depot\nworkbook", "The depot list ships as an .xlsx file", "ml/blocking.py"],
        ["Numerics", "numpy, scipy,\nscikit-learn", "TF-IDF baseline", "Used only for the benchmark rankers, never for\nthe shipped search", "ml/tfidf.py"],
        ["Testing", "pytest 8.3.4,\npytest-asyncio 0.24", "161 tests", "asyncio_mode = strict, so an async test cannot\nsilently be skipped", "pytest.ini"],
    ], widths=[0.85, 1.15, 1.2, 2.4, 1.2])

    h(doc, 2, "2.2 Frontend")
    table(doc, ["Layer", "Technology", "Purpose", "Why it is used here", "Evidence"], [
        ["Language", "TypeScript 5.7", "Typed UI code", "Catches shape mismatches between the API and\nthe UI at compile time", "tsconfig.json"],
        ["Framework", "React 19", "Component UI", "The component model suits many small panels\nsharing state", "package.json"],
        ["Build tool", "Vite 6", "Dev server and\nbundler", "Fast rebuilds; produces the static bundle that\nNginx and Capacitor serve", "vite.config.ts"],
        ["Routing", "react-router-dom 7", "Client-side pages", "Role-gated routes through ProtectedRoute", "src/App.tsx"],
        ["Styling", "Tailwind 3.4 plus\nstyles.css", "Visual design", "Utility classes plus a hand-written design system\nof CSS variables", "tailwind.config.ts"],
        ["Maps", "Leaflet 1.9 +\nreact-leaflet 5", "Route and live maps", "Free and needs no API key, unlike Google Maps", "components/\nRouteMap.tsx"],
        ["Charts", "Recharts 3.9", "Dashboard graphs", "Declarative charts for the depot and admin panels", "pages/\nDepotDashboard.tsx"],
        ["Animation", "framer-motion 12", "Page transitions", "Declarative animation of panels and results", "pages/PredictPage.tsx"],
        ["QR codes", "qrcode.react 4,\nhtml5-qrcode 2.3", "Ticket QR and\nscanner", "Generates the ticket QR, and reads it back on the\nconductor device", "pages/Tickets.tsx"],
        ["Icons, toasts", "lucide-react,\nreact-hot-toast", "UI feedback", "Consistent icon set and notification system", "package.json"],
        ["Mobile", "Capacitor 8", "Android wrapper", "Packages the built web app into an APK", "capacitor.config.ts"],
    ], widths=[0.85, 1.15, 1.2, 2.4, 1.2])
    callout(doc, "Finding - an unused dependency",
            "@vis.gl/react-google-maps is declared in package.json, but every map component imports "
            "Leaflet instead. This looks like a leftover from an earlier approach. CONFIRMED: no file "
            "under frontend/src imports @vis.gl. Removing it would cut dead weight from the dependency "
            "tree. Note the bundle is already large at ~1.6 MB (468 KB gzipped).", warn=True)

    h(doc, 2, "2.3 Data, storage and infrastructure")
    table(doc, ["Layer", "Technology", "Purpose", "Why it is used here", "Evidence"], [
        ["Primary data", "CSV / JSON / XLSX\nin dataset/", "The BMTC timetable", "The engine loads from files, not a database, so it\nkeeps working when Mongo is down", "ml/data_loader.py"],
        ["Database", "MongoDB", "Accounts, votes, tickets,\nwaybills, alerts", "Schema-free documents suited records whose shape\nevolved during development", "db/database.py"],
        ["Containers", "Docker and\nDocker Compose", "backend, frontend,\nmongo", "One command brings up the entire stack", "docker-compose.yml"],
        ["Web server", "Nginx", "Serves the built\nfrontend", "Static file serving inside the frontend image", "deployment/nginx.conf"],
        ["Hosting", "Render / Vercel", "Deployment targets", "render.yaml deploys both services; vercel.json\nhosts the frontend alone", "deployment/render.yaml"],
        ["CI", "GitHub Actions", "Tests on every push", "Runs pytest, compileall and the frontend build", ".github/workflows/ci.yml"],
    ], widths=[0.85, 1.15, 1.2, 2.4, 1.2])

    h(doc, 2, "2.4 What is NOT in the stack")
    para(doc, "Being explicit about absences is what prevents overclaiming in an interview.")
    bullets(doc, [
        ("No ORM.", "MongoDB is accessed directly through Motor. There is no SQLAlchemy, Django ORM or Prisma anywhere."),
        ("No JWT library.", "The JSON Web Token implementation is hand-written using hmac and hashlib in auth/auth.py."),
        ("No trained model file.", "There are no .pkl or .h5 weights. scikit-learn appears only in a TF-IDF benchmark baseline."),
        ("No LLM in the routing engine.", "The bus predictor contains no language model. A separate AI layer (Section 40) does use embeddings, a FAISS vector store and an optional Gemini call - keep the two apart. See Section 16."),
        ("No payment gateway.", "No Razorpay, Stripe or UPI SDK is present."),
        ("No queue and no cache server.", "No Redis, RabbitMQ or Celery. Expensive computations are cached in process memory instead."),
    ])
    page_break(doc)


def section_3(doc):
    h(doc, 1, "3. Project Architecture")

    h(doc, 2, "3.1 High-Level Architecture")
    para(doc, "DBARS is a client-server web application with an unusually heavy computational layer "
              "inside the server. The browser holds no business logic. Every decision - which bus, "
              "what fare, how many crew - is made in Python and sent to the interface as JSON.")
    code(doc,
         "  BROWSER / ANDROID APP                  SERVER (FastAPI)                     DATA\n"
         "  +--------------------+                                                              \n"
         "  | React 19 SPA       |   HTTPS / JSON   +----------------------+                    \n"
         "  |  - PredictPage     | <==============> |  API layer           |                    \n"
         "  |  - VotePage        |                  |  (app/api/*.py)      |                    \n"
         "  |  - Tickets         |                  +----------+-----------+                    \n"
         "  |  - LiveTracking    |                             |                                \n"
         "  |  - DepotDashboard  |                  +----------v-----------+     +------------+ \n"
         "  |  - AdminDashboard  |                  |  Service layer       |---->|  MongoDB   | \n"
         "  |  - ConductorDuty   |                  |  (app/services/*.py) |     |  17 colls  | \n"
         "  +--------------------+                  +----------+-----------+     +------------+ \n"
         "                                                     |                                \n"
         "  EXTERNAL CONSUMERS                      +----------v-----------+     +------------+ \n"
         "  +--------------------+  GTFS / protobuf |  Engine layer        |---->|  dataset/  | \n"
         "  | Google Maps, OTP,  | <=============== |  (app/ml, app/gtfs,  |     |  CSV JSON  | \n"
         "  | any journey planner|                  |   app/tracking)      |     |  XLSX      | \n"
         "  +--------------------+                  +----------------------+     +------------+ \n"
         "                                                     ^                                \n"
         "  SMS (feature phone) ---> /sms/webhook -------------+                                \n"
         "  Fleet AVL feed      ---> /avl/ingest --------------+                                ",
         caption="Figure 3.1 - High-level architecture. The engine layer reads the dataset directly "
                 "and has no dependency on MongoDB.")

    h(doc, 2, "3.2 Component Architecture - the four layers")
    para(doc, "The backend is organised in four layers. A request travels downward and a response "
              "travels back up. This is the single most likely architecture question in a viva, so "
              "learn this table.")
    table(doc, ["Layer", "Folder", "Responsibility", "May it touch the DB?"], [
        ["1. API", "app/api/,\napp/auth/", "HTTP concerns only: parse the request, check the role,\ncall a service, shape the response", "Only through services"],
        ["2. Service", "app/services/", "Business rules and orchestration: what a vote means,\nwhat closing a waybill implies", "Yes - this is the\ndatabase layer"],
        ["3. Engine", "app/ml/, app/gtfs/,\napp/tracking/", "Pure computation over the dataset: route search,\nblocking, crew, GTFS building, ETAs", "No - deliberately\nfile-only"],
        ["4. Data", "app/db/, dataset/", "Connection handling, index creation, and the CSV,\nJSON and XLSX source files", "Yes"],
    ], widths=[0.85, 1.35, 3.2, 1.4])
    callout(doc, "The most important architectural decision in this project",
            "The engine layer never touches MongoDB. Route prediction, fleet blocking, crew scheduling "
            "and GTFS export are pure functions of files that ship inside the repository. That is why "
            "the app still answers journey queries, and still shows a depot manager a full fleet plan, "
            "when the database is switched off - and why db/database.py can fail politely instead of "
            "taking the whole application down. CONFIRMED: services/blocking_service.py states this in "
            "its module docstring, and db/database.py init_db() catches PyMongoError and returns.")

    h(doc, 2, "3.3 Frontend Architecture")
    para(doc, "The frontend is a single-page application: React Router swaps pages without reloading "
              "the browser, and two React Contexts hold state that many pages need at once.")
    code(doc,
         "  main.tsx   (mounts React into #root)\n"
         "     |\n"
         "  App.tsx    (Router + AuthProvider + LanguageProvider)\n"
         "     |\n"
         "     +-- ProtectedRoute  (checks token, checks role, else redirects)\n"
         "     |        |\n"
         "     |        +-- /predict   PredictPage    -> RouteMap, NearestMetroPanel, SafetyPanel\n"
         "     |        +-- /vote      VotePage\n"
         "     |        +-- /track     LiveTracking\n"
         "     |        +-- /tickets   Tickets\n"
         "     |        +-- /depot     DepotDashboard -> BlockingPanel, ScenarioConsole, CrewPanel\n"
         "     |        +-- /admin     AdminDashboard -> MetricsDashboard, BlockingSummaryCard\n"
         "     |        +-- /duty      ConductorDuty  -> lib/offlineQueue.ts\n"
         "     |        +-- /scanner   ConductorScanner\n"
         "     |\n"
         "     +-- public routes:  /   /login   /register   /trip/:code\n"
         "\n"
         "  Shared state:  AuthContext      (user, token, isAdmin / isDepot / isConductor)\n"
         "                 LanguageContext  (en / kn / hi / te, with English fallback)\n"
         "  Shared I/O:    lib/apiClient.ts -> apiFetch() wraps every call to the backend",
         caption="Figure 3.2 - Frontend component tree and routing.")
    evidence(doc, "frontend/src/App.tsx lines 50-77; frontend/src/contexts/")

    h(doc, 2, "3.4 Backend Architecture - router registration")
    para(doc, "FastAPI composes the API from routers. Each router owns one subject area and is "
              "attached to the application inside create_app().")
    table(doc, ["Router", "Prefix", "Owns"], [
        ["predict_router", "(none)", "/predict, /routes, /metrics, /autocomplete, /health, /train,\nall /depot/* planning endpoints, /tracking/source, /directions"],
        ["auth_router", "/auth", "register, login, me, refresh"],
        ["votes_router", "/votes", "Demand voting, aggregation, allocation"],
        ["admin_router", "/admin", "Dashboards, user management, fraud alerts, pilot metrics"],
        ["tracking_router", "/tracking", "Vehicle positions, single bus, ETA, favourites, tick"],
        ["avl_router", "/avl", "Pushed vehicle positions from a fleet system"],
        ["tickets_router", "/api/tickets", "Fare quote, purchase, active, history, verify"],
        ["metro_router", "/metro", "Metro stations, nearest station, map PDF"],
        ["crowding_router", "/crowding", "Crowd reports and per-route crowding"],
        ["alerts_router", "/alerts", "Service disruption alerts"],
        ["sms_router", "/sms", "Twilio webhook and a JSON test twin"],
        ["safety_router", "/safety", "Trusted contacts and expiring trip shares"],
        ["gtfs_router,\ngtfs_realtime_router", "/gtfs,\n/gtfs-rt", "Static feed, feed info, rebuild; realtime alerts and vehicles"],
        ["conductor_router,\ndepot_router,\noffice_router", "/conductor,\n/depot,\n/admin", "Waybills, onboard tickets, passes, Shakti claim,\nrevenue reconciliation, audit log"],
    ], widths=[1.5, 1.1, 4.2])
    evidence(doc, "backend/app/main.py -> create_app()")

    h(doc, 2, "3.5 Database Architecture")
    para(doc, "MongoDB is a document database. It stores JSON-like records called documents inside "
              "named groups called collections. There is no fixed table schema, so two documents in "
              "one collection may carry different fields. DBARS uses 17 collections; the field-level "
              "breakdown is in Section 14.")
    para(doc, "Crucially the database is optional. init_db() tries to create indexes; if MongoDB cannot "
              "be reached it sets an internal _unavailable flag, logs a warning and returns. Endpoints "
              "that genuinely need the database then raise a clear 503, while route prediction, "
              "blocking, crew planning and GTFS export continue unaffected.")
    evidence(doc, "backend/app/db/database.py -> init_db(), db_available(), get_db()")

    h(doc, 2, "3.6 External Services")
    table(doc, ["Service", "Status in the code", "Purpose", "Fallback when absent"], [
        ["Google Maps\nDistance Matrix", "Optional; disabled by default\n(the API key is empty)", "Road distance and duration\nbetween two stops",
         "Straight-line distance from stop\ncoordinates, x1.28 road factor"],
        ["Twilio SMS", "Webhook implemented; needs\nTWILIO_AUTH_TOKEN to accept\nanything", "Receives SMS journey\nqueries from feature phones",
         "POST /sms/query exercises the\nsame pipeline with no gateway"],
        ["Fleet AVL feed", "Adapter written; not connected\nto any real feed", "Real vehicle positions",
         "Physics simulator, flagged\nis_live = False"],
        ["OpenStreetMap /\nCARTO tiles", "Active", "Map background tiles", "None - the map would be blank"],
    ], widths=[1.3, 1.95, 1.75, 1.9])

    h(doc, 2, "3.7 AI / ML Architecture")
    para(doc, "Two separate things live under this heading, and conflating them is the mistake to "
              "avoid. The ROUTING ENGINE - the thing that predicts buses - contains no artificial "
              "intelligence, no language model and no trained neural network. It is classical "
              "information retrieval and graph search: an inverted index, an ordered stop-pair index "
              "and a hand-weighted ranking function, benchmarked against three baselines.", bold=True)
    para(doc, "A separate AI Intelligence Layer was added afterwards, under backend/app/ai. That one "
              "does contain machine-learning machinery: sentence-level retrieval over an AST-chunked "
              "code index and a documentation index, a FAISS vector store, BM25 fused with vector "
              "similarity by Reciprocal Rank Fusion, and an optional Gemini call. It answers questions "
              "ABOUT the system; it does not route buses, and the engine does not import it.")
    para(doc, "The honest framing, and the one to use in a viva: no model decides which bus you catch. "
              "Sections 40 to 42 cover the AI layer in full, including the measurement showing that "
              "only 1.8% of its benchmark answers actually reach a language model.")

    h(doc, 2, "3.8 Authentication Architecture")
    code(doc,
         "  Register / Login\n"
         "      |   password hashed with PBKDF2-SHA256, per-user random salt\n"
         "      v\n"
         "  users collection  --->  access token (24 h)  +  refresh token (7 d)\n"
         "      |\n"
         "      v\n"
         "  Browser stores both tokens in localStorage\n"
         "      |\n"
         "      |   Authorization: Bearer <token>   on every protected request\n"
         "      v\n"
         "  get_current_user()  -> verify HMAC-SHA256 signature, check exp, check type == access\n"
         "      |\n"
         "      v\n"
         "  require_role(...)   -> compare the role claim against the roles the endpoint allows\n"
         "\n"
         "  THREE SEPARATE SIGNING KEYS, so one stolen key cannot mint another kind of credential:\n"
         "      SECRET_KEY         -> session tokens      (type: access / refresh)\n"
         "      TICKET_SECRET_KEY  -> e-ticket QR tokens  (type: qr_ticket)\n"
         "      PASS_SECRET_KEY    -> travel pass tokens  (type: travel_pass)",
         caption="Figure 3.3 - Authentication flow and the three token domains.")
    evidence(doc, "backend/app/auth/auth.py; backend/app/auth/routes.py")

    h(doc, 2, "3.9 Deployment Architecture")
    code(doc,
         "  docker compose up --build\n"
         "        |\n"
         "        +-- mongo     : official image, port 27017, named volume for persistence\n"
         "        +-- backend   : python image, uvicorn on port 8000, mounts dataset/ read-only\n"
         "        +-- frontend  : node build stage -> nginx serving the bundle on port 8080\n"
         "\n"
         "  Alternative targets present in the repository:\n"
         "        deployment/render.yaml   two Render services (backend API + static frontend)\n"
         "        vercel.json              frontend only; VITE_API_URL points at the backend",
         caption="Figure 3.4 - Deployment topology.")
    evidence(doc, "docker-compose.yml; deployment/render.yaml; vercel.json; frontend/Dockerfile")
    page_break(doc)
