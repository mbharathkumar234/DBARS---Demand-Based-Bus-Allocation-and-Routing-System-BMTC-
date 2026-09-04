# -*- coding: utf-8 -*-
"""Sections 26-30: Full story, professor defense, recruiter, rapid-fire, depths."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def _qa(doc, items):
    for q, a in items:
        p = doc.add_paragraph()
        r = p.add_run("Q. " + q)
        r.bold = True
        p.paragraph_format.space_after = 2
        p2 = doc.add_paragraph()
        p2.add_run("A. " + a)
        p2.paragraph_format.space_after = 8
        p2.paragraph_format.left_indent = __import__("docx").shared.Inches(0.18)


def section_26(doc):
    h(doc, 1, "26. How This Project Works From Start to Finish")
    para(doc, "This is the long-form answer to \"forget the files, explain your whole project to me\". "
              "It is written so that someone who has never seen the source can follow it.")

    h(doc, 2, "26.1 The starting point: a spreadsheet")
    para(doc, "Everything begins with a file: dataset/routes_cleaned.csv. It is BMTC's published "
              "timetable, and it contains 6,737 rows. Each row is one route in one direction - for "
              "example bus 335-G travelling from Majestic toward Marathahalli - and each row lists the "
              "stops in order and the times that bus departs through the day. Across all rows there "
              "are 3,940 distinct bus numbers and 4,883 distinct stops. A second file, "
              "stops_cleaned.csv, gives each stop a latitude and longitude.")
    para(doc, "That is all the raw material. Everything DBARS produces - route answers, fleet sizes, "
              "crew rosters, an open data feed - is squeezed out of those two files. No BMTC API is "
              "called, because none is available.")

    h(doc, 2, "26.2 What happens when the server starts")
    para(doc, "When the backend boots, it first checks that those data files exist and refuses to "
              "start if any is missing - an application with no timetable cannot answer anything, so "
              "failing loudly at boot is better than failing mysteriously later.")
    para(doc, "It then spends about seven seconds building indexes. The important one records, for "
              "every route, every ordered pair of stops along it: \"bus 335-G goes from Majestic to "
              "Marathahalli in that order\". Doing this once produces 655,438 such pairs. It is the "
              "difference between answering a query with a single dictionary lookup and scanning all "
              "6,737 routes every time somebody asks a question.")
    para(doc, "Two heavier computations then start in the background so nobody has to wait for them: "
              "the fleet blocking plan (about 25 seconds) and the GTFS export (about 11 seconds). "
              "Finally the server tries to connect to MongoDB. If MongoDB is not running, it logs a "
              "warning and carries on. That ordering is the single most important design decision in "
              "the project: route search is already working before the database is even attempted, so "
              "a database outage cannot take down the core feature.")

    h(doc, 2, "26.3 A commuter asks a question")
    para(doc, "Someone opens the app and types \"Majestic\" and \"Marathahalli\". Two things have to "
              "happen before a search can even begin. First, those words must be matched to real stop "
              "names - \"Majestic\" is a nickname; the official name is Kempegowda Bus Station, so the "
              "system expands known aliases and falls back to fuzzy string matching, keeping a "
              "confidence score. Second, the search itself runs.")
    para(doc, "The search looks up the ordered pair index for a direct bus. If one exists, that is the "
              "answer. If not, it builds two-leg journeys: buses that serve the origin, buses that "
              "serve the destination, and stops where the two sets meet. That last step is where a "
              "subtle and important bug lived. Transfers were matched by stop NAME, and Bengaluru "
              "reuses names - the system once told commuters to change buses at \"Avalahalli\", where "
              "the two stops of that name are 28.6 kilometres apart. A geometric check now rejects any "
              "changeover further apart than a short walk.")
    para(doc, "The whole search takes about a second of CPU, which is why the endpoint hands it to a "
              "worker thread. FastAPI serves many users on one thread; a one-second blocking call "
              "would make every other user wait a full second too.")
    para(doc, "The answer comes back with the bus number, the stops in between, the distance, an "
              "estimated fare, whether the route passes a metro station, and coordinates for drawing "
              "the route on a map.")

    h(doc, 2, "26.4 The commuter buys a ticket")
    para(doc, "The fare is computed on the server from the distance and BMTC's stage fare table - "
              "never trusted from the browser. Then something interesting happens. If the account "
              "records the passenger as female or transgender, and the service is an ordinary non-AC "
              "bus, the ticket is issued FREE under the Karnataka Shakti scheme.")
    para(doc, "But free to the passenger is not free to BMTC: the state reimburses the operator. So "
              "the ticket stores two numbers, not one. fare_value_inr is what the journey would have "
              "cost - that is the amount BMTC claims back. fare_collected_inr is zero. Revenue reports "
              "use the second; the reimbursement claim uses the first. A single fare_amount field "
              "could not express both, and collapsing them would misstate one or the other.")
    para(doc, "The ticket itself is a signed token rendered as a QR code, plus a six-character code "
              "for a quick visual check. A Shakti ticket looks identical to a paid one, because a "
              "conductor must be able to verify it with the same scan - the scheme changes who pays, "
              "not what a valid ticket looks like.")

    h(doc, 2, "26.5 Meanwhile, on the bus")
    para(doc, "A conductor signs on at the start of a shift, which opens a waybill - the daily record "
              "of which bus, which route, the opening odometer reading, and eventually all the money. "
              "Only one waybill can be open at a time, because two would mean tickets landing on "
              "whichever one the device happened to name, and the cash at the end reconciling against "
              "neither.")
    para(doc, "Through the shift the conductor sells tickets. Buses lose mobile signal constantly, so "
              "offline is the DEFAULT path, not a fallback: every sale is written to the device's own "
              "storage first, with a randomly generated identifier, and pushed to the server whenever "
              "a connection appears. The server has a uniqueness rule on that identifier, so if the "
              "device sends the same batch three times because it never saw the acknowledgement, the "
              "sale is still counted once. Revenue that double-counts on a flaky connection would be "
              "worse than useless.")
    para(doc, "At sign-off the conductor declares the cash in hand. The server recomputes the expected "
              "total from the ticket records - never from the device - and reports the difference. It "
              "does not correct it. A system that quietly adjusts a cash figure so the books balance "
              "has destroyed the only signal the depot had.")

    h(doc, 2, "26.6 The other half: what the operator sees")
    para(doc, "This is where DBARS stops being a commuter app. Using the same timetable, it answers "
              "questions no consumer app asks.")
    para(doc, "The first is: how few buses can actually run this timetable? A bus does not run \"a "
              "route\" - it runs a BLOCK. It pulls out of its depot, runs a chain of trips back to "
              "back, and pulls back in. The engine takes every scheduled trip and chains them: if a "
              "bus is already standing at a trip's starting terminal and has had enough turnaround "
              "time, it takes that trip; otherwise another bus must pull out. Counting the buses "
              "needed gives the fleet size - 6,849 across 44 depots - and the distance run empty "
              "between the depot and the first stop gives the dead kilometres. The engine also "
              "computes a hard lower bound by asking how many trips are ever in progress at the same "
              "moment, so the output can say whether its answer is provably minimal rather than just "
              "the best it found.")
    para(doc, "The second question is the one that first question invites: a plan that saves buses by "
              "stretching each one across fourteen hours has saved nothing if no roster can staff it. "
              "So a second engine cuts those vehicle blocks into crew duties, at points where a "
              "changeover is legal, respecting limits on continuous driving, break placement, total "
              "working time and spreadover. The result is 15,636 daily duties for 6,849 buses - a "
              "ratio of 2.28, which matches what real transport undertakings run.")
    para(doc, "Every number in both engines rests on assumptions - average running speed, dwell time, "
              "layover, crew agreement rules - because BMTC has not published those figures. The "
              "project's answer to that is not to hide them but to bundle them into parameter objects "
              "that are echoed back in every API response, and to let a depot manager change them in a "
              "scenario console and see what the change costs.")

    h(doc, 2, "26.7 Closing the loop")
    para(doc, "The project is named Demand Based Allocation, and this is where that name earns itself. "
              "A commuter who cannot find a good route can VOTE for the journey they want. Votes are "
              "checked against four fraud heuristics - the same pair repeatedly, too many votes per "
              "hour, too many from one address, an implausible spread of destinations - and then "
              "aggregated by origin-destination pair. The depot manager sees those pairs ranked by "
              "genuine demand, with each one resolved to a real bus by the same prediction engine. "
              "Demand from passengers becomes information for the operator.")

    h(doc, 2, "26.8 Giving the data away")
    para(doc, "The last piece is the least visible and arguably the most useful. The project exports "
              "the whole timetable as GTFS - the standard format every journey planner in the world "
              "understands. 3,713 routes, 47,295 trips and 1.46 million stop times, built in eleven "
              "seconds and streamed straight into a 14 MB zip file.")
    para(doc, "Two decisions in that export matter. First, depot positioning runs are excluded: those "
              "are non-revenue trips from a depot gate, and a journey planner cannot tell, so leaving "
              "them in would route a passenger to a depot to board a bus that will not carry them. "
              "Second, only the first departure time of each trip is real data - every later stop time "
              "is interpolated from geometry and an assumed speed, so every one is flagged with GTFS's "
              "own marker for interpolated values, and a README inside the zip states exactly what was "
              "modelled. Publishing a feed whose times were invented, without saying so, would be "
              "worse than publishing nothing.")

    h(doc, 2, "26.9 The thing the project refuses to do")
    para(doc, "DBARS can show buses moving on a map. By default those positions come from a physics "
              "simulation, because no real BMTC vehicle feed is available. The project is built so "
              "that this can never be passed off as real.")
    para(doc, "Every position carries a flag saying whether it is live. The endpoint that reports what "
              "is powering the map reads that flag from whichever adapter is running, rather than from "
              "a stored label - an earlier version had a label that could be flipped to claim the data "
              "came from a government feed, while the underlying positions never changed. And the "
              "GTFS-Realtime vehicle endpoint refuses to publish anything at all while the feed is "
              "simulated, returning an error that explains why: the format has no field meaning \"this "
              "is simulated\", so a consumer could not tell the difference.")
    para(doc, "Swapping in a real feed is a configuration change, because the vehicle source is an "
              "interface with four implementations. That is the whole reason the layer exists rather "
              "than a thin wrapper over the simulator.")

    h(doc, 2, "26.10 In one paragraph")
    para(doc, "DBARS reads BMTC's published timetable and builds three things from it. For commuters: "
              "a journey planner with transfers, e-ticketing including the Shakti free-travel scheme, "
              "and a way to vote for routes they wish existed. For the operator: the minimum fleet and "
              "crew a timetable needs, a conductor waybill with offline-safe ticketing and cash "
              "reconciliation, and the reimbursement claim the state owes. For everyone else: the data "
              "itself, published as GTFS. It runs as a FastAPI backend with a React frontend and "
              "MongoDB, is covered by 161 tests, and is built throughout on one rule - never present "
              "modelled or simulated data as measured fact.", bold=True)
    page_break(doc)


def section_27(doc):
    h(doc, 1, "27. Professor Defense Preparation")
    para(doc, "Model answers below are written to be spoken aloud in thirty to sixty seconds. Where a "
              "question invites an overclaim, the answer says so.")

    h(doc, 2, "27.1 Basic questions")
    _qa(doc, [
        ("What is your project?",
         "DBARS is a transit platform for BMTC built on their published timetable. It does three "
         "things: it plans journeys for commuters including transfers, it tells depot managers how "
         "many buses and crew that timetable actually needs, and it publishes the whole dataset as "
         "GTFS so external journey planners can use it. Backend is FastAPI, frontend is React, "
         "database is MongoDB."),
        ("What problem does it solve?",
         "Three gaps. Commuters cannot easily find which of 3,940 buses connects two of 4,883 stops, "
         "especially with a transfer. Operators get nothing operational from a commuter app - no "
         "fleet sizing, no crew planning. And external planners can only be as good as the data they "
         "are given, which is why the GTFS export matters."),
        ("Why did you build it?",
         "Because the same dataset can answer both a consumer question and an operations-research "
         "question, and nobody was doing the second one. The fleet blocking and crew scheduling "
         "engines are the part I would defend most strongly - they produce numbers a transport "
         "corporation actually uses."),
        ("Who are the users?",
         "Four roles with real screens: commuters, conductors, depot managers and admins. A driver "
         "role exists in the code so a waybill can name the driver, but there is no driver-facing "
         "interface yet - I would rather say that than pretend it is finished."),
        ("What technologies did you use?",
         "Python 3.12 with FastAPI and Pydantic on the backend, Motor for async MongoDB access, React "
         "19 with TypeScript and Vite on the frontend, Leaflet for maps, Docker Compose for "
         "deployment, and GitHub Actions for CI. No ORM - MongoDB is accessed directly."),
    ])

    h(doc, 2, "27.2 Architecture questions")
    _qa(doc, [
        ("Explain the architecture.",
         "Four backend layers. The API layer handles HTTP only. The service layer holds business "
         "rules and is the only layer that touches MongoDB. The engine layer - route search, "
         "blocking, crew, GTFS - is pure computation over the dataset files and never touches the "
         "database at all. The data layer owns the connection and the CSV files. Dependencies point "
         "one way, which is what makes the engines testable without a database."),
        ("How does the frontend communicate with the backend?",
         "HTTP with JSON. Every call goes through one wrapper, apiFetch in lib/apiClient.ts, which "
         "prefixes the base URL and converts network failures into readable messages. Authenticated "
         "calls carry a Bearer token in the Authorization header."),
        ("Where is the business logic?",
         "In app/services for anything involving stored data, and app/ml for computation. "
         "Deliberately not in the endpoints - an endpoint parses the request, checks the role, calls "
         "a service and shapes the response."),
        ("How does data move through the system?",
         "Browser to apiFetch to CORS middleware to rate limiting to the FastAPI router, then "
         "pydantic validation, then the auth dependency, then the endpoint, then a service or "
         "engine, then MongoDB or the dataset files, and back out as JSON."),
        ("Why a monolith rather than microservices?",
         "Because the layers already give separation, and splitting into services would add network "
         "calls, deployment complexity and failure modes with no benefit at this size. It is a "
         "modular monolith by choice, not by accident."),
    ])

    h(doc, 2, "27.3 Code questions")
    _qa(doc, [
        ("Where does the application start?",
         "backend/app/main.py. create_app() builds the FastAPI object, adds middleware and registers "
         "fourteen routers. The lifespan function runs at startup: verify dataset files, train the "
         "predictor, warm the blocking plan and GTFS feed in the background, start the vehicle ingest "
         "loop, then connect to MongoDB."),
        ("What is the most important file?",
         "backend/app/ml/predictor.py. It is the biggest file and it holds the search engine - the "
         "indexes, the ranking and the transfer logic. If you understand that file you understand the "
         "product."),
        ("Explain your main classes.",
         "BMTCBusPredictor holds the dataset and every index and answers journey queries. "
         "BlockingEngine computes fleet size and dead kilometres. The parameter classes - "
         "BlockingParameters and CrewParameters - bundle every assumption so they can be listed in "
         "the output and varied in a scenario."),
        ("Why did you structure the code this way?",
         "So the expensive, valuable computation is independent of everything fragile. Route "
         "prediction, blocking, crew planning and GTFS export all work with MongoDB stopped. That is "
         "not an accident of layout - it is why train() runs before init_db() and why init_db() "
         "cannot raise."),
    ])

    h(doc, 2, "27.4 Database questions")
    _qa(doc, [
        ("Why did you choose MongoDB?",
         "Two honest reasons. The records evolved a lot during development - a waybill grew new "
         "fields for scheme value and reconciliation - and a schema-free store absorbed that without "
         "migrations. And most of the app's heavy data is not in the database at all; it is in CSV "
         "files. The trade-off is real: no foreign keys and no joins, so referential integrity is my "
         "responsibility. A relational database would have enforced more."),
        ("What are the main collections?",
         "Seventeen. The important ones are users, votes, tickets, waybills, conductor_tickets, "
         "travel_passes, service_alerts and audit_events."),
        ("How are relationships handled?",
         "By storing identifiers and querying separately - conductor_tickets holds a waybill_id, for "
         "example. There are no joins, so I use indexes on those fields instead."),
        ("How does the application read and write data?",
         "Through Motor, the async MongoDB driver, and only from the service layer. Documents are "
         "built as plain dictionaries and validated by pydantic models at the API boundary. There is "
         "no ORM."),
        ("What happens if the database is down?",
         "Route prediction, autocomplete, the blocking plan, the crew plan and the GTFS export all "
         "keep working, because they read files. Anything needing stored data returns a 503 that says "
         "so explicitly, or returns an empty result with a note - never a misleading zero."),
    ])

    h(doc, 2, "27.5 Security questions")
    _qa(doc, [
        ("How does authentication work?",
         "Signed tokens. On login the password is checked against a PBKDF2-SHA256 hash, and the "
         "server issues an access token valid 24 hours and a refresh token valid 7 days. Every "
         "protected request carries the access token as a Bearer header; a dependency verifies the "
         "HMAC-SHA256 signature, the expiry and the token type."),
        ("How are passwords protected?",
         "PBKDF2-SHA256 with a fresh 16-byte random salt per user, and a constant-time comparison on "
         "verification. It is a legitimate standards-based choice. It is not the strongest available "
         "- bcrypt, scrypt or Argon2 resist GPU attack better - and that is what I would change "
         "first."),
        ("How are secrets stored?",
         "In environment variables loaded from a .env file that is gitignored. The signing key used "
         "to be a fixed constant committed to source, which meant anyone who had seen the repository "
         "could forge an admin token. Now it is read from the environment, and if unset a random "
         "per-process key is generated with a loud warning rather than falling back to another "
         "guessable constant."),
        ("What vulnerabilities could exist?",
         "Several I can name. POST /train has no authentication and triggers an expensive retrain - "
         "that is the clearest hole and it is a one-line fix. There is no token revocation, so a "
         "stolen token stays valid until it expires. Tokens live in localStorage, so an XSS flaw "
         "would expose them. And the rate limiter is in-memory, so multiple workers would each get "
         "their own budget."),
        ("Why three different signing keys?",
         "So one leaked key cannot mint another kind of credential. A travel pass is verified offline "
         "on a shared device in a bus, so its key is the most likely to leak - and it must not be "
         "able to produce a session token or an e-ticket."),
    ])

    h(doc, 2, "27.6 AI questions")
    callout(doc, "Be ready for this, and answer it straight",
            "If asked \"where is the AI in your project?\", the correct answer is: there is none. "
            "Some UI text uses the word and that wording is misleading. What exists is classical "
            "information retrieval and graph search, plus a benchmark comparing four ranking "
            "strategies. Trying to dress that up as machine learning is the fastest way to lose "
            "credibility, because an examiner will ask which model and where the weights are.", warn=True)
    _qa(doc, [
        ("Did you use AI or machine learning?",
         "No language model and no trained neural network. The search is an inverted index plus an "
         "ordered stop-pair index with a hand-weighted scoring function - classical information "
         "retrieval. I did build a benchmark harness that scores four ranking strategies, and "
         "scikit-learn appears there for a TF-IDF baseline, but nothing is fitted or learned."),
        ("Then why does train() exist?",
         "It is a misleading name for index building plus evaluation. It loads the CSV, builds the "
         "indexes and measures the candidate rankers. No parameters are learned."),
        ("How accurate is it?",
         "Under relevance-set scoring — where any bus that genuinely serves the stop pair in order is a valid "
         "answer — the search scores 100% top-1 across 120 test journeys. "
         "The old single-label metric (which required guessing which of a median 22 valid buses the generator picked) "
         "reported 19.2% top-1 and 40% top-5. Because validity is saturated, I added a rank-quality metric "
         "evaluating whether the best valid bus (fewest stops, highest frequency) is ranked first: "
         "it achieves 71.7% best_option_rate, with 99.2% within 2 stops of optimal, and a mean percentile "
         "rank of 0.044 (top 4.4% of available choices). What I defend is the measurement methodology: "
         "separating validity from ranking quality."),
    ])

    h(doc, 2, "27.7 Failure questions")
    _qa(doc, [
        ("What happens when the database is unavailable?",
         "The app still starts and still answers journey queries, because the engines read files. "
         "init_db catches the connection error and sets a flag; endpoints that need data raise a 503 "
         "explaining that route prediction is unaffected. Some read endpoints return an empty result "
         "with a note instead, so nobody reads a zero as a real answer."),
        ("What happens when an external API fails?",
         "Google Maps is optional - the failure is caught and the code falls back to straight-line "
         "distance from stop coordinates. The vehicle feed backs off exponentially up to five minutes "
         "and records the error, so a stalled feed is visible rather than silent."),
        ("What happens when a user submits invalid input?",
         "Pydantic rejects it with a 422 before any of my code runs. If a stop name cannot be "
         "resolved, the predictor raises ValueError and the endpoint converts it to a 422 that passes "
         "the user's own words back so they can correct it."),
        ("What if a conductor loses signal mid-shift?",
         "Nothing stops. Sales queue on the device and sync when a connection returns. Because each "
         "sale carries a client-generated identifier and the database has a uniqueness rule on it, "
         "replaying the queue cannot double-count revenue."),
    ])

    h(doc, 2, "27.8 Scalability questions")
    _qa(doc, [
        ("What happens with 100 users?",
         "Fine. The search is about a second of CPU but runs on a thread pool, so the event loop "
         "keeps serving. The indexes are read-only and shared."),
        ("What about 10,000 users?",
         "It would not hold as built, and I can say exactly why. It is a single process: the rate "
         "limiter, the blocking and crew caches and the vehicle store all live in process memory. "
         "Adding workers would give each its own copy, so the rate limit would multiply and the "
         "caches would be duplicated."),
        ("What is the first bottleneck?",
         "The one-second CPU cost of a route search. At scale that saturates the thread pool long "
         "before MongoDB becomes a problem. I would cache popular origin-destination pairs first - "
         "the distribution is heavily skewed toward a few corridors."),
        ("What would you improve to scale it?",
         "In order: move shared state to Redis so the app can run multiple workers; add a result "
         "cache for common queries; split the read-only engines onto their own instances since they "
         "need no database; and add proper observability, because right now I have logs and nothing "
         "else."),
    ])

    h(doc, 2, "27.9 Critical questions")
    _qa(doc, [
        ("What is the weakest part of your project?",
         "The frontend has zero automated tests - 8,459 lines verified only by the TypeScript "
         "compiler and by me clicking through it. The backend has 161 tests, so the asymmetry is "
         "indefensible; it is just where I ran out of time."),
        ("What would you change?",
         "Four things. Gate POST /train behind admin. Add a global exception handler with request "
         "ids. Add frontend tests, starting with the offline queue because it handles money. And "
         "correct the UI text that says AI, because it does not describe what the code does."),
        ("What did you learn?",
         "That the hard part was not making features work but making them honest. Several bugs "
         "produced confident, plausible, wrong output - a route map drawing a 69 km line for a 19 km "
         "journey, a fleet calculation returning 30,000 buses for a 6,000-bus operator. None of them "
         "crashed. That taught me to write tests that assert plausibility ranges and invariants, not "
         "just that a function returns something."),
        ("What was the hardest technical problem?",
         "A route map drawing random straight lines across the city. The cause was resolving stop "
         "names without an anchor - Bengaluru has several Kodihallis, and one route matched the wrong "
         "one 28 km away. Fixing that exposed a worse bug underneath: the planner was matching "
         "transfers purely by stop name, so it offered a changeover at Avalahalli where the two "
         "Avalahallis are 28.6 km apart - a journey nobody can make. The map was not malfunctioning; "
         "it was faithfully drawing a route that should never have been offered."),
        ("What are the current limitations?",
         "Vehicle tracking is simulated unless a real feed is configured. There is no payment "
         "gateway. Shakti eligibility is taken from the account rather than verified against a "
         "government ID. Every fleet and crew number rests on assumed running speeds and crew rules, "
         "because BMTC has not published them. All of those are stated in the code and in the API "
         "responses rather than hidden."),
    ])
    page_break(doc)


def section_28(doc):
    h(doc, 1, "28. Recruiter / Interview Preparation")
    callout(doc, "On claiming contribution",
            "This document cannot verify who wrote which line. Describe your own contribution "
            "accurately - what you designed, decided, debugged and understood. The strongest signal in "
            "an interview is not \"I wrote all of it\" but being able to explain WHY a decision was "
            "made and what the alternative would have cost.")

    h(doc, 2, "28.1 Tell me about this project")
    para(doc, "\"DBARS is a transit platform for Bengaluru's bus network. It takes BMTC's published "
              "timetable - 6,700 route-directions, 4,900 stops - and builds three things from it. For "
              "commuters, a journey planner that handles transfers, plus e-ticketing. For depot "
              "managers, an operations tool that computes the minimum fleet and crew a timetable "
              "actually needs. And it exports the whole dataset as GTFS so external journey planners "
              "can consume it. It is FastAPI and React with MongoDB, containerised, with 161 backend "
              "tests running in CI. The part I find most interesting is the operations side, because "
              "it answers questions no consumer app asks.\"")

    h(doc, 2, "28.2 What was the architecture?")
    para(doc, "\"Four backend layers with a strict dependency direction. The key decision was making "
              "the computation engines - route search, fleet blocking, crew scheduling, GTFS export - "
              "pure functions of files on disk with no database dependency at all. That means the core "
              "features keep working when MongoDB is down, and it means all of that logic is unit "
              "testable without any infrastructure. Concretely, the startup sequence trains the engine "
              "before it attempts a database connection, and the database connection is not allowed to "
              "raise.\"")

    h(doc, 2, "28.3 What was the hardest technical problem?")
    para(doc, "\"A route map drawing random straight lines across the city. The distances printed "
              "beside the map were always correct, so the bug hid for a long time - only the drawing "
              "was wrong. The cause was resolving stop names one at a time: Bengaluru reuses names, "
              "and one route matched the wrong Kodihalli 28 kilometres east, so it drew a 69 km line "
              "for a 19 km journey. The fix was two-pass anchored resolution - establish the route's "
              "centre, then resolve each stop relative to its predecessor.")
    para(doc, "\"But fixing it exposed something worse. Transfers were being matched purely on stop "
              "name, so the planner was telling people to change at Avalahalli when the two stops with "
              "that name are 28.6 kilometres apart. The map had been faithfully drawing an impossible "
              "journey. I added a geometric check that rejects any changeover further apart than a "
              "short walk. Then I had to fix my own fix twice: I first ran the check after "
              "re-anchoring, which forces both stops onto one point and made the test always pass; and "
              "filtering a fixed-size shortlist made one real journey unroutable, so it now scans "
              "deeper until the shortlist genuinely fills. The final version also moved the check "
              "before leg construction, which took one slow query from 7.5 seconds to 1.2.\"")

    h(doc, 2, "28.4 Why did you choose this technology?")
    table(doc, ["Choice", "Answer"], [
        ["FastAPI", "Async by default, validation from type hints, and automatic OpenAPI docs. The\nvalidation matters most - malformed input never reaches business logic."],
        ["MongoDB", "The records evolved during development and a schema-free store absorbed that\nwithout migrations. I would flag the trade-off honestly: no joins, no foreign\nkeys, so integrity is my job."],
        ["Leaflet over\nGoogle Maps", "No API key, no cost, no rate limit. The whole project runs with no external\nkeys, which makes it demonstrable anywhere."],
        ["No ORM", "The data model is simple and document-shaped. An ORM would have added a layer\nwithout removing work."],
        ["Files over a\ndatabase for\nthe timetable", "The deliberate one. It makes the engines pure functions, testable with no\ninfrastructure, and it is why a database outage does not break route search."],
    ], widths=[1.3, 5.5])

    h(doc, 2, "28.5 How does feature X work internally?")
    para(doc, "Pick the offline conductor sync - it is the most senior-sounding answer in the project:")
    para(doc, "\"Buses lose signal constantly and a conductor cannot stop selling tickets, so offline "
              "is the default path rather than a fallback. Each sale is written to device storage with "
              "a client-generated UUID and replayed until the server acknowledges it. The server has a "
              "unique index on the waybill id plus that UUID, so a replayed batch raises a duplicate "
              "key error which is caught and reported as 'duplicate' rather than an error. The sync "
              "response is per-item, so the device clears only what the server confirmed - clearing "
              "the whole queue on a 200 is exactly how offline sales disappear, and a lost cash sale "
              "is indistinguishable afterwards from one that never happened. Totals are always "
              "recomputed server-side from the ticket rows; a client-supplied total in a revenue "
              "document is a fraud vector.\"")

    h(doc, 2, "28.6 How would you scale it?")
    para(doc, "\"First I would name the constraint: it is single-process today. The rate limiter, the "
              "plan caches and the vehicle store are all in process memory, so adding workers would "
              "multiply the rate limit and duplicate the caches. So step one is moving that shared "
              "state to Redis. Step two is caching popular origin-destination results, because the "
              "one-second search is the real bottleneck and the query distribution is heavily skewed "
              "toward a few corridors. Step three is splitting the read-only engines onto their own "
              "instances, which is easy precisely because they have no database dependency.\"")

    h(doc, 2, "28.7 How would you debug a production issue?")
    para(doc, "\"I would start with GET /health and GET /tracking/source, because between them they "
              "tell me whether the predictor trained, how many routes loaded, which vehicle feed is "
              "running and when it last succeeded. Then GET /gtfs/feed-info for the last build report. "
              "The honest gap is that I have logs and nothing else - no request ids, no metrics, no "
              "tracing - so correlating a user report to a specific request is manual. Adding a global "
              "exception handler that logs a request id is the first thing I would fix.\"")

    h(doc, 2, "28.8 What would you do differently?")
    numbered(doc, [
        "Write frontend tests from the start. Having 161 backend tests and zero frontend tests is the clearest imbalance in the project.",
        "Add observability early - request ids, structured logs, timing metrics. I optimised by measuring by hand, which worked but does not scale.",
        "Design the shared-state story before building caches, so horizontal scaling would not need retrofitting.",
        "Name things accurately from the beginning. Calling index-building \"training\" and a string parser an \"AI assistant\" created confusion I then had to correct.",
        "Extract shared logic sooner. The stop-resolution bug existed because three subsystems each did the same thing slightly differently.",
    ])
    page_break(doc)


def section_29(doc):
    h(doc, 1, "29. Rapid-Fire Interview Questions")
    para(doc, "Short questions with short answers, grouped by area. Use these for revision.")

    h(doc, 2, "29.1 Project and architecture (1-15)")
    _qa(doc, [
        ("What does DBARS stand for?", "Demand Based Bus Allocation & Routing System."),
        ("How many API endpoints?", "82."),
        ("How many backend tests?", "161, across 15 files, all passing."),
        ("Entry point?", "backend/app/main.py, object app = create_app()."),
        ("How many layers in the backend?", "Four: API, service, engine, data."),
        ("Which layer talks to MongoDB?", "Only the service layer."),
        ("Which layer never touches MongoDB?", "The engine layer - app/ml, app/gtfs, app/tracking."),
        ("Why does that matter?", "Route search, blocking, crew and GTFS keep working when the database is down."),
        ("How many user roles?", "Five: commuter, conductor, depot_manager, admin, driver."),
        ("Which role has no UI?", "driver - it exists so a waybill can name the driver."),
        ("Monolith or microservices?", "Modular monolith, by choice."),
        ("How many MongoDB collections?", "17."),
        ("How many frontend pages?", "13 routes in App.tsx."),
        ("What runs at startup, in order?", "Verify files, train predictor, warm blocking and GTFS, start vehicle ingest, init DB, optional admin seed."),
        ("Why train before init_db?", "So route prediction works before the database is even attempted, and a DB failure cannot abort startup."),
    ])

    h(doc, 2, "29.2 The routing engine (16-30)")
    _qa(doc, [
        ("How many route-directions in the dataset?", "6,737."),
        ("How many distinct bus numbers?", "3,940."),
        ("How many stops?", "4,883 unique names; 9,507 platform rows."),
        ("How many indexed stop pairs?", "655,438 ordered pairs over 3,946,744 route segments."),
        ("Why ORDERED pairs?", "Direction matters - a bus passing both stops in the wrong order is not an answer."),
        ("How many transfers are supported?", "One. Direct and one-transfer journeys only."),
        ("How long does a search take?", "Median 0.94 s, p90 1.52 s."),
        ("Why asyncio.to_thread?", "One second of blocking CPU would stall the single event loop for every other user."),
        ("What is the interchange rule?", "A transfer is rejected if its two stops are more than 1.2 km apart."),
        ("Why is that rule needed?", "Transfers match by stop name, and Bengaluru reuses names - two Avalahallis are 28.6 km apart."),
        ("What is anchored resolution?", "Resolving each stop relative to the previous one, so a route does not jump between same-named places."),
        ("Why the median, not the mean, for the centre?", "One badly resolved outlier 28 km away would drag a mean; a median ignores it."),
        ("Is there a trained model?", "No. No weights file, no fitting, no learning."),
        ("What does train() do then?", "Loads the CSV, builds indexes, evaluates four candidate rankers, writes metrics.json."),
        ("Which ranker ships?", "LiveTransferSearch - the real graph search."),
    ])

    h(doc, 2, "29.3 Operations engines (31-45)")
    _qa(doc, [
        ("What is a block?", "One physical bus's day: pull out of the depot, run a chain of trips, pull back in."),
        ("What are dead kilometres?", "Distance run with no passengers - depot to first stop, and last stop back to depot."),
        ("How many buses does the network need?", "6,849 interlined, across 44 depots."),
        ("What is the lower bound?", "Peak simultaneous trips - no cleverness can run two overlapping trips with one bus."),
        ("Why report the bound?", "So the output can say \"provably minimal\" rather than \"best we found\"."),
        ("What is a duty?", "One person's working day, as opposed to a block, which is one bus's day."),
        ("How many duties are needed?", "15,636 for 6,849 buses - a ratio of 2.28."),
        ("Is 2.28 plausible?", "Yes - real transport undertakings run roughly 2.0 to 2.5."),
        ("What is a split duty?", "Two separate pieces of work with an unpaid gap, worked by one person."),
        ("What bounds split duties?", "The spreadover ceiling - elapsed time from sign-on to final sign-off."),
        ("What if no legal split exists?", "The block is reported as unstaffable by name, not silently dropped."),
        ("How was crew pairing optimised?", "Binary search on the spreadover window plus a path-compressed skip list: 36 s to 1.6 s."),
        ("Did the faster version give worse results?", "No - slightly fewer duties."),
        ("Where do the assumptions live?", "BlockingParameters and CrewParameters, echoed into every API response."),
        ("Why surface assumptions?", "An assumption a reader cannot see is one they will mistake for a measurement."),
    ])

    h(doc, 2, "29.4 Data, GTFS and tracking (46-60)")
    _qa(doc, [
        ("How big is the GTFS feed?", "3,713 routes, 47,295 trips, 1,459,066 stop_times, ~14.4 MB."),
        ("How long does it take to build?", "About 11 seconds."),
        ("Why stream it into the zip?", "1.46 million rows in memory would cost over a gigabyte."),
        ("What is excluded from the feed?", "325 depot positioning runs and 55 outstation services over 100 km."),
        ("Why exclude depot runs?", "They carry no passengers, and a journey planner cannot tell - it would route riders to a depot gate."),
        ("Why exclude long services?", "Timed at city speed, a 672 km coach route produced a 37-hour trip - broken data, not imprecise."),
        ("What is timepoint=0?", "GTFS's own marker for an interpolated time. Only the first departure of each trip is real data."),
        ("How is provenance recorded?", "Three places: feed_info.txt, a README inside the zip, and namespaced ids."),
        ("Is vehicle tracking real?", "No - simulated by default, unless TRACKING_FEED names a real adapter."),
        ("How many feed adapters?", "Four: simulated, gtfs_rt, http_json, push."),
        ("What is is_live?", "A flag on every observation saying whether the data is real. It travels with the data."),
        ("What does it gate?", "The GTFS-RT vehicle endpoint returns 503 while the feed is simulated."),
        ("Why refuse rather than label?", "GTFS-Realtime has no field meaning 'simulated' - a consumer could not tell."),
        ("What is the staleness rule?", "Observations older than 120 s are withheld, not shown."),
        ("Why withhold rather than show?", "A stalled feed would otherwise show ghost buses that riders stand and wait for."),
    ])

    h(doc, 2, "29.5 Money, auth and security (61-80)")
    _qa(doc, [
        ("What is the Shakti scheme?", "Karnataka's free bus travel for women and transgender passengers on non-AC services."),
        ("Why two fare fields?", "Free to the passenger is not free to BMTC - the state reimburses. Revenue uses collected; the claim uses value."),
        ("Does Shakti cover AC buses?", "No. Vajra and Vayu Vajra are chargeable for everyone."),
        ("Where does the eligibility rule live?", "core/shakti.py - one function used by both the app and the conductor path."),
        ("Why one shared rule?", "Two implementations would drift, and a passenger told free then charged has been failed twice."),
        ("Is gender stored on a ticket?", "No. The claim needs a count and a value, not a record of who travelled."),
        ("Is gender in the JWT?", "No - a bearer token travels through logs and browser storage."),
        ("How is offline ticketing made safe?", "Client-generated UUID plus a unique index on (waybill_id, client_ticket_uuid)."),
        ("What happens on a replay?", "DuplicateKeyError, caught and reported as 'duplicate' - the queue working correctly."),
        ("Who computes waybill totals?", "The server, from the ticket rows. Never the client."),
        ("What happens to a cash variance?", "It is reported and flagged, never auto-corrected."),
        ("How are passwords hashed?", "PBKDF2-SHA256 with a 16-byte random salt per user."),
        ("Why a salt?", "So two users with the same password do not produce the same hash."),
        ("How many token types?", "Four: access, refresh, qr_ticket, travel_pass."),
        ("How many signing keys?", "Three separate domains."),
        ("Why separate keys?", "So a leaked ticket or pass key cannot mint a session."),
        ("Can a user register as admin?", "No. RegisterRequest has no role field; the server forces commuter."),
        ("Is there token revocation?", "No. Logout only clears localStorage - a known limitation."),
        ("What is the biggest security hole?", "POST /train is unauthenticated and expensive. One-line fix."),
        ("Is the rate limiter production-ready?", "No - it is in-memory, so multiple workers each get their own budget."),
    ])

    h(doc, 2, "29.6 Testing, deployment and debugging (81-95)")
    _qa(doc, [
        ("How do you test the engines without a database?", "They read files only, so tests construct them directly."),
        ("What does asyncio_mode = strict do?", "Forces async tests to be marked, so they cannot be silently skipped."),
        ("Why does that matter?", "A previous setup skipped async tests and still reported green - a regression test sat inert."),
        ("How are the operations engines tested?", "Invariants and plausibility ranges, not fixed values."),
        ("Give an invariant example.", "Every trip is worked by exactly one crew duty; no duty breaks a declared rule."),
        ("Are there frontend tests?", "None. That is the clearest gap in the project."),
        ("Is coverage measured?", "No tool is configured, so no percentage can be quoted."),
        ("What does CI run?", "pytest, compileall, and the frontend build, on every push."),
        ("Does CI deploy?", "No. Build and test only."),
        ("How is it deployed?", "Docker Compose with three services, or Render, or Vercel for the frontend."),
        ("Why a multi-stage frontend Dockerfile?", "Build with Node, serve with Nginx - the final image has no Node runtime."),
        ("Where do you look first when something breaks?", "GET /health and GET /tracking/source."),
        ("What does /tracking/source tell you?", "Which adapter is running, whether it is live, last poll time, and error state."),
        ("What observability is missing?", "Request ids, metrics and tracing. Logs only."),
        ("How would you find a slow endpoint today?", "By hand - there is no timing instrumentation."),
    ])
    page_break(doc)


def section_30(doc):
    h(doc, 1, "30. Explain This Project In Different Depths")

    h(doc, 2, "30.1 The 30-second explanation (recruiter, no time)")
    para(doc, "\"DBARS is a full-stack transit platform for Bengaluru's bus network. It takes the "
              "published BMTC timetable and does three things: plans journeys for commuters including "
              "transfers, tells depot managers the minimum buses and crew that timetable needs, and "
              "publishes the whole dataset as GTFS for external journey planners. FastAPI, React, "
              "MongoDB, Docker, 161 tests in CI.\"", italic=True)

    h(doc, 2, "30.2 The 1-minute explanation (interview opener)")
    para(doc, "\"DBARS is built on BMTC's published timetable - about 6,700 route-directions across "
              "4,900 stops. There are three products in it.")
    para(doc, "\"For commuters, a journey planner that answers 'which bus from A to B', including "
              "one-transfer journeys, plus e-ticketing with QR codes and the Karnataka Shakti free "
              "travel scheme.")
    para(doc, "\"For the operator, something no consumer app does: it computes the minimum fleet that "
              "can run the timetable, the kilometres run empty, and the crew duties needed to staff "
              "it - about 15,600 duties for 6,800 buses.")
    para(doc, "\"And it exports everything as GTFS so Google Maps and any other planner can use the "
              "data.")
    para(doc, "\"Backend is FastAPI with MongoDB, frontend is React and TypeScript, containerised with "
              "Docker, 161 backend tests in CI. The design decision I would highlight is that the "
              "computation engines read files rather than the database, so the core features keep "
              "working when MongoDB is down.\"")

    h(doc, 2, "30.3 The 3-minute explanation (technical interview)")
    para(doc, "Start with the 1-minute version, then add:")
    bullets(doc, [
        ("The architecture.", "Four layers with a strict dependency direction: API, service, engine, "
         "data. The engine layer - route search, blocking, crew, GTFS - is pure computation over CSV "
         "files with no database dependency. That is why 161 tests run in CI with no MongoDB "
         "container, and why the startup sequence trains the engine before it attempts a database "
         "connection."),
        ("How the search works.", "Not a trained model - an inverted index plus an ordered stop-pair "
         "index, 655,438 pairs built at startup. Direct routes are a dictionary lookup; transfers are "
         "built by intersecting the routes serving each end. It takes about a second of CPU, so the "
         "endpoint hands it to a worker thread."),
        ("The hardest bug.", "Route maps drew straight lines across the city. Bengaluru reuses stop "
         "names, and unanchored resolution matched the wrong Kodihalli 28 km away - a 69 km line for "
         "a 19 km journey. Fixing it exposed a worse bug: transfers matched purely by name, offering "
         "a changeover between two Avalahallis 28.6 km apart."),
        ("The honesty design.", "Vehicle positions are simulated by default, and every observation "
         "carries an is_live flag. The GTFS-Realtime vehicle endpoint returns 503 rather than publish "
         "simulated data, because the format has no way to mark data as simulated and a consumer "
         "could not tell."),
        ("What I would fix.", "No frontend tests, no token revocation, POST /train is "
         "unauthenticated, and it is single-process so horizontal scaling needs shared state moved to "
         "Redis first."),
    ])

    h(doc, 2, "30.4 The 5-minute explanation (project evaluation)")
    para(doc, "Deliver the 3-minute version, then walk through one complete flow end to end and one "
              "operations engine in detail. Suggested structure:")
    numbered(doc, [
        "Problem and dataset (30 s) - three gaps, and the two CSV files everything comes from.",
        "Architecture (60 s) - the four layers, and why the engines are database-free.",
        "One full flow (90 s) - a commuter searching a journey, from keystroke to drawn map, naming the files at each step.",
        "One operations engine (90 s) - blocking: what a block is, the greedy chaining, the provable lower bound, and 6,849 buses across 44 depots.",
        "Honesty and limits (60 s) - what is simulated, why it cannot leak, and the assumptions surfaced in every response.",
        "Testing and what you would improve (30 s).",
    ])

    h(doc, 2, "30.5 The 10-minute deep technical explanation (senior engineer)")
    para(doc, "Cover the 5-minute structure, then go deeper on these five topics. Each is a genuine "
              "engineering discussion rather than a feature list.")
    table(doc, ["Topic", "What to cover"], [
        ["1. The index design",
         "Why ordered pairs rather than a graph library: direction is the whole question, and a\ndictionary lookup on (A,B) is O(1) where a graph traversal is not. Memory-for-speed\ntrade-off: 655,438 pairs and 3.9M segments built once in seconds. Where it breaks down:\nonly one transfer is supported, because two-transfer chains would explode the candidate\nspace."],
        ["2. The anchoring bug and its class",
         "Distances were right and only the drawing was wrong, which is why it survived review.\nThe two-pass algorithm with a median centre. Then the deeper bug it exposed - name-matched\ntransfers - and the three attempts it took to fix correctly: the check first ran after\nre-anchoring and always passed; then filtering a fixed shortlist made a real journey\nunroutable; then moving it before leg construction cut a 7.5 s query to 1.2 s."],
        ["3. Idempotency under intermittent connectivity",
         "Why the identifier must come from the client, not the server: the device must retry\nwithout knowing whether the first attempt landed. Why the uniqueness rule is enforced by\nthe database rather than application logic: a race between two concurrent syncs cannot\nslip through. Why the response is per-item: clearing the whole queue on a 200 is how\noffline sales disappear."],
        ["4. Modelling money correctly",
         "fare_value_inr versus fare_collected_inr, and why one field cannot express both. The\nshared eligibility rule, and the AC exclusion that a single-implementation version got\nwrong - the conductor path was zero-rating AC Shakti journeys, which would have billed\nthe state for money already taken from the passenger. Server-side totals as a fraud\nboundary."],
        ["5. Designing for honesty",
         "is_live as a property of the data rather than the endpoint. The 503 gate. The staleness\nrule and why recorded_at must be the source's time, not receipt time. Assumptions bundled\ninto parameter objects and echoed in responses. Benchmarking four rankers and shipping the\none whose metric describes the real output rather than the one that scored better."],
    ], widths=[1.6, 5.2])
    callout(doc, "Closing line that works in any depth",
            "\"The thing I would want you to take away is that most of the hard problems in this "
            "project were not about making features work - they were about making sure the system "
            "never presents a modelled or simulated number as a measured one. Several of the worst "
            "bugs produced confident, plausible, completely wrong output without ever crashing.\"")
    page_break(doc)
