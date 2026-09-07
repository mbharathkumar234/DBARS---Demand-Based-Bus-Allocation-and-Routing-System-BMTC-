# -*- coding: utf-8 -*-
"""Sections 36-39: Weaknesses, technical debt, code quality, master map."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_36(doc):
    h(doc, 1, "36. Project Weaknesses & Improvements")
    para(doc, "Findings are separated into confirmed problems (visible in the code), likely concerns "
              "(reasonable inference), and suggested improvements. Being able to lead with these is a "
              "strength in a viva - an examiner trusts a candidate who found the flaws first.")

    h(doc, 2, "36.1 Confirmed problems")
    table(doc, ["Area", "Problem", "Evidence", "Impact"], [
        ["Testing", "Zero frontend tests. 8,459 lines of\nTypeScript verified only by the compiler", "package.json has no\ntest script", "High - the offline\nqueue handles money\nand is untested"],
        ["Security", "POST /train has no authentication and\ntriggers a full retrain", "api/routes.py train()", "High - trivial CPU\nexhaustion vector"],
        ["Security", "No token revocation; logout only clears\nlocalStorage", "No blacklist exists", "Medium - a stolen\ntoken lives 24 h"],
        ["Scalability", "Rate limiter, plan caches and vehicle\nstore all in process memory", "core/rate_limit.py,\nservice singletons", "High - blocks\nhorizontal scaling"],
        ["Observability", "No global exception handler, no request\nids, no metrics, no tracing", "None registered in\nmain.py", "High - production\ndebugging would be\nguesswork"],
        ["Reliability", "No multi-document transactions", "No start_session use\nanywhere", "Medium - a crash\nmid-sign-off leaves a\nwaybill inconsistent"],
        ["Naming", "train() does not train. The old string-parser\n'assistant' is superseded by the AI layer (section 40)", "ml/predictor.py", "Medium - actively\nmisleads readers and\ninvites bad claims"],
        ["Dependencies", "@vis.gl/react-google-maps declared but\nnever imported", "No import anywhere\nin src/", "Low - dead weight"],
        ["Dependencies", "numpy, scipy, scikit-learn shipped in\nproduction for a benchmark only", "requirements.txt vs\nml/tfidf.py usage", "Low - image size"],
        ["Frontend", "1.6 MB bundle (468 KB gzipped), no code\nsplitting", "Vite build warning", "Medium - slow first\nload on mobile"],
        ["Data", "Three copies of the metro map PDF\n(~8.6 MB total)", "dataset/ and\nfrontend/public/", "Low - repository\nbloat"],
        ["Auth", "No email verification, weak password\npolicy (min 6 chars)", "auth/routes.py\nRegisterRequest", "Medium"],
    ], widths=[1.0, 2.3, 1.6, 1.9])

    h(doc, 2, "36.2 Likely concerns")
    bullets(doc, [
        ("Memory footprint is unmeasured.", "655,438 stop pairs and 3.9M route segments live in "
         "memory, plus a 14 MB GTFS build. No profiling was done, so instance sizing would be "
         "guesswork. UNCERTAIN - measure before deploying."),
        ("The predictor is shared mutable state in principle.", "After train() it is only read, which "
         "makes concurrent access safe. But there is no lock and no explicit immutability, so a future "
         "change that writes to it during a request would introduce a race that is very hard to "
         "reproduce. INFERRED."),
        ("Fare accuracy depends on data that carries its own caveats.", "fares.json includes "
         "per-stage confidence notes, which is good practice, but the fares themselves may be out of "
         "date. Any revenue figure inherits that uncertainty."),
        ("The GTFS calendar overstates Sunday service.", "The dataset has no day-of-week information, "
         "so the feed declares one daily service. This is documented in the feed README, but a "
         "consumer who ignores it would be misled. CONFIRMED as a documented limitation."),
    ])

    h(doc, 2, "36.3 Suggested improvements, ranked by value for effort")
    table(doc, ["#", "Improvement", "Effort", "Why it is worth it"], [
        ["1", "Gate POST /train behind admin", "One line", "Closes the clearest security hole"],
        ["2", "Add a global exception handler with\nrequest ids and structured logging", "Half a day", "Turns production debugging from\nguesswork into a lookup"],
        ["3", "Frontend tests, starting with\noffline queue and apiClient", "Two days", "The largest untested surface, and it\nhandles money"],
        ["4", "Correct the misleading naming\n(train, AI assistant)", "Two hours", "Removes a claim you would otherwise\nhave to defend"],
        ["5", "Move rate limiting and caches to\nRedis", "Two days", "The precondition for running more\nthan one worker"],
        ["6", "Route-level code splitting", "One day", "Cuts first-load time substantially"],
        ["7", "Login throttling and a stronger\npassword policy", "Half a day", "Closes the practical brute-force path"],
        ["8", "Deduplicate the metro PDF; move the\nscientific stack to dev-only", "One hour", "Smaller repository and image"],
        ["9", "Driver role: give it an interface or\nremove it", "Varies", "Removes an obviously half-finished\nfeature from the codebase"],
        ["10", "Measure memory and add a coverage\ntool", "Half a day", "Replaces two UNCERTAIN answers with\nmeasured ones"],
    ], widths=[0.3, 2.2, 0.85, 3.45])
    page_break(doc)


def section_37(doc):
    h(doc, 1, "37. Technical Debt")
    para(doc, "Technical debt is a shortcut that works now and costs later. Each item below states "
              "what the shortcut was and what it will cost.")

    table(doc, ["Debt", "What it is", "Why it matters"], [
        ["Misleading names", "train() builds indexes and evaluates; it fits\nnothing. AssistantPanel is called an AI\nassistant but splits strings. The repository\nfolder was once named bmtc-ai-fixed.",
         "Names are documentation. These invite a\nfalse claim in an interview and mislead\nany new developer reading the code."],
        ["No frontend tests", "The backend has 161 tests; the frontend has\nnone, including the offline money queue.",
         "Every frontend change is verified by hand.\nA regression in offlineQueue.ts would lose\nreal sales silently."],
        ["In-memory shared state", "Rate limiter, blocking cache, crew cache,\nGTFS lock and vehicle store all live in\nprocess memory.",
         "The application cannot be scaled\nhorizontally without redesigning all five.\nThe debt is paid the day traffic grows."],
        ["No transactions", "Closing a waybill reads tickets, then writes\ntotals, with no atomic boundary.",
         "A crash between the two leaves a waybill\nOPEN with tickets recorded. Recovery is\nmanual."],
        ["Duplicated physical\nassumptions", "average_speed_kmph exists in both\nBlockingParameters and GtfsParameters.",
         "Changing one and not the other makes the\npublished timetable disagree with the fleet\nplan. The code comments warn about this,\nbut nothing enforces it."],
        ["Oversized files", "predictor.py is over 1,600 lines;\nPredictPage.tsx is 861; VotePage.tsx is 697.",
         "Hard to navigate and hard to review. The\npredictor mixes indexing, ranking, transfer\nsearch and benchmarking in one class."],
        ["Private methods called\nacross modules", "crew_service.py calls\nblocking_plan_service._get_context(), and\nwaybill_service calls predictor._resolve_\nstop_name().",
         "The leading underscore says \"internal\", so\nthese are informal contracts that can break\nsilently when the private method changes."],
        ["Mixed styling approaches", "Tailwind utility classes, a hand-written\nstyles.css design system, and large inline\nstyle objects all coexist.",
         "Three places to look when changing an\nappearance, and no single source of truth\nfor spacing or colour."],
        ["Advisory-only write\nendpoints", "/depot/deploy-bus and\n/depot/blocking-decision append to in-memory\nlists (DEPLOYED_BUSES, BLOCKING_DECISIONS).",
         "Those records vanish on restart. Honest as\na prototype - the code says so - but it is\nstate that looks persisted and is not."],
        ["No API versioning", "Endpoints are unversioned, except the\ninconsistent /api/tickets prefix.",
         "A breaking change would break every client\nat once. The inconsistent prefix also makes\nthe API surface look accidental."],
        ["Configuration drift risk", "VITE_API_URL is baked in at build time.",
         "A rebuilt frontend pointed at the wrong\nbackend fails in a way that looks like a\nnetwork fault. apiClient.ts exists because\nthis URL was once hard-coded in nine files."],
    ], widths=[1.35, 2.6, 2.85])

    callout(doc, "How to talk about technical debt in an interview",
            "Do not present this list apologetically. Presenting it at all is the signal. The strong "
            "framing is: \"here is what I would fix first and why\" - it shows you can evaluate your "
            "own work, which is what distinguishes an engineer from someone who only completes tasks. "
            "Pick the naming issue and the missing frontend tests as your two examples; both are "
            "concrete and both have an obvious fix.")
    page_break(doc)


def section_38(doc):
    h(doc, 1, "38. Code Quality Review")
    para(doc, "Observations are tied to specific code. Generic criticism is deliberately avoided.")

    h(doc, 2, "38.1 Assessment by dimension")
    table(doc, ["Dimension", "Rating", "Observation"], [
        ["Naming", "Mixed", "Domain vocabulary is excellent and correct: block, duty, piece,\nspreadover, dead kilometres, interlining, revenue service. These are\nthe real terms a transport planner uses. Against that, train() and\n\"AI assistant\" actively mislead."],
        ["Comments", "Strong", "Unusually good. Comments explain WHY, not what, and several record\nthe bug that motivated the code - for example the note above\nTOKEN_TYPE_ACCESS explaining that a ticket token once authenticated\nas a session. This is the single most valuable quality in the\ncodebase for a new reader."],
        ["Structure", "Strong", "The four-layer split is real and consistently followed. The\ndependency direction (api -> services -> db; api -> ml -> files) is\nnot violated anywhere examined."],
        ["Modularity", "Mixed", "The tracking and gtfs packages are well decomposed. predictor.py is\nnot - over 1,600 lines mixing indexing, ranking, transfer search and\nbenchmarking in one class."],
        ["Coupling", "Mostly low", "Good: the engines depend on nothing but the dataset. Weak points:\ncross-module calls to private methods (_get_context,\n_resolve_stop_name) create informal contracts."],
        ["Cohesion", "Strong", "Each service module owns one subject. core/shakti.py is a good\nexample - one rule, one file, two consumers."],
        ["Duplication", "Low, and\nactively\nreduced", "route_geometry.py was extracted precisely because three subsystems\nhad drifted apart doing the same thing. The remaining known\nduplication is average_speed_kmph in two parameter classes."],
        ["Error handling", "Strong at the\nedges, weak\nat the centre", "Excellent per-case handling with meaningful messages and honest\ndegradation. But there is no global handler, so an unexpected\nexception becomes an opaque 500."],
        ["Testing", "Strong\nbackend,\nabsent\nfrontend", "The backend tests are thoughtful - invariants and plausibility\nranges rather than brittle expected values. The frontend has none."],
        ["Security practice", "Good\nfundamentals", "Hashed passwords, signed tokens, separated key domains, role checks,\nserver-side pricing, no secrets in source. Gaps are known and\nlisted rather than hidden."],
        ["Type safety", "Good", "Python type hints throughout; pydantic at every boundary;\nTypeScript on the frontend. Some `any` casts remain in PredictPage."],
        ["Consistency", "Mixed", "Backend conventions are consistent. Frontend styling is not - three\napproaches coexist."],
    ], widths=[1.15, 0.95, 4.7])

    h(doc, 2, "38.2 The strongest quality in this codebase")
    para(doc, "The comments record decisions and the bugs that caused them. Examples worth quoting:")
    bullets(doc, [
        ("distance.py _minimal_normalize", "explains that stripping suffix words collapses "
         "\"Syndicate Bank\" and \"Syndicate Bank Layout\" - two real places 9 km apart - and that this "
         "fabricated bogus distances."),
        ("blocking.py module docstring", "separates what is measured from what is assumed, and states "
         "outright: do not quote a fuel or rupee figure from these numbers without replacing the "
         "assumptions first."),
        ("pytest.ini", "explains that strict asyncio mode exists because the previous setup skipped "
         "async tests while still reporting green."),
        ("rate_limit.py", "explains why /avl/ingest is exempt and notes it is exempt from the budget, "
         "not from authentication."),
    ])
    para(doc, "This matters practically: it is why this document could be written with confidence about "
              "WHY things are the way they are, not just what they do.")

    h(doc, 2, "38.3 The weakest quality")
    para(doc, "Naming that contradicts behaviour, and the absence of any frontend verification. Both "
              "are cheap to fix relative to their cost, and both are the first things a reviewer would "
              "raise.")
    page_break(doc)


def section_39(doc):
    h(doc, 1, "39. Final Project Master Map")

    h(doc, 2, "39.1 The whole system in one tree")
    code(doc,
         "DBARS\n"
         "|\n"
         "+-- USERS  (5 roles)\n"
         "|   +-- commuter       search, vote, e-ticket, crowding, safety share\n"
         "|   +-- conductor      waybill, onboard sales, pass scanning, cash sign-off\n"
         "|   +-- depot_manager  fleet blocking, crew duties, scenarios, waybill oversight\n"
         "|   +-- admin          dashboards, users, Shakti claim, revenue, audit\n"
         "|   +-- driver         role exists; no interface (declared gap)\n"
         "|\n"
         "+-- FRONTEND  React 19 + TypeScript + Vite    (8,459 lines, 45 files)\n"
         "|   +-- App.tsx            router, AuthProvider, LanguageProvider, ProtectedRoute\n"
         "|   +-- pages/             13 screens: Predict, Vote, Tickets, Track, Duty,\n"
         "|   |                      Scanner, Depot, Admin, Login, Register, Landing, Share\n"
         "|   +-- components/        RouteMap, BlockingPanel, CrewPanel, ScenarioConsole,\n"
         "|   |                      MetricsDashboard, AutocompleteInput, SafetyPanel\n"
         "|   +-- contexts/          AuthContext (token, role), LanguageContext (4 languages)\n"
         "|   +-- lib/               apiClient.ts (one HTTP wrapper), offlineQueue.ts (money)\n"
         "|\n"
         "+-- BACKEND  FastAPI + Python 3.12           (13,562 lines, 65 files, 82 endpoints)\n"
         "|   +-- API layer          app/api/ + app/auth/    HTTP only, no business rules\n"
         "|   +-- SERVICE layer      app/services/           business rules; ONLY DB access\n"
         "|   +-- ENGINE layer       app/ml/, app/gtfs/, app/tracking/   NO database at all\n"
         "|   |   +-- predictor.py   route search: 655,438 ordered stop pairs\n"
         "|   |   +-- blocking.py    fleet size + dead km: 6,849 buses, 44 depots\n"
         "|   |   +-- crew.py        duties: 15,636 duties, 2.28 crew per bus\n"
         "|   |   +-- gtfs/          47,295 trips, 1.46M stop_times, ~14 MB\n"
         "|   |   +-- tracking/      4 feed adapters, is_live gate, route-following ETA\n"
         "|   +-- DATA layer         app/db/ (Motor) + dataset/ (CSV, JSON, XLSX)\n"
         "|\n"
         "+-- DATABASE  MongoDB, 17 collections, OPTIONAL\n"
         "|   +-- users, votes, tickets, transactions, favorites, predictions, notifications\n"
         "|   +-- waybills, conductor_tickets, travel_passes, audit_events\n"
         "|   +-- service_alerts, crowd_reports, trip_shares (TTL 6h), usage_events (TTL 90d)\n"
         "|\n"
         "+-- EXTERNAL SERVICES  (all optional)\n"
         "|   +-- Google Maps Distance Matrix   optional; falls back to coordinates\n"
         "|   +-- Twilio SMS                    refuses everything when unconfigured\n"
         "|   +-- Fleet AVL feed                adapter written, not connected\n"
         "|   +-- OpenStreetMap / CARTO tiles   map background\n"
         "|\n"
         "+-- AI / ML\n"
         "|   +-- NONE. No model, no weights, no LLM, no inference API.\n"
         "|   +-- Classical IR + graph search, benchmarked against 3 baselines.\n"
         "|\n"
         "+-- DEPLOYMENT\n"
         "    +-- Docker Compose   backend:8000, frontend:8080 (nginx), mongo:27017\n"
         "    +-- Render / Vercel  alternative targets\n"
         "    +-- GitHub Actions   pytest + compileall + frontend build on every push\n"
         "    +-- Capacitor        Android APK from the built web bundle",
         caption="Figure 39.1 - The complete project map.")

    h(doc, 2, "39.2 The entire project in one page")
    para(doc, "PURPOSE. Turn BMTC's published timetable into three products: a commuter journey "
              "planner, an operations planner for depot managers, and an open GTFS data feed.", bold=True)
    para(doc, "ARCHITECTURE. Four backend layers with a one-way dependency rule. API handles HTTP; "
              "services hold business rules and are the only layer touching MongoDB; engines are pure "
              "computation over CSV files; the data layer owns the connection and the files. The "
              "engines' independence from the database is the defining decision - it is why route "
              "search, fleet planning, crew planning and GTFS export all survive a database outage, "
              "and why 161 tests run in CI with no MongoDB.", bold=True)
    para(doc, "TECHNOLOGY. Python 3.12, FastAPI, Pydantic, Motor, MongoDB. React 19, TypeScript, Vite, "
              "Leaflet, Tailwind. Docker Compose, Nginx, GitHub Actions, Capacitor. No ORM, no JWT "
              "library, no ML framework in the serving path.", bold=True)
    para(doc, "DATA FLOW. Browser -> apiFetch -> CORS -> rate limiter -> router -> pydantic validation "
              "-> auth dependency -> endpoint -> service or engine -> MongoDB or dataset -> JSON -> "
              "React state -> UI.", bold=True)
    para(doc, "TEN KEY FILES. main.py (entry point); ml/predictor.py (search engine); ml/blocking.py "
              "(fleet); ml/crew.py (duties); ml/route_geometry.py (anchored resolution); "
              "gtfs/builder.py (open data); tracking/ingest.py (vehicle honesty); auth/auth.py "
              "(security); services/waybill_service.py (money); core/shakti.py (the shared scheme rule).", bold=True)
    para(doc, "TEN KEY FUNCTIONS. predict(); _interchange_is_walkable(); resolve_stop_sequence(); "
              "chain_blocks(); concurrency_lower_bound(); cut_block_into_pieces(); "
              "combine_pieces_into_duties(); is_shakti_eligible(); issue_tickets(); estimate_arrival().", bold=True)
    para(doc, "DATABASE. MongoDB, 17 collections, no joins and no foreign keys. Critical indexes: "
              "users.email unique; conductor_tickets (waybill_id, client_ticket_uuid) unique, which is "
              "what makes offline ticketing idempotent; trip_shares TTL 6 hours; audit_events "
              "deliberately without a TTL.", bold=True)
    para(doc, "API. 82 endpoints across fourteen routers. Public: predict, autocomplete, GTFS, "
              "tracking, alerts. Role-gated: all depot planning, conductor money paths, admin "
              "reporting. Interactive docs at /docs.", bold=True)
    para(doc, "AI. None. The word appears in some UI text and is inaccurate. What exists is an "
              "inverted index plus an ordered stop-pair index with hand-weighted scoring, benchmarked "
              "against TF-IDF, fuzzy and distance-aware baselines - and the shipped model reports the "
              "accuracy of exactly what the API returns rather than a flattering proxy.", bold=True)
    para(doc, "SECURITY. PBKDF2-SHA256 passwords with per-user salts; HMAC-SHA256 signed tokens across "
              "three separate signing domains; role-based access control; server-side pricing; "
              "idempotent money writes; no secrets in source. Known gaps: POST /train unauthenticated, "
              "no token revocation, tokens in localStorage, in-memory rate limiting.", bold=True)
    para(doc, "DEPLOYMENT. Docker Compose with three services, or Render, or Vercel for the frontend. "
              "CI runs tests and builds but does not deploy. Single-process by design - horizontal "
              "scaling requires moving shared state to Redis first.", bold=True)
    para(doc, "THE GOVERNING PRINCIPLE. Never present modelled or simulated data as measured fact. "
              "Assumptions are bundled into parameter objects and echoed in every response; simulated "
              "vehicle positions carry an is_live flag that hard-gates the GTFS-Realtime endpoint; the "
              "GTFS feed marks every interpolated time and ships a provenance README; and endpoints "
              "that cannot answer say so rather than returning a misleading zero.", bold=True)

    h(doc, 2, "39.3 Analysis coverage statement")
    para(doc, "Analysed in depth: main.py, config.py, database.py, auth/auth.py, auth/routes.py, "
              "predictor.py, blocking.py, crew.py, distance.py, route_geometry.py, data_loader.py, "
              "gtfs/builder.py, gtfs/realtime.py, all five tracking modules, waybill_service.py, "
              "pass_service.py, shakti.py, fares.py, rate_limit.py, api/routes.py, api/tickets.py, "
              "api/conductor.py, api/gtfs.py, api/tracking.py, api/votes.py, App.tsx, AuthContext.tsx, "
              "apiClient.ts, offlineQueue.ts, RouteMap.tsx, and the test suite.")
    para(doc, "Analysed at a lower level of detail: admin.py, alerts.py, crowding.py, metro.py, "
              "safety.py, sms.py and their services; tfidf.py, stop_registry.py, text.py; seed.py; "
              "the larger page components (VotePage, AdminDashboard, LiveTracking) beyond their data "
              "flow; the Capacitor Android shell; and Docker and deployment files beyond their "
              "structure.")
    para(doc, "Not determinable from the supplied code: actual production memory usage; real-world "
              "prediction accuracy against genuine commuter journeys (no ground-truth data exists); "
              "test coverage percentage (no coverage tool is configured); and whether the fare table "
              "matches current BMTC fares.")
    page_break(doc)
