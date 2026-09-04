# -*- coding: utf-8 -*-
"""Sections 10-12: Function analysis, class analysis, line-by-line."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def _fn(doc, name, rows):
    h(doc, 3, name)
    table(doc, ["Aspect", "Detail"], rows, widths=[1.25, 5.55])


def section_10(doc):
    h(doc, 1, "10. Function-by-Function Analysis")
    para(doc, "The functions below are ordered by importance to the system, not by file order. "
              "Trivial helpers are omitted; the ones here are those an examiner is likely to ask "
              "about, or that you would need to understand before changing anything.")

    h(doc, 2, "10.1 BMTCBusPredictor.predict()")
    _fn(doc, "predict(current_stop, destination, limit=50)", [
        ["File", "backend/app/ml/predictor.py"],
        ["Purpose", "The single most important function in the project. Given two stop names typed by\na human, return the best bus (or bus chain) that connects them, plus alternatives."],
        ["Parameters", "current_stop (str) - what the user typed as their origin\ndestination (str) - what the user typed as their destination\nlimit (int) - how many alternatives to return"],
        ["Returns", "A dict with best_match, alternatives, message, resolved stop names,\nroute_coordinates, and legs when the journey needs a transfer"],
        ["Side effects", "None. It only reads in-memory indexes built during train()."],
        ["Dependencies", "_resolve_stop_name, _find_transfer_suggestions, _detect_metro_interchange,\nGoogleMapsDistanceService"],
        ["Called by", "api/routes.py predict(); api/votes.py vote_allocation();\napi/sms.py; rank_dispatch_recommendations()"],
        ["Logic", "1. Normalise and fuzzy-resolve both stop names to real stops, keeping a\n   confidence score for each.\n2. Reject the request if the two resolve to the same place.\n3. Run _find_transfer_suggestions() to build direct and one-transfer journeys.\n4. If the best option is direct, build best_match from that single route.\n5. If the best option needs a transfer, build best_match from the chain,\n   combining stop paths and coordinates across legs.\n6. Attach metro interchange information if the path passes a metro station."],
        ["Beginner view", "Think of two lookup tables built once at startup: \"which buses stop here\"\nand \"which buses go from A to B in that order\". The function looks up both,\nassembles candidate journeys, scores them, and returns the best."],
        ["Example in", "predict(\"Majestic\", \"Marathahalli\", 3)"],
        ["Example out", "best_match.bus_number = \"335-G\", 24 stops, distance_km 19.2, 0 transfers"],
        ["Failure cases", "Raises ValueError when a stop name cannot be resolved at all, or when origin\nand destination resolve to the same stop. api/routes.py converts that into a\n422 response carrying the user's own words back to them."],
        ["Why it exists", "It is the product. Everything else in the commuter half of the app is built\naround this one answer."],
    ])

    h(doc, 2, "10.2 BMTCBusPredictor._interchange_is_walkable()")
    _fn(doc, "_interchange_is_walkable(path_tuples) -> bool", [
        ["File", "backend/app/ml/predictor.py"],
        ["Purpose", "Reject a proposed transfer whose two buses do not actually meet in the\nphysical world."],
        ["Parameters", "path_tuples - the raw candidate journey as a list of (route, start_index,\nend_index) tuples, before any leg objects are built"],
        ["Returns", "True if every changeover is within MAX_INTERCHANGE_WALK_KM (1.2 km)"],
        ["The problem", "Transfers are found by matching stop NAMES, and Bengaluru reuses names.\nBanashankari -> Hebbal was answered with \"take 215-K to Avalahalli, then\n285-M from Avalahalli\". Both stops are real and both are called Avalahalli -\nbut they are 28.6 km apart. The journey is impossible."],
        ["Two ordering rules", "It must run BEFORE _reanchor_legs(), which resolves a whole journey as one\nsequence and therefore forces the interchange onto a single point - checking\nafterwards would be asking whether two stops agree after making them agree.\nIt must also run BEFORE _make_transfer_leg(), because building a leg costs a\nfull distance walk and most rejects would be discarded immediately after."],
        ["Performance note", "Uses _route_points(), a per-route-direction cache of anchored coordinates.\nWithout it, this check turned one query from 1.2 s into 7.5 s."],
        ["Why it exists", "It is a correctness guard, not a cosmetic one. Without it the app tells a\ncommuter to change buses at a stop 28 km from where the second bus is."],
    ])

    h(doc, 2, "10.3 resolve_stop_sequence()")
    _fn(doc, "resolve_stop_sequence(stops, distance_service) -> list[StopRecord | None]", [
        ["File", "backend/app/ml/route_geometry.py"],
        ["Purpose", "Turn an ordered list of stop names into coordinates, each anchored to the\nprevious one, so a route does not teleport across the city."],
        ["Returns", "A list the SAME LENGTH as the input, with None where a name could not be\nresolved - so callers keep positional alignment with their stop names"],
        ["Logic", "Pass 1: resolve every name with no anchor, and take the median point as this\n        sequence's rough centre.\nPass 2: walk the list in order, resolving each name with near=<previous\n        accepted point>, so each stop is chosen as the one nearest its\n        neighbour rather than an arbitrary same-named place."],
        ["Why it matters", "Resolving BMTC route 335-G's stops independently drew a 69.4 km line for a\n19.2 km route: its \"Kodihalli\" matched the wrong Kodihalli 28 km east, so the\npath spiked out and back. The distances printed beside the map were always\ncorrect, because route_distance() already walked an anchor - only the drawing\nwas wrong, which is exactly why the bug survived review for so long."],
        ["Called by", "predictor._path_coordinates(), gtfs/builder.py, services/vehicle_service.py"],
        ["Why shared", "Three subsystems need the identical operation. Writing it three times is how\nthey drift apart; two of the three had already drifted before it was extracted."],
    ])

    h(doc, 2, "10.4 cut_block_into_pieces()")
    _fn(doc, "cut_block_into_pieces(block, block_index, parameters) -> list[DutyPiece] | None", [
        ["File", "backend/app/ml/crew.py"],
        ["Purpose", "Split one vehicle's whole day into the fewest legal pieces of crew work."],
        ["Parameters", "block - a Block from the blocking engine (one bus's chain of trips)\nparameters - CrewParameters holding the crew-agreement assumptions"],
        ["Returns", "A list of DutyPiece, or None when no legal split exists at all"],
        ["Algorithm", "A dynamic program, not a greedy scan. best[i] = fewest pieces covering\ntrips[i:]. For each start position it extends the piece while the working-time\nand continuous-driving limits still hold, considering only cut positions that\nare legal (a relief point, with at least min_relief_gap_minutes of turnaround)."],
        ["Why not greedy", "Greedy cutting - \"run until the limit, then cut\" - can be forced into an extra\npiece when a slightly earlier cut would have fitted the remainder. Blocks hold\ntens of trips, so the O(n^2) dynamic program is effectively free."],
        ["Complexity", "O(n^2) in the number of trips per block; n is at most 16 in this dataset"],
        ["Returns None when", "A block offers no legal relief opportunity - for example six hours of trips\nrunning back to back with no gap anywhere. Those blocks are reported as\nunstaffable rather than silently dropped, because hiding them would make the\nduty count look better than the schedule really is."],
    ])

    h(doc, 2, "10.5 combine_pieces_into_duties()")
    _fn(doc, "combine_pieces_into_duties(pieces, parameters) -> list[Duty]", [
        ["File", "backend/app/ml/crew.py"],
        ["Purpose", "Pair up pieces of work that one person could do as a single duty, which is\nwhat an operator means by a split duty."],
        ["Algorithm", "Every piece starts as its own duty. Processing in start-time order, each\nunpaired piece looks for the partner that uses the most of its remaining\nworking-time budget, subject to the spreadover ceiling and no overlap."],
        ["Performance", "Two devices keep this near-linear rather than quadratic: binary search to\nrestrict candidates to the spreadover window, and a path-compressed next_free\narray so already-paired pieces are skipped in O(1) instead of being re-scanned.\nMeasured: 36 s before, 1.6 s after, on 21,453 pieces - and it produced\nslightly FEWER duties."],
        ["Why greedy is safe", "Pairing only ever REDUCES the duty count, so a greedy result is a safe\nover-estimate of the crew required. Over-estimating crew is the right\ndirection to be wrong in when the output is a staffing number."],
    ])

    h(doc, 2, "10.6 is_shakti_eligible()")
    _fn(doc, "is_shakti_eligible(gender, *, is_ac=False) -> tuple[bool, str | None]", [
        ["File", "backend/app/core/shakti.py"],
        ["Purpose", "The single shared rule deciding whether a journey travels free under the\nKarnataka Shakti scheme."],
        ["Returns", "(eligible, reason_if_not). The reason is written to be shown to a passenger."],
        ["Rules", "1. No gender on the account -> not eligible, with a reason explaining how to\n   fix it.\n2. Gender not in {female, transgender} -> not eligible, reason None. The\n   scheme simply does not apply; returning an explanation would imply the\n   passenger had been assessed and refused.\n3. AC service -> not eligible, with a reason. The real scheme covers ordinary\n   services only; Vajra and Vayu Vajra are chargeable for everyone."],
        ["Called by", "api/tickets.py purchase_ticket(); services/waybill_service.py price_ticket();\nauth/routes.py _format_user()"],
        ["Why one function", "The commuter app and the conductor both need this rule. Two implementations\nwould eventually disagree, and a passenger told by the app that her journey is\nfree and then charged on the bus has been failed by the software twice."],
    ])

    h(doc, 2, "10.7 issue_tickets()")
    _fn(doc, "issue_tickets(conductor_id, tickets, request) -> dict", [
        ["File", "backend/app/services/waybill_service.py"],
        ["Purpose", "Record a batch of onboard sales, idempotently, so an offline device can replay\nits queue safely."],
        ["Returns", "Per-item lists: accepted, duplicates, rejected, plus counts"],
        ["Idempotency", "Each sale carries a client-generated UUID. A unique MongoDB index on\n(waybill_id, client_ticket_uuid) turns a replay into a DuplicateKeyError,\nwhich is caught and reported as 'duplicate' - the offline queue working\ncorrectly, not an error."],
        ["Per-item results", "The device must clear only what the server acknowledged. Clearing the whole\nqueue on a 200 response is exactly how offline sales vanish, and a lost cash\nsale is indistinguishable afterwards from one that never happened."],
        ["Rejections", "An unknown waybill, another conductor's waybill, a CLOSED waybill (the normal\ncase for a late offline arrival), or an unpriceable journey"],
    ])

    h(doc, 2, "10.8 close_waybill()")
    _fn(doc, "close_waybill(conductor_id, payload) -> dict", [
        ["File", "backend/app/services/waybill_service.py"],
        ["Purpose", "End a duty: recompute the totals and compare declared cash against expected."],
        ["Key rule", "Totals are recomputed from the ticket rows by recompute_totals() and are NEVER\ntaken from the client. A client-supplied total in a revenue document is a fraud\nvector, and the device is a phone on a bus."],
        ["Variance", "variance = declared_cash - expected_cash. It is reported and flagged, never\nauto-corrected. A system that quietly adjusts a cash figure so the books\nbalance has destroyed the only signal the depot had."],
        ["Validation", "Refuses if the waybill is not OPEN, belongs to someone else, or if the closing\nodometer is below the opening reading"],
    ])

    h(doc, 2, "10.9 estimate_arrival()")
    _fn(doc, "estimate_arrival(projection, target_distance_km, ...) -> EtaEstimate | None", [
        ["File", "backend/app/tracking/matcher.py"],
        ["Purpose", "Work out when a bus will reach a stop, measured ALONG the route rather than\nin a straight line."],
        ["Returns", "None if the target is behind the bus - a bus that has passed your stop is not\narriving in negative minutes, and the caller should look for the next vehicle"],
        ["Confidence", "The label is derived from which speed source was available, not guessed:\nhigh   - observed speed on this stretch of route\nmedium - this vehicle's current reported speed\nlow    - the assumed average running speed\nThe returned range widens as confidence falls (15%, 25%, 40%)."],
        ["Why it replaced\nthe old version", "The previous estimate took a straight-line haversine distance, multiplied by\n1.4 and divided by current speed. That is wrong in a specific and misleading\nway: a bus 400 m away across a block can be fifteen minutes from you if the\nroute loops, and the old figure confidently said two."],
    ])

    h(doc, 2, "10.10 Other important functions, in brief")
    table(doc, ["Function", "File", "What it does and why it matters"], [
        ["train()", "ml/predictor.py", "Loads the CSV, builds every index, evaluates the models and\nwrites metrics.json. Runs once at startup."],
        ["_build_stop_pair_index()", "ml/predictor.py", "Builds the 655,438-entry ordered stop-pair index. This is what\nmakes the search fast enough to serve."],
        ["chain_blocks()", "ml/blocking.py", "Greedy earliest-available chaining of trips onto buses. Without an\nidle cap it provably matches the maximum-overlap lower bound."],
        ["concurrency_lower_bound()", "ml/blocking.py", "Peak simultaneous trips - a hard floor on fleet size. Lets the\noutput say \"provably minimal\" rather than \"best we found\"."],
        ["resolve_stop_record()", "ml/distance.py", "Resolves a stop name to a published stop row, using a near anchor\nto disambiguate repeated names."],
        ["get_fare()", "core/fares.py", "The single authoritative fare path, used by both the commuter\ne-ticket and the conductor sale."],
        ["hash_password() /\nverify_password()", "auth/auth.py", "PBKDF2-SHA256 with a per-user random salt; verification uses a\nconstant-time comparison."],
        ["require_role()", "auth/auth.py", "A dependency factory - returns a dependency that enforces a set of\nallowed roles on an endpoint."],
        ["build_service_alerts_feed()", "gtfs/realtime.py", "Turns real depot alerts into GTFS-RT, checking every referenced id\nagainst the published static feed."],
        ["flush()", "lib/offlineQueue.ts", "Drains the offline sale queue and clears only acknowledged items."],
    ], widths=[1.6, 1.3, 3.9])
    page_break(doc)


def section_11(doc):
    h(doc, 1, "11. Class-by-Class Analysis")
    para(doc, "A class is a template that bundles data (attributes) with the operations on that data "
              "(methods). An object is one instance made from that template. DBARS uses classes for "
              "three purposes: long-lived engines that hold expensive indexes, small immutable value "
              "records, and parameter bundles that make assumptions explicit.")

    h(doc, 2, "11.1 BMTCBusPredictor")
    table(doc, ["Aspect", "Detail"], [
        ["File", "backend/app/ml/predictor.py"],
        ["Responsibility", "Own the route dataset and every index built from it, and answer journey queries"],
        ["Constructor", "__init__(dataset_path, artifact_dir) - stores paths only; builds nothing"],
        ["Key attributes", "routes - list[RouteRecord] loaded from the CSV\nstop_names, destination_names - sorted name lists for autocomplete\nstop_to_route_indices - dict: normalised stop -> set of route indexes\nstop_pair_to_segments - dict: (A,B) -> route segments, 655,438 entries\nstop_registry - stable hashed IDs for stops\ndistance_service - the coordinate and distance resolver\n_route_points_cache - anchored coordinates per route-direction\nmetrics, profile - benchmark results and dataset statistics"],
        ["Key methods", "train(), predict(), autocomplete(), list_routes(), _rank(),\n_find_transfer_suggestions(), _interchange_is_walkable(), _reanchor_legs(),\n_evaluate_models(), _cross_validate()"],
        ["Lifecycle", "Constructed once in create_app(); trained once in lifespan(); then read-only\nand shared by every request through app.state.predictor"],
        ["Why a class", "It holds roughly 4 million indexed route segments. Rebuilding that per request\nwould be impossible, so the state must live somewhere long-lived. A class\ninstance stored on app.state is exactly that."],
        ["Thread safety", "After train() the object is only read, which is why it is safe to call from\nasyncio.to_thread(). INFERRED - there is no lock, and no write path after\ntraining, so concurrent reads are safe."],
    ], widths=[1.25, 5.55])

    h(doc, 2, "11.2 BlockingEngine")
    table(doc, ["Aspect", "Detail"], [
        ["File", "backend/app/ml/blocking.py"],
        ["Responsibility", "Answer the operations question: how few buses can hold this timetable, and\nhow many kilometres are run empty"],
        ["Constructor", "__init__(routes, depots, distance_service, parameters=None)"],
        ["Key attributes", "routes, depots, parameters (BlockingParameters),\n_point_cache, _geometry_cache, _neighbour_cache - three caches, because the\nsame geometry is consulted thousands of times"],
        ["Key methods", "route_polyline(), route_length_km(), running_time_minutes(), assign_depot(),\nbuild_trips(), chain_blocks(), concurrency_lower_bound(), apply_dead_km(),\nblock_by_route(), block_interlined(), revenue_service()"],
        ["Domain idea", "A bus does not run \"a route\". It runs a BLOCK: it pulls out of its depot,\nruns a chain of trips back to back, and pulls back in. Two costs follow -\npeak vehicle requirement (which sizes the fleet) and dead kilometres\n(distance run with no passengers)."],
        ["Why a class", "It caches geometry and depot assignment across many queries, and the scenario\nconsole re-uses one engine for repeated what-if runs."],
    ], widths=[1.25, 5.55])

    h(doc, 2, "11.3 Parameter classes - BlockingParameters and CrewParameters")
    para(doc, "These two frozen dataclasses are the most quotable design decision in the project.")
    table(doc, ["Class", "Holds", "Why it exists"], [
        ["BlockingParameters", "average_speed_kmph (16.0),\ndwell_minutes_per_stop (0.3),\nlayover_minutes (10),\nmax_terminal_idle_minutes,\nmax_deadhead_km (5.0),\nduty_limit_minutes (480),\ncircuity_factor (1.2)",
         "Every one of these is an ASSUMPTION, not a BMTC\nmeasurement. Bundling them into one frozen object\nmeans they can be listed in the API response,\nvaried in a scenario, and corrected without\nhunting through the code. Each field carries a\ndocstring explaining what it means and how wrong\nit might be."],
        ["CrewParameters", "sign_on_minutes (15),\nsign_off_minutes (15),\nmax_continuous_driving (240),\nmin_break_minutes (30),\nmax_working_minutes (480),\nmax_spreadover_minutes (720),\nmin_relief_gap_minutes (10),\nallow_split_duties,\nrelief_points",
         "BMTC's real crew agreement is not in any published\ndataset, so all seven values are assumptions. The\n.assumptions property echoes them into every API\nresponse, so a reader can never mistake a modelled\nnumber for a measured one."],
    ], widths=[1.3, 2.5, 3.0])
    callout(doc, "How to talk about this in a viva",
            "If asked \"how accurate is your fleet number?\", the strong answer is not a number - it is "
            "this design. The honest version of the analysis is \"here is the structure; please replace "
            "our four assumptions with your observed running times\". Surfacing assumptions rather than "
            "burying them is what separates a model from a guess. CONFIRMED: ml/blocking.py module "
            "docstring says exactly this.")

    h(doc, 2, "11.4 Value classes (small immutable records)")
    table(doc, ["Class", "File", "Fields and purpose"], [
        ["RouteRecord", "ml/data_loader.py", "One route-direction from the CSV. __post_init__ precomputes\nstop_positions, is_self_loop and search_text once at load time -\nprofiling showed 512,956 repeated normalize_text calls costing\n7.0 s without it."],
        ["StopRecord", "ml/distance.py", "One physical stop: stop_id, stop_name, zone_id, lat, lon.\nAdded so the GTFS exporter could reach the published stop_id,\nwhich resolve_coordinate() used to discard."],
        ["Trip", "ml/blocking.py", "One scheduled journey: route, direction, departure and arrival\nminute, origin, destination, revenue_km."],
        ["Block", "ml/blocking.py", "One physical bus's day. Properties compute revenue_km, dead_km,\nstart, end and idle_minutes from its trips."],
        ["DutyPiece", "ml/crew.py", "An unbroken stretch of crew work - the atom of crew scheduling.\nIt cannot be split further and cannot be shared."],
        ["Duty", "ml/crew.py", "One person's day: one piece, or two with an unpaid gap between\nthem. Distinguishes working_minutes (paid) from\nspreadover_minutes (elapsed)."],
        ["VehicleObservation", "tracking/base.py", "One sighting of one vehicle. Carries recorded_at (the SOURCE\ntime, never receipt time) and is_live."],
        ["Projection", "tracking/matcher.py", "Where a vehicle sits along a route line, plus offset_km - how\nfar it is from the line, which tells you whether to trust it."],
    ], widths=[1.35, 1.35, 4.1])

    h(doc, 2, "11.5 Service classes (stateful, cached)")
    table(doc, ["Class", "Responsibility", "Concurrency handling"], [
        ["BlockingPlanService", "Computes the fleet plan once (~25 s) and caches it,\nplus a reusable engine context for scenarios",
         "asyncio.Lock with a re-check inside,\nso queued callers take the first result\nrather than each starting a computation"],
        ["CrewPlanService", "Same pattern for the crew plan; reuses the blocking\nservice's cached context rather than rebuilding",
         "asyncio.Lock, same double-check"],
        ["GtfsFeedService", "Builds and caches the ~14 MB GTFS zip; can adopt a\nfeed a previous process left on disk",
         "asyncio.Lock; the build runs in a\nthread via asyncio.to_thread"],
        ["VehicleStateStore", "Latest observation per vehicle, with the staleness rule",
         "Single-threaded access from the ingest\nloop and request handlers"],
        ["VehicleIngestService", "Owns the poll loop, backoff, and honest source reporting",
         "asyncio.Event for cooperative shutdown"],
        ["BusSimulator", "The physics simulation behind simulated positions",
         "asyncio.Lock so N concurrent viewers\nproduce one shared timeline, not N\nstacked ones"],
    ], widths=[1.5, 3.0, 2.3])

    h(doc, 2, "11.6 VehicleFeed - an interface, not a class")
    para(doc, "VehicleFeed is a typing.Protocol: a description of the shape any vehicle feed must "
              "have (a name, an is_live flag, and start/stop/poll methods), without inheritance. "
              "Four adapters satisfy it - SimulatedFeed, GtfsRealtimeFeed, HttpJsonFeed and "
              "PushIngestFeed - and build_feed() returns whichever one TRACKING_FEED names.")
    para(doc, "This is the classic strategy pattern. Its value here is precise: the rest of the "
              "system depends on the interface, so swapping the simulator for a real BMTC feed is a "
              "configuration change rather than a code change - and every honesty gate in the "
              "codebase reads is_live from whichever adapter is active.")
    evidence(doc, "backend/app/tracking/base.py; backend/app/tracking/adapters.py")
    page_break(doc)


def section_12(doc):
    h(doc, 1, "12. Line-by-Line Code Explanation")
    para(doc, "This section walks through the code that matters most, in small logical blocks. "
              "Each block follows the same five levels: WHAT it does, HOW it does it, WHY it is "
              "written that way, how it CONNECTS to the rest of the system, and what the "
              "CONSEQUENCE of changing it would be.")

    h(doc, 2, "12.1 Application assembly - main.py")
    code(doc,
         "app.add_middleware(\n"
         "    RateLimitMiddleware,\n"
         "    max_requests_per_minute=settings.rate_limit_per_minute,\n"
         "    trust_proxy_headers=settings.trust_proxy_headers,\n"
         ")\n"
         "app.add_middleware(\n"
         "    CORSMiddleware,\n"
         "    allow_origins=list(settings.cors_origins),\n"
         "    allow_credentials=\"*\" not in settings.cors_origins,\n"
         "    allow_methods=[\"*\"],\n"
         "    allow_headers=[\"*\"],\n"
         ")")
    bullets(doc, [
        ("WHAT.", "Attaches two pieces of middleware - code that sees every request before it reaches an endpoint."),
        ("HOW.", "add_middleware wraps the application. In Starlette the middleware added LAST ends up OUTERMOST, so CORS wraps rate limiting."),
        ("WHY.", "The ordering is deliberate and commented in the source. If rate limiting were outermost, a 429 response would be sent without CORS headers, and the browser would refuse to let JavaScript read it - the user would see an opaque network failure instead of \"too many requests\"."),
        ("CONNECTION.", "Every request in Section 4.1 passes through both of these before any endpoint runs."),
        ("CONSEQUENCE.", "Swap the two lines and rate-limited responses become unreadable in the browser."),
    ])
    para(doc, "allow_credentials is computed rather than hard-coded: it is True only when the origin "
              "list is not a wildcard. Browsers refuse to send credentials to a wildcard origin, so "
              "setting both would be a silent misconfiguration.")

    h(doc, 2, "12.2 The startup ordering that defines the project - main.py lifespan()")
    code(doc,
         "logger.info(\"Training BMTC predictor from %s\", settings.dataset_path)\n"
         "app.state.predictor.train()\n"
         "...\n"
         "await init_db()\n"
         "if db_available():\n"
         "    logger.info(\"MongoDB connection established and database initialized\")\n"
         "else:\n"
         "    logger.warning(\n"
         "        \"Starting without MongoDB: account, voting, ticketing, and admin/depot \"\n"
         "        \"features are unavailable until it is reachable. Route prediction is unaffected.\"\n"
         "    )")
    bullets(doc, [
        ("WHAT.", "Trains the route engine, then tries to connect to MongoDB."),
        ("HOW.", "train() is synchronous and blocking - the server accepts no traffic until it finishes (~7 s). init_db() is awaited but cannot raise; it catches PyMongoError internally."),
        ("WHY.", "This exact order is the architectural decision of the project. Route prediction is already working before the database is even attempted, so an unreachable database cannot take the core feature down."),
        ("CONNECTION.", "It is why /predict, /depot/blocking-plan, /depot/crew-plan and /gtfs/static.zip all work with Mongo stopped, while /votes returns a clear 503."),
        ("CONSEQUENCE.", "Reverse these two steps, or let init_db() raise, and a database outage becomes a total outage. The init_db docstring records that this used to happen."),
    ])
    evidence(doc, "backend/app/main.py; backend/app/db/database.py -> init_db()")

    h(doc, 2, "12.3 Password hashing - auth/auth.py")
    code(doc,
         "def hash_password(password: str) -> str:\n"
         "    \"\"\"Hash a password using PBKDF2-SHA256 (stdlib, no bcrypt needed).\"\"\"\n"
         "    import os\n"
         "    salt = os.urandom(16)\n"
         "    ...")
    bullets(doc, [
        ("WHAT.", "Converts a plain-text password into a value safe to store."),
        ("HOW.", "PBKDF2-SHA256 with a fresh 16-byte random salt per user. Hashing is one-way: you cannot reverse the output back to the password."),
        ("WHY a salt.", "Without one, two users who chose the same password would produce the same hash, and a precomputed rainbow table would crack both at once. A per-user random salt makes every hash unique."),
        ("WHY PBKDF2.", "It is deliberately slow, so brute-forcing many guesses is expensive. It is in the Python standard library, so the project needs no bcrypt dependency."),
        ("CONNECTION.", "Called by register() and by admin user creation; verify_password() is its counterpart at login."),
        ("CONSEQUENCE.", "Store passwords in plain text, or hash with plain SHA-256 and no salt, and a database leak becomes an immediate account compromise for every user."),
    ])
    callout(doc, "Honest assessment for a security question",
            "PBKDF2-SHA256 with a random salt is a legitimate, standards-based choice and far better "
            "than plain hashing. It is not the strongest option available: bcrypt, scrypt and Argon2 "
            "are more resistant to GPU attack. If an examiner asks how you would harden it, that is "
            "the answer. Do not claim the scheme is unbreakable.")

    h(doc, 2, "12.4 Token creation and the three domains - auth/auth.py")
    code(doc,
         "def _sign(payload: str, secret: str) -> str:\n"
         "    return _b64_encode(\n"
         "        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()\n"
         "    )\n"
         "\n"
         "def create_token(data, expires_seconds=ACCESS_TOKEN_EXPIRE_SECONDS, secret=None):\n"
         "    header = _b64_encode(json.dumps({\"alg\": ALGORITHM, \"typ\": \"JWT\"}).encode())\n"
         "    payload_data = {**data, \"exp\": int(time.time()) + expires_seconds,\n"
         "                    \"iat\": int(time.time())}\n"
         "    payload = _b64_encode(json.dumps(payload_data).encode())\n"
         "    signature = _sign(f\"{header}.{payload}\", secret or SECRET_KEY)\n"
         "    return f\"{header}.{payload}.{signature}\"")
    bullets(doc, [
        ("WHAT.", "Builds a JSON Web Token by hand: three base64url pieces joined by dots."),
        ("HOW.", "The header and payload are readable by anyone - base64 is encoding, not encryption. The third piece is an HMAC-SHA256 signature over the first two, computed with a secret only the server knows."),
        ("WHY it is secure without hiding the contents.", "The point is not secrecy, it is tamper-detection. Change the role claim from commuter to admin and the signature no longer matches, so decode_token() rejects it."),
        ("WHY a secret parameter.", "The same function mints three different kinds of credential with three different keys, so a stolen ticket key cannot forge a session."),
        ("CONNECTION.", "Every protected endpoint depends on get_current_user(), which calls decode_token()."),
        ("CONSEQUENCE.", "Never put a password or anything sensitive in a token payload - it is publicly readable. This is exactly why the project does not put gender in the token and reads it from the account instead."),
    ])
    para(doc, "decode_token() verifies with hmac.compare_digest, a constant-time comparison. A normal "
              "== comparison returns faster when the first characters differ, and that timing "
              "difference can leak information about the correct value.")

    h(doc, 2, "12.5 The secret-key decision - auth/auth.py")
    code(doc,
         "if settings.jwt_secret_key:\n"
         "    SECRET_KEY = settings.jwt_secret_key\n"
         "else:\n"
         "    SECRET_KEY = secrets.token_hex(32)\n"
         "    logger.warning(\n"
         "        \"JWT_SECRET_KEY is not set. Generated a random, process-local secret ...\"\n"
         "    )")
    bullets(doc, [
        ("WHAT.", "Reads the signing key from configuration, or generates a random one."),
        ("WHY not a default constant.", "This code previously contained a fixed literal committed to source control. Anyone who had ever seen the repository could forge a valid token for any user, including an admin, with no password. A secret readable in source control is not a secret."),
        ("WHY random rather than a second fixed fallback.", "A random per-process key keeps local development working with zero configuration, while guaranteeing no guessable secret is ever baked in again."),
        ("The trade-off, stated honestly.", "Tokens stop validating after a restart, and in a multi-worker deployment each worker would sign with a different key. That is the correct failure mode for an unconfigured environment, and it is why a loud warning is logged."),
        ("CONSEQUENCE.", "In production JWT_SECRET_KEY must be set, or users are logged out on every restart."),
    ])

    h(doc, 2, "12.6 The anchoring fix - ml/route_geometry.py")
    code(doc,
         "rough = [distance_service.resolve_stop_record(stop) for stop in stops]\n"
         "known = [record.point for record in rough if record]\n"
         "if not known:\n"
         "    return [None] * len(stops)\n"
         "\n"
         "centre = (\n"
         "    sorted(point[0] for point in known)[len(known) // 2],\n"
         "    sorted(point[1] for point in known)[len(known) // 2],\n"
         ")\n"
         "\n"
         "resolved = []\n"
         "previous = centre\n"
         "for stop in stops:\n"
         "    record = distance_service.resolve_stop_record(stop, near=previous)\n"
         "    resolved.append(record)\n"
         "    if record is not None:\n"
         "        previous = record.point\n"
         "return resolved")
    bullets(doc, [
        ("WHAT.", "Turns a list of stop names into coordinates without the route jumping across the city."),
        ("HOW - pass 1.", "Resolve every name with no anchor and take the MEDIAN latitude and longitude. The median is used rather than the mean because one badly-resolved outlier 28 km away would drag a mean with it; a median ignores it."),
        ("HOW - pass 2.", "Walk the list in order, resolving each stop with near=<previous accepted point>. Each stop is chosen as the instance nearest its neighbour."),
        ("WHY.", "Bengaluru reuses stop names. Route 335-G drew a 69.4 km line for a 19.2 km journey because its \"Kodihalli\" matched the wrong Kodihalli 28 km east."),
        ("CONNECTION.", "Three subsystems call this: the predictor's map coordinates, the GTFS exporter's stop_times, and vehicle projection for ETAs."),
        ("CONSEQUENCE.", "Remove the anchoring and every route map, every GTFS shape and every ETA becomes wrong for any route touching a repeated stop name."),
    ])
    para(doc, "Note the return contract: the list is the SAME LENGTH as the input, with None where a "
              "name failed. Returning a shorter list would silently shift every later stop up by one "
              "position, corrupting the pairing of names to coordinates.")

    h(doc, 2, "12.7 Idempotent offline sync - services/waybill_service.py")
    code(doc,
         "try:\n"
         "    await db.conductor_tickets.insert_one(document)\n"
         "except DuplicateKeyError:\n"
         "    # The device replayed a sale the server already has. This is\n"
         "    # the offline queue working correctly, not an error.\n"
         "    duplicates.append({\"client_ticket_uuid\": ticket.client_ticket_uuid})\n"
         "    continue")
    bullets(doc, [
        ("WHAT.", "Inserts one onboard sale, treating a repeat as a duplicate rather than a failure."),
        ("HOW.", "A unique index on (waybill_id, client_ticket_uuid) makes MongoDB itself reject the second insert. The database enforces the rule, not application logic - so a race between two concurrent sync requests cannot slip through."),
        ("WHY the UUID comes from the client.", "The device must be able to retry without knowing whether the first attempt reached the server. A server-generated id cannot do that, because a retry would look like a brand-new sale."),
        ("CONNECTION.", "lib/offlineQueue.ts replays the queue until acknowledged, and clears only settled items."),
        ("CONSEQUENCE.", "Drop the unique index and every retry on a flaky bus connection inflates the day's revenue."),
    ])

    h(doc, 2, "12.8 The honesty gate - api/gtfs.py")
    code(doc,
         "if not report[\"is_live\"] and not allow_simulated:\n"
         "    raise HTTPException(\n"
         "        status_code=503,\n"
         "        detail=(\n"
         "            \"Vehicle positions are currently produced by a simulation, not a BMTC \"\n"
         "            \"vehicle feed, and are therefore not published as GTFS-realtime. ...\"\n"
         "        ),\n"
         "    )")
    bullets(doc, [
        ("WHAT.", "Refuses to publish vehicle positions as GTFS-Realtime while they come from the simulator."),
        ("HOW.", "is_live is a property of the ACTIVE ADAPTER, not of the endpoint, so it travels with the data and cannot be overridden by the layer serving it."),
        ("WHY.", "GTFS-Realtime has no field meaning \"this data is simulated\". A consumer ingesting the feed could not tell. Publishing simulator output here would be indistinguishable from claiming BMTC's fleet is being tracked."),
        ("CONNECTION.", "The same flag drives GET /tracking/source and the is_live field on every /tracking/buses payload."),
        ("CONSEQUENCE.", "Remove this check and the project becomes one that fabricates a government data feed. This single gate is the reason the whole adapter layer exists rather than a five-line wrapper over the simulator."),
    ])

    h(doc, 2, "12.9 The staleness rule - tracking/store.py")
    code(doc,
         "def fresh(self) -> list[VehicleObservation]:\n"
         "    now = datetime.now(timezone.utc)\n"
         "    return [\n"
         "        observation for observation in self._observations.values()\n"
         "        if observation.age_seconds(now) <= self.stale_after_seconds\n"
         "    ]")
    bullets(doc, [
        ("WHAT.", "Returns only observations recent enough to be worth showing."),
        ("HOW.", "age is computed from recorded_at, the time the SOURCE observed the vehicle - never the time the server received it."),
        ("WHY that distinction matters.", "A feed that stalls keeps returning its last payload. If the timestamp were stamped on receipt, every stale position would look freshly observed, and the map would show a fleet of ghosts frozen mid-road that riders would stand and wait for."),
        ("CONNECTION.", "Stale vehicles are still counted and surfaced in /tracking/source, so a stalled feed is visible rather than silently shrinking the fleet."),
        ("CONSEQUENCE.", "Remove it and a broken upstream feed becomes indistinguishable from a working one."),
    ])

    h(doc, 2, "12.10 Moving CPU work off the event loop - api/routes.py")
    code(doc,
         "# A real graph search over the stop index, ~1s of CPU. Off the event\n"
         "# loop, or every other request queued behind it waits that long too.\n"
         "prediction = await asyncio.to_thread(predictor.predict, current_stop, destination, 4)")
    bullets(doc, [
        ("WHAT.", "Runs the route search on a worker thread instead of the main async loop."),
        ("HOW.", "asyncio.to_thread hands the function to a thread pool and awaits the result, freeing the event loop meanwhile."),
        ("WHY.", "FastAPI serves many requests concurrently on ONE thread. A synchronous function that takes a second blocks that thread completely - every other user waits a full second, not just the one who asked."),
        ("Beginner analogy.", "The event loop is a single receptionist serving many visitors quickly. A one-second computation is a visitor who monopolises the desk. to_thread sends that visitor to a back office so the queue keeps moving."),
        ("CONSEQUENCE.", "Call predictor.predict() directly in an async endpoint and throughput collapses under concurrent load."),
    ])
    page_break(doc)
