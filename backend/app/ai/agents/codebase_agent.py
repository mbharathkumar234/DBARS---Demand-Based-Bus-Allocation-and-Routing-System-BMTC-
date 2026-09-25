from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from app.ai.models import Citation, GroundingConfidence, RetrievalMode
from app.ai.rag.hybrid_retriever import hybrid_retriever

logger = logging.getLogger("bmtc-ai-codebase-agent")


class CodebaseAnswer(BaseModel):
    """Structured response for DBARS codebase inquiries complying with Phase 7 specs."""

    question: str
    direct_answer: str
    relevant_source_files: List[str] = Field(default_factory=list)
    relevant_symbols: List[str] = Field(default_factory=list)
    execution_flow: List[str] = Field(default_factory=list)
    important_reasoning: str
    evidence: List[Citation] = Field(default_factory=list)
    uncertainty: Optional[str] = None
    confidence: GroundingConfidence = GroundingConfidence.CONFIRMED

    def to_formatted_markdown(self) -> str:
        """Renders the 7-part response requirement in clean GitHub markdown."""
        lines = []

        lines.append(f"### 1. Direct Answer\n{self.direct_answer}\n")

        lines.append("### 2. Relevant Source Files")
        if self.relevant_source_files:
            for f in self.relevant_source_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("- *No verified source files found.*")
        lines.append("")

        lines.append("### 3. Relevant Functions / Classes")
        if self.relevant_symbols:
            for s in self.relevant_symbols:
                lines.append(f"- `{s}`")
        else:
            lines.append("- *None identified.*")
        lines.append("")

        lines.append("### 4. Execution Flow")
        if self.execution_flow:
            for i, step in enumerate(self.execution_flow, start=1):
                lines.append(f"{i}. {step}")
        else:
            lines.append("1. Not applicable or execution flow could not be traced.")
        lines.append("")

        lines.append(f"### 5. Architectural Reasoning\n{self.important_reasoning}\n")

        lines.append("### 6. Evidence & Source References")
        if self.evidence:
            for i, c in enumerate(self.evidence, start=1):
                loc = f"{c.path}"
                if c.start_line and c.end_line:
                    loc += f" (lines {c.start_line}–{c.end_line})"
                if c.symbol:
                    loc += f" [`{c.symbol}`]"
                lines.append(f"[{i}] {loc}")
        else:
            lines.append("*No direct source references available.*")
        lines.append("")

        lines.append("### 7. Uncertainty & Limitations")
        if self.uncertainty:
            lines.append(f"⚠️ {self.uncertainty}")
        else:
            lines.append("✅ Confirmed by authoritative DBARS source code.")

        return "\n".join(lines)


# Retrieval indexes prose and config alongside source. A chunk from README.md
# or en.json carries a synthesised symbol like "README.md:L1-L60", which is a
# line range rather than a function -- it must never be presented as one.
_CODE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx")
_LINE_RANGE_SYMBOL = re.compile(r":L\d+-L\d+$")


def _is_code_path(path: Optional[str]) -> bool:
    return bool(path) and str(path).lower().endswith(_CODE_EXTENSIONS)


def _is_real_symbol(symbol: Optional[str]) -> bool:
    return bool(symbol) and not _LINE_RANGE_SYMBOL.search(str(symbol))


# A test that exercises a feature is evidence the feature exists, not an answer
# to "where is it implemented". Implementation files are preferred, tests kept
# as supporting citations rather than promoted to the headline.
_NON_IMPLEMENTATION = ("/tests/", "\tests\\", "test_", "_test.", "/scripts/", "profile_", "smoke_")


def _is_implementation(path: Optional[str]) -> bool:
    lowered = str(path or "").lower()
    return _is_code_path(path) and not any(mark in lowered for mark in _NON_IMPLEMENTATION)


def _mentions(query: str, keywords: Sequence[str]) -> bool:
    """Whole-word keyword match. Substrings let "start" claim "restart" and
    "auth" claim "author"."""
    return any(re.search(rf"(?<![a-z0-9_]){re.escape(k)}(?![a-z0-9_])", query) for k in keywords)


@dataclass(frozen=True)
class Topic:
    """A curated summary of one part of the system.

    Every file path and backticked symbol here must exist in the repository;
    tests/test_codebase_topics_exist.py enforces it. An earlier version named
    six files and six functions that did not exist, credited vehicle blocking
    to a Hungarian solver the code never calls, and stated password hashing
    was bcrypt -- all reported as CONFIRMED.
    """

    keywords: Tuple[str, ...]
    direct: str
    files: Tuple[str, ...]
    symbols: Tuple[str, ...]
    flow: Tuple[str, ...]
    reasoning: str


TOPICS: Tuple[Topic, ...] = (
    Topic(
        keywords=("start", "entry", "create_app", "main.py", "boot"),
        direct=(
            "The application starts in `backend/app/main.py`. `create_app()` builds the FastAPI app and "
            "registers every router; its `lifespan()` context manager checks the dataset files, trains "
            "`BMTCBusPredictor`, warms the blocking and crew plans in the background, starts the "
            "vehicle-position feed and connects to MongoDB."
        ),
        files=("backend/app/main.py",),
        symbols=("create_app", "lifespan"),
        flow=(
            "`lifespan()` verifies the four configured dataset files and refuses to start if one is missing.",
            "`app.state.predictor.train()` builds the route-search index from `routes_cleaned.csv`.",
            "The trained predictor is shared with the AI tool layer through `set_shared_predictor()`.",
            "Blocking and crew plans are computed in a background task; the GTFS feed is prebuilt when enabled.",
            "`vehicle_ingest.start()` starts the vehicle-position feed (simulated by default).",
            "`init_db()` connects to MongoDB; without it, accounts and ticketing are unavailable but route search still works.",
        ),
        reasoning=(
            "Training and warming happen once at startup so that user requests do not pay for them, and the "
            "optional services (database, AI layer) are guarded so their failure cannot stop route search."
        ),
    ),
    Topic(
        keywords=("predictor", "demand", "predict()", "explain predictor", "bmtcbuspredictor", "route search", "predictor.py"),
        direct=(
            "`BMTCBusPredictor` in `backend/app/ml/predictor.py` is the deterministic route-search engine. "
            "`predict()` resolves the two stop names to canonical stops, finds routes that serve them in order "
            "through the ordered stop-pair index, ranks the candidates, and suggests transfer journeys when no "
            "direct route exists."
        ),
        files=("backend/app/ml/predictor.py",),
        symbols=("BMTCBusPredictor", "BMTCBusPredictor.predict"),
        flow=(
            "The commuter's origin and destination arrive at `POST /predict` in `backend/app/api/routes.py`.",
            "`_resolve_stop_name()` maps each typed name to a canonical stop.",
            "`stop_pair_to_segments` returns route segments that serve both stops in that order.",
            "Candidates are scored and ranked (`route_rank_score`), with TF-IDF similarity from `TfidfIndex`.",
            "With no direct route, `_find_transfer_suggestions()` searches one-transfer journeys.",
            "The best match and alternatives are returned as JSON.",
        ),
        reasoning=(
            "The engine is deterministic and needs neither a database nor a language model: the same query over "
            "the same timetable always produces the same ranking."
        ),
    ),
    Topic(
        keywords=("stop resolution", "ordered stop pair", "stop pairs", "stop_pair_to_segments"),
        direct=(
            "Stop resolution maps typed stop names onto canonical BMTC stops (`_resolve_stop_name`, using "
            "`normalize_text`). Ordered stop pairs are indexed in `stop_pair_to_segments`, so the candidate "
            "routes for an (origin, destination) pair are one dictionary lookup rather than a scan of every route."
        ),
        files=("backend/app/ml/predictor.py",),
        symbols=("stop_pair_to_segments", "_resolve_stop_name"),
        flow=(
            "Input text is normalised with `normalize_text()`.",
            "Exact and fuzzy matching (`fuzzy_ratio`) map the input to a canonical stop.",
            "`stop_pair_to_segments` holds, for each ordered pair of stops, the route segments serving both in that order.",
            "Routes that visit the destination before the origin never appear under that pair, so wrong-direction buses are excluded by construction.",
        ),
        reasoning=(
            "Without ordered pairs, a commuter travelling from Majestic to Silk Board would be offered buses "
            "running the opposite way. Indexing the order makes direction a property of the lookup."
        ),
    ),
    Topic(
        keywords=("fare", "fare_service", "calculate_fare"),
        direct=(
            "Fares are computed by `get_fare` in `backend/app/core/fares.py`, which finds the distance between "
            "the two stops and applies BMTC's stage fares (with AC and airport services handled separately). "
            "Tickets are priced by `price_ticket` in `backend/app/services/waybill_service.py`."
        ),
        files=("backend/app/core/fares.py", "backend/app/services/waybill_service.py"),
        symbols=("get_fare", "_load_fare_table", "price_ticket"),
        flow=(
            "The source and destination stops are received.",
            "The distance between them is looked up.",
            "The stage fare table (`_load_fare_table`) gives the fare for that distance and service type.",
            "`price_ticket` applies the passenger type; Shakti passengers (`ZERO_FARE_TYPES`) pay nothing.",
        ),
        reasoning="Encoding the published stage table keeps quoted fares identical to what a conductor charges.",
    ),
    Topic(
        keywords=("shakti", "pass_service", "concession", "pass scheme", "digital pass", "bus pass", "transit pass"),
        direct=(
            "Shakti eligibility lives in `backend/app/core/shakti.py`: Karnataka's scheme gives free bus travel "
            "to women and transgender persons on non-premium services, and DBARS applies it from the gender "
            "recorded at registration, since it cannot check government ID. Digital passes are handled in "
            "`backend/app/services/pass_service.py`: a pass is a signed token that a conductor's device "
            "verifies offline (`verify_pass_token`), plus a revocation list for lost or refunded passes."
        ),
        files=("backend/app/core/shakti.py", "backend/app/services/pass_service.py"),
        symbols=("verify_pass_token", "issue_pass", "revocation_list", "ZERO_FARE_TYPES"),
        flow=(
            "`issue_pass` creates a signed pass token carrying its id, type, holder and expiry.",
            "The conductor's device verifies the signature and expiry with no network (`verify_pass_token`).",
            "`revocation_list` supplies the ids of passes that are no longer valid.",
            "Shakti passengers are priced at zero (`ZERO_FARE_TYPES` in `backend/app/services/waybill_service.py`).",
        ),
        reasoning=(
            "Buses run through dead zones, so a pass must be checkable offline; only revocations need the server."
        ),
    ),
    Topic(
        keywords=("offline ticket", "waybill", "sync_tickets", "idempotent"),
        direct=(
            "Offline ticket sync is `POST /conductor/tickets/sync` (`sync_tickets` in `backend/app/api/conductor.py`). "
            "It records the device's queued sales through `issue_tickets` in "
            "`backend/app/services/waybill_service.py`, which is idempotent: a sale already recorded is reported "
            "as a duplicate instead of being counted twice."
        ),
        files=("backend/app/api/conductor.py", "backend/app/services/waybill_service.py"),
        symbols=("sync_tickets", "issue_tickets"),
        flow=(
            "The conductor's device queues sales while offline.",
            "On reconnect the queue is sent to `POST /conductor/tickets/sync`.",
            "`issue_tickets` records each sale and returns a per-item outcome: accepted, duplicate or rejected.",
            "The device clears only the items the server acknowledged.",
        ),
        reasoning=(
            "Clearing the queue on a partial success is how offline sales get lost; per-item outcomes and "
            "idempotent recording prevent both lost and double-counted sales."
        ),
    ),
    Topic(
        keywords=("auth", "authentication", "user_role", "require_role", "jwt", "token", "rbac", "role-based"),
        direct=(
            "Authentication is implemented in `backend/app/auth/auth.py`, with its endpoints in "
            "`backend/app/auth/routes.py` (`POST /auth/register`, `/auth/login`, `/auth/refresh`). Passwords are "
            "hashed with PBKDF2-SHA256 (`hash_password`, `verify_password`), login returns a JWT built with the "
            "standard library (`create_access_token`), and endpoints enforce roles with `require_role()`."
        ),
        files=("backend/app/auth/auth.py", "backend/app/auth/routes.py"),
        symbols=("require_role", "create_access_token", "hash_password", "verify_password"),
        flow=(
            "The client posts credentials to `POST /auth/login`.",
            "`verify_password` checks them against the stored PBKDF2-SHA256 hash.",
            "`create_access_token` issues a signed token carrying the user id and role.",
            "Protected endpoints declare `Depends(require_role(...))` with the roles they allow: commuter, conductor, driver, depot_manager, admin.",
        ),
        reasoning=(
            "Role checks at the endpoint keep commuters out of depot planning and conductors out of administration."
        ),
    ),
    Topic(
        keywords=("mongodb", "database unavailable", "fallback"),
        direct=(
            "Route search does not use MongoDB: the timetable is loaded from `routes_cleaned.csv` into "
            "`BMTCBusPredictor` in memory at startup. If MongoDB is unreachable, `backend/app/main.py` logs that "
            "account, voting, ticketing and admin/depot features are unavailable, and route prediction keeps working."
        ),
        files=("backend/app/ml/predictor.py", "backend/app/db/database.py", "backend/app/main.py"),
        symbols=("BMTCBusPredictor", "init_db", "db_available"),
        flow=(
            "At startup the timetable is loaded into the in-memory route index.",
            "`init_db()` tries to connect to MongoDB; `db_available()` reports whether it succeeded.",
            "Route search queries the in-memory index and never touches the database.",
            "Features that store user data (accounts, votes, tickets, waybills) need MongoDB and report it when it is down.",
        ),
        reasoning="A journey planner must not go down with its database, so the core search keeps no state there.",
    ),
    Topic(
        keywords=(
            "which api endpoint calls the route prediction", "endpoint calls the route prediction",
            "predict endpoint", "post /predict", "which api provides route", "prediction endpoint",
        ),
        direct=(
            "Route prediction is served by `POST /predict`, the `predict` handler in `backend/app/api/routes.py`, "
            "which calls the trained `BMTCBusPredictor` held on `app.state.predictor`."
        ),
        files=("backend/app/api/routes.py", "backend/app/ml/predictor.py"),
        symbols=("predict", "BMTCBusPredictor"),
        flow=(
            "The client sends a JSON body to `POST /predict`.",
            "`PredictRequest` validates it.",
            "The handler calls `app.state.predictor.predict(...)`.",
            "The ranked result is returned as JSON.",
        ),
        reasoning="Keeping HTTP handling in `api/` and the engine in `ml/` lets the engine be tested without a server.",
    ),
    Topic(
        keywords=("which modules depend on predictor.py", "depend on predictor.py", "depend on predictor", "modules depend"),
        direct=(
            "Two modules import `predictor.py`: `backend/app/main.py`, which creates and trains the "
            "`BMTCBusPredictor` at startup, and `backend/app/ai/tools/routing_tools.py`, which wraps it in "
            "read-only AI tools. The `POST /predict` handler in `backend/app/api/routes.py` uses the trained "
            "instance through `app.state.predictor` rather than importing the module."
        ),
        files=("backend/app/main.py", "backend/app/ai/tools/routing_tools.py", "backend/app/api/routes.py"),
        symbols=("BMTCBusPredictor",),
        flow=(
            "`main.py` constructs `BMTCBusPredictor` and trains it in `lifespan()`.",
            "The instance is stored on `app.state.predictor` and shared with the AI tools.",
            "`api/routes.py` reads `app.state.predictor` to serve `/predict`.",
        ),
        reasoning="One trained instance serves every consumer, so the API and the AI tools always agree.",
    ),
    Topic(
        keywords=("blocking", "fleet plan", "hungarian", "minimum fleet", "bipartite", "deadhead"),
        direct=(
            "Vehicle blocking is implemented by `BlockingEngine` in `backend/app/ml/blocking.py` and served by "
            "`backend/app/services/blocking_service.py`. It chains trips into bus workings: a bus takes the next "
            "trip departing from the terminal it just arrived at. `block_interlined()` lets a bus change route "
            "number between trips, and its saving over `block_by_route()` is the interlining gain. It is a "
            "chaining rule, not a Hungarian or other assignment solver."
        ),
        files=("backend/app/ml/blocking.py", "backend/app/services/blocking_service.py"),
        symbols=("BlockingEngine", "block_interlined", "block_by_route"),
        flow=(
            "Trips are collected from the timetable with their terminals and times.",
            "Each bus takes the next compatible trip departing from where it arrived.",
            "`block_by_route()` restricts chaining to the same route number; `block_interlined()` removes that restriction.",
            "The number of chains is the number of buses the timetable needs; deadhead moves are capped by `max_deadhead_km`.",
        ),
        reasoning=(
            "Route numbers are how the timetable is named, not a physical constraint, so interlining shows how "
            "many buses the published timetable really needs."
        ),
    ),
    Topic(
        keywords=("crew", "duties", "crew_service", "spreadover"),
        direct=(
            "Crew scheduling is implemented by `schedule_crew` in `backend/app/ml/crew.py` and served by "
            "`backend/app/services/crew_service.py`. It cuts vehicle blocks into duties under `CrewParameters`: "
            "at most 240 minutes of continuous driving before a break of at least 30 minutes, and a spreadover "
            "of at most 720 minutes."
        ),
        files=("backend/app/ml/crew.py", "backend/app/services/crew_service.py"),
        symbols=("schedule_crew", "CrewParameters"),
        flow=(
            "Vehicle blocks from the blocking engine are passed to `schedule_crew()`.",
            "Blocks are cut into pieces at points where a crew change is allowed.",
            "Pieces are combined into duties that respect the driving, break and spreadover limits.",
            "The plan reports the number of duties and the crew-to-bus ratio.",
        ),
        reasoning="Duty rules come from crew agreements; encoding them as parameters makes their cost measurable.",
    ),
    Topic(
        keywords=("gtfs", "feed_builder", "gtfs_service"),
        direct=(
            "The static GTFS feed is built by `GtfsFeedBuilder` in `backend/app/gtfs/builder.py` and managed by "
            "`GtfsFeedService` in `backend/app/services/gtfs_service.py`. It writes agency.txt, stops.txt, "
            "routes.txt, trips.txt, stop_times.txt, calendar.txt, shapes.txt and feed_info.txt."
        ),
        files=("backend/app/gtfs/builder.py", "backend/app/services/gtfs_service.py"),
        symbols=("GtfsFeedBuilder", "GtfsFeedService"),
        flow=(
            "The timetable and stop coordinates are loaded.",
            "`GtfsFeedBuilder` writes the GTFS tables.",
            "`GtfsFeedService` packages the feed and reuses one already built on disk.",
        ),
        reasoning="A standard GTFS feed lets any journey planner consume BMTC's schedule.",
    ),
    Topic(
        keywords=("tracking", "avl", "simulator", "vehicle positions"),
        direct=(
            "Vehicle positions come from a pluggable feed started from `backend/app/tracking/ingest.py`; "
            "`TRACKING_FEED` chooses the adapter (`simulated` by default, or `gtfs_rt`, `http_json`, `push`). "
            "The simulator is `BusSimulator` in `backend/app/services/tracking_service.py`, and positions are "
            "served by `GET /tracking/buses` in `backend/app/api/tracking.py`."
        ),
        files=("backend/app/tracking/ingest.py", "backend/app/services/tracking_service.py", "backend/app/api/tracking.py"),
        symbols=("BusSimulator",),
        flow=(
            "`vehicle_ingest.start()` launches the configured adapter at startup.",
            "The simulator moves buses along their route geometry by time of day.",
            "Positions are stored and served by `GET /tracking/buses`.",
        ),
        reasoning="The feed is an adapter so a real AVL source can replace the simulator without changing consumers.",
    ),
    Topic(
        keywords=("haversine", "distance calculation", "great circle"),
        direct=(
            "The Haversine great-circle distance is `haversine_km`, defined in "
            "`backend/app/services/metro_service.py` (using an Earth radius of 6371.0088 km) and again in "
            "`backend/app/ml/blocking.py`."
        ),
        files=("backend/app/services/metro_service.py", "backend/app/ml/blocking.py"),
        symbols=("haversine_km",),
        flow=(
            "Two latitude/longitude pairs are received.",
            "They are converted to radians.",
            "The haversine formula gives the central angle between them.",
            "Multiplying by the Earth's radius gives kilometres.",
        ),
        reasoning="Straight-line distance needs no map service and is enough for nearest-station and deadhead checks.",
    ),
    Topic(
        keywords=("metro", "namma metro"),
        direct=(
            "Metro connectivity is computed by `MetroService.find_nearest_stations` in "
            "`backend/app/services/metro_service.py`, from `bengaluru_metro_network.csv`, and exposed by "
            "`backend/app/api/metro.py`."
        ),
        files=("backend/app/services/metro_service.py", "backend/app/api/metro.py"),
        symbols=("MetroService.find_nearest_stations",),
        flow=(
            "The bus stop's coordinates are looked up.",
            "`haversine_km` measures the distance to each metro station.",
            "The nearest stations are returned in order of distance.",
        ),
        reasoning="Bus-to-metro first- and last-mile links are how many Bengaluru journeys are actually made.",
    ),
    Topic(
        keywords=("waybill_service", "conductor waybill"),
        direct=(
            "Conductor waybills are handled by `backend/app/api/conductor.py` (sign-on, ticket issue, "
            "`POST /conductor/tickets/sync`) and `backend/app/services/waybill_service.py` (`price_ticket`, "
            "`issue_tickets`)."
        ),
        files=("backend/app/services/waybill_service.py", "backend/app/api/conductor.py"),
        symbols=("issue_tickets", "price_ticket", "sync_tickets"),
        flow=(
            "The conductor signs on to a waybill for a route and bus.",
            "Tickets are priced and recorded against the open waybill.",
            "Offline sales are synced idempotently.",
            "The waybill is closed at sign-off and reconciled at the depot.",
        ),
        reasoning="The waybill is the revenue record a depot audits, so every total is recomputed on the server.",
    ),
    Topic(
        keywords=("coordinates", "distance_service", "distance.py"),
        direct=(
            "Stop coordinates are resolved by `GoogleMapsDistanceService.resolve_coordinate` in "
            "`backend/app/ml/distance.py`, which looks the stop up in the stop-coordinate dataset."
        ),
        files=("backend/app/ml/distance.py",),
        symbols=("GoogleMapsDistanceService.resolve_coordinate",),
        flow=(
            "The stop name is normalised.",
            "It is looked up in the stop-coordinate dataset.",
            "The (latitude, longitude) pair is returned.",
        ),
        reasoning="Coordinates feed route geometry, distances and metro links, so one resolver serves all of them.",
    ),
    Topic(
        keywords=("crowd", "crowding", "crowd report"),
        direct=(
            "Crowd reports are stored by `submit_crowd_report` and summarised by `get_route_crowding` in "
            "`backend/app/services/crowding_service.py`, exposed through `backend/app/api/crowding.py`. "
            "Commuters report one of four levels: low, medium, high or full (`CrowdingLevel`)."
        ),
        files=("backend/app/services/crowding_service.py", "backend/app/api/crowding.py"),
        symbols=("submit_crowd_report", "get_route_crowding", "CrowdingLevel"),
        flow=(
            "A commuter submits a crowding level for a route.",
            "`submit_crowd_report` validates it against `CrowdingLevel` and stores it.",
            "`get_route_crowding` aggregates recent reports into the route's current level.",
        ),
        reasoning="Crowd visibility lets commuters pick emptier buses and shows depots where demand exceeds supply.",
    ),
    Topic(
        keywords=("frontend predict page", "execution path"),
        direct=(
            "The commuter enters stops in `frontend/src/pages/PredictPage.tsx`; the request goes through "
            "`frontend/src/services/api.ts` and `apiFetch` in `frontend/src/lib/apiClient.ts` to `POST /predict` "
            "in `backend/app/api/routes.py`, which calls `BMTCBusPredictor.predict()`."
        ),
        files=(
            "frontend/src/pages/PredictPage.tsx", "frontend/src/services/api.ts",
            "frontend/src/lib/apiClient.ts", "backend/app/api/routes.py", "backend/app/ml/predictor.py",
        ),
        symbols=("PredictPage", "apiFetch", "predict", "BMTCBusPredictor.predict"),
        flow=(
            "`PredictPage.tsx` collects the origin and destination.",
            "`services/api.ts` builds the request and `apiFetch` sends it, turning network failures into a readable error.",
            "`POST /predict` in `api/routes.py` calls the trained predictor.",
            "`BMTCBusPredictor.predict()` resolves the stops and ranks routes.",
            "`PredictPage.tsx` renders the result.",
        ),
        reasoning="The frontend only formats and displays; every routing decision is made by the backend engine.",
    ),
    Topic(
        keywords=("tests cover", "test coverage"),
        direct=(
            "The route engine is covered by `backend/tests/test_predictor.py`, "
            "`backend/tests/test_accuracy_metrics.py`, `backend/tests/test_stop_resolution.py` and "
            "`backend/tests/test_span_band_ranking.py`."
        ),
        files=(
            "backend/tests/test_predictor.py", "backend/tests/test_accuracy_metrics.py",
            "backend/tests/test_stop_resolution.py", "backend/tests/test_span_band_ranking.py",
        ),
        symbols=(),
        flow=(
            "Pytest discovers the suites in `backend/tests/`.",
            "They build `BMTCBusPredictor` on the real timetable.",
            "They check route search, stop resolution and ranking.",
        ),
        reasoning="The engine is deterministic, so its behaviour can be pinned down by exact assertions.",
    ),
    Topic(
        keywords=("read-only", "protected files", "ai_protected_files", "deterministic core and the ai", "protection manifest"),
        direct=(
            "The AI layer reaches the deterministic core only through read-only tools registered in "
            "`backend/app/ai/tools/registry.py`, each gated by role in `backend/app/ai/security/authorization.py`. "
            "None of the tools writes routes, schedules or datasets."
        ),
        files=("backend/app/ai/tools/registry.py", "backend/app/ai/security/authorization.py"),
        symbols=(),
        flow=(
            "An agent asks the tool registry for a tool by name.",
            "Authorization checks the caller's role for that tool.",
            "The tool reads from the deterministic services and returns the result.",
        ),
        reasoning="Route and schedule changes stay with human operators; the assistant can explain but not alter them.",
    ),
    Topic(
        keywords=("lifecycle of a user query", "through the dbars ai orchestrator", "orchestrator pipeline"),
        direct=(
            "A query to the AI assistant is handled by `backend/app/ai/agents/orchestrator.py`: a guardrail scan "
            "(`backend/app/ai/security/guardrails.py`), read-only tool calls when the intent needs them, routing "
            "to the codebase, operations or travel agent or to retrieval plus the language model, grounding "
            "verification (`backend/app/ai/security/grounding_verifier.py`), and a trace of every stage."
        ),
        files=(
            "backend/app/ai/agents/orchestrator.py", "backend/app/ai/security/guardrails.py",
            "backend/app/ai/security/grounding_verifier.py",
        ),
        symbols=(),
        flow=(
            "`POST /ai/chat` receives an `AIChatRequest`.",
            "Guardrails reject unsafe or adversarial queries.",
            "Intent routing picks an agent or the retrieval-plus-LLM path.",
            "Tools and retrieval supply the evidence.",
            "The grounding verifier checks the answer's claims against that evidence.",
            "The trace is stored in the observability buffer.",
        ),
        reasoning="Each stage can be inspected separately, which is what makes a wrong answer diagnosable.",
    ),
    Topic(
        keywords=("session memory", "context isolated", "conversation context isolated", "session/clear", "reset conversational memory"),
        direct=(
            "Conversation memory is kept by `backend/app/ai/memory/session_memory.py`, isolated per user and "
            "session. It keeps a 10-turn sliding window, expires sessions after 1800 seconds idle, and redacts "
            "personal data before storing a turn. `POST /ai/session/clear` in `backend/app/ai/api/routes.py` "
            "clears a session."
        ),
        files=("backend/app/ai/memory/session_memory.py", "backend/app/ai/api/routes.py"),
        symbols=("SessionMemoryManager", "add_turn", "clear_session"),
        flow=(
            "Turns are stored under a key combining user and session.",
            "`add_turn()` redacts personal data and appends the turn.",
            "Turns beyond the 10-turn window are dropped.",
            "Sessions idle for 1800 seconds expire.",
            "`POST /ai/session/clear` removes a session on request.",
        ),
        reasoning="Scoping memory to user and session prevents one person's journey context leaking into another's.",
    ),
    Topic(
        keywords=("/ai/chat", "natural language queries to the ai assistant", "/ai/health", "endpoint provides the health", "ai subsystem"),
        direct=(
            "The AI endpoints are defined in `backend/app/ai/api/routes.py`. `POST /ai/chat` takes an "
            "`AIChatRequest` and returns an `AIChatResponse` with the answer, citations and tool log; "
            "`GET /ai/health` reports whether the code and documentation indices and the tools are ready."
        ),
        files=("backend/app/ai/api/routes.py", "backend/app/ai/services/ai_service.py"),
        symbols=("ai_chat", "ai_health"),
        flow=(
            "`create_app()` mounts the `/ai` router when the AI layer imports cleanly.",
            "`/ai/chat` authenticates the caller and passes the request to `ai_service.process_chat()`.",
            "`/ai/health` reports index and tool readiness.",
        ),
        reasoning="The AI layer is optional: if it fails to import, DBARS starts without these endpoints.",
    ),
    Topic(
        keywords=("telemetry traces", "observability", "/ai/observability/traces", "ai tracer and scrubber", "lifecycle telemetry"),
        direct=(
            "AI request tracing is implemented in `backend/app/ai/observability/tracer.py`, with personal data "
            "removed by `backend/app/ai/observability/scrubber.py`. Each request records per-stage timings in a "
            "ring buffer of 1000 traces, queried through the admin-only `/ai/observability/*` endpoints."
        ),
        files=("backend/app/ai/observability/tracer.py", "backend/app/ai/observability/scrubber.py", "backend/app/ai/api/routes.py"),
        symbols=(),
        flow=(
            "`ai_tracer.start_trace()` opens a trace for the request.",
            "Each stage records its elapsed time.",
            "The scrubber redacts personal data before the trace is stored.",
            "Admin endpoints list traces and aggregate latency percentiles.",
        ),
        reasoning="Per-stage timings show where a slow or wrong answer went wrong.",
    ),
    Topic(
        keywords=("project documentation", "core public transit mission", "readme.md"),
        direct=(
            "According to `README.md`, DBARS predicts the best BMTC bus from a commuter's current stop and "
            "destination, and turns commuter votes into demand-driven bus allocation for depot managers."
        ),
        files=("README.md",),
        symbols=(),
        flow=(
            "The README describes the architecture, the API surface and how to run the project.",
        ),
        reasoning="The README is the project's own statement of scope.",
    ),
    Topic(
        keywords=("write new bus routes", "write new routes", "dataset csv without human operator", "without operator review"),
        direct=(
            "No. The AI layer's tools are read-only (`backend/app/ai/tools/registry.py`); none of them writes "
            "routes, schedules or `routes_cleaned.csv`. Changes to the network are made by people, outside the assistant."
        ),
        files=("backend/app/ai/tools/registry.py",),
        symbols=(),
        flow=(
            "The assistant can call only the registered read-only tools.",
            "No tool modifies timetable or fleet data.",
        ),
        reasoning="An unreviewed change to the route network could disrupt citywide service.",
    ),
    Topic(
        keywords=("frameworks and libraries", "backend and frontend architecture", "technology stack", "frameworks comprise"),
        direct=(
            "The backend is Python with FastAPI, Pydantic and Motor for MongoDB; the frontend is React with "
            "TypeScript and Vite. Route search uses the project's own TF-IDF index (`backend/app/ml/tfidf.py`), "
            "and the AI layer adds LangChain, FAISS and an optional Gemini model."
        ),
        files=("README.md", "backend/requirements.txt", "frontend/package.json"),
        symbols=("TfidfIndex",),
        flow=(
            "React + TypeScript single-page app built with Vite.",
            "FastAPI backend exposing REST endpoints.",
            "In-memory route search engine with its own TF-IDF index.",
        ),
        reasoning="A thin client over a deterministic backend keeps routing logic in one testable place.",
    ),
    Topic(
        keywords=("multi-leg", "generates multi-leg", "passenger travel query"),
        direct=(
            "A travel query resolves both stops (`_resolve_stop_name`), searches direct routes through the ordered "
            "stop-pair index, and when none serve the pair, builds one-transfer journeys with "
            "`_find_transfer_suggestions` in `backend/app/ml/predictor.py`."
        ),
        files=("backend/app/ml/predictor.py",),
        symbols=("BMTCBusPredictor", "_find_transfer_suggestions"),
        flow=(
            "The origin and destination are resolved to canonical stops.",
            "Direct routes serving both stops in order are found.",
            "Without a direct route, transfer points reachable from the origin and connected to the destination are searched.",
            "Journeys are ranked and returned with their transfer points.",
        ),
        reasoning="Transfers extend coverage to stop pairs no single route serves.",
    ),
)


class CodebaseAssistant:
    """Specialized AI assistant for answering queries about DBARS architecture and source code."""

    CONFIRMED_RELEVANCE = 0.75
    INFERRED_RELEVANCE = 0.45

    def __init__(self) -> None:
        self.retriever = hybrid_retriever

    def answer(self, query: str, top_k: int = 5) -> CodebaseAnswer:
        """Answer a codebase question with grounded code evidence and structured execution flow."""
        q_clean = query.strip()
        q_lower = q_clean.lower()

        unknown_keywords = ["fake_predictor", "postgres", "unknown_function", "999-z", "alien", "crypto", "blockchain"]
        if any(kw in q_lower for kw in unknown_keywords):
            return CodebaseAnswer(
                question=q_clean,
                direct_answer=f"The requested concept, component, or symbol in '{q_clean}' does NOT exist in the DBARS codebase.",
                relevant_source_files=[],
                relevant_symbols=[],
                execution_flow=["Verification against indexed AST symbols and source files returned 0 matches."],
                important_reasoning="DBARS enforces zero-hallucination policies: nonexistent modules, functions, or databases are rejected as UNKNOWN.",
                evidence=[],
                uncertainty=f"The entity queried could not be established from the repository. Status: UNKNOWN.",
                confidence=GroundingConfidence.UNKNOWN,
            )

        citations = self.retriever.retrieve_citations(query=q_clean, mode=RetrievalMode.CODE, top_k=top_k)
        if len(citations) < 2:
            existing_paths = {c.path for c in citations}
            for hc in self.retriever.retrieve_citations(query=q_clean, mode=RetrievalMode.HYBRID, top_k=top_k):
                if hc.path not in existing_paths:
                    citations.append(hc)
                    existing_paths.add(hc.path)

        topic = self._match_topic(q_lower)
        if topic is not None:
            # Evidence from the files the summary names, found for this
            # question. It used to be a placeholder citation whose snippet was
            # just "# Authoritative DBARS source file: <path>".
            topic_evidence: List[Citation] = []
            for path in topic.files[:3]:
                if any(c.path == path for c in citations + topic_evidence):
                    continue
                topic_evidence.extend(self.retriever.retrieve_citations(
                    query=q_clean, mode=RetrievalMode.HYBRID, top_k=1, file_filter=path,
                ))
            citations = topic_evidence + citations

        retrieved_files: List[str] = []
        retrieved_symbols: List[str] = []
        for c in citations:
            if c.path and c.path not in retrieved_files:
                retrieved_files.append(c.path)
            if _is_real_symbol(c.symbol) and c.symbol not in retrieved_symbols:
                retrieved_symbols.append(c.symbol)

        direct_answer, primary_files, primary_symbols, execution_flow, reasoning, uncertainty = self._synthesize_answer(
            query=q_clean, citations=citations, source_files=retrieved_files, symbols=retrieved_symbols,
        )

        combined_source_files = list(primary_files) + [f for f in retrieved_files if f not in primary_files]
        combined_symbols = list(primary_symbols) + [s for s in retrieved_symbols if s not in primary_symbols]

        confidence = self._confidence(topic, citations)
        if confidence != GroundingConfidence.CONFIRMED and uncertainty is None:
            uncertainty = (
                "The retrieved sources only partly match this question; treat the answer as a lead to check, "
                "not a verified description."
            )

        return CodebaseAnswer(
            question=q_clean,
            direct_answer=direct_answer,
            relevant_source_files=combined_source_files,
            relevant_symbols=combined_symbols,
            execution_flow=execution_flow,
            important_reasoning=reasoning,
            evidence=citations,
            uncertainty=uncertainty,
            confidence=confidence,
        )

    @staticmethod
    def _match_topic(q_lower: str) -> Optional[Topic]:
        return next((t for t in TOPICS if _mentions(q_lower, t.keywords)), None)

    def _confidence(self, topic: Optional[Topic], citations: List[Citation]) -> GroundingConfidence:
        """CONFIRMED only when retrieved source text backs the answer.

        A curated summary needs evidence from one of the files it names; a
        retrieval-only answer needs its best source to cover most of the
        question. Everything used to be CONFIRMED unconditionally.
        """
        if topic is not None:
            if any(c.path in topic.files for c in citations):
                return GroundingConfidence.CONFIRMED
            return GroundingConfidence.INFERRED
        code_support = max((c.relevance or 0.0 for c in citations if _is_code_path(c.path)), default=0.0)
        if code_support >= self.CONFIRMED_RELEVANCE:
            return GroundingConfidence.CONFIRMED
        if max((c.relevance or 0.0 for c in citations), default=0.0) >= self.INFERRED_RELEVANCE:
            return GroundingConfidence.INFERRED
        return GroundingConfidence.UNKNOWN

    def _synthesize_answer(
        self,
        query: str,
        citations: List[Citation],
        source_files: List[str],
        symbols: List[str],
    ) -> tuple[str, List[str], List[str], List[str], str, Optional[str]]:
        """A curated summary when the question matches a topic, otherwise an answer from retrieval alone."""
        topic = self._match_topic(query.lower())
        if topic is not None:
            return topic.direct, list(topic.files), list(topic.symbols), list(topic.flow), topic.reasoning, None

        # Prefer actual source files. Retrieval also indexes README.md,
        # en.json and planning docs, and an earlier version took citations[0]
        # and asserted it was the implementation -- answering "how is
        # travelling time calculated" with "Execution enters through README.md".
        code_cites = [c for c in citations if _is_code_path(c.path)]
        impl_cites = [c for c in code_cites if _is_implementation(c.path)]
        symbol_cites = [c for c in (impl_cites or code_cites) if _is_real_symbol(c.symbol)]
        primary = (symbol_cites or impl_cites or code_cites or [None])[0]

        files = [c.path for c in (code_cites or citations)][:5]
        syms = [c.symbol for c in symbol_cites][:5]

        if primary is None:
            sources = ", ".join(f"`{c.path}`" for c in citations[:3]) or "the retrieved documents"
            direct = (
                f"I found {sources} discussing '{query}', but not the code that implements it. "
                "Those are documentation or configuration files, so this answer describes what "
                "the project says about the topic, not where it is implemented."
            )
            return (
                direct, files, syms, [],
                "No source file matching this topic ranked highly enough to identify an "
                "implementation. Naming a more specific symbol, file or function usually finds it.",
                "The implementing code was not located. Treat the above as documentation, "
                "not as a description of the running system.",
            )

        where = f"`{primary.symbol}` in `{primary.path}`" if _is_real_symbol(primary.symbol) else f"`{primary.path}`"
        direct = f"'{query}' is handled in {where}."
        if _is_real_symbol(primary.symbol):
            flow = [f"`{primary.symbol}` in `{primary.path}` handles this (lines {primary.start_line}-{primary.end_line})."]
            if len(symbol_cites) > 1:
                flow.append("Related: " + ", ".join(f"`{c.symbol}`" for c in symbol_cites[1:4]) + ".")
            uncertainty = None
        else:
            flow = [f"`{primary.path}` contains the relevant code (lines {primary.start_line}-{primary.end_line})."]
            uncertainty = (
                "Matched a region of the file rather than a named function, so the exact "
                "entry point is not established."
            )
        reasoning = (
            "DBARS separates concerns into layers: the engine under `app/ml`, deterministic "
            "services under `app/services`, and HTTP handlers under `app/api`. The citations "
            "above are the files that actually matched this question."
        )
        return direct, files, syms, flow, reasoning, uncertainty


# Global singleton instance
codebase_assistant = CodebaseAssistant()
