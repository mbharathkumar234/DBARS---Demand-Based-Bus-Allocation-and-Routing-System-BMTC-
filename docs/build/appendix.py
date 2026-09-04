# -*- coding: utf-8 -*-
"""Appendices A-H."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def appendices(doc):
    h(doc, 1, "Appendix A - Project File Tree")
    para(doc, "234 files are tracked in version control. Build outputs, dependencies and .env files "
              "are excluded by .gitignore. The full tree is given in Section 6; this appendix lists "
              "file counts by area.")
    table(doc, ["Area", "Files", "Lines", "Notes"], [
        ["backend/app/", "65 .py", "13,562", "API, services, engines, models, auth, core, db"],
        ["backend/tests/", "15 .py", "2,440", "161 tests"],
        ["frontend/src/", "45 .ts/.tsx", "8,459", "13 pages, 17 components, contexts, lib"],
        ["dataset/", "8 files", "n/a", "~12 MB of CSV, JSON, XLSX and PDF"],
        ["frontend/android/", "~90 files", "n/a", "Capacitor Android shell"],
        ["deployment/, .github/", "3 files", "n/a", "nginx.conf, render.yaml, ci.yml"],
        ["docs/", "3 files", "n/a", "implementation plan, resume entry, this document"],
    ], widths=[1.7, 1.0, 0.9, 3.2])
    page_break(doc)

    h(doc, 1, "Appendix B - API Reference (quick card)")
    para(doc, "The complete reference is in Section 13. This is the one-page version for revision.")
    code(doc,
         "PUBLIC\n"
         "  POST /predict                     find the bus between two stops\n"
         "  GET  /autocomplete?q=             stop name suggestions\n"
         "  GET  /routes  /metrics  /health   catalogue, benchmarks, liveness\n"
         "  GET  /gtfs/static.zip             the full GTFS feed (~14 MB)\n"
         "  GET  /gtfs/feed-info              build report and assumptions\n"
         "  GET  /gtfs-rt/service-alerts.pb   realtime alerts (real data)\n"
         "  GET  /gtfs-rt/vehicle-positions.pb  503 while the feed is simulated\n"
         "  GET  /tracking/buses  /bus/{n}  /eta  /source\n"
         "  GET  /alerts   /metro/stations   /metro/nearest\n"
         "  GET  /safety/trip/{code}          shared trip, no login by design\n"
         "  POST /conductor/verify-pass       offline signature + expiry check\n"
         "\n"
         "AUTH\n"
         "  POST /auth/register  /auth/login  /auth/refresh      GET /auth/me\n"
         "\n"
         "USER (any logged-in account)\n"
         "  POST /votes                       GET /votes/my  /allocation  /aggregate\n"
         "  POST /api/tickets/purchase        GET /api/tickets/active  /history  /fare\n"
         "  POST /crowding/report             GET /crowding/route/{n}\n"
         "  POST /safety/share-trip           GET/PUT /safety/contacts\n"
         "  GET/POST/DELETE /tracking/favorites\n"
         "\n"
         "CONDUCTOR\n"
         "  POST /conductor/sign-on  /tickets/issue  /tickets/sync  /sign-off\n"
         "  GET  /conductor/waybill  /conductor/pass-revocations\n"
         "\n"
         "DEPOT MANAGER / ADMIN\n"
         "  GET  /depot/blocking-plan  /depot/crew-plan  /depot/routes  /depot/waybills\n"
         "  POST /depot/blocking-scenario  /depot/crew-scenario  /depot/blocking-decision\n"
         "  GET  /depot/dispatch-recommendations    POST /depot/deploy-bus\n"
         "  POST /depot/passes    POST /depot/passes/{id}/revoke\n"
         "  GET  /admin/shakti/claim   /admin/revenue/reconciliation\n"
         "\n"
         "ADMIN ONLY\n"
         "  GET  /admin/dashboard  /admin/users  /admin/votes/analytics\n"
         "  GET  /admin/fraud/alerts  /admin/pilot-metrics  /admin/audit\n"
         "  POST /admin/users   PUT /admin/users/{id}/toggle-active\n"
         "  POST /gtfs/rebuild\n"
         "\n"
         "MACHINE-TO-MACHINE\n"
         "  POST /avl/ingest        X-AVL-Key header; exempt from rate limiting\n"
         "  POST /sms/webhook       X-Twilio-Signature verified\n"
         "\n"
         "UNGATED AND SHOULD NOT BE\n"
         "  POST /train             expensive retrain, no authentication  <-- known issue")
    page_break(doc)

    h(doc, 1, "Appendix C - Database Schema")
    para(doc, "MongoDB has no enforced schema; the shapes below are what the code writes.")
    code(doc,
         "users {\n"
         "  _id, email (UNIQUE), name, password_hash, role, preferred_lang,\n"
         "  gender, reliability, is_active, created_at\n"
         "}\n"
         "\n"
         "votes {\n"
         "  _id, user_id, current_stop, destination, time_preference,\n"
         "  flagged, reason, ip_address, created_at\n"
         "}\n"
         "  index (current_stop, destination) | (created_at desc) | user_id\n"
         "\n"
         "tickets {\n"
         "  ticket_id, user_id, source_stop, destination_stop,\n"
         "  fare_amount,            <- what the passenger paid (0 for Shakti)\n"
         "  fare_value_inr,         <- what it would have cost (the claim)\n"
         "  fare_collected_inr, is_zero_fare, scheme,\n"
         "  issue_time, expiry_time, status, qr_token, short_code\n"
         "}\n"
         "\n"
         "waybills {\n"
         "  waybill_id (UNIQUE), conductor_id, driver_id, bus_reg, depot,\n"
         "  route_number, direction_id, duty_date, status(OPEN|CLOSED|RECONCILED),\n"
         "  sign_on_at, sign_off_at, opening_km, closing_km,\n"
         "  totals { tickets_issued, passengers, cash_amount, digital_amount,\n"
         "           pass_boardings, shakti_boardings, shakti_claim_value,\n"
         "           fare_value_total, fare_collected_total },\n"
         "  reconciliation { declared_cash, expected_cash, variance,\n"
         "                   variance_flagged, note, remitted_at }\n"
         "}\n"
         "  index (conductor_id, status) | (depot, duty_date desc) | waybill_id UNIQUE\n"
         "\n"
         "conductor_tickets {\n"
         "  ticket_id, client_ticket_uuid, waybill_id, conductor_id, route_number,\n"
         "  from_stop, to_stop, is_ac, payment_mode, passengers,\n"
         "  lines[ { passenger_type, count, unit_fare_value_inr, fare_value_inr,\n"
         "            fare_collected_inr, is_zero_fare, scheme } ],\n"
         "  fare_value_inr, fare_collected_inr, shakti_boardings,\n"
         "  shakti_claim_value, issued_at, synced_at\n"
         "}\n"
         "  index (waybill_id, client_ticket_uuid) UNIQUE   <-- idempotency\n"
         "\n"
         "travel_passes { pass_id (UNIQUE), holder_name, pass_type, route_permission,\n"
         "                user_id, issued_by, issued_at, expires_at, status,\n"
         "                revoked_at, revoked_reason }\n"
         "\n"
         "audit_events  { action, actor_id, subject, metadata, created_at }   NO TTL\n"
         "usage_events  { event_type, metadata, created_at }                  TTL 90 days\n"
         "trip_shares   { code (UNIQUE), user_id, trip data, expires_at }     TTL 0 (at expiry)\n"
         "service_alerts{ title, description, severity, affected_routes,\n"
         "                affected_stops, status, created_by, created_at, resolved_at }\n"
         "crowd_reports { user_id, route_number, crowding_level, stop_name, created_at }\n"
         "favorites     { user_id, current_stop, destination, label }  UNIQUE triple\n"
         "bus_positions { bus_number, route_id, latitude, longitude, speed_kmh,\n"
         "                occupancy_pct, heading, next_stop, updated_at }\n"
         "transactions  { transaction_id, ticket_id, user_id, amount, status,\n"
         "                scheme, timestamp }")
    page_break(doc)

    h(doc, 1, "Appendix D - Environment Variables")
    callout(doc, "No real secret values appear here",
            "All secrets are shown as [REDACTED SECRET]. The repository contains none: .env files are "
            "gitignored, and only .env.example files with placeholders are committed.")
    code(doc,
         "# ---- Datasets (all required; the app refuses to start if any is missing) ----\n"
         "DATASET_PATH=../dataset/routes_cleaned.csv\n"
         "STOP_COORDINATES_PATH=../dataset/stops_cleaned.csv\n"
         "METRO_DATASET_PATH=../dataset/bengaluru_metro_network.csv\n"
         "FARES_DATASET_PATH=../dataset/fares.json\n"
         "DEPOT_DATASET_PATH=../dataset/BMTC_depot_place_zone.xlsx\n"
         "ARTIFACT_DIR=./artifacts\n"
         "\n"
         "# ---- Database (optional; the app degrades gracefully without it) ----\n"
         "MONGO_URI=mongodb://localhost:27017        # no credentials in the default\n"
         "MONGO_DB_NAME=bmtc\n"
         "MONGO_SERVER_SELECTION_TIMEOUT_MS=3000     # fail fast rather than hang 30 s\n"
         "\n"
         "# ---- Secrets ----\n"
         "JWT_SECRET_KEY=[REDACTED SECRET]           # unset -> random per process + warning\n"
         "TICKET_SIGNING_KEY=[REDACTED SECRET]       # unset -> derived from JWT_SECRET_KEY\n"
         "PASS_SIGNING_KEY=[REDACTED SECRET]         # unset -> derived from JWT_SECRET_KEY\n"
         "PASS_VERIFICATION_SECRET=[REDACTED SECRET]\n"
         "GOOGLE_MAPS_API_KEY=                       # empty -> feature skipped entirely\n"
         "TWILIO_AUTH_TOKEN=                         # unset -> the webhook refuses everything\n"
         "AVL_INGEST_KEY=                            # unset -> /avl/ingest refuses everything\n"
         "\n"
         "# ---- Network and limits ----\n"
         "CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173\n"
         "RATE_LIMIT_PER_MINUTE=120\n"
         "TRUST_PROXY_HEADERS=false                  # true only behind ONE trusted proxy\n"
         "\n"
         "# ---- Vehicle tracking ----\n"
         "TRACKING_FEED=simulated                    # simulated|gtfs_rt|http_json|push\n"
         "TRACKING_FEED_URL=\n"
         "TRACKING_FEED_FIELD_MAP=                   # JSON map for a bespoke ITS API\n"
         "TRACKING_POLL_SECONDS=10\n"
         "AVL_STALE_SECONDS=120                      # older positions are withheld\n"
         "\n"
         "# ---- GTFS ----\n"
         "GTFS_BUILD_ON_STARTUP=true\n"
         "GTFS_RT_ALLOW_SIMULATED=false              # dev only; serves a separate .sim.pb path\n"
         "GTFS_FEED_PREFIX=dbars                     # namespaces every id\n"
         "GTFS_PUBLISHER_NAME=DBARS (unofficial, derived from published BMTC data)\n"
         "\n"
         "# ---- Demo and seeding ----\n"
         "DEMO_PASS_MODE=false                       # accepts unsigned pass ids; labels them\n"
         "SEED_DEFAULT_ADMIN=false\n"
         "DEFAULT_ADMIN_PASSWORD=admin123            # refused when ENV=production\n"
         "\n"
         "# ---- Frontend (BUILD time, not runtime) ----\n"
         "VITE_API_URL=http://localhost:8000")
    page_break(doc)

    h(doc, 1, "Appendix E - Important Code Snippets")
    para(doc, "The five excerpts most worth being able to recognise and explain.")

    h(doc, 2, "E.1 The startup ordering (main.py)")
    code(doc,
         "app.state.predictor.train()          # engines ready FIRST\n"
         "...\n"
         "await init_db()                      # cannot raise; logs and continues\n"
         "if not db_available():\n"
         "    logger.warning(\"Starting without MongoDB: ... Route prediction is unaffected.\")")

    h(doc, 2, "E.2 Anchored stop resolution (route_geometry.py)")
    code(doc,
         "centre = (sorted(p[0] for p in known)[len(known)//2],      # median, not mean\n"
         "          sorted(p[1] for p in known)[len(known)//2])\n"
         "previous = centre\n"
         "for stop in stops:\n"
         "    record = distance_service.resolve_stop_record(stop, near=previous)\n"
         "    resolved.append(record)\n"
         "    if record is not None:\n"
         "        previous = record.point")

    h(doc, 2, "E.3 Idempotent offline sync (waybill_service.py)")
    code(doc,
         "try:\n"
         "    await db.conductor_tickets.insert_one(document)\n"
         "except DuplicateKeyError:\n"
         "    duplicates.append({\"client_ticket_uuid\": ticket.client_ticket_uuid})\n"
         "    continue\n"
         "# index: (waybill_id, client_ticket_uuid) UNIQUE -> the DATABASE enforces this")

    h(doc, 2, "E.4 The honesty gate (api/gtfs.py)")
    code(doc,
         "if not report[\"is_live\"] and not allow_simulated:\n"
         "    raise HTTPException(503, detail=(\n"
         "        \"Vehicle positions are currently produced by a simulation, not a BMTC \"\n"
         "        \"vehicle feed, and are therefore not published as GTFS-realtime.\"))")

    h(doc, 2, "E.5 Separating value from collection (core/shakti.py + tickets.py)")
    code(doc,
         "free_travel, reason = is_shakti_eligible(gender, is_ac=payload.is_ac)\n"
         "fare_value     = round(float(fare), 2)          # what the STATE reimburses\n"
         "fare_collected = 0.0 if free_travel else fare_value   # what the PASSENGER paid\n"
         "# One combined fare_amount field cannot express both.")
    page_break(doc)

    h(doc, 1, "Appendix F - Glossary")
    para(doc, "The full glossary is Section 31. The ten terms most likely to be asked about:")
    table(doc, ["Term", "One-line answer"], [
        ["Block", "One physical bus's day: pull out, chain of trips, pull in"],
        ["Duty", "One person's working day - distinct from a block"],
        ["Dead kilometres", "Distance run with no passengers aboard"],
        ["Interlining", "Letting one bus serve trips from different route numbers"],
        ["Spreadover", "Elapsed time from sign-on to final sign-off, including unpaid gaps"],
        ["GTFS", "The worldwide standard format for publishing transit timetables"],
        ["Idempotent", "Doing it twice has the same effect as doing it once"],
        ["Anchored resolution", "Resolving each stop relative to the previous one, so a route\ncannot jump between same-named places"],
        ["Shakti scheme", "Karnataka's free bus travel for women and transgender passengers\non non-AC services"],
        ["is_live", "The flag on every vehicle observation stating whether the data is\nreal; it gates the GTFS-Realtime endpoint"],
    ], widths=[1.6, 5.2])
    page_break(doc)

    h(doc, 1, "Appendix G - Interview Questions")
    para(doc, "Sections 27 to 29 contain roughly 130 questions with answers. The structure is:")
    table(doc, ["Section", "Contains"], [
        ["27.1 - 27.9", "Professor defense: basic, architecture, code, database, security, AI,\nfailure, scalability and critical questions, with spoken-length answers"],
        ["28.1 - 28.8", "Recruiter and interview: the project pitch, architecture, hardest problem,\ntechnology choices, feature deep dive, scaling, debugging, hindsight"],
        ["29.1 - 29.6", "95 rapid-fire questions with one-line answers, grouped by area"],
        ["30.1 - 30.5", "The same project explained in 30 seconds, 1, 3, 5 and 10 minutes"],
    ], widths=[1.4, 5.4])
    callout(doc, "The three questions most likely to catch you out",
            "1. \"Where is the AI?\" - There is none; say so plainly and describe the retrieval system "
            "instead. 2. \"How accurate is it?\" - 100% validity (relevance-set), 71.7% rank quality, "
            "19.2% single-label; defend the measurement methodology. 3. \"Is the tracking real?\" - No, it is simulated by default, and the "
            "code is built so it cannot be published as real.", warn=True)
    page_break(doc)

    h(doc, 1, "Appendix H - Identified Issues")
    para(doc, "Every finding raised in this document, in one list, with severity. Confirmed means "
              "visible in the code.")
    table(doc, ["#", "Issue", "Severity", "Status", "Section"], [
        ["1", "POST /train has no authentication and triggers a\nfull retrain", "High", "CONFIRMED", "13.1, 20.2"],
        ["2", "Zero frontend tests across 8,459 lines, including\nthe offline money queue", "High", "CONFIRMED", "21.3, 36.1"],
        ["3", "No global exception handler, no request ids, no\nmetrics or tracing", "High", "CONFIRMED", "18.2, 36.1"],
        ["4", "In-memory rate limiter and caches prevent running\nmore than one worker", "High", "CONFIRMED", "22.3, 36.1"],
        ["5", "No token revocation; logout is client-side only", "Medium", "CONFIRMED", "15.5"],
        ["6", "Tokens stored in localStorage (XSS exposure)", "Medium", "CONFIRMED", "15.5, 20.2"],
        ["7", "No multi-document transactions; a crash mid-sign-off\nleaves a waybill inconsistent", "Medium", "CONFIRMED", "14.6, 37"],
        ["8", "Misleading naming: train() trains nothing; the AI\nassistant is a string parser", "Medium", "CONFIRMED", "16.1, 37"],
        ["9", "average_speed_kmph duplicated in two parameter\nclasses that must stay in step", "Medium", "CONFIRMED", "37"],
        ["10", "Weak password policy (min 6) and no email\nverification", "Medium", "CONFIRMED", "15.5, 20.2"],
        ["11", "No login-specific throttling or account lockout", "Medium", "CONFIRMED", "20.2"],
        ["12", "1.6 MB frontend bundle with no code splitting", "Medium", "CONFIRMED", "23.3, 36.1"],
        ["13", "Cross-module calls to private methods\n(_get_context, _resolve_stop_name)", "Low", "CONFIRMED", "37"],
        ["14", "predictor.py exceeds 1,600 lines and mixes four\nresponsibilities", "Low", "CONFIRMED", "38.1"],
        ["15", "@vis.gl/react-google-maps declared but never used", "Low", "CONFIRMED", "2.2, 23.2"],
        ["16", "numpy, scipy and scikit-learn shipped in production\nfor a benchmark only", "Low", "CONFIRMED", "23.3"],
        ["17", "Three copies of the metro map PDF (~8.6 MB)", "Low", "CONFIRMED", "36.1"],
        ["18", "driver role exists with no interface or endpoints", "Low", "CONFIRMED", "1.5"],
        ["19", "Advisory endpoints write to in-memory lists that\nvanish on restart", "Low", "CONFIRMED", "37"],
        ["20", "No API versioning; inconsistent /api prefix", "Low", "CONFIRMED", "37"],
        ["21", "Three coexisting frontend styling approaches", "Low", "CONFIRMED", "37, 38.1"],
        ["22", "GTFS calendar declares daily service, overstating\nSundays (documented in the feed)", "Low", "CONFIRMED", "36.2"],
        ["23", "Memory footprint never measured", "Unknown", "UNCERTAIN", "22.3, 36.2"],
        ["24", "Test coverage percentage unknown - no tool\nconfigured", "Unknown", "UNCERTAIN", "21.3"],
        ["25", "Fare table currency versus current BMTC fares", "Unknown", "UNCERTAIN", "36.2"],
    ], widths=[0.3, 2.9, 0.75, 0.95, 0.9])

    para(doc, "")
    callout(doc, "Closing note",
            "This document was written from the source code of the repository, not from its "
            "documentation. Where the code and the README disagreed, the code was treated as the "
            "source of truth. Where something could not be established, it is marked UNCERTAIN or "
            "stated as not determinable. Nothing in this document was invented to fill a gap.")
