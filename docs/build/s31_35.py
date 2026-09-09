# -*- coding: utf-8 -*-
"""Sections 31-35: Glossary, study sheet, whiteboard, debugging, modification."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_31(doc):
    h(doc, 1, "31. Beginner Glossary")
    para(doc, "Alphabetical. Each term gives a simple definition, what it means specifically in DBARS, "
              "and where to look.")
    table(doc, ["Term", "Simple definition", "In this project"], [
        ["Adapter", "A wrapper that makes one thing look\nlike another", "Four vehicle feed adapters all satisfy the\nVehicleFeed interface"],
        ["API", "A set of URLs a program can call to\nask another program for something", "82 endpoints; the React app calls them and\nrenders the JSON that comes back"],
        ["Async / await", "Letting a program do other work while\nwaiting for a slow operation", "FastAPI serves many users on one thread;\nawait frees it during database calls"],
        ["Authentication", "Proving who you are", "Email and password, exchanged for a signed\ntoken"],
        ["Authorization", "Deciding what you may do", "require_role() compares your role claim with\nwhat the endpoint allows"],
        ["Backend", "The server-side program", "Python, FastAPI, in backend/"],
        ["Bearer token", "A credential sent in a header that\nproves who you are", "Authorization: Bearer <token> on every\nprotected request"],
        ["Blocking (transit)", "Assigning trips to physical buses", "ml/blocking.py - answers how few buses can\nrun the timetable"],
        ["Class", "A template bundling data with the\noperations on that data", "BMTCBusPredictor holds the indexes and the\nmethods that search them"],
        ["Collection", "A named group of documents in\nMongoDB, like a table", "17 of them: users, votes, waybills, tickets"],
        ["Component", "A reusable piece of user interface", "RouteMap, CrewPanel, BlockingPanel"],
        ["CORS", "Browser rule about which sites may\ncall an API", "CORS_ORIGINS lists allowed origins"],
        ["CI", "Automation that tests every code\nchange", "GitHub Actions runs pytest and the frontend\nbuild on every push"],
        ["Dead kilometres", "Distance a bus runs with no\npassengers aboard", "Depot to first stop, and last stop back to\nthe depot"],
        ["Dependency injection", "The framework supplies what a\nfunction needs, rather than the\nfunction fetching it", "Depends(get_current_user) puts the user in\nthe function signature"],
        ["Docker", "Packaging an app with everything it\nneeds so it runs anywhere", "Three containers: backend, frontend, mongo"],
        ["Document", "One JSON-like record in MongoDB", "One user, one ticket, one waybill"],
        ["Duty (transit)", "One crew member's working day", "Distinct from a block, which is one bus's day"],
        ["Endpoint", "One specific URL the API answers", "POST /predict, GET /gtfs/static.zip"],
        ["Environment variable", "A setting supplied from outside the\ncode", "JWT_SECRET_KEY, TRACKING_FEED, MONGO_URI"],
        ["Framework", "A skeleton that provides structure\nso you write only your logic", "FastAPI on the backend, React on the frontend"],
        ["Fuzzy matching", "Finding the closest text match when\nthere is no exact one", "Matches a typed stop name to a real one"],
        ["GTFS", "The worldwide standard format for\npublishing transit timetables", "The export at /gtfs/static.zip that any\njourney planner can read"],
        ["GTFS-Realtime", "The live companion to GTFS, sent as\nprotobuf", "Service alerts are published; vehicles are\nrefused while simulated"],
        ["Hashing", "One-way scrambling that cannot be\nreversed", "Passwords are stored hashed, never in plain\ntext"],
        ["HMAC", "A signature proving a message was\nnot altered, using a shared secret", "Signs every token; verified with a\nconstant-time compare"],
        ["HTTP", "The language browsers and servers\nspeak", "GET reads, POST creates, status codes carry\nmeaning"],
        ["Idempotent", "Doing it twice has the same effect\nas doing it once", "Replaying an offline ticket batch cannot\ndouble-count revenue"],
        ["Index (database)", "A lookup structure that makes\nsearching fast", "email is unique; (waybill_id, uuid) enforces\nidempotency"],
        ["Interlining", "Letting one bus serve trips from\ndifferent route numbers", "Reduces the fleet from the per-route baseline"],
        ["JSON", "A text format for structured data", "Every request and response body"],
        ["JWT", "A signed token carrying claims,\nreadable by anyone but tamper-proof", "Hand-implemented in auth/auth.py; three\nseparate signing domains"],
        ["localStorage", "Browser storage that survives a\nrefresh", "Holds tokens, and the conductor offline\nticket queue"],
        ["Middleware", "Code that sees every request before\nit reaches an endpoint", "CORS and rate limiting"],
        ["MongoDB", "A database that stores JSON-like\ndocuments instead of table rows", "Accounts, votes, tickets, waybills"],
        ["ORM", "A library that maps objects to\ndatabase rows", "NOT used here - documents are built as plain\ndictionaries"],
        ["Pydantic", "A library that validates data\nagainst a declared shape", "Rejects malformed request bodies with 422"],
        ["Polyline", "A line made of connected points", "The drawn route; buses are projected onto it\nfor ETAs"],
        ["Protobuf", "A compact binary data format", "Used by GTFS-Realtime feeds"],
        ["REST", "A style of API using resource URLs\nand HTTP verbs", "The overall API design"],
        ["Router", "A group of related endpoints", "Fourteen routers registered in create_app()"],
        ["Salt", "Random data added before hashing so\nidentical passwords differ", "16 random bytes per user"],
        ["Service layer", "Where business rules live", "app/services - the only layer touching\nMongoDB"],
        ["SPA", "A web app that swaps pages without\nreloading", "React Router does this in App.tsx"],
        ["State (React)", "Data a component remembers between\nrenders", "useState for search results and form fields"],
        ["TTL index", "A database rule that deletes\ndocuments after a set time", "trip_shares vanish after 6 hours"],
        ["TF-IDF", "A way of scoring how relevant a\ndocument is to a query", "One of the four benchmark rankers"],
        ["Token type", "A claim saying what a token is for", "access, refresh, qr_ticket, travel_pass"],
        ["TypeScript", "JavaScript with type checking", "The whole frontend; the only automated\nverification it has"],
        ["Uvicorn", "The program that actually runs a\nPython async web app", "Serves FastAPI on port 8000"],
        ["Waybill", "A conductor's daily record of bus,\nroute, tickets and cash", "Modelled fully in this project"],
    ], widths=[1.35, 2.35, 3.1])
    page_break(doc)


def section_32(doc):
    h(doc, 1, "32. What I Must Memorise")
    para(doc, "Study time is limited. This is what deserves it, in priority order.")

    h(doc, 2, "32.1 MUST KNOW - you cannot defend the project without these")
    table(doc, ["#", "Item", "The answer in one line"], [
        ["1", "What the project is", "Three products from one timetable: journey planner, operations\nplanner, open data feed"],
        ["2", "The four layers", "API -> service -> database; API -> engine -> dataset files"],
        ["3", "The key architectural\ndecision", "Engines read files, not the database, so core features survive a\ndatabase outage - and train() runs before init_db()"],
        ["4", "Entry point", "backend/app/main.py: create_app() then lifespan()"],
        ["5", "The startup order", "Verify files, train, warm blocking and GTFS, start ingest, init DB"],
        ["6", "How the search works", "Ordered stop-pair index, 655,438 pairs, direct plus one transfer"],
        ["7", "The dataset numbers", "6,737 route-directions, 3,940 buses, 4,883 stops"],
        ["8", "Block versus duty", "A block is a bus's day; a duty is a person's day"],
        ["9", "The headline\noperations figures", "6,849 buses, 44 depots, 15,636 duties, 2.28 crew per bus"],
        ["10", "The two fare fields", "fare_value_inr is what the state reimburses; fare_collected_inr is\nwhat the passenger paid"],
        ["11", "Where the AI is,\nand is not", "The bus predictor: none, classical IR and graph search. The AI\nlayer (S40): real retrieval, but only 1.8% of answers reach an LLM"],
        ["12", "What is simulated", "Vehicle positions, payment, Shakti eligibility verification"],
        ["13", "The hardest bug", "Unanchored stop resolution, and the name-matched transfer bug beneath it"],
        ["14", "Auth in one sentence", "PBKDF2 hashed passwords, HMAC-signed tokens, three signing domains,\nrole checks by dependency"],
        ["15", "The weakest part", "No frontend tests; POST /train unauthenticated; no token revocation"],
    ], widths=[0.3, 1.6, 4.9])

    h(doc, 2, "32.2 SHOULD KNOW - expected in a technical discussion")
    bullets(doc, [
        ("The interchange rule.", "Transfers rejected beyond 1.2 km, and why - two Avalahallis 28.6 km apart."),
        ("Anchored resolution.", "Two passes, median centre, each stop resolved relative to the previous."),
        ("Idempotent sync.", "Client UUID plus a unique index; per-item response; server-side totals."),
        ("The honesty gate.", "is_live on the data; 503 on the GTFS-RT vehicle endpoint; the 120 s staleness rule."),
        ("Parameter objects.", "BlockingParameters and CrewParameters echoed into every response."),
        ("The benchmark result.", "Four rankers; the shipped one scores lower on a proxy metric but measures the real output."),
        ("GTFS exclusions.", "325 depot runs and 55 outstation services, and why each would corrupt a journey planner."),
        ("Why asyncio.to_thread.", "One second of blocking CPU would stall the event loop for everyone."),
        ("The caching pattern.", "asyncio.Lock with a re-check inside, so concurrent callers share one computation."),
        ("Testing philosophy.", "Invariants and plausibility ranges, not fixed expected values."),
    ])

    h(doc, 2, "32.3 NICE TO KNOW - detail that adds credibility if it comes up")
    bullets(doc, [
        ("The crew pairing optimisation.", "36 s to 1.6 s via a windowed search and a path-compressed skip list."),
        ("Why the median, not the mean.", "One outlier 28 km away would drag a mean."),
        ("The token type bug.", "A ticket token once authenticated as a session because two files spelled the type differently."),
        ("The CORS ordering.", "Rate limiting added first so CORS wraps it, keeping 429 responses readable."),
        ("The TTL indexes.", "trip_shares expire after 6 hours; audit_events deliberately have none."),
        ("Streaming the GTFS zip.", "1.46 million rows would cost over a gigabyte if buffered."),
        ("RouteRecord.__post_init__.", "Precomputes derived fields; profiling found 512,956 redundant calls costing 7 seconds."),
        ("The four fraud heuristics.", "Repeat pair, velocity, IP spraying, destination spread."),
    ])

    h(doc, 2, "32.4 Numbers worth memorising")
    table(doc, ["Figure", "Value"], [
        ["Route-directions / buses / stops", "6,737 / 3,940 / 4,883"],
        ["Indexed ordered stop pairs", "655,438 (over 3,946,744 route segments)"],
        ["Search latency", "median 0.94 s, p90 1.52 s"],
        ["GTFS feed", "3,713 routes, 47,295 trips, 1,459,066 stop_times, ~14.4 MB, ~11 s"],
        ["Fleet", "6,849 buses across 44 depots"],
        ["Crew", "21,453 pieces, 15,636 duties, ratio 2.28, 37.2% split"],
        ["Endpoints / tests", "82 / 161"],
        ["Code size", "~13,562 lines backend, ~8,459 frontend, 2,440 tests"],
    ], widths=[2.4, 4.4])
    page_break(doc)


def section_33(doc):
    h(doc, 1, "33. What I Should Be Able To Draw On A Whiteboard")
    para(doc, "Seven diagrams, each simple enough to reproduce from memory in under two minutes. "
              "Practise drawing them; a diagram drawn while you talk is worth more than a paragraph.")

    h(doc, 2, "33.1 High-level architecture")
    code(doc,
         "   [Browser / Android]\n"
         "           |  JSON over HTTPS\n"
         "           v\n"
         "   +-------------------+\n"
         "   |    API layer      |   app/api/\n"
         "   +-------------------+\n"
         "           |\n"
         "     +-----+------+\n"
         "     |            |\n"
         "     v            v\n"
         "  [Services]   [Engines]        <-- engines never touch the DB\n"
         "     |            |\n"
         "     v            v\n"
         "  [MongoDB]   [dataset/*.csv]\n"
         "                  |\n"
         "                  v\n"
         "            [GTFS export] --> external journey planners")

    h(doc, 2, "33.2 Request flow")
    code(doc,
         "  User -> apiFetch -> CORS -> RateLimit -> Router -> Pydantic\n"
         "                                                       |\n"
         "                                                  Auth depends\n"
         "                                                       |\n"
         "                                                    Endpoint\n"
         "                                                       |\n"
         "                                              Service or Engine\n"
         "                                                       |\n"
         "                                              Mongo or dataset\n"
         "                                                       |\n"
         "                                              JSON -> setState -> UI")

    h(doc, 2, "33.3 Journey search")
    code(doc,
         "  \"Majestic\" + \"Marathahalli\"\n"
         "         |\n"
         "   resolve names (alias + fuzzy, with a confidence score)\n"
         "         |\n"
         "   stop_pair_to_segments[(A,B)]  --> direct route found?\n"
         "         |  no\n"
         "   routes(A) x routes(B) via a shared interchange stop\n"
         "         |\n"
         "   reject transfers > 1.2 km apart\n"
         "         |\n"
         "   score, rank, deduplicate\n"
         "         |\n"
         "   best_match + alternatives + coordinates")

    h(doc, 2, "33.4 Database structure")
    code(doc,
         "  users ----< votes\n"
         "    |\n"
         "    +-------< tickets ----- transactions\n"
         "    |\n"
         "    +-------< trip_shares      (TTL 6 h)\n"
         "    |\n"
         "    +-------< favorites\n"
         "\n"
         "  waybills ----< conductor_tickets      unique(waybill_id, client_uuid)\n"
         "\n"
         "  travel_passes    service_alerts    crowd_reports\n"
         "  audit_events (no TTL)    usage_events (TTL 90 d)\n"
         "\n"
         "  ----<  means 'referenced by user_id / waybill_id'.\n"
         "         There are NO foreign keys - MongoDB does not enforce them.")

    h(doc, 2, "33.5 Authentication flow")
    code(doc,
         "  Register --> PBKDF2 hash + salt --> users\n"
         "                                        |\n"
         "  Login ----> verify -----------------> access token (24 h)\n"
         "                                        refresh token (7 d)\n"
         "                                        |\n"
         "  Request --> Bearer header --> verify HMAC + exp + type\n"
         "                                        |\n"
         "                              require_role(...) --> 403 or proceed\n"
         "\n"
         "  Three keys:  SECRET_KEY | TICKET_SECRET_KEY | PASS_SECRET_KEY")

    h(doc, 2, "33.6 Operations pipeline (blocking to crew)")
    code(doc,
         "  routes_cleaned.csv\n"
         "         |\n"
         "   build_trips()          every scheduled trip, with times and terminals\n"
         "         |\n"
         "   chain_blocks()         greedy: reuse a bus standing at this terminal\n"
         "         |                otherwise a new bus pulls out\n"
         "         +--> concurrency_lower_bound()   hard floor - provably minimal?\n"
         "         |\n"
         "   apply_dead_km()        depot -> first stop, last stop -> depot\n"
         "         |\n"
         "   BLOCKS  (6,849 buses)\n"
         "         |\n"
         "   cut_block_into_pieces()      DP: fewest legal pieces per block\n"
         "         |\n"
         "   combine_pieces_into_duties() greedy pairing into split duties\n"
         "         |\n"
         "   DUTIES  (15,636, ratio 2.28)")

    h(doc, 2, "33.7 The vehicle data honesty gate")
    code(doc,
         "  TRACKING_FEED = simulated | gtfs_rt | http_json | push\n"
         "         |\n"
         "   build_feed() --> adapter (each declares is_live)\n"
         "         |\n"
         "   poll loop every 10 s --> VehicleStateStore\n"
         "         |                        |\n"
         "         |                  stale > 120 s --> WITHHELD\n"
         "         v\n"
         "   /tracking/buses          carries is_live on every payload\n"
         "   /tracking/source         reports the adapter, not a stored label\n"
         "   /gtfs-rt/vehicle-positions.pb\n"
         "         |\n"
         "         +-- is_live == False --> HTTP 503, with the reason")
    page_break(doc)


def section_34(doc):
    h(doc, 1, "34. Debugging Guide")
    para(doc, "For each workflow: what to check, in what order, and what the likely causes are. This "
              "is written so you could actually diagnose the system, not just describe it.")

    h(doc, 2, "34.1 First moves, whatever the symptom")
    table(doc, ["Check", "Command / URL", "Tells you"], [
        ["Is the app alive and trained?", "GET /health", "Predictor state and route count. A route count of\n0 means the dataset did not load"],
        ["Is the database connected?", "Server log at startup", "\"MongoDB initialized\" or the degradation warning"],
        ["What is powering the map?", "GET /tracking/source", "Active adapter, is_live, last poll time, error,\nfresh and stale vehicle counts"],
        ["Is the GTFS feed built?", "GET /gtfs/feed-info", "Build report, counts, what was excluded"],
        ["Are the model metrics sane?", "GET /metrics", "Dataset profile and benchmark results"],
        ["Run the tests", "cd backend && pytest tests -q", "161 tests; a failure usually localises the\nproblem immediately"],
    ], widths=[1.5, 1.9, 3.4])

    h(doc, 2, "34.2 Journey search returns nothing or the wrong bus")
    numbered(doc, [
        "Check the resolved stop names in the response - the API returns what it thought you meant. Most \"wrong bus\" reports are actually a stop-name resolution problem.",
        "Look at the confidence score. Below about 0.55 the match is a guess.",
        "Open backend/app/ml/predictor.py -> _resolve_stop_name() and check whether an alias is missing from normalize_text in ml/text.py.",
        "If the stops resolve correctly but no route is found, check _find_transfer_suggestions() - it may be rejecting every candidate. Set a breakpoint before _interchange_is_walkable() and count how many candidates it discards.",
        "If a transfer looks impossible, that is the interchange rule working, not failing.",
        "Root causes seen before: a missing alias; a name that exists twice in the city; a shortlist filtered to empty; a stop present in routes_cleaned.csv but absent from stops_cleaned.csv.",
    ])

    h(doc, 2, "34.3 The route map draws straight lines across the city")
    numbered(doc, [
        "This is the anchoring bug. Compare the drawn length with the stated distance - drawn should be roughly 78% of stated, because the drawing is straight-line and the stated distance carries a 1.28 road factor.",
        "If drawn is much LARGER than stated, a stop resolved to the wrong same-named place.",
        "Check that the coordinate builder is calling resolve_stop_sequence() from ml/route_geometry.py and not resolve_coordinate() directly per stop.",
        "Run pytest tests/test_route_geometry.py - it asserts no consecutive hop exceeds 5 km across ten real journeys.",
        "If the spike is exactly at a leg boundary, the problem is the transfer, not the drawing - check _interchange_is_walkable().",
    ])

    h(doc, 2, "34.4 The full-screen map collapses or will not zoom")
    numbered(doc, [
        "Check for a CSS containing block. Any ancestor with transform, filter, backdrop-filter, perspective or contain makes position:fixed resolve against THAT element instead of the viewport. .bento-card sets backdrop-filter, which caused exactly this.",
        "The fix in place is a React portal to document.body - confirm the expanded map is still being portaled.",
        "If it renders but will not zoom: MapContainer props such as scrollWheelZoom and zoomControl are read ONCE at construction. Later changes are ignored, so zoom must be toggled imperatively on the map instance.",
        "If it snaps back when you zoom: something is re-running fitBounds. Check that the bounds array is memoised - an array rebuilt every render changes identity and re-triggers the effect.",
        "After any container size change, Leaflet needs invalidateSize() or it keeps drawing at its old dimensions.",
    ])

    h(doc, 2, "34.5 Conductor tickets are missing or double-counted")
    numbered(doc, [
        "Check the device first: the unsynced badge on /duty shows how many sales are still queued in localStorage.",
        "Inspect the sync response - it is per-item. A ticket in \"rejected\" carries the reason.",
        "The most common rejection is a CLOSED waybill: a late offline arrival after sign-off. That is correct behaviour, and it is why sign-off refuses to proceed while items are unsynced.",
        "If revenue looks doubled, verify the unique index exists: db.conductor_tickets.getIndexes() should show (waybill_id, client_ticket_uuid) as unique. Without it, replays insert duplicates.",
        "If totals disagree with the tickets, remember they are recomputed by recompute_totals() from the ticket rows - so the tickets are the source of truth, not the stored totals.",
    ])

    h(doc, 2, "34.6 The vehicle map is empty or frozen")
    numbered(doc, [
        "GET /tracking/source - look at last_poll_at, last_poll_age_seconds, consecutive_failures and last_error.",
        "If vehicles_stale is high and vehicles_fresh is zero, the feed has stalled and the staleness rule is correctly withholding ghosts.",
        "If consecutive_failures is climbing, the adapter is failing - check TRACKING_FEED_URL and the recorded error. The loop backs off exponentially to 300 s, so recovery may take a few minutes.",
        "If the feed is 'push', nothing arrives unless AVL_INGEST_KEY is set and the sender supplies X-AVL-Key.",
        "An empty map with the simulator usually means the predictor has no routes with resolvable coordinates - check /health.",
    ])

    h(doc, 2, "34.7 Authentication problems")
    table(doc, ["Symptom", "Likely cause"], [
        ["Everyone logged out after a restart", "JWT_SECRET_KEY is unset, so a new random key was generated.\nCheck the startup warning."],
        ["401 on every request", "Missing or malformed Authorization header, or an expired token"],
        ["401 with \"Not a ticket token\"", "A token of the wrong type was used - the type check is working"],
        ["403 rather than 401", "Authenticated but the role is wrong; check the role claim"],
        ["Login works, /auth/me fails", "MongoDB is unavailable - login can succeed from the token path\nwhile the profile lookup needs the database"],
    ], widths=[2.3, 4.5])

    h(doc, 2, "34.8 The depot dashboard is slow or empty")
    numbered(doc, [
        "The first request after startup may wait for the ~25 s blocking computation if the background warm-up has not finished. Check the log for \"Blocking plan ready\".",
        "The crew plan builds on the blocking context, so it is slow only on the first call, then cached.",
        "If dispatch recommendations are empty, that is honest output - it means no votes exist in the window, and the response says so in a note.",
        "If the whole panel is empty, check the role: these endpoints require depot_manager or admin.",
    ])
    page_break(doc)


def section_35(doc):
    h(doc, 1, "35. Modification Guide")
    para(doc, "How to make common changes, following the project's existing architecture. Each recipe "
              "lists the files to touch in order.")

    h(doc, 2, "35.1 Add a new API endpoint")
    numbered(doc, [
        "Decide the layer. HTTP handling goes in app/api/, business rules in app/services/, pure computation in app/ml/.",
        "Define the request and response shapes in app/models/schemas.py as pydantic models, with field constraints.",
        "Write the business logic as a function in the appropriate service module. Keep it independent of FastAPI so it can be unit-tested.",
        "Add the endpoint in the relevant router with a decorator, and add Depends(require_role(...)) if it is privileged.",
        "If the work is CPU-heavy, wrap it in asyncio.to_thread.",
        "Register the router in main.py create_app() only if it is a new router.",
        "Add a test in backend/tests/ - test the service function directly rather than through HTTP where possible.",
        "Add the TypeScript type in frontend/src/types/api.ts and call it through apiFetch.",
    ])

    h(doc, 2, "35.2 Add a new database field")
    numbered(doc, [
        "MongoDB needs no migration, but existing documents will not have the field - so plan for both shapes.",
        "Add it to the pydantic response model as Optional with a default. A required field would break every historical document, which is exactly why every Shakti field on TicketResponse is optional.",
        "Write it in the service function that creates the document.",
        "Add an index in db/database.py init_db() if you will query or sort by it.",
        "Update the frontend type and handle the undefined case in the UI.",
    ])
    callout(doc, "The trap to avoid",
            "Do not add a required field to a response model for a collection that already has "
            "documents. Every read of an old document will raise a validation error, and the failure "
            "appears in an unrelated endpoint - typically a history listing - which makes it slow to "
            "diagnose.", warn=True)

    h(doc, 2, "35.3 Add a new user role")
    numbered(doc, [
        "Add the member to UserRole in auth/auth.py.",
        "Add it to the User type union in frontend/src/contexts/AuthContext.tsx.",
        "Gate endpoints with require_role(UserRole.YOUR_ROLE, ...).",
        "Add a ProtectedRoute with a roles array in App.tsx, and a page under frontend/src/pages/.",
        "Decide how the role is assigned - public registration forces commuter, so it must come from admin user creation.",
    ])
    para(doc, "The driver role is a worked example of steps 1 and 2 only; steps 3 to 5 were never done, "
              "which is why it has no interface.")

    h(doc, 2, "35.4 Change a modelling assumption")
    para(doc, "For example, replacing the assumed 16 km/h average running speed with a real BMTC "
              "figure:")
    numbered(doc, [
        "Change the default in BlockingParameters in ml/blocking.py, and in GtfsParameters in gtfs/builder.py - both carry the same physical assumption and must stay in step.",
        "Nothing else needs to change: the value flows into running_time_minutes(), the GTFS stop_times model, and every response that echoes assumptions.",
        "Rerun pytest tests/test_blocking.py - the plausibility ranges will tell you if the new value produces an implausible fleet.",
        "Rebuild the GTFS feed with POST /gtfs/rebuild so published times reflect the new speed.",
    ])

    h(doc, 2, "35.5 Add a new vehicle feed adapter")
    numbered(doc, [
        "Create a class in tracking/adapters.py with name, is_live, and async start / stop / poll methods - this satisfies the VehicleFeed protocol without inheriting from anything.",
        "Convert the upstream format into VehicleObservation objects. Set recorded_at from the SOURCE timestamp, never from now(), or staleness detection breaks.",
        "Set is_live truthfully. This single flag gates the GTFS-Realtime vehicle endpoint.",
        "Register the name in build_feed().",
        "Add a test in tests/test_avl.py that feeds a recorded fixture through it.",
    ])

    h(doc, 2, "35.6 Add a new language")
    numbered(doc, [
        "Copy frontend/src/i18n/en.json to the new locale code and translate the values.",
        "Import it in LanguageContext.tsx and add it to the translations map and LANGUAGE_LABELS.",
        "Nothing else changes - t() already falls back to English for any missing key, so a partial translation is safe to ship.",
    ])

    h(doc, 2, "35.7 Add validation to an existing endpoint")
    para(doc, "Prefer declarative validation in the pydantic model over imperative checks in the "
              "endpoint - Field(min_length=..., ge=..., pattern=...) rejects bad input before your "
              "code runs, and the error message is generated for you. Use a field_validator for rules "
              "that span fields, as PassengerCount does to reject duplicate passenger types.")

    h(doc, 2, "35.8 Add a frontend test suite (the highest-value change available)")
    numbered(doc, [
        "Install vitest and @testing-library/react as dev dependencies and add a \"test\" script.",
        "Start with lib/offlineQueue.ts - it is pure logic, it handles money, and it has no React dependency. Test that flush() clears only acknowledged items and that a corrupt queue returns empty rather than throwing.",
        "Then test lib/apiClient.ts error conversion.",
        "Then component tests for RouteMap leg rendering and the Shakti display in Tickets.tsx.",
        "Add the test step to .github/workflows/ci.yml so it runs on every push.",
    ])
    page_break(doc)
