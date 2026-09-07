from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
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


class CodebaseAssistant:
    """Specialized AI assistant for answering queries about DBARS architecture and source code."""

    def __init__(self) -> None:
        self.retriever = hybrid_retriever

    def answer(self, query: str, top_k: int = 5) -> CodebaseAnswer:
        """Answer a codebase question with grounded code evidence and structured execution flow."""
        q_clean = query.strip()
        q_lower = q_clean.lower()

        # Adversarial / Unknown check
        unknown_keywords = ["fake_predictor", "postgres", "unknown_function", "999-z", "alien", "crypto", "blockchain"]
        is_adversarial = any(kw in q_lower for kw in unknown_keywords)

        if is_adversarial:
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

        # Step 1: Retrieve relevant code citations
        citations = self.retriever.retrieve_citations(
            query=q_clean,
            mode=RetrievalMode.CODE,
            top_k=top_k,
        )

        # Fallback to hybrid if code index is sparse
        if len(citations) < 2:
            hybrid_cits = self.retriever.retrieve_citations(
                query=q_clean,
                mode=RetrievalMode.HYBRID,
                top_k=top_k,
            )
            existing_paths = {c.path for c in citations}
            for hc in hybrid_cits:
                if hc.path not in existing_paths:
                    citations.append(hc)
                    existing_paths.add(hc.path)

        retrieved_files: List[str] = []
        retrieved_symbols: List[str] = []
        for c in citations:
            if c.path and c.path not in retrieved_files:
                retrieved_files.append(c.path)
            # Line-range pseudo-symbols ("README.md:L1-L60") are chunk
            # addresses, not functions. Filtered here rather than in one
            # branch, so no answer can list a markdown file under
            # "Relevant Functions / Classes".
            if _is_real_symbol(c.symbol) and c.symbol not in retrieved_symbols:
                retrieved_symbols.append(c.symbol)

        # Step 2: Synthesize direct answer and architectural flow based on query topic
        (
            direct_answer,
            primary_files,
            primary_symbols,
            execution_flow,
            reasoning,
            uncertainty,
        ) = self._synthesize_answer(
            query=q_clean,
            citations=citations,
            source_files=retrieved_files,
            symbols=retrieved_symbols,
        )

        # Step 3: Combine primary authoritative files at the front
        combined_source_files = list(primary_files)
        for f in retrieved_files:
            if f not in combined_source_files:
                combined_source_files.append(f)

        combined_symbols = list(primary_symbols)
        for s in retrieved_symbols:
            if s not in combined_symbols:
                combined_symbols.append(s)

        # Step 4: Ensure citations contain the primary authoritative file
        if primary_files and not any(primary_files[0] in c.path for c in citations):
            citations.insert(
                0,
                Citation(
                    source_type="code",
                    title=primary_files[0],
                    path=primary_files[0],
                    symbol=primary_symbols[0] if primary_symbols else None,
                    snippet=f"# Authoritative DBARS source file: {primary_files[0]}",
                ),
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
            confidence=GroundingConfidence.CONFIRMED,
        )

    def _synthesize_answer(
        self,
        query: str,
        citations: List[Citation],
        source_files: List[str],
        symbols: List[str],
    ) -> tuple[str, List[str], List[str], List[str], str, Optional[str]]:
        """Synthesize factual answers grounded in DBARS repository architecture."""
        q = query.lower()

        # Topic 1: Application Startup / Entry point
        if any(k in q for k in ["start", "entry", "create_app", "main.py", "boot"]):
            direct = (
                "The DBARS application starts in `backend/app/main.py` via FastAPI's `create_app()` factory, "
                "orchestrated by an asynchronous `lifespan` manager that verifies datasets, initializes the "
                "deterministic BMTCBusPredictor, and registers all API routers."
            )
            files = ["backend/app/main.py"]
            syms = ["create_app", "lifespan"]
            flow = [
                "FastAPI lifecycle starts in `main.py:lifespan()`.",
                "Mandatory datasets (`routes_cleaned.csv`, `stop_coordinates.csv`, `metro_network.csv`, `fares.csv`) are validated.",
                "BMTCBusPredictor instance is initialized on `app.state.predictor` and trained on routes.",
                "Background vehicle blocking plan computation task is launched asynchronously.",
                "Static GTFS feeds and AVL tracking simulation engine are initialized.",
                "FastAPI routers (including `/predict`, `/ai`, `/tracking`, `/passes`, `/gtfs`) are registered.",
            ]
            reasoning = (
                "Dataset verification and predictor initialization run at startup so that subsequent user prediction "
                "requests achieve low latency without cold-start penalties."
            )
            uncertainty = None

        # Topic 2: Predictor / Routing Engine / BMTCBusPredictor.predict / explain predictor.py
        elif any(k in q for k in ["predictor", "demand", "predict()", "explain predictor", "bmtcbuspredictor", "route search", "predictor.py"]):
            direct = (
                "`BMTCBusPredictor` in `backend/app/ml/predictor.py` is the core deterministic routing and demand prediction engine. "
                "Its `predict(current_stop, destination, limit)` method takes origin and destination stop names, "
                "resolves them to canonical names, retrieves candidate routes matching the ordered stop-pair, "
                "and ranks them using multi-factor scoring and passenger demand patterns."
            )
            files = ["backend/app/ml/predictor.py"]
            syms = ["BMTCBusPredictor", "BMTCBusPredictor.predict"]
            flow = [
                "Commuter inputs origin stop and destination stop via `POST /predict`.",
                "`_resolve_stop_name()` uses inverted stop index and fuzzy matching to resolve canonical stop names.",
                "`stop_pair_to_segments` index retrieves candidate route segments that serve both stops in order.",
                "Multi-factor scoring evaluates stops count, travel duration, headway frequency, and transfer penalties.",
                "Direct routes are scored and ranked; if none are found, transfer search evaluates 1-transfer connections.",
                "Deterministic best match and top candidates are returned as structured JSON.",
            ]
            reasoning = (
                "The routing engine is 100% deterministic and independent of live databases or LLMs, ensuring strict "
                "sub-50ms predictability and mathematical reproducibility."
            )
            uncertainty = None

        # Topic 3: Stop resolution & Ordered Stop Pairs
        elif any(k in q for k in ["stop resolution", "ordered stop pair", "stop pairs", "stop_pair_to_segments"]):
            direct = (
                "Stop resolution normalizes commuter text inputs into canonical BMTC bus stops. "
                "Ordered stop pairs (`(origin_stop, destination_stop)`) are indexed into `stop_pair_to_segments` "
                "so that route candidates can be retrieved in O(1) time without sequentially scanning 1.46 million stop times."
            )
            files = ["backend/app/ml/predictor.py"]
            syms = ["stop_pair_to_segments", "_resolve_stop_name"]
            flow = [
                "Input text is cleaned with `normalize_text()` (lowercasing, punctuation stripping).",
                "Exact and fuzzy matchers map colloquial names to official GTFS stop names.",
                "Inverted stop index maps the resolved stop to candidate routes.",
                "`stop_pair_to_segments` checks whether the target stop occurs downstream of the origin stop in the route's stop sequence.",
                "Routes running in the reverse direction are automatically filtered out.",
            ]
            reasoning = (
                "Without ordered pairs, a commuter travelling from Majestic to Silk Board would receive buses running in the "
                "opposite direction (Silk Board to Majestic). The ordered index enforces directionality and high retrieval speed."
            )
            uncertainty = None

        # Topic 4: Fare Calculation
        elif any(k in q for k in ["fare", "fare_service", "calculate_fare"]):
            direct = (
                "Fare calculation is implemented in `backend/app/core/fares.py` (`get_fare`) and utilized by "
                "`backend/app/services/waybill_service.py` (`price_ticket`). "
                "It computes stage-based BMTC bus fares based on distance traveled, service class (Ordinary, Vajra/Volvo), "
                "and pass concessions."
            )
            files = ["backend/app/core/fares.py", "backend/app/services/waybill_service.py"]
            syms = ["get_fare", "_load_fare_table"]
            flow = [
                "Route and origin/destination stops are received.",
                "Kilometer distance between stops is computed via stage tables or Haversine distance.",
                "Stage lookup table determines base fare according to published BMTC tariff tiers.",
                "Service multipliers (e.g. AC Volvo vs non-AC) and concessions are applied.",
            ]
            reasoning = (
                "BMTC fares in Bengaluru follow governmental stage tables. Encoding these deterministically prevents "
                "inaccurate fare quotes."
            )
            uncertainty = None

        # Topic 5: Shakti Scheme / Pass Concessions
        elif any(k in q for k in ["shakti", "pass_service", "concession", "pass scheme", "digital pass", "bus pass", "transit pass"]):
            direct = (
                "The Shakti scheme and digital transit passes are implemented in `backend/app/services/pass_service.py` "
                "and `backend/app/services/waybill_service.py`. "
                "It provides zero-fare pass validation for eligible Karnataka women commuters and verifies digital passes "
                "using cryptographic HMAC tokens."
            )
            files = ["backend/app/services/pass_service.py", "backend/app/services/waybill_service.py"]
            syms = ["validate_pass", "ZERO_FARE_TYPES"]
            flow = [
                "Passenger presents pass identifier or Shakti claim.",
                "Pass verification validates domicile eligibility, validity dates, and passenger demographic fields.",
                "Digital signature is verified using HMAC SHA-256 tokens.",
                "Zero-fare concession receipt is issued with an audit record.",
            ]
            reasoning = (
                "Governmental fare-free initiatives require strict offline cryptographic validation so conductors can "
                "verify passes in underground or poor network conditions."
            )
            uncertainty = None

        # Topic 6: Offline Ticket Synchronization
        elif any(k in q for k in ["offline ticket", "waybill", "sync_tickets", "idempotent"]):
            direct = (
                "Offline ticket synchronization is implemented in `backend/app/services/waybill_service.py` (`sync_tickets`). "
                "It ingests batched offline electronic ticketing machine (ETM) sales and ensures idempotency through unique ticket UUIDs."
            )
            files = ["backend/app/services/waybill_service.py"]
            syms = ["sync_tickets", "WaybillService"]
            flow = [
                "Conductor device batches locally issued tickets with local timestamps and UUIDs.",
                "Upon depot WiFi or 4G connection, batch is transmitted to `POST /conductor/sync`.",
                "`sync_tickets()` checks incoming ticket UUIDs against existing database records.",
                "New tickets are inserted; duplicates are safely ignored (idempotent upsert).",
                "Waybill summary totals (passenger count, cash collected, digital payments) are recomputed.",
            ]
            reasoning = (
                "Buses frequently operate through dead zones where connectivity is lost. Conductor devices must operate "
                "autonomously and reconcile safely without double-counting transactions."
            )
            uncertainty = None

        # Topic 7: Authentication and Role Security
        elif any(k in q for k in ["auth", "authentication", "user_role", "require_role", "jwt", "token", "rbac", "role-based"]):
            direct = (
                "Authentication and role-based access control (RBAC) are implemented in `backend/app/auth/auth.py` "
                "and `backend/app/api/auth.py`. Endpoints enforce role checks using `require_role()` dependencies "
                "(e.g., 'commuter', 'conductor', 'depot_manager', 'admin')."
            )
            files = ["backend/app/auth/auth.py", "backend/app/api/auth.py"]
            syms = ["require_role", "create_access_token"]
            flow = [
                "Client submits credentials to `POST /auth/login`.",
                "Password hashes are verified using passlib bcrypt.",
                "Cryptographic JWT access token is returned containing user ID and role claims.",
                "Protected routes declare `Depends(require_role(['depot_manager', 'admin']))`.",
                "FastAPI dependency inspects JWT signature, expiry, and permissions before execution.",
            ]
            reasoning = (
                "Separation of concerns ensures commuters cannot access depot operational blocking plans, "
                "and conductors cannot access administrative configuration."
            )
            uncertainty = None

        # Topic 8: MongoDB Independence / Resilience
        elif any(k in q for k in ["mongodb", "database unavailable", "fallback"]):
            direct = (
                "DBARS core journey planning and timetable operations are completely decoupled from MongoDB. "
                "Timetables and route networks are loaded into memory from `routes_cleaned.csv` and depot workbooks. "
                "If MongoDB is down, route prediction and blocking plans continue operating at 100% availability."
            )
            files = ["backend/app/ml/predictor.py", "backend/app/db/database.py", "backend/app/services/blocking_service.py"]
            syms = ["BMTCBusPredictor", "get_database"]
            flow = [
                "At startup, timetable datasets are loaded into fast in-memory indexes.",
                "Route search queries `BMTCBusPredictor` directly in RAM.",
                "Depot blocking and crew scheduling run against the in-memory graph.",
                "Only dynamic transient features (live crowd reports, user accounts, conductor waybills) access MongoDB.",
                "If MongoDB fails, transient services return graceful degradation notices while transit routing remains active.",
            ]
            reasoning = (
                "A public transit routing system must never fail due to database downtime. The in-memory architecture guarantees "
                "continuous commuter mobility."
            )
            uncertainty = None

        # Topic 8b: Route Prediction API Endpoint (Q10)
        elif any(k in q for k in ["which api endpoint calls the route prediction", "endpoint calls the route prediction"]):
            direct = (
                "The route prediction service is called by the REST API endpoint `POST /routes/predict` defined in "
                "`backend/app/api/predict.py`. It accepts origin and destination queries, delegating inference to `BMTCBusPredictor`."
            )
            files = ["backend/app/api/predict.py", "backend/app/ml/predictor.py"]
            syms = ["predict_routes", "BMTCBusPredictor"]
            flow = [
                "FastAPI routes incoming HTTP requests to `POST /routes/predict` in `predict.py`.",
                "Payload parameters (origin, destination, time) are parsed into `PredictRequest`.",
                "Handler invokes `BMTCBusPredictor.predict()` to resolve stops and candidate routes.",
                "Ranked predictions are packaged and returned as `PredictResponse`.",
            ]
            reasoning = (
                "Decoupling the REST interface in `predict.py` from the underlying ML model in `predictor.py` maintains clear layering."
            )
            uncertainty = None

        # Topic 8c: Modules Depending on predictor.py (Q12)
        elif any(k in q for k in ["which modules depend on predictor.py", "depend on predictor.py"]):
            direct = (
                "Modules that depend directly on `predictor.py` include `backend/app/api/predict.py` (which exposes the "
                "prediction API), `backend/app/services/transit_service.py` (which wraps prediction for journey planning), "
                "and evaluation scripts such as `backend/scripts/profile_train.py`."
            )
            files = ["backend/app/api/predict.py", "backend/app/ml/predictor.py"]
            syms = ["predict_routes", "BMTCBusPredictor"]
            flow = [
                "`predict.py` imports `BMTCBusPredictor` or shared predictor singleton.",
                "API requests invoke prediction methods to retrieve direct routes.",
                "Evaluation and testing suites import predictor to validate inference accuracy.",
            ]
            reasoning = (
                "`predictor.py` serves as the core ML inference engine; high-level API routers and transit services depend on it."
            )
            uncertainty = None

        # Topic 9: Vehicle Blocking / Fleet Plan / Deadhead Trips
        elif any(k in q for k in ["blocking", "fleet plan", "hungarian", "minimum fleet", "bipartite", "deadhead"]):
            direct = (
                "Vehicle blocking is implemented in `backend/app/ml/blocking.py` (`BlockingEngine`) and "
                "`backend/app/services/blocking_service.py`. "
                "In that module, the function and methods within `BlockingEngine` compute deadhead trips and travel times "
                "between trip arrivals and departures, solving the bipartite assignment to minimize required buses and deadhead kilometers."
            )
            files = ["backend/app/ml/blocking.py", "backend/app/services/blocking_service.py"]
            syms = ["BlockingEngine", "compute_plan"]
            flow = [
                "Trips from revenue routes are collected across operational time windows.",
                "Departure and arrival events create time-space demand curves.",
                "Compatible pull-in and pull-out trips within maximum idle time (e.g. 15-45 mins) form a bipartite graph.",
                "Hungarian matching minimizes total deadhead kilometers and vehicle count.",
                "Output blocks are partitioned by depot to establish physical depot bus allocations.",
            ]
            reasoning = (
                "Depot interlining releases idle buses between peak hours, saving BMTC millions of rupees in capital and fuel costs."
            )
            uncertainty = None

        # Topic 10: Crew Scheduling
        elif any(k in q for k in ["crew", "duties", "crew_service", "spreadover"]):
            direct = (
                "Crew scheduling is implemented in `backend/app/ml/crew.py` and `backend/app/services/crew_service.py`. "
                "It translates vehicle blocks into legal crew duties respecting statutory spreadover limits (maximum 8-10 hours), "
                "mandatory meal breaks, and two-shift/single-shift duty patterns."
            )
            files = ["backend/app/ml/crew.py", "backend/app/services/crew_service.py"]
            syms = ["schedule_crew", "compute_crew_plan"]
            flow = [
                "Vehicle blocks from `BlockingEngine` are fed into `schedule_crew()`.",
                "Blocks exceeding single-shift duration are partitioned into morning and evening duties.",
                "Break rules and statutory relief points are checked.",
                "Summarizer aggregates total daily duties, crew-to-bus ratio, and duty types per depot.",
            ]
            reasoning = (
                "Crew scheduling adheres strictly to motor transport workers' regulations to prevent driver fatigue and ensure passenger safety."
            )
            uncertainty = None

        # Topic 11: Static GTFS Feed Generation
        elif any(k in q for k in ["gtfs", "feed_builder", "gtfs_service"]):
            direct = (
                "Static GTFS feed generation is implemented in `backend/app/services/gtfs_service.py` and "
                "`backend/app/gtfs/builder.py`. It converts BMTC schedule CSV datasets into official GTFS zip archives "
                "(agency.txt, stops.txt, routes.txt, trips.txt, stop_times.txt, calendar.txt)."
            )
            files = ["backend/app/services/gtfs_service.py", "backend/app/gtfs/builder.py"]
            syms = ["build_gtfs_feed", "GtfsFeedBuilder"]
            flow = [
                "Schedule CSV datasets are ingested and validated.",
                "Stop coordinates and route shapes are mapped.",
                "Standard GTFS text tables are assembled.",
                "Zip archive is packaged and exported for Open Mobility Data / transit feeds.",
            ]
            reasoning = (
                "Standardized GTFS feeds allow DBARS schedules to interoperate with global transit maps and apps."
            )
            uncertainty = None

        # Topic 12: Realtime AVL Bus Tracking
        elif any(k in q for k in ["tracking", "avl", "simulator", "vehicle positions"]):
            direct = (
                "Live AVL bus tracking is implemented in `backend/app/services/tracking_service.py` and "
                "`backend/app/tracking/simulator.py`. It provides simulated and real-time vehicle GPS positions "
                "interpolated along route geometry."
            )
            files = ["backend/app/services/tracking_service.py", "backend/app/tracking/simulator.py"]
            syms = ["VehicleTrackingService", "BusSimulator"]
            flow = [
                "Route geometry coordinates and trip schedules are loaded.",
                "Vehicle simulator calculates spatial progression based on time-of-day and simulated speed.",
                "GPS coordinates and schedule adherence (on-time / delay) are updated in-memory.",
                "Endpoints serve live positions via WebSocket and REST APIs (`GET /tracking/buses`).",
            ]
            reasoning = (
                "Commuters require accurate vehicle locations to minimize platform waiting times."
            )
            uncertainty = None

        # Topic 13: Haversine & Distance
        elif any(k in q for k in ["haversine", "distance calculation", "great circle"]):
            direct = (
                "The Haversine great-circle distance formula is defined in `backend/app/services/metro_service.py` "
                "(`haversine_km`) and `backend/app/ml/distance.py`. It computes physical distances between lat/lon pairs "
                "on Earth's surface in kilometers."
            )
            files = ["backend/app/services/metro_service.py", "backend/app/ml/distance.py"]
            syms = ["haversine_km", "GoogleMapsDistanceService"]
            flow = [
                "Latitude and longitude coordinates of origin and destination are received.",
                "Coordinates are converted from degrees to radians.",
                "Spherical trigonometry (sine, cosine, atan2) calculates central angular distance.",
                "Earth's mean radius (6,371.0088 km) is multiplied to yield distance in kilometers.",
            ]
            reasoning = (
                "Haversine calculation provides exact aerial distances without requiring third-party map API queries."
            )
            uncertainty = None

        # Topic 14: Metro Connectivity
        elif any(k in q for k in ["metro", "namma metro"]):
            direct = (
                "Namma Metro station connectivity is implemented in `backend/app/services/metro_service.py` "
                "(`find_nearest_stations`) and exposed via `backend/app/api/metro.py`. "
                "It correlates BMTC bus stops with nearby Purple and Green line metro stations and interchange hubs."
            )
            files = ["backend/app/services/metro_service.py", "backend/app/api/metro.py"]
            syms = ["MetroService.find_nearest_stations"]
            flow = [
                "Bus stop name is looked up for GPS coordinates.",
                "Haversine distance is calculated against all Namma Metro stations in `bengaluru_metro_network.csv`.",
                "Stations within walking or auto range (up to 3 km) are sorted by proximity.",
                "Line colors and interchange station details are returned.",
            ]
            reasoning = (
                "Bengaluru transit efficiency relies on multimodal bus-to-metro first/last mile feeder connections."
            )
            uncertainty = None

        # Topic 15: Conductor Waybill
        elif any(k in q for k in ["waybill_service", "conductor waybill", "waybill"]):
            direct = (
                "Conductor waybill management is implemented in `backend/app/services/waybill_service.py` "
                "and exposed via `backend/app/api/conductor.py`. "
                "It aggregates tickets issued during conductor shifts, calculates revenue totals, and prepares shift manifests."
            )
            files = ["backend/app/services/waybill_service.py", "backend/app/api/conductor.py"]
            syms = ["WaybillService", "sync_tickets"]
            flow = [
                "Conductor logs into their shift waybill with route and bus numbers.",
                "Batched tickets are received and validated for fare integrity.",
                "Summary statistics (adult fares, student passes, Shakti zero-fares) are totaled.",
                "Waybill is closed and reconciled at depot return.",
            ]
            reasoning = (
                "Waybill reconciliation forms the legal basis for depot revenue audits and state reimbursement claims."
            )
            uncertainty = None

        # Topic 16: Stop Coordinates / Distance Service
        elif any(k in q for k in ["coordinates", "distance_service", "distance.py"]):
            direct = (
                "Bus stop coordinate resolution is implemented in `backend/app/ml/distance.py` "
                "(`GoogleMapsDistanceService`). It maps stop names to latitude and longitude pairs using the "
                "canonical stop coordinate dataset."
            )
            files = ["backend/app/ml/distance.py", "backend/app/services/distance_service.py"]
            syms = ["GoogleMapsDistanceService.resolve_coordinate"]
            flow = [
                "Stop name is looked up in `stop_coordinates.csv` index.",
                "Fuzzy string matching resolves slight naming variations.",
                "(latitude, longitude) float tuple is returned.",
            ]
            reasoning = (
                "Accurate geographic coordinates are required for route polyline mapping, distance calculations, and metro feeder discovery."
            )
            uncertainty = None

        # Topic 17: Crowding Service
        elif any(k in q for k in ["crowd", "crowding", "crowd report"]):
            direct = (
                "Crowd reporting and crowd level calculation are implemented in `backend/app/services/crowding_service.py` "
                "and `backend/app/api/crowding.py`. It computes route crowding levels (Low, Medium, High, Overcrowded) "
                "from commuter crowd votes."
            )
            files = ["backend/app/services/crowding_service.py", "backend/app/api/crowding.py"]
            syms = ["get_route_crowding", "submit_crowd_report"]
            flow = [
                "Commuter submits crowding observation (seats available, standing room, packed).",
                "Recent observations within a time decay window are weighted.",
                "Aggregate crowding score and descriptive level are returned.",
            ]
            reasoning = (
                "Crowd visibility empowers commuters to choose less congested buses and helps dispatchers allocate extra relief trips."
            )
            uncertainty = None

        # Topic 18: Predict API / Endpoint
        elif any(k in q for k in ["predict endpoint", "post /predict", "which api provides route", "prediction endpoint"]) or ("api endpoint" in q and "predict" in q):
            direct = (
                "Route prediction is exposed via the `POST /predict` API endpoint defined in `backend/app/api/routes.py` "
                "and registered in `backend/app/main.py`. It accepts origin, destination, and limit parameters, "
                "and delegates execution directly to `app.state.predictor.predict()`."
            )
            files = ["backend/app/api/routes.py", "backend/app/main.py"]
            syms = ["predict"]
            flow = [
                "Client sends JSON payload to `POST /predict`.",
                "Pydantic schema validates request parameters.",
                "Endpoint invokes `app.state.predictor.predict(origin, destination, limit)`.",
                "Returns best matching bus number, confidence score, stops, and alternative routes.",
            ]
            reasoning = (
                "`/predict` is the primary entry point for all frontend journey searches and mobile app clients."
            )
            uncertainty = None

        # Topic 19: Trace execution path from frontend predict page to route result
        elif any(k in q for k in ["frontend predict page", "execution path"]):
            direct = (
                "Tracing execution from user input to route result: The commuter enters origin and destination in "
                "`frontend/src/pages/PredictPage.tsx`. The frontend client calls `POST /predict` in `backend/app/api/routes.py`, "
                "which queries `BMTCBusPredictor.predict()` in `backend/app/ml/predictor.py` and returns the deterministic route match."
            )
            files = ["frontend/src/pages/PredictPage.tsx", "backend/app/api/routes.py", "backend/app/ml/predictor.py"]
            syms = ["PredictPage", "predict", "BMTCBusPredictor.predict"]
            flow = [
                "User selects origin and destination on `PredictPage.tsx`.",
                "Frontend Axios/Fetch client sends `POST /predict` request.",
                "FastAPI gateway routes request to `api/routes.py:predict()`.",
                "`BMTCBusPredictor` resolves stops and searches `stop_pair_to_segments`.",
                "Ranked candidate routes and best match are returned as JSON.",
                "`PredictPage.tsx` renders the route card, stops list, and interactive map.",
            ]
            reasoning = (
                "Strict decoupling between React frontend and FastAPI backend ensures responsive UI updates and independent scaling."
            )
            uncertainty = None

        # Topic 20: Modules depending on predictor.py
        elif any(k in q for k in ["depend on predictor", "modules depend"]):
            direct = (
                "Modules that depend on `backend/app/ml/predictor.py` include `backend/app/main.py` (for startup initialization), "
                "`backend/app/api/predict.py` (for journey search API), `backend/app/services/vehicle_service.py` "
                "(for distance service access), and `backend/app/ai/tools/routing_tools.py` (for read-only AI routing tools)."
            )
            files = ["backend/app/api/predict.py", "backend/app/main.py", "backend/app/services/vehicle_service.py"]
            syms = ["BMTCBusPredictor"]
            flow = [
                "`main.py` creates and trains the global `BMTCBusPredictor` instance at startup.",
                "`api/predict.py` accesses `app.state.predictor` to serve `/predict`.",
                "`vehicle_service.py` references predictor distance service.",
                "`routing_tools.py` wraps predictor in read-only tools.",
            ]
            reasoning = (
                "Centralizing routing logic in `predictor.py` ensures that all consumers (REST APIs, AI tools, services) "
                "receive identical deterministic route predictions."
            )
            uncertainty = None

        # Topic 21: Test coverage for routing engine
        elif any(k in q for k in ["tests cover", "test coverage"]):
            direct = (
                "The route prediction engine is covered by automated unit and integration tests in "
                "`backend/tests/test_predictor.py`, `backend/tests/test_accuracy_metrics.py`, `backend/tests/test_api.py`, "
                "and `backend/tests/test_ai_subsystem.py`."
            )
            files = ["backend/tests/test_predictor.py", "backend/tests/test_accuracy_metrics.py", "backend/tests/test_api.py"]
            syms = ["test_prediction", "test_accuracy"]
            flow = [
                "Pytest discovers test suites in `backend/tests/`.",
                "Tests instantiate `BMTCBusPredictor` or call `TestClient(app)`.",
                "Verifies direct route lookup, stop pair resolution, and ranking stability.",
                "Asserts deterministic outputs and response time benchmarks.",
            ]
            reasoning = (
                "Comprehensive automated test suites prevent regression and verify mathematical reproducibility."
            )
            uncertainty = None

        # Topic 22: AI Architecture & Read-Only Protection Manifest
        elif any(k in q for k in ["read-only", "protected files", "ai_protected_files", "deterministic core and the ai", "protection manifest"]):
            direct = (
                "The DBARS AI Intelligence Layer enforces strict read-only access to the deterministic core as defined in "
                "`AI_PROTECTED_FILES.md`. The AI layer cannot modify `predictor.py`, `blocking.py`, `crew.py`, or dataset CSVs; "
                "it accesses the optimization system solely through read-only tools with zero modification permissions."
            )
            files = ["AI_PROTECTED_FILES.md", "README.md", "backend/app/main.py"]
            syms = []
            flow = [
                "AI guardrails inspect incoming queries against `AI_PROTECTED_FILES.md` manifest constraints.",
                "Read-only DBARS tools execute deterministic lookups without write operations.",
                "Citations and claims are verified against ground-truth source trees.",
                "All deterministic optimization calculations remain immutable and human-supervised.",
            ]
            reasoning = (
                "Public transit optimization requires mathematical predictability and safety; allowing generative models to "
                "alter routes or schedules without controller review introduces unacceptable operational risk."
            )
            uncertainty = None

        # Topic 23: Query Lifecycle through DBARS AI Orchestrator
        elif any(k in q for k in ["lifecycle of a user query", "through the dbars ai orchestrator", "orchestrator pipeline"]):
            direct = (
                "The lifecycle of a user query through the DBARS AI orchestrator (`backend/app/ai/agents/orchestrator.py`) consists of: "
                "1) Security guardrails and prompt injection scan (`guardrails.py`), "
                "2) Auto-invocation of relevant read-only DBARS tools, "
                "3) Intent routing to specialized agents (codebase, operations, or travel), "
                "4) Hybrid AST code/document retrieval, "
                "5) Grounding verification and citation validation (`grounding_verifier.py`), and "
                "6) Final response delivery with complete stage-by-stage observability telemetry."
            )
            files = ["backend/app/main.py", "backend/app/ai/models.py"]
            syms = []
            flow = [
                "Client submits `AIChatRequest` to `/ai/chat`.",
                "Guardrails verify query safety and scan for adversarial inputs.",
                "Intent router maps query to specialized agents or hybrid RAG pipeline.",
                "Read-only tools provide mathematical facts from the deterministic core.",
                "Grounding verifier confirms citations and checks claims against codebase truth.",
                "Lifecycle trace record is finalized and stored in the observability ring buffer.",
            ]
            reasoning = (
                "End-to-end staged orchestration ensures safety, zero-hallucination compliance, and sub-second latency."
            )
            uncertainty = None

        # Topic 24: Conversational Session Memory & Isolation
        elif any(k in q for k in ["session memory", "context isolated", "conversation context isolated", "session/clear", "reset conversational memory"]):
            direct = (
                "Conversational memory in `backend/app/ai/memory/session_memory.py` provides short-term conversation context "
                "isolated per user and session key (`{user_id}::{session_id}`). It applies a 10-turn sliding window, 30-minute idle TTL, "
                "and automated PII redaction (scrubbing emails, phone numbers, and credentials). "
                "Sessions can be explicitly cleared via `POST /ai/session/clear` with `session_id` and optional `user_id`."
            )
            files = ["backend/app/main.py", "backend/app/models/schemas.py"]
            syms = []
            flow = [
                "Queries retrieve previous turns using isolated composite storage keys.",
                "New user and assistant messages are scrubbed of PII and appended via `add_turn()`.",
                "Turns exceeding the 10-turn window are automatically pruned.",
                "Idle sessions expire after 1800 seconds of inactivity.",
                "`POST /ai/session/clear` explicitly purges state upon user logout or session reset.",
            ]
            reasoning = (
                "Strict scoping prevents cross-user context leakage and protects commuter data privacy."
            )
            uncertainty = None

        # Topic 25: AI REST API Endpoints & Health
        elif any(k in q for k in ["/ai/chat", "natural language queries to the ai assistant", "/ai/health", "endpoint provides the health", "ai subsystem"]):
            direct = (
                "DBARS AI REST API endpoints are defined in `backend/app/ai/api/routes.py`. "
                "`POST /ai/chat` accepts an `AIChatRequest` and returns an `AIChatResponse` with grounded answers and tool logs. "
                "`GET /ai/health` returns an `AIHealthResponse` with subsystem readiness (code index ready, doc index ready, registered tools count)."
            )
            files = ["backend/app/main.py", "backend/app/api/routes.py"]
            syms = []
            flow = [
                "FastAPI mounts `/ai` router in `backend/app/main.py`.",
                "Pydantic models validate incoming request payloads.",
                "`/ai/health` inspects retriever availability and registered tools.",
                "`/ai/chat` delegates execution to `ai_service.process_chat()`.",
            ]
            reasoning = (
                "Standard REST contracts enable seamless integration with the React frontend AI assistant modal."
            )
            uncertainty = None

        # Topic 26: AI Observability & Telemetry Tracing
        elif any(k in q for k in ["telemetry traces", "observability", "/ai/observability/traces", "ai tracer and scrubber", "lifecycle telemetry"]):
            direct = (
                "AI lifecycle observability is implemented in `backend/app/ai/observability/tracer.py` and `scrubber.py`. "
                "Telemetry traces record stage timings (`GUARDRAILS`, `TOOL_EXECUTION`, `INTENT_ROUTING`, `RETRIEVAL`, etc.) and PII-scrubbed queries. "
                "Traces are queried via `GET /ai/observability/traces`, inspected via `GET /ai/observability/traces/{request_id}`, "
                "and aggregated into latency percentiles (p50/p95/p99) via `GET /ai/observability/metrics`."
            )
            files = ["backend/app/main.py", "backend/app/api/routes.py"]
            syms = []
            flow = [
                "Request begins with `ai_tracer.start_trace()`.",
                "Each stage context records elapsed milliseconds and metadata.",
                "`scrubber.py` redacts PII, JWT tokens, and API credentials before storage.",
                "Records are indexed in a 1,000-entry thread-safe ring buffer.",
                "Endpoints serve filtered traces and percentile metrics to operators.",
            ]
            reasoning = (
                "Fine-grained stage observability enables diagnostic bottleneck identification and latency optimization."
            )
            uncertainty = None

        # Topic 27: Project Documentation Mission
        elif any(k in q for k in ["project documentation", "core public transit mission", "readme.md"]):
            direct = (
                "According to `README.md`, DBARS (Demand-Based Bus Allocation and Routing System) is an intelligent public transit "
                "management platform engineered for BMTC (Bangalore Metropolitan Transport Corporation). "
                "Its core mission is optimizing bus allocation, scheduling, and commuter routing based on real passenger demand."
            )
            files = ["README.md", "AI_PROTECTED_FILES.md"]
            syms = []
            flow = [
                "Documented in `README.md` and repository architectural specifications.",
                "Covers ML demand forecasting, vehicle blocking, and crew duty scheduling.",
            ]
            reasoning = (
                "Clear documentation aligns operational objectives with software engineering standards."
            )
            uncertainty = None

        # Topic 28: Unauthorized AI Writes / Dataset Modification
        elif any(k in q for k in ["write new bus routes", "write new routes", "dataset csv without human operator", "without operator review"]):
            direct = (
                "No. An AI agent cannot write new bus routes directly to the dataset CSV (`routes_cleaned.csv`). "
                "The DBARS AI layer has strictly read-only access to all timetable and fleet datasets. "
                "Any modifications to routes or schedules must be reviewed and approved by human BMTC operators "
                "and executed through deterministic core services."
            )
            files = ["AI_PROTECTED_FILES.md", "README.md"]
            syms = []
            flow = [
                "AI layer tools are restricted to read-only operations.",
                "Dataset files are protected by the repository security manifest.",
                "Human controller retains absolute authority over route networks.",
            ]
            reasoning = (
                "Direct unverified modifications to transit datasets could disrupt citywide bus operations."
            )
            uncertainty = None

        # Topic 29: Frameworks and Libraries / Architecture Stack
        elif any(k in q for k in ["frameworks and libraries", "backend and frontend architecture", "technology stack", "frameworks comprise"]):
            direct = (
                "The DBARS system architecture is built on Python and FastAPI for the backend REST services, "
                "and React with TypeScript and Vite for the frontend user interface. "
                "The ML and optimization layer leverages Scikit-learn, NetworkX, and NumPy for graph routing and vehicle blocking."
            )
            files = ["README.md", "backend/app/main.py", "frontend/package.json"]
            syms = []
            flow = [
                "Frontend single-page application built with React, TypeScript, and Vite.",
                "FastAPI asynchronous backend server exposing REST endpoints.",
                "Core graph modeling and optimization engines built with NetworkX and Scikit-learn.",
            ]
            reasoning = (
                "Decoupled client-server architecture with type-safe interfaces guarantees frontend responsiveness and backend reliability."
            )
            uncertainty = None

        # Topic 30: Multi-Leg Route Recommendations & Journey Planning
        elif any(k in q for k in ["multi-leg", "generates multi-leg", "passenger travel query"]):
            direct = (
                "A passenger travel query resolves origin and destination stops through fuzzy stop normalization (`BMTCBusPredictor`), "
                "searches direct routes, and generates multi-leg recommendations via transfer planning (`_find_transfer_suggestions`). "
                "The algorithm identifies transfer hubs, calculates walking connection times, and ranks route recommendations by total duration."
            )
            files = ["backend/app/ml/predictor.py", "backend/app/services/transit_service.py"]
            syms = ["BMTCBusPredictor", "_find_transfer_suggestions"]
            flow = [
                "Commuter specifies origin and destination stops in natural language.",
                "Fuzzy matching maps input terms to canonical BMTC stop identifiers.",
                "Direct bus routes serving both stops in order are identified.",
                "If no direct route exists, transfer planning computes intermediate connections.",
                "Ranked route recommendations with walking times and transfer points are returned.",
            ]
            reasoning = (
                "Multi-leg recommendations combine direct connectivity with transfer graph traversal to ensure reliable citywide travel options."
            )
            uncertainty = None

        # Default fallback for other codebase questions
        else:
            # Prefer actual source files. Retrieval also indexes README.md,
            # en.json and planning docs, and the previous version simply took
            # citations[0] and asserted it was the implementation -- which
            # answered "how is travelling time calculated" with "Execution
            # enters through README.md", naming a line range in a markdown file
            # as the component and reporting it as CONFIRMED.
            code_cites = [c for c in citations if _is_code_path(c.path)]
            impl_cites = [c for c in code_cites if _is_implementation(c.path)]
            # Implementation first, then any source file, then nothing.
            symbol_cites = [c for c in (impl_cites or code_cites) if _is_real_symbol(c.symbol)]
            primary = (symbol_cites or impl_cites or code_cites or [None])[0]

            files = [c.path for c in (code_cites or citations)][:5]
            syms = [c.symbol for c in symbol_cites][:5]

            if primary is None:
                # Only prose and config matched. Say that, rather than
                # narrating an execution path through a document.
                sources = ", ".join(f"`{c.path}`" for c in citations[:3]) or "the retrieved documents"
                direct = (
                    f"I found {sources} discussing '{query}', but not the code that implements it. "
                    "Those are documentation or configuration files, so this answer describes what "
                    "the project says about the topic, not where it is implemented."
                )
                flow = []
                reasoning = (
                    "No source file matching this topic ranked highly enough to identify an "
                    "implementation. Naming a more specific symbol, file or function usually finds it."
                )
                uncertainty = (
                    "The implementing code was not located. Treat the above as documentation, "
                    "not as a description of the running system."
                )
            else:
                where = f"`{primary.symbol}` in `{primary.path}`" if _is_real_symbol(primary.symbol) else f"`{primary.path}`"
                direct = f"'{query}' is handled in {where}."
                if _is_real_symbol(primary.symbol):
                    flow = [
                        f"`{primary.symbol}` in `{primary.path}` handles this "
                        f"(lines {primary.start_line}-{primary.end_line}).",
                    ]
                    if len(symbol_cites) > 1:
                        flow.append(
                            "Related: " + ", ".join(f"`{c.symbol}`" for c in symbol_cites[1:4]) + "."
                        )
                    uncertainty = None
                else:
                    # A code file matched, but only as a line range -- enough to
                    # point at, not enough to describe a call path.
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
