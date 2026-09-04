# -*- coding: utf-8 -*-
"""Sections 4-5: Complete System Data Flow, User Journey."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_4(doc):
    h(doc, 1, "4. Complete System Data Flow")
    para(doc, "This section traces what actually happens for each major action a user can perform. "
              "Only flows that exist in the code are included. Each flow names the real file and "
              "function at every step, so you can open the source and follow along.")

    h(doc, 2, "4.1 The generic request lifecycle")
    code(doc,
         "  User action in the browser\n"
         "        |\n"
         "  React event handler  (e.g. handleSubmit in PredictPage.tsx)\n"
         "        |\n"
         "  apiFetch()           (lib/apiClient.ts - prefixes the base URL, converts network errors)\n"
         "        |\n"
         "  HTTP request over the network\n"
         "        |\n"
         "  CORSMiddleware       (outermost - allows the browser origin)\n"
         "        |\n"
         "  RateLimitMiddleware  (per-IP sliding window, 120 requests/minute)\n"
         "        |\n"
         "  FastAPI router       (matches the path to a function)\n"
         "        |\n"
         "  Pydantic validation  (rejects a malformed body with 422 before any logic runs)\n"
         "        |\n"
         "  Depends(get_current_user) / Depends(require_role(...))   [protected endpoints only]\n"
         "        |\n"
         "  Endpoint function    (app/api/*.py)\n"
         "        |\n"
         "  Service or engine    (app/services/*.py or app/ml/*.py)\n"
         "        |\n"
         "  MongoDB or dataset files\n"
         "        |\n"
         "  Return value -> JSON serialisation -> HTTP response\n"
         "        |\n"
         "  React setState -> re-render -> user sees the result",
         caption="Figure 4.1 - The path every request takes. Middleware order is set in create_app().")
    evidence(doc, "backend/app/main.py -> create_app(); frontend/src/lib/apiClient.ts")

    h(doc, 2, "4.2 Flow A - Registration")
    code(doc,
         "  User fills the form on /register  (name, email, password, gender, language)\n"
         "        |\n"
         "  AuthContext.register()  strips gender when it is the empty string, so the server\n"
         "                          receives an absent field rather than an invalid enum value\n"
         "        |\n"
         "  POST /auth/register     body validated by RegisterRequest (pydantic)\n"
         "        |\n"
         "  register()              auth/routes.py\n"
         "        |-- db.users.find_one({email})      -> 400 if the email already exists\n"
         "        |-- hash_password(password)         -> PBKDF2-SHA256, random 16-byte salt\n"
         "        |-- db.users.insert_one({...role: 'commuter' forced...})\n"
         "        |-- create_access_token(...)        -> 24 hour token\n"
         "        |-- create_refresh_token(...)       -> 7 day token\n"
         "        v\n"
         "  Response { access_token, refresh_token, user }\n"
         "        |\n"
         "  Browser stores both tokens in localStorage; setUser() re-renders; redirect /dashboard",
         caption="Figure 4.2 - Registration. Note the role is forced to commuter server-side.")
    callout(doc, "Why the role is forced",
            "RegisterRequest deliberately has no role field, and register() hard-codes "
            "role = 'commuter'. If the role came from the request body, anyone could register "
            "themselves as an admin. Privilege must never be self-assigned by the client. "
            "CONFIRMED: auth/routes.py, comment \"role intentionally absent\".")

    h(doc, 2, "4.3 Flow B - Login")
    code(doc,
         "  POST /auth/login { email, password }\n"
         "        |-- db.users.find_one({email})       -> 401 if missing\n"
         "        |-- verify_password(plain, stored)   -> constant-time compare of PBKDF2 output\n"
         "        |-- is_active check                  -> 403 if the account was disabled\n"
         "        v\n"
         "  access_token + refresh_token + user profile  (including shakti_eligible)",
         caption="Figure 4.3 - Login.")

    h(doc, 2, "4.4 Flow C - Journey search (the core feature)")
    para(doc, "This is the flow to know best. It is the feature the project is named after and the "
              "one an examiner is most likely to probe.")
    code(doc,
         "  User types two stop names on /predict, assisted by AutocompleteInput\n"
         "        |                       (each keystroke -> GET /autocomplete?q=...)\n"
         "        v\n"
         "  POST /predict { current_stop, destination, limit }\n"
         "        |\n"
         "  predict()  api/routes.py\n"
         "        |-- asyncio.to_thread(predictor.predict, ...)   <-- CPU work moved OFF the\n"
         "        |                                                   event loop, ~1 second\n"
         "        v\n"
         "  BMTCBusPredictor.predict()   ml/predictor.py\n"
         "        |-- _resolve_stop_name(origin)        fuzzy match to a real stop name\n"
         "        |-- _resolve_stop_name(destination)\n"
         "        |-- _find_transfer_suggestions()      the actual search:\n"
         "        |        |-- stop_to_route_indices    which routes touch each stop\n"
         "        |        |-- stop_pair_to_segments    655,438 ordered (A,B) pairs\n"
         "        |        |-- build direct candidates, then one-transfer chains\n"
         "        |        |-- _interchange_is_walkable()   reject transfers whose two stops\n"
         "        |        |                                are more than 1.2 km apart\n"
         "        |        |-- _make_transfer_leg() per leg -> distance, fare inputs, EV specs\n"
         "        |        |-- _reanchor_legs()             resolve the whole journey as ONE\n"
         "        |        |                                anchored sequence of stops\n"
         "        |        +-- rank and deduplicate by bus chain\n"
         "        |-- _detect_metro_interchange()       does the path pass a metro station?\n"
         "        v\n"
         "  { best_match, alternatives, message, resolved stop names, route_coordinates, legs }\n"
         "        |\n"
         "  api/routes.py enriches with metro info, logs a predict_query usage event\n"
         "        v\n"
         "  Frontend renders: bus number, stop list, distance, fare, RouteMap polyline per leg",
         caption="Figure 4.4 - Journey search, end to end.")
    evidence(doc, "backend/app/api/routes.py -> predict(); backend/app/ml/predictor.py")

    h(doc, 2, "4.5 Flow D - Demand voting, and the loop back to the depot")
    para(doc, "This flow is the project name in action: commuter demand becoming an operator decision.")
    code(doc,
         "  COMMUTER SIDE\n"
         "  POST /votes { current_stop, destination, time_preference }\n"
         "        |-- VoteFraudDetector.check()   four heuristics:\n"
         "        |        1. same pair more than 10 times in 24 h\n"
         "        |        2. more than 30 votes in one hour from one user\n"
         "        |        3. more than 50 votes in one hour from one IP\n"
         "        |        4. an implausible spread of distinct destinations\n"
         "        |-- db.votes.insert_one({... flagged: bool, reason })\n"
         "        v\n"
         "  GET /votes/allocation -> which bus already serves that pair + how many votes it has\n"
         "\n"
         "  DEPOT SIDE\n"
         "  GET /depot/dispatch-recommendations   (admin / depot_manager only)\n"
         "        |-- get_vote_aggregation(days)          group votes by (origin, destination)\n"
         "        |-- rank_dispatch_recommendations()     genuine votes = total minus flagged\n"
         "        |        +-- predictor.predict(pair)    resolve each pair to a REAL bus\n"
         "        v\n"
         "  Ranked list with surge level HIGH / MEDIUM / LOW, or an honest empty list",
         caption="Figure 4.5 - The demand loop.")
    callout(doc, "A design decision worth quoting in a viva",
            "rank_dispatch_recommendations() is a separate, pure function rather than inline endpoint "
            "code, specifically so it can be unit-tested against fixture vote data with no MongoDB "
            "running. If it cannot resolve a voted pair to a real bus it skips the pair instead of "
            "inventing a route number. CONFIRMED: api/routes.py, and tests/test_votes.py.")

    h(doc, 2, "4.6 Flow E - Buying an e-ticket (including Shakti free travel)")
    code(doc,
         "  POST /api/tickets/purchase { source_stop, destination_stop, is_ac }\n"
         "        |-- get_fare()                    resolve both stops, compute distance,\n"
         "        |                                 look up the stage fare in fares.json\n"
         "        |-- _account_gender(db, user_id)  read gender from the ACCOUNT, never the token\n"
         "        |-- is_shakti_eligible(gender, is_ac)      core/shakti.py, the one shared rule\n"
         "        |        female or transgender AND not AC  -> free\n"
         "        |        anything else                     -> chargeable\n"
         "        |-- fare_value_inr    = the full fare (what the state reimburses)\n"
         "        |-- fare_collected_inr= 0 for Shakti, else the full fare\n"
         "        |-- create_ticket_token(...)      signed with TICKET_SECRET_KEY, 2 h expiry\n"
         "        |-- short_code                    6 random characters from A-Z0-9\n"
         "        |-- db.tickets.insert_one(...)\n"
         "        |-- db.transactions.insert_one(...)   amount 0 for a scheme ticket\n"
         "        v\n"
         "  Ticket rendered as a QR code plus the short code\n"
         "        |\n"
         "  CONDUCTOR SIDE: POST /api/tickets/verify { qr_token }\n"
         "        |-- decode_ticket_token()  signature + expiry + type must be qr_ticket\n"
         "        v\n"
         "  { success: true, ticket_id, status }",
         caption="Figure 4.6 - E-ticket purchase and verification.")
    callout(doc, "The single most important idea in the ticketing code",
            "fare_value_inr and fare_collected_inr are two separate fields. A Shakti ticket costs the "
            "passenger nothing and costs BMTC the full fare, which the state reimburses. One combined "
            "fare_amount field cannot express both, so revenue reporting and the reimbursement claim "
            "would misstate one or the other. Revenue uses fare_collected_inr; the claim uses "
            "fare_value_inr. CONFIRMED: api/tickets.py and services/waybill_service.py.")

    h(doc, 2, "4.7 Flow F - Conductor waybill, offline sales and cash reconciliation")
    code(doc,
         "  POST /conductor/sign-on { route_number, bus_reg, depot, opening_km }\n"
         "        |-- refuse if this conductor already has an OPEN waybill  -> 409\n"
         "        |-- create waybill WB-YYYYMMDD-XXXXXXXX, status OPEN\n"
         "        |-- audit_service.record('waybill.sign_on')\n"
         "        v\n"
         "  DURING THE SHIFT (signal is unreliable, so offline is the DEFAULT path)\n"
         "  issueTicket() on the device\n"
         "        |-- enqueue() into localStorage with a client-generated UUID\n"
         "        |-- if online, immediately flush()\n"
         "        v\n"
         "  POST /conductor/tickets/sync { tickets: [...] }\n"
         "        |-- for each ticket: price it with the SAME core/fares.py used by the app\n"
         "        |-- insert into conductor_tickets\n"
         "        |-- unique index (waybill_id, client_ticket_uuid) -> DuplicateKeyError on a\n"
         "        |   replay, which is reported as 'duplicate', not an error\n"
         "        v\n"
         "  { accepted: [...], duplicates: [...], rejected: [...], counts }\n"
         "        |-- the device clears ONLY what the server acknowledged\n"
         "\n"
         "  POST /conductor/sign-off { closing_km, declared_cash }\n"
         "        |-- recompute_totals()   derived from the ticket rows, never from the client\n"
         "        |-- variance = declared_cash - expected_cash   (reported, never auto-corrected)\n"
         "        v\n"
         "  Waybill CLOSED; visible to the depot at GET /depot/waybills",
         caption="Figure 4.7 - The conductor money path.")

    h(doc, 2, "4.8 Flow G - GTFS export")
    code(doc,
         "  Startup (or POST /gtfs/rebuild, or the first GET /gtfs/static.zip)\n"
         "        |\n"
         "  GtfsFeedService.ensure_built()   asyncio.Lock so concurrent callers share one build\n"
         "        |-- adopt an existing feed on disk if both the zip and its report are present\n"
         "        |-- else asyncio.to_thread(_build_sync, ...)\n"
         "                 |\n"
         "                 GtfsFeedBuilder.build()\n"
         "                 |-- pass 1: resolve every route to anchored published stops\n"
         "                 |           exclude depot pull-out runs        (325 dropped)\n"
         "                 |           exclude services over 100 km       (55 dropped)\n"
         "                 |-- write agency, stops, routes, calendar, trips\n"
         "                 |-- STREAM stop_times straight into the zip   (1,459,066 rows)\n"
         "                 |-- write shapes, feed_info, README.txt (provenance)\n"
         "                 +-- atomic rename of the temp file into place\n"
         "        v\n"
         "  GET /gtfs/static.zip  -> 14.4 MB feed, built in about 11 seconds",
         caption="Figure 4.8 - GTFS static build.")

    h(doc, 2, "4.9 Flow H - Vehicle positions and the honesty gate")
    code(doc,
         "  Startup: vehicle_ingest.start()  builds the adapter named by TRACKING_FEED\n"
         "        simulated | gtfs_rt | http_json | push        (default: simulated)\n"
         "        |\n"
         "  Background loop every TRACKING_POLL_SECONDS (default 10 s)\n"
         "        |-- feed.poll() -> list[VehicleObservation]   each carrying is_live\n"
         "        |-- vehicle_store.replace_all(observations)\n"
         "        |-- on failure: exponential backoff up to 300 s, error recorded\n"
         "        v\n"
         "  GET /tracking/buses   -> fresh observations only; anything older than\n"
         "                           AVL_STALE_SECONDS (120 s) is WITHHELD, not shown\n"
         "  GET /tracking/eta     -> project the bus onto the route polyline, sum the REMAINING\n"
         "                           distance along the route, return a range plus a confidence\n"
         "                           label (high / medium / low) naming which speed source was used\n"
         "  GET /gtfs-rt/vehicle-positions.pb\n"
         "        |-- if the active feed is NOT live -> HTTP 503 with an explanation\n"
         "        +-- GTFS-Realtime has no field meaning 'this is simulated', so a consumer\n"
         "            could not tell. The gate is the whole reason this layer exists.",
         caption="Figure 4.9 - Vehicle location and the simulated-data gate.")

    h(doc, 2, "4.10 Flow I - SMS journey query (feature phones)")
    code(doc,
         "  Feature phone sends an SMS: 'Majestic to Whitefield'\n"
         "        v\n"
         "  Twilio POSTs to /sms/webhook  (form-encoded Body, From)\n"
         "        |-- X-Twilio-Signature verified; with no TWILIO_AUTH_TOKEN set, everything\n"
         "        |   is refused rather than trusted\n"
         "        |-- parse_sms_query()   splits on 'to', '->' or ',' but deliberately NOT '-',\n"
         "        |                       because real stop names contain hyphens\n"
         "        |-- predictor.predict()\n"
         "        |-- if stop-name confidence < 0.55 -> format_low_confidence_reply(), which\n"
         "        |   says what it understood instead of stating a route as fact\n"
         "        v\n"
         "  TwiML reply, truncated to 320 characters (about two SMS segments)",
         caption="Figure 4.10 - The low-bandwidth channel.")
    page_break(doc)


def section_5(doc):
    h(doc, 1, "5. User Journey")
    para(doc, "This section walks through the application screen by screen, in the order a new user "
              "would meet them. Every screen names the file that implements it.")

    h(doc, 2, "5.1 Landing page  (/)  -  pages/Landing.tsx")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "Introduce the project and route the visitor to sign in or sign up"],
        ["User sees", "Project name, description and call-to-action buttons"],
        ["Interaction", "Click Login or Register"],
        ["Request", "None - this page is static"],
        ["Note", "If already authenticated, App.tsx redirects straight to /dashboard"],
    ], widths=[1.3, 5.5])

    h(doc, 2, "5.2 Register  (/register)  -  pages/Register.tsx")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "Create a commuter account"],
        ["User sees", "Name, email, password, phone, gender and preferred language fields"],
        ["Interaction", "Fill and submit. Choosing Female or Transgender shows a green line\nconfirming that ordinary (non-AC) tickets will be free under Shakti"],
        ["Request", "POST /auth/register"],
        ["Backend", "Duplicate email check, PBKDF2 password hash, insert with role commuter,\nmint access and refresh tokens"],
        ["Database", "db.users.insert_one(...)"],
        ["Response", "Tokens plus the user profile, including shakti_eligible"],
        ["Afterwards", "Tokens go to localStorage; the user lands on /dashboard"],
    ], widths=[1.3, 5.5])
    callout(doc, "Why gender is collected here",
            "Gender is a sensitive attribute, so the form states its single purpose at the point of "
            "asking: applying the Karnataka Shakti scheme, which gives free travel to women and "
            "transgender passengers. It is optional, \"Prefer not to say\" is a first-class answer, and "
            "it is used nowhere else in the codebase - not in prediction, not in analytics, not in any "
            "dashboard. It is also never placed in the JWT, because a bearer token travels through "
            "logs and browser storage. CONFIRMED: core/shakti.py; auth/routes.py; api/tickets.py "
            "reads it from the account with a database lookup.")

    h(doc, 2, "5.3 Dashboard  (/dashboard)  -  DashboardRouter")
    para(doc, "A dispatcher rather than a screen. It reads the role from AuthContext and renders the "
              "right dashboard: CommuterDashboard, DepotDashboard or AdminDashboard.")

    h(doc, 2, "5.4 Journey search  (/predict)  -  pages/PredictPage.tsx  (861 lines)")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "The core feature: find the bus from A to B"],
        ["User sees", "Two autocomplete inputs, a voice button, a swap button, and an\nassistant panel that accepts free text such as \"Majestic to Whitefield\""],
        ["Interaction", "Type or speak two stops and submit"],
        ["Request", "GET /autocomplete on each keystroke, then POST /predict"],
        ["Backend", "predictor.predict() on a worker thread; metro interchange enrichment;\nusage event logged"],
        ["Response", "best_match, alternatives, resolved stop names, coordinates, legs"],
        ["Afterwards", "Result card with bus number, confidence, distance, fare, stop list;\nRouteMap draws one coloured polyline per leg; service alerts for the\nroute appear above; NearestMetroPanel and SafetyPanel appear below"],
    ], widths=[1.3, 5.5])

    h(doc, 2, "5.5 Vote  (/vote)  -  pages/VotePage.tsx  (697 lines)")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "Register demand for a journey the network serves poorly"],
        ["User sees", "Origin and destination inputs, a time-of-day preference, and the\ncurrent aggregated demand"],
        ["Request", "POST /votes, then GET /votes/allocation and GET /votes/aggregate"],
        ["Backend", "Fraud heuristics, insert, then resolve the pair to a real bus so the\nvoter sees what already serves it"],
        ["Afterwards", "Vote count and the allocated bus, or an honest note if MongoDB is down"],
    ], widths=[1.3, 5.5])

    h(doc, 2, "5.6 Live tracking  (/track)  -  pages/LiveTracking.tsx")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "Show where buses are on a map"],
        ["User sees", "A Leaflet map with bus markers coloured by occupancy, a searchable\nlist, and a detail panel with speed, occupancy and next stop"],
        ["Request", "GET /tracking/buses, polled"],
        ["Backend", "Reads the vehicle store; withholds observations older than 120 s;\nenriches each bus with its next stop by projecting it onto the route"],
        ["Honesty", "Every payload carries is_live. With the default simulator this is\nfalse, and mode is reported as \"simulated\""],
    ], widths=[1.3, 5.5])

    h(doc, 2, "5.7 Tickets  (/tickets)  -  pages/Tickets.tsx")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "Buy and display an e-ticket"],
        ["User sees", "Two stop inputs, a fare quote, then a QR code with a 6-character code"],
        ["Shakti path", "An eligible passenger sees Rs 0 with the real fare struck through, and\na \"Get free Shakti ticket\" button, BEFORE the payment step - never a\nsurprise zero afterwards"],
        ["Request", "GET /api/tickets/fare, then POST /api/tickets/purchase"],
        ["Afterwards", "Active ticket with a live pulse indicator and an expiry countdown"],
    ], widths=[1.3, 5.5])

    h(doc, 2, "5.8 Depot dashboard  (/depot)  -  pages/DepotDashboard.tsx")
    para(doc, "The operations screen, and the one worth demonstrating to an examiner, because it "
              "shows work no consumer app does. It stacks four panels:")
    bullets(doc, [
        ("BlockingPanel.", "Minimum fleet and dead kilometres per depot, with per-route re-block "
         "proposals a manager approves or rejects. Advisory only - nothing is dispatched."),
        ("ScenarioConsole.", "\"What would this frequency change cost?\" - re-blocks one depot with "
         "and without a timetable change."),
        ("CrewPanel.", "Daily crew duties, crew-to-bus ratio, split-duty percentage, unstaffable "
         "blocks, and a rule console for testing crew-agreement changes."),
        ("Dispatch recommendations.", "The vote-driven list from Flow D, with a Deploy button that "
         "records a human acknowledgement."),
    ])

    h(doc, 2, "5.9 Conductor duty  (/duty)  -  pages/ConductorDuty.tsx")
    table(doc, ["Aspect", "What happens"], [
        ["Purpose", "The conductor working day"],
        ["User sees", "Sign-on form; then waybill id, an issue-ticket form, and a sign-off form.\nAn always-visible badge shows how many sales are still unsynced"],
        ["Offline", "Every sale is written to localStorage first and pushed opportunistically;\nthe queue drains automatically when the browser reports it is online"],
        ["Sign-off", "Refuses to close while tickets are unsynced, because the server rejects\ntickets against a closed waybill"],
    ], widths=[1.3, 5.5])

    h(doc, 2, "5.10 Conductor scanner  (/scanner)  -  pages/ConductorScanner.tsx")
    para(doc, "Uses the device camera through html5-qrcode. A scanned token is inspected for its "
              "declared type - qr_ticket or travel_pass - and routed to the correct verifier, because "
              "both are three-segment signed tokens and cannot be told apart by shape alone. The "
              "signature itself is always checked on the server, with a different key per type.")

    h(doc, 2, "5.11 Admin dashboard  (/admin)  -  pages/AdminDashboard.tsx")
    para(doc, "Network-level view: user counts, vote analytics, fraud alerts, model metrics "
              "(MetricsDashboard), and the citywide fleet roll-up (BlockingSummaryCard).")

    h(doc, 2, "5.12 Shared trip view  (/trip/:code)  -  pages/SharedTripView.tsx")
    para(doc, "The only authenticated-user-generated page that a stranger can open without logging in. "
              "A commuter shares a trip; a trusted contact opens the link and sees the journey. The "
              "share expires after 6 hours, enforced by a MongoDB TTL index that physically deletes "
              "the document rather than merely hiding it.")
    evidence(doc, "backend/app/services/safety_service.py; db/database.py trip_shares TTL index")
    page_break(doc)
