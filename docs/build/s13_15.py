# -*- coding: utf-8 -*-
"""Sections 13-15: API, Database, Authentication."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_13(doc):
    h(doc, 1, "13. API Documentation")
    para(doc, "DBARS exposes 82 routes. FastAPI generates live interactive documentation at /docs "
              "(Swagger UI) and /redoc, which is worth demonstrating in a viva. The tables below "
              "group the endpoints by subject. Auth column: PUBLIC = no token needed, USER = any "
              "logged-in account, and a named role = that role only.")

    h(doc, 2, "13.1 Core prediction and data")
    table(doc, ["Method", "Endpoint", "Purpose", "Input", "Auth", "Output / errors"], [
        ["POST", "/predict", "Find the bus between two stops", "current_stop,\ndestination, limit", "PUBLIC", "best_match, alternatives\n422 if a stop is unresolvable"],
        ["GET", "/autocomplete", "Stop name suggestions", "q, limit, kind", "PUBLIC", "Ranked name list"],
        ["GET", "/routes", "Browse the route catalogue", "limit, offset, search", "PUBLIC", "Paginated routes"],
        ["GET", "/metrics", "Model benchmark results", "-", "PUBLIC", "metrics.json contents"],
        ["GET", "/health", "Liveness and readiness", "-", "PUBLIC", "status, route count"],
        ["POST", "/train", "Force a retrain", "force", "PUBLIC", "New metrics\n(see the finding below)"],
        ["POST", "/directions", "Google Maps directions", "stops", "PUBLIC", "503 when no API key is set"],
    ], widths=[0.55, 1.15, 1.5, 1.15, 0.55, 1.9])
    callout(doc, "Finding - an unauthenticated expensive endpoint",
            "POST /train has no authentication and triggers a full retraining cycle. Repeated calls "
            "would consume significant CPU and could be used to degrade service. Every other "
            "state-changing or expensive endpoint in the project is role-gated, so this looks like an "
            "oversight rather than a decision. Recommended fix: wrap it in "
            "Depends(require_role(UserRole.ADMIN)), exactly as POST /gtfs/rebuild already is. "
            "CONFIRMED: api/routes.py train() has no Depends on a role.", warn=True)

    h(doc, 2, "13.2 Authentication")
    table(doc, ["Method", "Endpoint", "Purpose", "Input", "Auth", "Output / errors"], [
        ["POST", "/auth/register", "Create a commuter account", "email, password, name,\ngender (optional)", "PUBLIC", "tokens + user\n400 duplicate email"],
        ["POST", "/auth/login", "Sign in", "email, password", "PUBLIC", "tokens + user\n401 bad credentials\n403 disabled account"],
        ["GET", "/auth/me", "Current profile", "-", "USER", "user, incl. shakti_eligible"],
        ["POST", "/auth/refresh", "New access token", "refresh_token", "PUBLIC", "access_token\n401 if not a refresh token"],
    ], widths=[0.55, 1.15, 1.5, 1.35, 0.55, 1.7])

    h(doc, 2, "13.3 Voting and demand")
    table(doc, ["Method", "Endpoint", "Purpose", "Auth", "Notes"], [
        ["POST", "/votes", "Record a demand vote", "USER", "Runs four fraud heuristics before inserting"],
        ["GET", "/votes/my", "The caller's own votes", "USER", "Paginated"],
        ["GET", "/votes/allocation", "Which bus serves my voted pair", "USER", "Bus resolves without a DB; vote counts need one"],
        ["GET", "/votes/aggregate", "Demand by origin-destination pair", "USER", "Feeds the depot dispatch screen"],
        ["GET", "/depot/dispatch-\nrecommendations", "Ranked real demand", "DEPOT,\nADMIN", "Returns an honest empty list when there are\nno votes, never invented recommendations"],
        ["POST", "/depot/deploy-bus", "Acknowledge a recommendation", "DEPOT,\nADMIN", "Records that a human reviewed it. Nothing is\nactually dispatched"],
    ], widths=[0.55, 1.5, 1.75, 0.7, 2.3])

    h(doc, 2, "13.4 Operations planning")
    table(doc, ["Method", "Endpoint", "Purpose", "Auth", "Notes"], [
        ["GET", "/depot/blocking-plan", "Fleet size and dead kilometres", "DEPOT,\nADMIN", "Cached; no database needed"],
        ["POST", "/depot/blocking-scenario", "Cost of a timetable change", "DEPOT,\nADMIN", "Scoped to one depot so it answers in\nunder a second"],
        ["POST", "/depot/blocking-decision", "Record an approve/reject", "DEPOT,\nADMIN", "Advisory only"],
        ["GET", "/depot/crew-plan", "Daily crew duties", "DEPOT,\nADMIN", "Builds on the cached blocking context"],
        ["POST", "/depot/crew-scenario", "Cost of a crew rule change", "DEPOT,\nADMIN", "422 if working time exceeds spreadover"],
        ["GET", "/depot/routes", "Route names for type-ahead", "DEPOT,\nADMIN", "Supports the scenario console"],
    ], widths=[0.55, 1.6, 1.7, 0.7, 2.25])

    h(doc, 2, "13.5 Tickets, conductor and revenue")
    table(doc, ["Method", "Endpoint", "Purpose", "Auth", "Notes"], [
        ["GET", "/api/tickets/fare", "Quote a fare", "PUBLIC", "Server-side pricing"],
        ["POST", "/api/tickets/purchase", "Buy an e-ticket", "USER", "Free under Shakti when eligible"],
        ["GET", "/api/tickets/active", "The current valid ticket", "USER", "404 when none"],
        ["GET", "/api/tickets/history", "All past tickets", "USER", "Legacy tickets lack scheme fields"],
        ["POST", "/api/tickets/verify", "Conductor scans a QR", "CONDUCTOR,\nDEPOT, ADMIN", "Verifies signature, expiry and type"],
        ["POST", "/conductor/sign-on", "Open a waybill", "CONDUCTOR,\nADMIN", "409 if one is already open"],
        ["GET", "/conductor/waybill", "The open waybill", "CONDUCTOR", "Lets the device recover after a crash"],
        ["POST", "/conductor/tickets/issue", "One onboard sale", "CONDUCTOR", "Shares its implementation with sync"],
        ["POST", "/conductor/tickets/sync", "Drain the offline queue", "CONDUCTOR", "Idempotent; per-item results"],
        ["POST", "/conductor/sign-off", "Close and reconcile cash", "CONDUCTOR", "Reports variance, never corrects it"],
        ["POST", "/conductor/verify-pass", "Verify a travel pass", "PUBLIC", "Offline signature and expiry check"],
        ["GET", "/conductor/pass-revocations", "Revocation list to cache", "CONDUCTOR", "Ids only - no personal data"],
        ["POST", "/depot/passes", "Issue a signed pass", "DEPOT, ADMIN", "Returns the QR token"],
        ["POST", "/depot/passes/{id}/revoke", "Revoke a pass", "DEPOT, ADMIN", "Audited"],
        ["GET", "/depot/waybills", "Waybills for a depot/day", "DEPOT, ADMIN", "Surfaces open waybills and variances"],
        ["GET", "/admin/shakti/claim", "Reimbursement claim", "DEPOT, ADMIN", "Splits conductor-issued from app-issued"],
        ["GET", "/admin/revenue/\nreconciliation", "Cash vs digital vs scheme", "DEPOT, ADMIN", "Scheme value shown beside revenue,\nnever inside it"],
        ["GET", "/admin/audit", "Who did what, when", "ADMIN", "No TTL - accountability is not expired"],
    ], widths=[0.55, 1.65, 1.55, 0.95, 2.1])

    h(doc, 2, "13.6 Tracking, open data and the remaining endpoints")
    table(doc, ["Method", "Endpoint", "Purpose", "Auth", "Notes"], [
        ["GET", "/tracking/buses", "Current vehicle positions", "PUBLIC", "Every payload carries is_live"],
        ["GET", "/tracking/bus/{n}", "One route's vehicles", "PUBLIC", "Adds schedule adherence"],
        ["GET", "/tracking/eta", "Arrival estimate", "PUBLIC", "Range plus a confidence label"],
        ["GET", "/tracking/source", "What is powering the map", "PUBLIC", "Derived from the adapter, not a\nstored label"],
        ["POST", "/avl/ingest", "Push vehicle positions", "X-AVL-Key", "Exempt from rate limiting; refuses\neverything when no key is configured"],
        ["GET", "/gtfs/static.zip", "The full GTFS feed", "PUBLIC", "~14.4 MB, built in ~11 s"],
        ["GET", "/gtfs/feed-info", "Build report and assumptions", "PUBLIC", "Answers without triggering a build"],
        ["POST", "/gtfs/rebuild", "Force a rebuild", "ADMIN", "Correctly gated"],
        ["GET", "/gtfs-rt/service-alerts.pb", "Realtime alerts", "PUBLIC", "Real data; 503 when Mongo is down"],
        ["GET", "/gtfs-rt/vehicle-positions.pb", "Realtime vehicles", "PUBLIC", "503 while the feed is simulated"],
        ["GET/POST", "/alerts", "List / create disruptions", "PUBLIC /\nDEPOT, ADMIN", "Creation is moderated"],
        ["POST", "/crowding/report", "Report bus occupancy", "USER", "10-minute per-user cooldown"],
        ["GET", "/metro/nearest", "Nearest metro stations", "PUBLIC", "Haversine over the metro CSV"],
        ["POST", "/sms/webhook", "Twilio SMS query", "Twilio\nsignature", "Refuses everything when no auth\ntoken is configured"],
        ["POST", "/safety/share-trip", "Create a share link", "USER", "Expires after 6 hours"],
        ["GET", "/safety/trip/{code}", "View a shared trip", "PUBLIC", "Deliberately public - a trusted\ncontact has no account"],
    ], widths=[0.7, 1.65, 1.5, 0.9, 2.05])

    h(doc, 2, "13.7 How an endpoint is implemented, in order")
    numbered(doc, [
        "Route registration - a decorator such as @router.post(\"/predict\") binds the path to a function.",
        "Request parsing - FastAPI reads the body and constructs the pydantic model named in the signature.",
        "Validation - pydantic rejects wrong types or lengths with 422 before any project code runs.",
        "Authorisation - Depends(get_current_user) or Depends(require_role(...)) resolves before the body executes.",
        "Business logic - the endpoint calls a service or an engine. Heavy CPU work is wrapped in asyncio.to_thread.",
        "Data access - services talk to MongoDB; engines read in-memory indexes.",
        "Serialisation - the returned dict or response_model becomes JSON.",
        "Error handling - HTTPException produces a clean status and detail; unexpected exceptions become a 500.",
    ])
    page_break(doc)


def section_14(doc):
    h(doc, 1, "14. Database Deep Dive")

    h(doc, 2, "14.1 What kind of database, and why")
    para(doc, "MongoDB, a document database. Instead of tables with fixed columns, it stores "
              "JSON-like documents inside collections. Two documents in one collection can hold "
              "different fields.")
    table(doc, ["Aspect", "Detail"], [
        ["Driver", "Motor 3.6 - the async MongoDB driver, so a slow query does not block the event loop"],
        ["Connection", "MONGO_URI, default mongodb://localhost:27017; database name MONGO_DB_NAME,\ndefault \"bmtc\""],
        ["Timeout", "serverSelectionTimeoutMS = 3000, deliberately reduced from the driver default of\n30000 so a missing database fails fast instead of hanging the app for half a minute"],
        ["Access pattern", "Only the service layer touches the database. Engines never do."],
    ], widths=[1.2, 5.6])
    callout(doc, "Why a document database was a reasonable choice here",
            "The honest answer is fit plus flexibility. Records like a waybill grew new fields during "
            "development (scheme, fare_value_inr, reconciliation) and a schema-free store absorbed that "
            "without migrations. The trade-off is real and worth stating: there are no foreign keys and "
            "no joins, so referential integrity is the application's responsibility. A relational "
            "database would have enforced more for you. INFERRED from the code; the project contains no "
            "written justification of the choice.")

    h(doc, 2, "14.2 Collections")
    table(doc, ["Collection", "Holds", "Key fields", "Written by"], [
        ["users", "Accounts", "email (unique), name, password_hash, role,\npreferred_lang, gender, is_active, created_at", "auth/routes.py,\napi/admin.py"],
        ["votes", "Demand votes", "user_id, current_stop, destination,\ntime_preference, flagged, reason, ip_address,\ncreated_at", "vote_service.py"],
        ["tickets", "Commuter e-tickets", "ticket_id, user_id, source_stop,\ndestination_stop, fare_amount, fare_value_inr,\nfare_collected_inr, is_zero_fare, scheme,\nqr_token, short_code, status, expiry_time", "api/tickets.py"],
        ["transactions", "Payment records", "transaction_id, ticket_id, amount, status,\nscheme, timestamp", "api/tickets.py"],
        ["waybills", "Conductor duty records", "waybill_id (unique), conductor_id, driver_id,\nbus_reg, depot, route_number, duty_date, status,\nopening_km, closing_km, totals, reconciliation", "waybill_service.py"],
        ["conductor_tickets", "Onboard sales", "ticket_id, client_ticket_uuid, waybill_id, lines,\nfare_value_inr, fare_collected_inr,\nshakti_boardings, payment_mode, issued_at", "waybill_service.py"],
        ["travel_passes", "Season passes", "pass_id (unique), holder_name, pass_type,\nexpires_at, status, revoked_at, revoked_reason", "pass_service.py"],
        ["audit_events", "Accountability log", "action, actor_id, subject, metadata, created_at", "audit_service.py"],
        ["service_alerts", "Disruptions", "title, description, severity, affected_routes,\naffected_stops, status, created_at", "alerts_service.py"],
        ["crowd_reports", "Occupancy reports", "user_id, route_number, crowding_level,\nstop_name, created_at", "crowding_service.py"],
        ["trip_shares", "Shared trip links", "code (unique), user_id, trip data, expires_at", "safety_service.py"],
        ["favorites", "Saved routes", "user_id, current_stop, destination, label", "api/tracking.py"],
        ["bus_positions", "Simulated positions", "bus_number, latitude, longitude, speed_kmh,\noccupancy_pct, updated_at", "tracking_service.py"],
        ["usage_events", "Privacy-minimal analytics", "event_type, metadata, created_at", "analytics_service.py"],
        ["predictions", "Query history", "user_id and query details", "api/routes.py"],
        ["notifications", "User notifications", "user_id, is_read", "db/seed.py"],
        ["verification_logs", "Pass scan log", "scan records", "pass verification path"],
    ], widths=[1.15, 1.15, 2.75, 1.15])

    h(doc, 2, "14.3 Indexes, and why each one exists")
    table(doc, ["Index", "Type", "Why"], [
        ["users.email", "unique", "Prevents two accounts sharing an email, and makes login lookup fast"],
        ["votes.(current_stop, destination)", "compound", "The aggregation groups by this pair"],
        ["votes.created_at desc", "single", "Time-window queries for the fraud detector"],
        ["favorites.(user_id, current_stop,\ndestination)", "unique", "Stops the same route being saved twice"],
        ["conductor_tickets.(waybill_id,\nclient_ticket_uuid)", "UNIQUE", "THE index that makes offline ticketing safe. Without it a\nreplayed batch is counted again and the day's revenue is\noverstated."],
        ["waybills.waybill_id", "unique", "Identity"],
        ["waybills.(conductor_id, status)", "compound", "Finds a conductor's open waybill instantly"],
        ["waybills.(depot, duty_date desc)", "compound", "The depot oversight screen"],
        ["travel_passes.(status, expires_at)", "compound", "Builds the revocation list without a full scan"],
        ["trip_shares.expires_at", "TTL (0 s)", "MongoDB physically DELETES an expired share. It does not\nmerely stop returning it - someone's past travel plans do\nnot linger as a forgotten record."],
        ["usage_events.created_at", "TTL (90 days)", "Raw analytics rows are not kept indefinitely"],
        ["audit_events.created_at desc", "single", "Deliberately NO TTL - these record who moved money, and a\nretention window on them would be a retention window on\naccountability"],
    ], widths=[2.0, 0.95, 3.85])

    h(doc, 2, "14.4 How an application object becomes a stored record")
    code(doc,
         "  1. HTTP JSON body\n"
         "         { \"source_stop\": \"Majestic\", \"destination_stop\": \"Marathahalli\" }\n"
         "         |\n"
         "  2. Pydantic model  TicketPurchaseRequest\n"
         "         validated Python object with typed attributes\n"
         "         |\n"
         "  3. Endpoint builds a plain dict, adding server-computed fields\n"
         "         ticket_id, fare_value_inr, fare_collected_inr, qr_token, short_code\n"
         "         |\n"
         "  4. await db.tickets.insert_one(ticket_doc)\n"
         "         Motor serialises the dict to BSON; Mongo adds an _id\n"
         "         |\n"
         "  5. Reading back: db.tickets.find_one(...) returns a dict\n"
         "         |\n"
         "  6. TicketResponse(**ticket_doc) validates it on the way out\n"
         "         _id is dropped; datetimes become ISO strings in JSON",
         caption="Figure 14.1 - The object-to-document round trip. There is no ORM; the mapping is "
                 "explicit dictionary construction.")
    callout(doc, "A schema-evolution detail worth knowing",
            "Every Shakti field on TicketResponse (fare_value_inr, is_zero_fare, scheme, scheme_note) "
            "is Optional with a default. Tickets issued before the scheme existed have none of those "
            "fields, and a required field would break every historical ticket in "
            "GET /api/tickets/history. This is the document-database trade-off made concrete: no "
            "migration was run, so the code must tolerate both shapes. CONFIRMED: "
            "backend/app/models/tickets.py.")

    h(doc, 2, "14.5 A full read-write trace")
    code(doc,
         "  Conductor taps 'Issue' on the device\n"
         "     -> localStorage queue (client-generated UUID)\n"
         "     -> POST /conductor/tickets/sync\n"
         "     -> issue_tickets()\n"
         "         -> db.waybills.find_one({waybill_id})        READ  - verify OPEN and owner\n"
         "         -> price_ticket() -> get_fare()              READ  - dataset files, not the DB\n"
         "         -> db.conductor_tickets.insert_one(...)      WRITE - unique index enforced\n"
         "     -> per-item response\n"
         "\n"
         "  Conductor taps 'Sign off'\n"
         "     -> close_waybill()\n"
         "         -> recompute_totals()\n"
         "              -> db.conductor_tickets.find({waybill_id})   READ  - cursor over all sales\n"
         "         -> db.waybills.update_one({...totals, reconciliation})  WRITE\n"
         "\n"
         "  Office opens the claim report\n"
         "     -> shakti_claim()\n"
         "         -> db.waybills.aggregate([...])   READ - group by depot and duty_date\n"
         "         -> db.tickets.aggregate([...])    READ - app-issued Shakti tickets, separately",
         caption="Figure 14.2 - Reads and writes across one conductor shift.")

    h(doc, 2, "14.6 Transactions and migrations")
    para(doc, "There are no multi-document transactions in this project, and no migration framework. "
              "CONFIRMED: no use of start_session or with_transaction appears anywhere. Both are "
              "genuine limitations and are listed in Section 36. The practical consequence: closing a "
              "waybill updates the waybill document after reading its tickets, and if the process died "
              "between those steps the waybill would remain OPEN with its tickets already recorded. "
              "Recovery would be manual.")
    page_break(doc)


def section_15(doc):
    h(doc, 1, "15. Authentication & Authorization")
    para(doc, "Authentication answers \"who are you?\". Authorization answers \"what are you allowed "
              "to do?\". DBARS implements both, and it is worth being precise about how, because it "
              "is a favourite examiner topic.")

    h(doc, 2, "15.1 The complete flow")
    code(doc,
         "  REGISTRATION\n"
         "     password -> hash_password() -> PBKDF2-SHA256, 16-byte random salt\n"
         "     stored in users.password_hash; the plain password is never stored or logged\n"
         "     role forced to 'commuter' server-side\n"
         "\n"
         "  LOGIN\n"
         "     find user by email -> verify_password(plain, stored) -> constant-time compare\n"
         "     is_active check -> 403 if disabled\n"
         "     issue access token (24 h) + refresh token (7 d)\n"
         "\n"
         "  AUTHENTICATED REQUEST\n"
         "     Authorization: Bearer <access token>\n"
         "     get_current_user()\n"
         "        - split into header.payload.signature\n"
         "        - recompute the HMAC and compare with hmac.compare_digest\n"
         "        - check exp has not passed\n"
         "        - check type == 'access'   <-- rejects a refresh or ticket token used as a session\n"
         "     returns the token claims: sub, email, role, name\n"
         "\n"
         "  AUTHORIZATION\n"
         "     require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)\n"
         "        - a dependency FACTORY: returns a dependency that checks the role claim\n"
         "        - 403 when the role is not in the allowed set\n"
         "\n"
         "  LOGOUT\n"
         "     Client-side only: remove both tokens from localStorage.\n"
         "     There is no server-side token blacklist - see the finding below.",
         caption="Figure 15.1 - Authentication and authorization end to end.")

    h(doc, 2, "15.2 The three token domains")
    table(doc, ["Token type", "Key", "Lifetime", "Purpose"], [
        ["access", "SECRET_KEY", "24 hours", "Session credential for API calls"],
        ["refresh", "SECRET_KEY", "7 days", "Obtain a new access token without re-entering a password"],
        ["qr_ticket", "TICKET_SECRET_KEY", "2 hours", "The e-ticket QR a conductor scans"],
        ["travel_pass", "PASS_SECRET_KEY", "up to 400 days", "A season pass, verifiable offline"],
    ], widths=[1.1, 1.5, 1.1, 3.1])
    para(doc, "The separation is deliberate and defensive. Each key is derived independently when not "
              "configured (for example sha256(\"ticket-domain:\" + SECRET_KEY)), so a compromised "
              "ticket key cannot mint a session, and a pass key cached on a shared device in a bus - "
              "the key most likely to leak - cannot mint either.")
    callout(doc, "The bug this design was built to prevent",
            "The token type constants exist because they were once duplicated as bare strings across "
            "three files and drifted: tickets.py minted tokens typed \"qr_ticket\" while "
            "get_current_user rejected \"ticket\". The guard was therefore dead code, and a ticket QR "
            "token authenticated successfully as a user session. Constants in one place fixed it. "
            "CONFIRMED: the comment above TOKEN_TYPE_ACCESS in auth/auth.py.")

    h(doc, 2, "15.3 Roles and what they unlock")
    table(doc, ["Role", "Can do", "Cannot do"], [
        ["commuter", "Search, vote, buy tickets, report crowding,\nshare trips, save favourites", "Any depot, admin or conductor endpoint"],
        ["conductor", "Waybills, onboard sales, sign-off, verify\ntickets and passes", "Issue passes, view revenue reports,\nread the audit log"],
        ["depot_manager", "Blocking and crew plans, scenarios, alerts,\nwaybill oversight, issue and revoke passes,\nShakti and revenue reports", "User management, the audit log"],
        ["admin", "Everything, including user management and\nthe audit log", "-"],
        ["driver", "Nothing yet - the role exists but no endpoint\nor page grants it anything", "Everything"],
    ], widths=[1.05, 3.0, 2.75])

    h(doc, 2, "15.4 What is protected, and what is deliberately not")
    para(doc, "Public by design: /predict, /autocomplete, /routes, /metrics, /health, "
              "/gtfs/*, /tracking/*, /alerts (read), /metro/*, and /safety/trip/{code}. The last is "
              "the interesting one - a trusted contact opening a shared trip link has no account, so "
              "requiring a login would defeat the feature. The link is unguessable, expires in six "
              "hours, and is then physically deleted by a TTL index.")

    h(doc, 2, "15.5 Honest weaknesses in the auth design")
    bullets(doc, [
        ("No token revocation.", "Logout only clears localStorage. A stolen access token stays valid "
         "for up to 24 hours; a refresh token for 7 days. There is no blacklist and no session store. "
         "CONFIRMED - no revocation logic exists."),
        ("Tokens in localStorage.", "This is readable by any JavaScript running on the page, so a "
         "cross-site scripting flaw would expose it. An httpOnly cookie would be safer against XSS, "
         "at the cost of needing CSRF protection."),
        ("No rate limit on login specifically.", "The global 120 requests/minute per IP applies, but "
         "there is no per-account lockout or exponential backoff, so password guessing is slowed "
         "rather than stopped."),
        ("No password complexity rule.", "min_length=6 is the only constraint."),
        ("No email verification.", "An account is usable immediately; the address is never confirmed."),
        ("PBKDF2 rather than Argon2/bcrypt.", "Legitimate and standards-based, but not the strongest "
         "modern option."),
    ])
    para(doc, "None of these makes the project insecure for its purpose, but claiming it is \"secure\" "
              "without qualification would be an overclaim. The defensible statement is: it implements "
              "signed-token authentication with hashed passwords and role-based authorization, and has "
              "known limitations around revocation and token storage.")
    page_break(doc)
