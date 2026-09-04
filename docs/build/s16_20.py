# -*- coding: utf-8 -*-
"""Sections 16-20: AI/ML, external services, errors, config, security."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_16(doc):
    h(doc, 1, "16. AI / ML / LLM Deep Dive")

    h(doc, 2, "16.1 The honest headline")
    callout(doc, "There is no AI in this project",
            "No large language model, no neural network, no trained model file, no inference API, no "
            "embeddings and no vector database. CONFIRMED: the repository contains no LLM SDK, no .pkl "
            "or .h5 weights, and no call to any model provider. Some UI text and an earlier folder name "
            "use the word \"AI\"; that wording is misleading and should be corrected. Claiming AI in a "
            "viva would be a claim an examiner could disprove in thirty seconds.", warn=True)
    para(doc, "What the project actually contains is a classical information-retrieval and graph-search "
              "system, plus a small benchmark harness that scores four candidate ranking strategies. "
              "That is a defensible and interesting thing to have built - it just is not machine "
              "learning in the modern sense.")

    h(doc, 2, "16.2 What \"training\" means here")
    para(doc, "BMTCBusPredictor.train() is called at startup, which invites the assumption that a model "
              "is fitted. It is not. train() means: load the CSV, build lookup indexes, and measure "
              "how well several ranking strategies score on synthetic journeys.")
    code(doc,
         "  train()\n"
         "   |-- load_routes(dataset_path)          6,737 RouteRecord objects\n"
         "   |-- _build_stop_name_indexes()         raw name -> normalised name, keeping collisions\n"
         "   |-- StopRegistry.build()               stable hashed IDs for stops\n"
         "   |-- stop_to_route_indices              normalised stop -> {route indexes}\n"
         "   |-- _build_stop_pair_index()           (A,B) -> segments   655,438 ordered pairs\n"
         "   |                                                          3,946,744 route segments\n"
         "   |-- if artifacts/metrics.json exists and not force:\n"
         "   |        reuse the cached metrics (skip re-evaluation)\n"
         "   |   else:\n"
         "   |        _evaluate_models()            score the four candidates\n"
         "   |        _cross_validate()             5-fold\n"
         "   +-- _save_metrics()                    write artifacts/metrics.json\n"
         "\n"
         "  Total: about 7 seconds. No parameters are learned. Nothing is fitted.",
         caption="Figure 16.1 - What train() actually does.")

    h(doc, 2, "16.3 The candidate rankers, relevance-set scoring, and measured results")
    para(doc, "Earlier benchmark versions evaluated models against a single expected route label (the route "
              "the test sample was drawn from). Because a median of 22 distinct buses serve each sampled pair, "
              "a perfect system picking uniformly among valid buses would score top-1 of only 0.16. "
              "The evaluation now uses relevance-set scoring: any route that legitimately serves the stop pair "
              "in the correct order is a valid answer. All models are evaluated on an identical sample count (N=120).")
    table(doc, ["Model", "Relevance-Set Top-1", "Lenient P@5", "Strict Top-1 (Exact Match)", "Strict Top-5"], [
        ["TFIDFCosine", "1.0000", "1.0000", "0.1667", "0.4417"],
        ["OrderedStopFuzzy", "1.0000", "1.0000", "0.1583", "0.3750"],
        ["DistanceAwareRouteRanker", "1.0000", "1.0000", "0.1583", "0.3833"],
        ["LiveTransferSearch (SHIPPED)", "1.0000", "1.0000", "0.1917", "0.4000"],
    ], widths=[2.2, 1.1, 1.0, 1.2, 1.0])
    para(doc, "Cross-validated (5-fold) figures for the shipped model: top-1 1.0000, top-3 1.0000, "
              "top-5 1.0000. Under single-label strict match, exact_route_match reports top-1 0.1917, top-3 0.3250, top-5 0.4000. "
              "Because correctness is saturated (100% of searches return a valid bus), optimization focuses on "
              "rank quality: whether the returned bus is the best available option (fewest stops, highest frequency, shortest distance). "
              "LiveTransferSearch achieves a best_option_rate of 71.7%, mean_percentile_rank of 0.044 (top 4.4% of options), "
              "and within_2_stops_rate of 99.2%.")
    evidence(doc, "backend/artifacts/metrics.json")

    h(doc, 2, "16.4 Why the shipped model is not the highest-scoring one on strict match")
    para(doc, "On single-label exact route match, TFIDFCosine scores slightly higher at top-5 (0.4417 vs 0.4000), "
              "yet LiveTransferSearch is what serves users. The project states its reasoning in metrics.json, "
              "and it is a strong answer to give an examiner:")
    bullets(doc, [
        ("The metric measures different things.", "The LiveTransferSearch numbers are the accuracy of "
         "exactly what predict() returns to a user. The other three are scored on a proxy task that "
         "does not have to produce a usable journey."),
        ("The dataset has no ground truth.", "There is no record of which bus a commuter actually took. "
         "The test set is synthetic journeys generated from the route catalogue, so a high score can "
         "reflect the generator as much as the ranker."),
        ("A classifier cannot answer the real question.", "The project's own reasoning: a pure "
         "classifier would learn route IDs from synthetic text but could not reliably answer whether a "
         "bus travels from stop A toward stop B in the correct order. Direction matters, and only the "
         "ordered stop-pair index encodes it."),
    ])
    callout(doc, "How to handle the accuracy question in a viva",
            "Do not quote 20% top-1 as an achievement, and do not claim to have simply 'improved accuracy to 100%'. "
            "Say: 'The original benchmark was single-label — it required naming the exact route the sample was drawn from, "
            "on pairs where a median of 22 buses are all correct. I measured a theoretical ceiling of 0.16 for a perfect system "
            "under that metric. I replaced it with relevance-set scoring, which showed that LiveTransferSearch returns a valid bus "
            "in 100% of test searches on N=120 samples. With correctness validated, I added a rank-quality metric that measures "
            "whether the best valid bus is ranked first — which was 57% at baseline, and through span weighting and frequency "
            "tuning, reached 71.7% with a mean percentile rank of 0.044.' That demonstrates measurement engineering.", warn=True)

    h(doc, 2, "16.5 The algorithm that actually serves users")
    code(doc,
         "  QUERY: 'Majestic' -> 'Marathahalli'\n"
         "     |\n"
         "  1. RESOLVE  each typed name to a real stop\n"
         "        normalize_text()  lowercases, strips punctuation and noise words,\n"
         "                          expands aliases (Majestic -> Kempegowda Bus Station)\n"
         "        fuzzy_ratio()     SequenceMatcher similarity when no exact match\n"
         "        returns (resolved_name, confidence)\n"
         "     |\n"
         "  2. RETRIEVE candidates\n"
         "        stop_pair_to_segments[(A,B)]     direct routes, already ordered A-then-B\n"
         "        stop_to_route_indices[A] / [B]   for building transfer chains\n"
         "     |\n"
         "  3. FILTER   _interchange_is_walkable()  drop transfers over 1.2 km apart\n"
         "     |\n"
         "  4. SCORE    ordered stop-path match, destination similarity, TF-IDF route text,\n"
         "              fuzzy match, trip frequency, distance efficiency, transfer penalty\n"
         "     |\n"
         "  5. RANK and DEDUPLICATE by bus chain, keeping the best variant of each\n"
         "     |\n"
         "  6. ENRICH   distance, fare inputs, metro interchange, EV estimate, coordinates",
         caption="Figure 16.2 - The retrieval pipeline. This is classical IR, not learning.")
    para(doc, "If asked to name the technique: it is an inverted index plus an ordered pair index, with "
              "a hand-weighted multi-signal scoring function and a graph search of depth two (direct "
              "and one transfer). It is closer to how a search engine or a journey planner works than "
              "to how a neural network works.")

    h(doc, 2, "16.6 Where the word AI does appear, and what to say")
    para(doc, "The interface includes an \"AI assistant\" panel (AssistantPanel.tsx). It accepts free "
              "text such as \"Majestic to Whitefield\" and answers with a route. Its implementation is "
              "string splitting on separator words, followed by the same /predict call the form makes. "
              "There is no language model behind it.")
    para(doc, "The honest description is \"natural-language input\", not \"AI assistant\". If an "
              "examiner asks, say exactly that - the parsing is deterministic and you can show the "
              "twelve lines that do it.")
    evidence(doc, "frontend/src/components/AssistantPanel.tsx -> extractStopCandidatePairs()")
    page_break(doc)


def section_17(doc):
    h(doc, 1, "17. External APIs & Third-Party Services")

    h(doc, 2, "17.1 Google Maps Distance Matrix")
    table(doc, ["Aspect", "Detail"], [
        ["Purpose", "Road distance and duration between two stops, more accurate than a\nstraight-line estimate"],
        ["Status", "OPTIONAL and disabled by default. GOOGLE_MAPS_API_KEY is empty in this\nrepository, and the code path is skipped entirely when it is unset."],
        ["Authentication", "API key as a query parameter"],
        ["Endpoint", "https://maps.googleapis.com/maps/api/distancematrix/json"],
        ["When called", "Only when allow_remote=True AND a key is set AND the per-request budget\n(GOOGLE_MAPS_MAX_REMOTE_LOOKUPS, default 24) is not exhausted"],
        ["Cost control", "Results are cached to a JSON file on disk, so a repeated stop pair is\nnever paid for twice"],
        ["On failure", "_fetch_google_segment catches httpx.HTTPError and ValueError and returns\nNone; the caller falls back to the coordinate estimate"],
        ["Fallback", "Straight-line haversine distance between stop coordinates, multiplied by\n1.28 as a road-circuity factor"],
        ["Implemented in", "backend/app/ml/distance.py -> GoogleMapsDistanceService"],
    ], widths=[1.25, 5.55])
    callout(doc, "A design point worth making",
            "The entire project works with no Google Maps key at all - the README says so explicitly. "
            "Distances come from the stop coordinate file instead. That means the demo has no external "
            "dependency, no cost and no rate limit, which is exactly what you want when presenting. "
            "The API is an enhancement, not a requirement.")

    h(doc, 2, "17.2 Twilio (SMS)")
    table(doc, ["Aspect", "Detail"], [
        ["Purpose", "Let a feature-phone user query a journey by SMS - the low-bandwidth channel"],
        ["Authentication", "Inbound: the X-Twilio-Signature header is verified against TWILIO_AUTH_TOKEN"],
        ["Endpoint", "POST /sms/webhook, form-encoded (Body, From), replying with TwiML"],
        ["Security default", "If TWILIO_AUTH_TOKEN is unset the webhook refuses to process ANYTHING.\nThe safe default is refusal, not trust."],
        ["Testing", "POST /sms/query exercises the identical pipeline as JSON, with no gateway"],
        ["On failure", "Low stop-name confidence produces a reply that says what was understood\ninstead of stating a route as fact"],
        ["Reply limit", "MAX_SMS_REPLY_CHARS = 320, about two SMS segments"],
        ["Implemented in", "backend/app/api/sms.py; backend/app/services/sms_service.py"],
    ], widths=[1.25, 5.55])

    h(doc, 2, "17.3 Vehicle location feeds (AVL)")
    table(doc, ["Adapter", "Protocol", "is_live", "Status"], [
        ["SimulatedFeed", "In-process physics simulation", "False", "ACTIVE by default"],
        ["GtfsRealtimeFeed", "Polls an upstream GTFS-RT protobuf URL", "True", "Written, not connected"],
        ["HttpJsonFeed", "Polls a bespoke JSON API, with a\nconfigurable field map", "True", "Written, not connected"],
        ["PushIngestFeed", "Receives pushes at POST /avl/ingest", "True", "Written; needs AVL_INGEST_KEY"],
    ], widths=[1.3, 3.0, 0.8, 1.7])
    para(doc, "Failure handling in the poll loop is explicit: an exception increments a failure counter, "
              "records the error on the store, and doubles the wait up to MAX_BACKOFF_SECONDS (300). A "
              "dead upstream is not hammered every ten seconds, and a recovered one is picked up "
              "without a restart. A misconfigured feed (for example gtfs_rt with no URL) is caught at "
              "startup and logged; it does not prevent the application from starting, because route "
              "prediction has no dependency on vehicle positions.")

    h(doc, 2, "17.4 Map tiles")
    para(doc, "Leaflet loads raster tiles from CARTO's basemap CDN, attributed to OpenStreetMap. No key "
              "and no account are required. If the CDN were unreachable the map would render blank "
              "while the route polyline and markers still drew, because those are computed locally.")
    page_break(doc)


def section_18(doc):
    h(doc, 1, "18. Error Handling")
    para(doc, "The project has a consistent philosophy that is worth stating as a principle: a feature "
              "that cannot work should say so, rather than returning something that looks like a valid "
              "answer. Several endpoints return an explanatory note with an empty result instead of "
              "silently returning zero.")

    h(doc, 2, "18.1 The error paths, by cause")
    table(doc, ["Cause", "What happens", "Status", "Where"], [
        ["Malformed request body", "Pydantic rejects it before any project code\nruns, listing the offending fields", "422", "Automatic\n(FastAPI)"],
        ["Unresolvable stop name", "predictor raises ValueError; the endpoint\nconverts it, passing the user's own words back", "422", "api/routes.py\npredict()"],
        ["Missing / invalid token", "get_current_user raises with a\nWWW-Authenticate header", "401", "auth/auth.py"],
        ["Wrong role", "require_role compares the claim and refuses", "403", "auth/auth.py"],
        ["Disabled account", "Login checks is_active", "403", "auth/routes.py"],
        ["Duplicate email", "Explicit find_one check before insert", "400", "auth/routes.py"],
        ["Database unreachable", "get_db raises a clear 503 explaining that route\nprediction is unaffected", "503", "db/database.py"],
        ["Database unreachable\n(read-only feature)", "Returns status \"unavailable\" with a note,\nrather than a misleading empty result", "200", "api/routes.py\ndispatch recs"],
        ["Rate limit exceeded", "Sliding window per IP", "429", "core/rate_limit.py"],
        ["Second open waybill", "WaybillError, converted by the endpoint", "409", "api/conductor.py"],
        ["Ticket for a closed waybill", "Reported per item as rejected, with a reason -\nnot a whole-batch failure", "200", "waybill_service.py"],
        ["Replayed offline ticket", "DuplicateKeyError caught, reported as\n\"duplicate\" - correct behaviour, not an error", "200", "waybill_service.py"],
        ["Simulated vehicle feed", "GTFS-RT vehicle endpoint refuses with an\nexplanation of why", "503", "api/gtfs.py"],
        ["Google Maps failure", "Caught; falls back to coordinate distance", "200", "ml/distance.py"],
        ["AVL feed failure", "Logged, recorded on the store, exponential\nbackoff", "n/a", "tracking/ingest.py"],
        ["Analytics write failure", "Logged and swallowed - a dropped analytics\nevent must never break a real request", "200", "analytics_service.py"],
        ["Audit write failure", "Logged and swallowed - a conductor must not be\nblocked from signing off by an audit failure", "200", "audit_service.py"],
        ["Corrupt offline queue", "JSON parse failure returns an empty queue - a\nconductor who cannot sell any ticket is worse\nthan losing unsynced ones", "n/a", "lib/offlineQueue.ts"],
        ["Network unreachable\n(browser)", "apiFetch converts TypeError into \"Can't reach\nthe server. Check your connection.\"", "n/a", "lib/apiClient.ts"],
        ["Missing dataset file", "FileNotFoundError at startup - the app REFUSES\nto start", "n/a", "main.py lifespan"],
    ], widths=[1.5, 3.0, 0.55, 1.35])

    h(doc, 2, "18.2 Two deliberate patterns")
    bullets(doc, [
        ("Fail loudly at boot, degrade gracefully at runtime.", "A missing dataset file stops the "
         "application from starting, because an app with no timetable cannot answer anything. A missing "
         "database does not, because most of the app does not need one. The severity of the response "
         "matches the severity of the loss."),
        ("Never let a secondary concern break a primary one.", "Analytics and audit writes are wrapped "
         "in try/except and swallowed. The trade-off is stated in the code: a dropped analytics event "
         "is an acceptable loss; a broken bus lookup is not."),
    ])
    callout(doc, "Where the error handling is weakest",
            "There is no global exception handler. An unexpected exception inside an endpoint becomes a "
            "generic FastAPI 500 with no correlation id, and the traceback goes to stdout. For a "
            "production system you would add an @app.exception_handler(Exception) that logs with a "
            "request id and returns a safe, consistent error body. This is a genuine gap, listed again "
            "in Section 36. CONFIRMED: no exception_handler is registered in main.py.", warn=True)
    page_break(doc)


def section_19(doc):
    h(doc, 1, "19. Configuration & Environment Variables")
    para(doc, "All configuration is centralised in one frozen dataclass, backend/app/core/config.py. "
              "Frozen means immutable at runtime, so behaviour cannot silently drift between requests. "
              "Values are read from the environment, with .env files loaded at import time.")
    callout(doc, "No real secret values appear in this document",
            "Every secret below is shown as [REDACTED SECRET]. The repository itself contains no real "
            "secrets: .env files are excluded by .gitignore, and only .env.example files with "
            "placeholder values are committed.")

    h(doc, 2, "19.1 Dataset paths")
    table(doc, ["Variable", "Default", "Controls"], [
        ["DATASET_PATH", "dataset/routes_cleaned.csv", "The route timetable - the source of truth"],
        ["STOP_COORDINATES_PATH", "dataset/stops_cleaned.csv", "Stop names to coordinates"],
        ["METRO_DATASET_PATH", "dataset/bengaluru_metro_network.csv", "Metro stations and lines"],
        ["FARES_DATASET_PATH", "dataset/fares.json", "Stage fare table"],
        ["DEPOT_DATASET_PATH", "dataset/BMTC_depot_place_zone.xlsx", "Depot list for blocking"],
        ["METRO_PDF_PATH", "dataset/Metro_Map_2025...pdf", "Served by GET /metro/map-pdf"],
        ["ARTIFACT_DIR", "backend/artifacts", "Where metrics.json and the GTFS zip are written"],
    ], widths=[1.9, 2.2, 2.7])

    h(doc, 2, "19.2 Secrets")
    table(doc, ["Variable", "Value in repo", "Controls", "If unset"], [
        ["JWT_SECRET_KEY", "[REDACTED SECRET]", "Signs session tokens", "A random per-process key is\ngenerated and a warning logged"],
        ["TICKET_SIGNING_KEY", "[REDACTED SECRET]", "Signs e-ticket QR tokens", "Derived from JWT_SECRET_KEY,\nstill a separate domain"],
        ["PASS_SIGNING_KEY", "[REDACTED SECRET]", "Signs travel passes", "Derived from JWT_SECRET_KEY"],
        ["PASS_VERIFICATION_SECRET", "[REDACTED SECRET]", "Legacy pass secret", "A random value"],
        ["GOOGLE_MAPS_API_KEY", "empty", "Enables road distances", "The feature is skipped entirely"],
        ["TWILIO_AUTH_TOKEN", "not set", "Verifies SMS webhooks", "The webhook refuses everything"],
        ["AVL_INGEST_KEY", "not set", "Authenticates pushed\nvehicle positions", "POST /avl/ingest refuses\neverything"],
        ["MONGO_URI", "mongodb://localhost:27017", "Database location", "Same default; note it carries\nno credentials"],
    ], widths=[1.7, 1.3, 1.6, 2.2])

    h(doc, 2, "19.3 Behavioural switches")
    table(doc, ["Variable", "Default", "Controls"], [
        ["CORS_ORIGINS", "localhost:5173, 127.0.0.1:5173", "Which browser origins may call the API"],
        ["RATE_LIMIT_PER_MINUTE", "120", "Requests per IP per minute"],
        ["TRUST_PROXY_HEADERS", "false", "Whether to believe X-Forwarded-For. Only set true\nbehind exactly one trusted proxy - otherwise a\nclient can spoof its IP and evade rate limiting"],
        ["TRACKING_FEED", "simulated", "Which vehicle adapter runs"],
        ["TRACKING_FEED_URL", "empty", "Upstream feed for gtfs_rt / http_json"],
        ["TRACKING_FEED_FIELD_MAP", "empty", "JSON field mapping for a bespoke ITS API"],
        ["TRACKING_POLL_SECONDS", "10", "Poll interval"],
        ["AVL_STALE_SECONDS", "120", "Age beyond which a position is withheld"],
        ["GTFS_BUILD_ON_STARTUP", "true", "Build the ~14 MB feed at boot"],
        ["GTFS_RT_ALLOW_SIMULATED", "false", "Local development only. Even when true, simulated\ndata is served on a separate .sim.pb path"],
        ["GTFS_FEED_PREFIX", "dbars", "Namespaces every id so it cannot be mistaken for\nan official BMTC identifier"],
        ["DEMO_PASS_MODE", "false", "Accept unsigned pass ids for a demonstration.\nEvery response is labelled demo_mode: true"],
        ["SEED_DEFAULT_ADMIN", "false", "Create demo admin and depot accounts"],
        ["DEFAULT_ADMIN_PASSWORD", "admin123", "Demo password. main.py REFUSES to seed this value\nwhen ENV=production"],
        ["VITE_API_URL", "http://localhost:8000", "Frontend only - where the backend lives.\nBaked into the bundle at build time"],
    ], widths=[1.9, 1.5, 3.4])

    h(doc, 2, "19.4 How configuration reaches the code")
    code(doc,
         "  core/config.py at import time:\n"
         "      load_dotenv(BACKEND_DIR / '.env')       backend/.env\n"
         "      load_dotenv(WORKSPACE_DIR / '.env')     project-root .env\n"
         "      settings = Settings()                   one frozen dataclass instance\n"
         "\n"
         "  Everywhere else:\n"
         "      from app.core.config import settings\n"
         "      settings.rate_limit_per_minute\n"
         "\n"
         "  Frontend (build time, NOT runtime):\n"
         "      import.meta.env.VITE_API_URL  ->  lib/apiClient.ts API_BASE_URL",
         caption="Figure 19.1 - Configuration loading.")
    callout(doc, "A frontend gotcha worth knowing",
            "VITE_API_URL is substituted at BUILD time, not read at runtime. Changing it requires "
            "rebuilding the frontend. apiClient.ts exists precisely because this value was once "
            "hard-coded in nine separate files, which is how a development IP address ended up baked "
            "into a production bundle. CONFIRMED: the comment at the top of lib/apiClient.ts.")
    page_break(doc)


def section_20(doc):
    h(doc, 1, "20. Security Analysis")
    para(doc, "This section separates what the code actually does from what it does not do. No claim "
              "of overall security is made.")

    h(doc, 2, "20.1 Protections that genuinely exist")
    table(doc, ["Protection", "Implementation", "What it defends against"], [
        ["Password hashing", "PBKDF2-SHA256, 16-byte random salt per user", "Password recovery from a stolen\ndatabase; rainbow tables"],
        ["Constant-time compare", "hmac.compare_digest for signatures and\npasswords", "Timing attacks that leak a secret\ncharacter by character"],
        ["Signed tokens", "HMAC-SHA256 over header and payload", "Tampering - editing a role claim\ninvalidates the signature"],
        ["Token type checking", "Every decode verifies the type field", "A ticket QR being used as a session\ncredential (a real past bug)"],
        ["Key separation", "Three independent signing domains", "One leaked key minting another kind\nof credential"],
        ["No secret in source", "Keys read from the environment; a random\nkey generated when unset", "A fixed secret committed to git,\nwhich this code once had"],
        ["Role-based access", "require_role on every privileged endpoint", "Privilege escalation between roles"],
        ["Role forced at signup", "RegisterRequest has no role field", "Self-assigned admin accounts"],
        ["Input validation", "Pydantic types, lengths and regex patterns", "Malformed input reaching logic"],
        ["Rate limiting", "Per-IP sliding window, 120/minute", "Casual brute force and scraping"],
        ["Webhook verification", "X-Twilio-Signature checked; refuses all when\nunconfigured", "Forged inbound SMS"],
        ["AVL ingest key", "Shared secret compared with compare_digest;\nrefuses all when unset", "Anyone injecting fake bus positions"],
        ["Server-side pricing", "Fares always recomputed; client totals ignored", "A client sending its own fare or\nwaybill total"],
        ["Idempotent writes", "Unique index on (waybill_id, uuid)", "Duplicated revenue from replays"],
        ["TTL deletion", "trip_shares expire and are physically deleted", "Old travel plans lingering"],
        ["Data minimisation", "No gender on tickets; analytics logs no IP or\ndevice id; revocation list carries ids only", "Unnecessary personal data exposure"],
        ["NoSQL injection", "Queries built from typed pydantic values, not\nstring concatenation", "Query injection"],
    ], widths=[1.35, 2.75, 2.7])

    h(doc, 2, "20.2 Weaknesses - confirmed")
    table(doc, ["Weakness", "Evidence", "Risk"], [
        ["POST /train is unauthenticated", "api/routes.py - no role dependency", "CPU exhaustion; anyone can trigger a\nfull retrain repeatedly"],
        ["No token revocation", "No blacklist or session store exists", "A stolen access token is valid for up\nto 24 h; a refresh token for 7 days"],
        ["Tokens in localStorage", "contexts/AuthContext.tsx", "Readable by any script on the page, so\nan XSS flaw exposes the session"],
        ["No login-specific throttle", "Only the global per-IP limit applies", "Password guessing is slowed, not\nstopped; no account lockout"],
        ["Weak password policy", "min_length = 6, no complexity rule", "Guessable passwords"],
        ["No email verification", "register() never confirms the address", "Accounts on addresses the user does\nnot control"],
        ["In-memory rate limiter", "core/rate_limit.py uses a process dict", "With multiple workers each has its own\nbudget, so the effective limit is\nN x 120"],
        ["No global exception handler", "None registered in main.py", "Unhandled errors return a generic 500;\nstack traces go to stdout"],
        ["No HTTPS enforcement", "No redirect or HSTS in the app", "Depends entirely on the deployment;\ntokens travel in the clear over HTTP"],
        ["No CSRF protection", "None present", "Currently low risk because auth uses a\nBearer header rather than cookies, but\nit would matter if that changed"],
    ], widths=[1.55, 2.1, 3.15])

    h(doc, 2, "20.3 Weaknesses - likely concerns")
    bullets(doc, [
        ("Demo passwords in .env.example.", "DEFAULT_ADMIN_PASSWORD=admin123 is documented. It is "
         "gated behind SEED_DEFAULT_ADMIN=false and main.py refuses it when ENV=production, so the "
         "actual risk is low - but a reviewer will flag it, so be ready to explain the guard."),
        ("Verbose error details.", "Some errors echo the user's input back. Helpful for usability, "
         "and a small information-disclosure surface. UNCERTAIN whether anything sensitive can leak "
         "this way; no case was identified."),
        ("CORS in production.", "Defaults are localhost only. A deployment must set CORS_ORIGINS "
         "correctly; a wildcard would be unsafe with credentials, which the code already guards "
         "against by computing allow_credentials."),
    ])

    h(doc, 2, "20.4 Recommended improvements, in priority order")
    numbered(doc, [
        "Gate POST /train behind require_role(UserRole.ADMIN). One line; removes the clearest hole.",
        "Add a global exception handler that logs with a request id and returns a consistent error body.",
        "Move the rate limiter to Redis, or accept and document the single-process limitation.",
        "Add per-account login throttling with exponential backoff.",
        "Add a token revocation list, or shorten the access-token lifetime and rely on refresh.",
        "Raise the password minimum and add a complexity or breach check.",
        "Enforce HTTPS and add HSTS at the deployment layer.",
        "Add email verification before a new account can vote or buy tickets.",
    ])
    page_break(doc)
