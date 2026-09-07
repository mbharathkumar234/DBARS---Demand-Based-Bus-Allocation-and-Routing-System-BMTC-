# DBARS — AI Protected Files and Deterministic Core Manifest

This manifest formally designates the protected, read-only boundaries of the existing deterministic DBARS system. No program logic, routing algorithms, prediction models, ranking functions, or deterministic business rules within these files may be altered, replaced, or degraded by the AI Intelligence Layer.


> **Amendment — one authorised exception.** `backend/app/ml/predictor.py` was
> edited once, on explicit instruction from the project owner, to fix a
> user-visible wrong result: "dasarahalli metro station" resolved to
> *Vajarahalli Metro Station*, a different station, with full confidence. The
> fault was in the deterministic engine, so `/predict` and the prediction page
> were wrong too — a fix confined to the AI layer would have left them broken.
> The change is limited to `_resolve_stop_name` and its supporting token
> index; no ranking formula, routing algorithm or data structure was altered,
> and every accuracy metric is unchanged (`best_option_rate` 0.7167,
> `ndcg@5` 0.9810). See `AI_IMPLEMENTATION_FINAL_REPORT.md` §2.1.
>
> This does not relax the policy. The AI layer still may not modify these files.

---

## 1. Protected Deterministic Core Modules

The following core modules are strictly READ-ONLY. The AI layer must NEVER alter their algorithms, constants, ranking formulas, or data structures.

| File Path | Description / Core Role | Protection Policy |
|---|---|---|
| `backend/app/ml/predictor.py` | Core hybrid recommender (`BMTCBusPredictor`), inverted index, ordered stop pairs, ranking, transfer enumeration | STRICTLY READ-ONLY |
| `backend/app/ml/route_geometry.py` | Stop coordinate distance estimation, haversine calculation, road distance caching | STRICTLY READ-ONLY |
| `backend/app/ml/blocking.py` | Depot vehicle blocking algorithm, minimum fleet calculation, deadhead minimization | STRICTLY READ-ONLY |
| `backend/app/ml/crew.py` | Crew duty scheduling, shift generation, crew-to-bus ratio | STRICTLY READ-ONLY |
| `backend/app/ml/data_loader.py` | CSV parsing, stop normalization, alias expansion | STRICTLY READ-ONLY |
| `backend/app/ml/distance.py` | Distance matrix and spatial lookup helpers | STRICTLY READ-ONLY |
| `backend/app/ml/stop_registry.py` | Inverted index and canonical stop resolution | STRICTLY READ-ONLY |
| `backend/app/ml/text.py` | Stop name cleaning, transliteration, phonetic/fuzzy normalization | STRICTLY READ-ONLY |
| `backend/app/ml/tfidf.py` | TF-IDF vectorizer and route similarity matching | STRICTLY READ-ONLY |

---

## 2. Protected GTFS & Tracking Systems

| Directory / File Path | Description / Core Role | Protection Policy |
|---|---|---|
| `backend/app/gtfs/builder.py` | Static GTFS zip builder, timetable interpolation, trip generation | STRICTLY READ-ONLY |
| `backend/app/gtfs/realtime.py` | GTFS-RT protobuf service alerts and vehicle position publisher | STRICTLY READ-ONLY |
| `backend/app/tracking/adapters.py` | AVL feed adapters (`simulated`, `gtfs_rt`, `http_json`, `push`) | STRICTLY READ-ONLY |
| `backend/app/tracking/base.py` | Vehicle position observation types and contracts | STRICTLY READ-ONLY |
| `backend/app/tracking/ingest.py` | Live vehicle ingest scheduler and background poller | STRICTLY READ-ONLY |
| `backend/app/tracking/matcher.py` | Map matching, shape projection, schedule adherence calculation | STRICTLY READ-ONLY |
| `backend/app/tracking/store.py` | In-memory vehicle position ring buffer and spatial indexing | STRICTLY READ-ONLY |

---

## 3. Protected Backend Services & Core Rules

| File Path | Description / Core Role | Protection Policy |
|---|---|---|
| `backend/app/core/fares.py` | Stage-based fare calculation and fare lookup | STRICTLY READ-ONLY |
| `backend/app/core/shakti.py` | Shakti scheme eligibility and reimbursement calculation | STRICTLY READ-ONLY |
| `backend/app/core/rate_limit.py` | Token bucket rate limiting middleware | STRICTLY READ-ONLY |
| `backend/app/services/blocking_service.py` | Blocking plan background computation & cache | STRICTLY READ-ONLY |
| `backend/app/services/crew_service.py` | Crew duty computation service | STRICTLY READ-ONLY |
| `backend/app/services/gtfs_service.py` | GTFS feed cache and build lifecycle service | STRICTLY READ-ONLY |
| `backend/app/services/tracking_service.py` | Live tracking query service | STRICTLY READ-ONLY |
| `backend/app/services/waybill_service.py` | Conductor waybill, offline ticket sync, and cash reconciliation | STRICTLY READ-ONLY |
| `backend/app/services/pass_service.py` | HMAC signed travel pass generation & verification | STRICTLY READ-ONLY |
| `backend/app/services/vote_service.py` | Commuter voting & demand aggregation service | STRICTLY READ-ONLY |
| `backend/app/services/crowding_service.py` | Crowding estimation service | STRICTLY READ-ONLY |
| `backend/app/services/alerts_service.py` | Service alert manager | STRICTLY READ-ONLY |
| `backend/app/services/metro_service.py` | Metro feeder connection & interchange service | STRICTLY READ-ONLY |
| `backend/app/services/safety_service.py` | SOS and shared trip emergency tracking | STRICTLY READ-ONLY |

---

## 4. Protected Existing APIs

The semantics, response schemas, and logic of existing endpoints must NOT be modified:

| Router File | Endpoints / Scope | Protection Policy |
|---|---|---|
| `backend/app/api/routes.py` | `POST /predict`, `GET /health`, `GET /routes`, `GET /metrics`, `GET /autocomplete` | STRICTLY READ-ONLY |
| `backend/app/api/tracking.py` | `GET /tracking/buses`, `GET /tracking/bus/{number}`, `GET /tracking/eta`, `POST /avl/ingest` | STRICTLY READ-ONLY |
| `backend/app/api/gtfs.py` | `GET /gtfs/static.zip`, `GET /gtfs/feed-info`, `GET /gtfs-rt/service-alerts.pb` | STRICTLY READ-ONLY |
| `backend/app/api/admin.py` | `GET /admin/blocking-plan`, `GET /admin/crew-plan`, `GET /admin/shakti/claim` | STRICTLY READ-ONLY |
| `backend/app/api/conductor.py`| Conductor sign-on, ticket issue, offline sync, pass verification | STRICTLY READ-ONLY |
| `backend/app/api/tickets.py` | Commuter ticket purchase and verification | STRICTLY READ-ONLY |
| `backend/app/api/metro.py` | Metro network queries and feeder routes | STRICTLY READ-ONLY |
| `backend/app/api/crowding.py` | Bus crowding queries and reports | STRICTLY READ-ONLY |
| `backend/app/api/alerts.py` | Active disruptions and service notifications | STRICTLY READ-ONLY |
| `backend/app/api/votes.py` | Demand voting and route support counters | STRICTLY READ-ONLY |
| `backend/app/auth/routes.py` | User authentication, token issuance, role assignment | STRICTLY READ-ONLY |

---

## 5. Protected Datasets & Benchmarks

| File / Folder Path | Description | Protection Policy |
|---|---|---|
| `dataset/routes_cleaned.csv` | 6,737 BMTC routes, stop sequences, and timetables | STRICTLY READ-ONLY |
| `dataset/stops_cleaned.csv` | BMTC stop coordinates and canonical names | STRICTLY READ-ONLY |
| `dataset/bengaluru_metro_network.csv` | Namma Metro stations, lines, and interchanges | STRICTLY READ-ONLY |
| `dataset/fares.json` & `dataset/fares.csv`| Stage fare tables | STRICTLY READ-ONLY |
| `dataset/BMTC_depot_place_zone.xlsx` | BMTC depot locations and zone mappings | STRICTLY READ-ONLY |
| `backend/artifacts/metrics.json` | Benchmark metrics generated from deterministic baseline | STRICTLY READ-ONLY |

---

## 6. Protected Automated Tests

All existing 167 automated tests in `backend/tests/` are immutable baseline regression tests:

```text
backend/tests/test_accuracy_metrics.py
backend/tests/test_avl.py
backend/tests/test_blocking.py
backend/tests/test_blocking_api.py
backend/tests/test_crew.py
backend/tests/test_gtfs_builder.py
backend/tests/test_gtfs_realtime.py
backend/tests/test_predictor.py
backend/tests/test_route_geometry.py
backend/tests/test_scenario.py
backend/tests/test_shakti.py
backend/tests/test_sms_webhook_signature.py
backend/tests/test_text.py
backend/tests/test_token_types.py
backend/tests/test_votes.py
backend/tests/test_waybill.py
```

---

## 7. AI Layer Connection Contract

1. **Isolation**: All AI Intelligence Layer components reside exclusively in `backend/app/ai/`.
2. **Access Method**: The AI layer accesses DBARS ONLY through read-only tools and public service wrappers.
3. **Additive Endpoints**: New AI endpoints are namespaced strictly under `/ai/*` (e.g. `POST /ai/chat`, `GET /ai/health`, `POST /ai/evaluate`).
4. **Non-Invasive Integration**: `backend/app/main.py` only imports the isolated `ai_router` and attaches it via `app.include_router(ai_router)`.
5. **Zero Side-Effects**: If the AI layer is unconfigured, disabled, or throws an unhandled exception, existing DBARS endpoints (especially `/predict`) function without interruption or latency degradation.
