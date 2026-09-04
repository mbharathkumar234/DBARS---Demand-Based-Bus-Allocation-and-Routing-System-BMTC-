# -*- coding: utf-8 -*-
"""Sections 21-25: Testing, deployment, dependencies, patterns, algorithms."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_21(doc):
    h(doc, 1, "21. Testing")

    h(doc, 2, "21.1 What exists")
    para(doc, "161 backend tests across 15 files, all passing, run in CI on every push. There are "
              "ZERO frontend tests - package.json defines no test script and no test framework is "
              "installed. That asymmetry is a real gap and is listed in Section 36.", bold=True)
    table(doc, ["Test file", "Covers", "Notable"], [
        ["test_predictor.py", "Route search, ranking, stop resolution", "The core engine"],
        ["test_route_geometry.py", "Anchored geometry, no teleporting hops,\ndrawn length vs stated distance", "23 tests; guards the mechanism,\nnot just the symptom"],
        ["test_blocking.py", "Chaining, lower bound, dataset plausibility", "Sanity ranges catch confident\nwrong answers"],
        ["test_blocking_api.py", "The depot blocking endpoints", "API-level"],
        ["test_scenario.py", "Timetable what-if logic", "Scenario console"],
        ["test_crew.py", "Cutting, pairing, constraint invariants", "17 tests"],
        ["test_gtfs_builder.py", "Feed integrity, monotonic times, provenance", "12 tests"],
        ["test_gtfs_realtime.py", "Alert protobuf, dangling references", "5 tests"],
        ["test_avl.py", "Staleness, adapters, projection, ETA", "13 tests"],
        ["test_waybill.py", "Pricing, Shakti split, pass verification", "13 tests"],
        ["test_shakti.py", "Eligibility rule, AC exclusion, claim safety", "8 tests"],
        ["test_votes.py", "Vote ranking on fixture data", "Runs without MongoDB"],
        ["test_text.py", "Normalisation, fuzzy matching, mojibake", "Utility layer"],
        ["test_token_types.py", "A ticket token cannot become a session", "Regression test for a real bug"],
        ["test_sms_webhook_signature.py", "Twilio signature verification", "Security regression"],
    ], widths=[1.6, 2.6, 2.6])

    h(doc, 2, "21.2 The testing philosophy, and why it is worth describing")
    para(doc, "The test suite follows a consistent split that is unusually thoughtful for a student "
              "project, and is worth explaining if asked how you tested it:")
    bullets(doc, [
        ("Unit tests on hand-built fixtures.", "Small inputs where the correct answer is countable "
         "by hand - three trips, a known cut point, a four-point polyline."),
        ("Dataset tests on real data with plausibility ranges.", "The blocking tests state the "
         "reasoning outright: every wrong version of the engine still ran cleanly and produced "
         "confident-looking numbers - 30,570 buses for a 6,000-bus operator, 36% dead kilometres. Only "
         "a sanity range catches that class of failure."),
        ("Invariant tests rather than value tests.", "The crew tests assert that every trip is worked "
         "by exactly one person and no duty breaks a declared rule, rather than asserting a specific "
         "duty count that would change whenever a parameter changed."),
        ("Regression tests that name the bug.", "test_token_types.py exists because a ticket token "
         "once authenticated as a session. test_route_geometry.py asserts that unanchored resolution "
         "still produces a visibly worse path, so the test keeps guarding the mechanism rather than "
         "silently passing after a refactor."),
    ])
    callout(doc, "A configuration detail that shows testing maturity",
            "pytest.ini sets asyncio_mode = strict and turns PytestUnhandledCoroutineWarning into an "
            "error. The comment explains why: the previous setup SKIPPED async tests and still "
            "reported the run green, so a regression test sat inert indefinitely. A test that silently "
            "does not run is worse than no test. CONFIRMED: backend/pytest.ini.")

    h(doc, 2, "21.3 What is not tested")
    bullets(doc, [
        ("The entire frontend.", "No component tests, no integration tests, no end-to-end tests. "
         "8,459 lines of TypeScript are verified only by the TypeScript compiler and manual use."),
        ("Most database write paths.", "Tests that need MongoDB largely avoid it by testing pure "
         "functions on fixtures. Waybill sync, sign-off and Shakti aggregation were verified manually "
         "against a live database during development, not by automated tests."),
        ("Authentication endpoints end to end.", "Token functions are unit-tested; the "
         "register/login HTTP flow is not."),
        ("Load and concurrency.", "No performance or concurrency tests exist."),
    ])
    para(doc, "Coverage is not measured - no coverage tool is configured, so no percentage can be "
              "quoted. Do not invent one.")
    page_break(doc)


def section_22(doc):
    h(doc, 1, "22. Deployment & Runtime")

    h(doc, 2, "22.1 The pipeline")
    code(doc,
         "  Developer machine\n"
         "      git push\n"
         "          |\n"
         "  GitHub Actions (.github/workflows/ci.yml)\n"
         "      backend job:   setup Python 3.12 -> pip install -r requirements.txt\n"
         "                     -> pytest tests -> python -m compileall app\n"
         "      frontend job:  setup Node 22 -> npm install -> npm run build\n"
         "          |\n"
         "  Deployment target (chosen per environment)\n"
         "      A. docker compose up --build          local or a single VM\n"
         "      B. Render (deployment/render.yaml)    two managed services\n"
         "      C. Vercel (vercel.json)               frontend only, backend elsewhere",
         caption="Figure 22.1 - From commit to running system.")
    para(doc, "Note what CI does and does not do: it runs tests and builds, but it does not deploy. "
              "There is no continuous deployment step. CONFIRMED: ci.yml contains only build and test "
              "jobs.")

    h(doc, 2, "22.2 Docker Compose - three services")
    table(doc, ["Service", "Image / build", "Port", "Notes"], [
        ["mongo", "Official MongoDB image", "27017", "Named volume for persistence"],
        ["backend", "backend/Dockerfile\n(Python + uvicorn)", "8000", "Mounts dataset/ read-only; depends on mongo"],
        ["frontend", "frontend/Dockerfile\n(node build -> nginx)", "8080", "Multi-stage: builds the bundle, then serves it\nwith Nginx"],
    ], widths=[1.0, 1.7, 0.7, 3.4])
    para(doc, "The frontend Dockerfile is a multi-stage build: the first stage installs Node "
              "dependencies and runs npm run build; the second copies only the resulting static files "
              "into an Nginx image. The final image therefore contains no Node runtime and no "
              "node_modules, which keeps it small.")

    h(doc, 2, "22.3 Runtime characteristics")
    table(doc, ["Aspect", "Detail"], [
        ["Startup time", "About 7 s to train the predictor before the first request is served; the\nblocking plan (~25 s) and GTFS feed (~11 s) warm in the background"],
        ["Memory", "Dominated by the in-memory indexes: 655,438 stop pairs and 3.9M route\nsegments. Not measured precisely - UNCERTAIN, and worth measuring before\nchoosing an instance size"],
        ["Disk", "The generated GTFS zip is ~14.4 MB and is gitignored"],
        ["Concurrency model", "Single-process async. CPU-bound work is pushed to a thread pool with\nasyncio.to_thread"],
        ["Process count", "One. Multiple uvicorn workers would break the in-memory rate limiter, the\nin-process caches and the vehicle store - each worker would hold its own"],
        ["Health check", "GET /health returns the predictor state and route count"],
    ], widths=[1.4, 5.4])
    callout(doc, "The scaling constraint to state honestly",
            "This application is currently single-process by design. The rate limiter, the blocking and "
            "crew caches, the GTFS build lock and the vehicle store all live in process memory. Running "
            "several uvicorn workers would give each its own copy, so the rate limit would multiply and "
            "the caches would be rebuilt per worker. Scaling horizontally requires moving that shared "
            "state to Redis or an equivalent first. This is the correct answer to \"how would you scale "
            "it?\" - see Section 28.", warn=True)
    page_break(doc)


def section_23(doc):
    h(doc, 1, "23. Dependency Analysis")
    para(doc, "Only dependencies that matter are analysed; transitive packages are not enumerated.")

    h(doc, 2, "23.1 Backend dependencies")
    table(doc, ["Dependency", "Purpose", "Where used", "Why it matters"], [
        ["fastapi", "Web framework", "Every api/*.py module", "Provides routing, dependency injection,\nvalidation and OpenAPI docs. Removing it\nwould mean rewriting the whole API layer"],
        ["uvicorn[standard]", "ASGI server", "Startup command", "Actually runs the app"],
        ["pydantic", "Data validation", "models/*.py", "The first line of defence against malformed\ninput; rejects bad bodies before any logic"],
        ["email-validator", "EmailStr support", "Auth and admin models", "Pydantic does NOT pull this in on its own -\nwithout it every import of app.main raises\nImportError at startup"],
        ["motor", "Async MongoDB driver", "db/database.py", "Non-blocking database access"],
        ["pymongo", "Mongo types and errors", "Services", "Supplies DuplicateKeyError, which is what\nmakes offline sync idempotent"],
        ["python-dotenv", "Loads .env", "core/config.py", "Keeps secrets out of source"],
        ["httpx", "Async HTTP client", "ml/distance.py,\ntracking/adapters.py", "Outbound calls to Google Maps and AVL feeds"],
        ["gtfs-realtime-bindings", "GTFS-RT protobuf", "gtfs/realtime.py", "The official schema; hand-rolling protobuf\nwould be error-prone and non-standard"],
        ["openpyxl", "Reads .xlsx", "ml/blocking.py", "The depot list ships as a spreadsheet"],
        ["numpy, scipy,\nscikit-learn", "Numerics and TF-IDF", "ml/tfidf.py", "Used ONLY for the benchmark baseline. The\nshipped search does not need them - they\ncould be moved to a dev-only requirement"],
        ["pytest,\npytest-asyncio", "Testing", "tests/", "161 tests. pytest-asyncio is essential:\nwithout it async tests are SKIPPED while the\nrun still reports green"],
        ["python-multipart", "Form parsing", "api/sms.py", "The Twilio webhook posts form-encoded data"],
        ["requests", "Sync HTTP", "scripts/", "Offline analysis scripts only"],
    ], widths=[1.35, 1.2, 1.5, 2.75])

    h(doc, 2, "23.2 Frontend dependencies")
    table(doc, ["Dependency", "Purpose", "Why it matters"], [
        ["react, react-dom", "UI framework", "The entire interface"],
        ["react-router-dom", "Client-side routing", "Page navigation and role gating"],
        ["typescript", "Type checking", "The only automated verification the frontend has,\ngiven there are no tests"],
        ["vite", "Build tool", "Produces the bundle Nginx and Capacitor serve"],
        ["leaflet, react-leaflet", "Maps", "Route and live tracking maps; no API key required"],
        ["recharts", "Charts", "Depot and admin dashboards"],
        ["framer-motion", "Animation", "Page and panel transitions"],
        ["qrcode.react", "QR generation", "Renders the e-ticket"],
        ["html5-qrcode", "QR scanning", "Camera access on the conductor device"],
        ["lucide-react", "Icons", "Consistent iconography"],
        ["react-hot-toast", "Notifications", "User feedback on every action"],
        ["tailwindcss", "Styling", "Utility classes alongside a hand-written stylesheet"],
        ["@capacitor/*", "Android packaging", "Wraps the built web app as an APK"],
        ["@vis.gl/react-google-maps", "UNUSED", "Declared but never imported. Dead weight - remove it"],
    ], widths=[1.6, 1.4, 3.8])

    h(doc, 2, "23.3 Dependency risks")
    bullets(doc, [
        ("Bundle size.", "The production JavaScript bundle is ~1.6 MB (468 KB gzipped), which Vite "
         "warns about. Leaflet, Recharts, framer-motion and two QR libraries all ship to every user. "
         "Route-level code splitting would help."),
        ("Heavy scientific stack for one baseline.", "numpy, scipy and scikit-learn are installed in "
         "production purely for a benchmark that runs at training time. They add significant image "
         "size for no runtime benefit."),
        ("No lockfile discipline on Python.", "requirements.txt pins some versions exactly and others "
         "with >=, so two installs can differ. A lockfile would make builds reproducible."),
    ])
    page_break(doc)


def section_24(doc):
    h(doc, 1, "24. Design Patterns & Architectural Patterns")
    para(doc, "Only patterns genuinely present are listed. A structure is not called a pattern merely "
              "because it superficially resembles one.")

    h(doc, 2, "24.1 Patterns confirmed in the code")
    table(doc, ["Pattern", "Where implemented", "Why it is useful here", "Complete?"], [
        ["Layered architecture", "api -> services -> db;\napi -> ml -> dataset", "Keeps HTTP concerns out of business logic\nand business logic out of computation.\nIt is what makes the engines testable\nwithout a database", "Complete and\nconsistently\nfollowed"],
        ["Dependency injection", "FastAPI Depends():\nget_current_user,\nrequire_role, get_db", "Authorisation is declared in the function\nsignature rather than written inside every\nendpoint, so it cannot be forgotten in the\nmiddle of a function body", "Complete"],
        ["Strategy", "tracking/base.py\nVehicleFeed protocol with\nfour adapters", "The vehicle source becomes a configuration\nchoice. The rest of the system depends on\nthe interface, not the implementation", "Complete"],
        ["Factory", "build_feed(kind, ...);\nrequire_role(*roles)", "build_feed constructs the right adapter from\na string. require_role is a dependency\nfactory - it returns a dependency function", "Complete"],
        ["Repository-ish\nservice layer", "app/services/*.py", "All database access is confined to one layer.\nNo endpoint issues a query directly", "Partial - there is\nno abstract\nrepository\ninterface"],
        ["Singleton (module-level)", "settings, metro_service,\nvehicle_store,\nblocking_plan_service,\ncrew_plan_service", "One shared instance holding expensive state.\nPython module-level objects give this without\na Singleton class", "Complete, via\nmodule scope\nrather than a\nclass"],
        ["Middleware / chain of\nresponsibility", "RateLimitMiddleware,\nCORSMiddleware", "Cross-cutting concerns applied uniformly to\nevery request without touching endpoints", "Complete"],
        ["REST", "82 HTTP endpoints", "Resource-shaped URLs, HTTP verbs, status\ncodes carrying meaning", "Mostly - some\nendpoints are\nRPC-shaped, e.g.\n/depot/deploy-bus"],
        ["Client-server", "React SPA plus JSON API", "The browser holds no business logic", "Complete"],
        ["Cache-aside", "BlockingPlanService,\nCrewPlanService,\nGtfsFeedService,\nRouteGeometryCache", "Expensive results computed once and reused.\nEach uses an asyncio.Lock with a re-check so\nconcurrent callers share one computation", "Complete"],
        ["Adapter", "HttpJsonFeed field map", "Translates a vendor's field names into the\nproject's own shape via configuration rather\nthan code", "Complete"],
    ], widths=[1.35, 1.55, 2.6, 1.3])

    h(doc, 2, "24.2 Patterns deliberately NOT used")
    bullets(doc, [
        ("No ORM / Active Record.", "Documents are built as plain dictionaries and validated by "
         "pydantic at the boundary."),
        ("No microservices.", "This is a modular monolith: one deployable backend with clear internal "
         "layers. For a project of this size that is the correct choice, and saying so confidently is "
         "better than pretending otherwise."),
        ("No event-driven architecture.", "No message queue, no pub/sub. The vehicle ingest loop is "
         "a polling loop, not an event stream."),
        ("No CQRS, no clean architecture ports and adapters.", "The layering is conventional and "
         "sufficient."),
    ])
    callout(doc, "If asked \"which pattern are you proudest of?\"",
            "The strategy pattern in the tracking layer, because it exists for a reason rather than "
            "for its own sake. Making the vehicle source an interface is what allowed is_live to become "
            "a property of the data instead of a property of the endpoint - and that single flag is "
            "what stops simulated positions being published as a real government feed.")
    page_break(doc)


def section_25(doc):
    h(doc, 1, "25. Algorithms & Core Logic")
    para(doc, "Five algorithms in this project are substantial enough to explain and defend. "
              "Complexity is given only where it is meaningful.")

    h(doc, 2, "25.1 Ordered stop-pair indexing and journey search")
    table(doc, ["Aspect", "Detail"], [
        ["Problem", "Given two stop names, find buses that travel from A toward B - direction\nmatters, so a bus passing both stops in the wrong order is not an answer"],
        ["Approach", "Precompute an inverted index at startup: for every route, for every ordered\npair of stops (i, j) with i < j, record (route_index, i, j)"],
        ["Scale", "655,438 ordered pairs over 3,946,744 route segments"],
        ["Query", "Direct routes: one dictionary lookup on (A, B). Transfers: intersect the\nroutes serving A with the routes serving B through a shared interchange stop"],
        ["Build cost", "O(sum over routes of n^2) where n is stops per route (mean 30, max 95)"],
        ["Query cost", "O(1) for the direct lookup, plus candidate scoring; measured median 0.94 s\nand p90 1.52 s end to end, which includes scoring and enrichment"],
        ["Trade-off", "Memory for speed. Building the index costs seconds once; without it every\nquery would scan all 6,737 routes"],
    ], widths=[1.15, 5.65])

    h(doc, 2, "25.2 Two-pass anchored stop resolution")
    para(doc, "Problem: Bengaluru reuses stop names. Several distinct places are called Kodihalli, "
              "several are called Hosahalli, often tens of kilometres apart. Resolving each name "
              "independently produces a route that teleports across the city.")
    code(doc,
         "  Pass 1  resolve every name with NO anchor\n"
         "          take the MEDIAN latitude and longitude as this route's centre\n"
         "          (median, not mean, so one 28 km outlier cannot drag the centre)\n"
         "\n"
         "  Pass 2  previous <- centre\n"
         "          for each stop in order:\n"
         "              record <- resolve(stop, near=previous)     pick the nearest instance\n"
         "              if record: previous <- record.point\n"
         "\n"
         "  Complexity: O(n) resolutions, each an O(1) dictionary hit or a fuzzy search\n"
         "  Measured effect: route 335-G went from a drawn 69.4 km to 15.0 km for a\n"
         "                   19.2 km stated journey (straight-line vs a 1.28 road factor)",
         caption="Figure 25.1 - The anchoring algorithm.")

    h(doc, 2, "25.3 Greedy vehicle blocking with a provable lower bound")
    table(doc, ["Aspect", "Detail"], [
        ["Problem", "Given a timetable of trips, find the minimum number of buses that can operate\nit - the peak vehicle requirement, which is what actually sizes a fleet"],
        ["Algorithm", "Process trips in departure order. A bus already standing at this trip's origin\nterminal, free for at least the layover, takes the trip; otherwise a new bus\npulls out. Among eligible buses the one waiting LONGEST is chosen, so\nterminals turn over instead of one bus absorbing every trip"],
        ["Lower bound", "concurrency_lower_bound() sweeps departure and arrival events to find the\nmaximum number of trips simultaneously in progress. No scheduling cleverness\ncan operate two overlapping trips with one bus, so this is a hard floor"],
        ["Optimality", "With no idle cap the greedy result equals the maximum-overlap bound, so it is\nprovably optimal for a single route. The output states whether it matched the\nbound, rather than merely claiming to be minimal"],
        ["Complexity", "O(T log T) for the sweep; the chaining is O(T x terminals) in the worst case"],
        ["Result", "6,849 buses interlined across 44 depots"],
    ], widths=[1.15, 5.65])

    h(doc, 2, "25.4 Crew duty scheduling - dynamic programming plus bounded greedy pairing")
    para(doc, "Stage 1 - cutting. For each vehicle block, a dynamic program finds the fewest legal "
              "pieces of crew work. best[i] is the fewest pieces covering trips[i:]; a cut is legal "
              "only at a relief point with a sufficient turnaround gap, and each piece must satisfy "
              "both the working-time and continuous-driving limits. O(n^2) per block, with n at most "
              "16 in this dataset.")
    para(doc, "Stage 2 - pairing. Pieces are combined into split duties. This was the performance "
              "problem: a twelve-hour spreadover window covers most of the day's 21,453 pieces, so an "
              "unbounded scan is quadratic and took 36 seconds. Two changes fixed it - binary search "
              "to restrict candidates to the spreadover window, and a path-compressed next_free array "
              "so already-paired pieces are skipped in O(1) rather than re-examined by every later "
              "piece. Result: 1.6 seconds, and slightly FEWER duties than the slow version produced.")
    table(doc, ["Measure", "Value"], [
        ["Vehicle blocks in", "6,849"],
        ["Duty pieces produced", "21,453"],
        ["Daily duties required", "15,636"],
        ["Hard lower bound", "7,003 (peak simultaneous pieces)"],
        ["Crew-to-bus ratio", "2.28 - real transport undertakings run roughly 2.0 to 2.5"],
        ["Split duties", "37.2%"],
        ["Unstaffable blocks", "15, reported by name rather than silently dropped"],
    ], widths=[2.0, 4.8])

    h(doc, 2, "25.5 Polyline projection and route-following ETA")
    code(doc,
         "  project_onto_polyline(point, polyline, cumulative_km):\n"
         "      for each segment (start, end):\n"
         "          t <- clamp(dot(point - start, end - start) / |end - start|^2, 0, 1)\n"
         "          nearest <- start + t * (end - start)\n"
         "          keep the segment with the smallest haversine(point, nearest)\n"
         "      return distance_along_route, offset_from_line\n"
         "\n"
         "  Complexity: O(segments) - tens of points per route, so an exhaustive scan is\n"
         "  cheaper than the bookkeeping needed to avoid one. A local search would also fail\n"
         "  on routes that double back on themselves.\n"
         "\n"
         "  offset_from_line is the useful by-product: a vehicle more than 1.5 km from the\n"
         "  line is not running that route, so the projection is reported as unreliable\n"
         "  rather than as a confident position on a line the bus is nowhere near.",
         caption="Figure 25.2 - Projection, used for both ETA and schedule adherence.")
    para(doc, "The ETA then sums the REMAINING distance along the route to the target stop and divides "
              "by a blended speed, adding dwell time per intervening stop. The confidence label is "
              "derived from which speed source was available, not guessed - and the returned range "
              "widens as confidence falls, because a low-confidence estimate quoting a two-minute "
              "window is worse than no estimate at all.")

    h(doc, 2, "25.6 The interchange walkability check")
    para(doc, "A small algorithm with an outsized correctness impact. For each consecutive pair of legs "
              "in a candidate journey, resolve the arrival stop and the departure stop within their own "
              "route geometry and compare them with a haversine distance. If they are more than 1.2 km "
              "apart, the whole candidate is rejected.")
    para(doc, "Two ordering constraints make it correct and affordable, and both are worth quoting: it "
              "must run BEFORE re-anchoring (which would force the two stops onto one point, making the "
              "test always pass) and BEFORE leg construction (which costs a full distance walk for a "
              "candidate about to be thrown away). A per-route coordinate cache turned one query from "
              "7.45 s back down to 1.17 s.")
    page_break(doc)
