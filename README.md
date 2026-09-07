# DBARS

**Demand Based Bus Allocation & Routing System**

A production-style full-stack web app that predicts the best BMTC bus number from a commuter's current stop and destination bus stop, and turns commuter votes into demand-driven bus allocation for depot managers. The project trains from `dataset/routes_cleaned.csv`, exposes FastAPI prediction endpoints, and ships a polished React + TypeScript dashboard.

## Architecture

```
frontend/              React, TypeScript, Tailwind, Framer Motion UI
backend/               FastAPI app, validation, rate limiting, ML services
backend/app/ml/        CSV preprocessing, TF-IDF index, hybrid route ranker
dataset/routes_cleaned.csv     BMTC route-direction training catalogue
deployment/            Render config, Nginx config
docker-compose.yml     Backend, frontend, and MongoDB (for account/voting/ticketing/admin features)
```

The backend trains on startup and stores model metrics in `backend/artifacts/metrics.json`. The frontend calls the REST API for autocomplete, prediction, metrics, e-ticketing, and live tracking.

## ML Strategy

The dataset is an ordered route catalogue, not a user-query label table. A pure classifier would learn route IDs from synthetic text but would not reliably answer whether a bus moves from stop A toward stop B. The selected model is therefore a hybrid recommender:

1. Clean and normalize bus stop names, route names, mojibake arrows, aliases such as `Majestic -> Kempegowda Bus Station`, and duplicate route rows.
2. Build an inverted stop index for fast candidate retrieval.
3. Train an ordered stop-pair index for every reachable stop-to-stop pair on every BMTC route.
4. Rank candidate buses using ordered stop-path matching, destination similarity, TF-IDF route text similarity, fuzzy matching, trip frequency, and distance efficiency.
5. Estimate route distance from `dataset/stops_cleaned.csv` coordinates for a free default distance signal.
6. Optionally enrich top predictions with Google Maps road distance and duration, cached locally to control API usage.
7. Benchmark `TFIDFCosine`, `OrderedStopFuzzy`, `DistanceAwareRouteRanker`, and `LiveTransferSearch` on identical sample sets using **relevance-set scoring**: a prediction is correct if the returned bus genuinely serves the queried stop pair in order, not only if it matches the exact route the sample was drawn from. The old single-label metric is retained as `exact_route_match` for comparison.
8. Report **lenient top-1/top-3/top-5 accuracy** (relevance-set), honest precision@k (`|returned ∩ valid| / min(k, |valid|)`), rank-quality metrics (`best_option_rate`, `mean_percentile_rank`, `within_2_stops_rate`, `ndcg@5`), and cross-validation metrics. The headline metric is **`rank_quality`** (`best_option_rate` 0.72), because it is the only metric here the system can actually fail. The relevance-set score is reported as **coverage, not accuracy**: it asks whether the search returned a route serving the pair, but the relevance set is derived from `stop_pair_to_segments` — the same index the search uses to generate candidates — so a score near 1.0 is close to tautological. It confirms the search never fails to find a valid route; it does not show the route is good.

## API Endpoints

```
GET  /health
POST /predict
POST /train
GET  /routes
GET  /metrics
GET  /autocomplete
GET  /tracking/buses
POST /api/tickets/purchase
POST /api/tickets/verify
```

### Open data (GTFS)

```
GET  /gtfs/static.zip                 full GTFS feed, built from the dataset
GET  /gtfs/feed-info                  what it contains, assumed, and excluded
POST /gtfs/rebuild                    admin
GET  /gtfs-rt/service-alerts.pb       GTFS-realtime alerts (real data)
GET  /gtfs-rt/vehicle-positions.pb    503 unless a live vehicle feed is active
```

The static feed is ~1.46M `stop_times` rows over 47k trips, built in ~11s. Trip
departure times are BMTC's published timetable; every later stop time is
interpolated and flagged `timepoint=0`. Depot pull-out schedules and outstation
coach services are excluded — see the README inside the zip.

### Vehicle location (AVL)

```
GET  /tracking/source                 which feed is running, and whether it is live
GET  /tracking/buses                  positions, with is_live on every payload
GET  /tracking/bus/{number}           positions + schedule adherence
GET  /tracking/eta                    along-route ETA with a confidence band
POST /avl/ingest                      pushed positions (X-AVL-Key)
```

`TRACKING_FEED` selects the adapter: `simulated` (default), `gtfs_rt`,
`http_json`, or `push`. Only a live adapter unlocks the GTFS-realtime vehicle
feed.

### Depot operations

```
GET  /depot/blocking-plan             minimum fleet and dead kilometres
POST /depot/blocking-scenario         what a timetable change costs in buses
GET  /depot/crew-plan                 daily duties needed to staff those blocks
POST /depot/crew-scenario             what a crew-agreement change costs in duties
GET  /depot/waybills                  conductor waybills, open and closed, variances
```

### Conductor, passes and revenue

```
POST /conductor/sign-on               open a waybill
POST /conductor/tickets/issue         one onboard sale
POST /conductor/tickets/sync          drain the device's offline queue (idempotent)
POST /conductor/sign-off              close the waybill, reconcile cash
POST /conductor/verify-pass           signed-token verification, offline-capable
GET  /conductor/pass-revocations      the list a scanner caches
POST /depot/passes                    issue a signed travel pass
GET  /admin/shakti/claim              Shakti boardings and reimbursement value
GET  /admin/revenue/reconciliation    cash vs digital vs pass vs scheme
GET  /admin/audit                     who did what, when
```

Example:

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d "{\"current_stop\":\"Silk Board\",\"destination\":\"Marathahalli\",\"limit\":5}"
```

## Android APK Build

The project is configured with Capacitor for Android.

1. Build the frontend:
   ```bash
   cd frontend
   npm install
   npm run build
   ```
2. Sync with Android:
   ```bash
   npx cap sync
   ```
3. Open in Android Studio or build via CLI:
   ```bash
   npx cap open android
   # OR
   cd android
   ./gradlew assembleDebug
   ```

The generated APK will be in `frontend/android/app/build/outputs/apk/debug/app-debug.apk`.

## Local Setup

### Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Database Seeding (Optional):
```bash
cd backend
python -m app.db.seed
```

### Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Training
```bash
cd backend
python train.py
```

The training job reads `dataset/routes_cleaned.csv`, evaluates candidate models, selects the transfer search ranker, and writes metrics to `backend/artifacts/metrics.json`.

## AI Intelligence Layer

An additive assistant over the deterministic engine: codebase and documentation
RAG, read-only DBARS tools, grounding checks, and role-based access. It cannot
modify anything, and `app/main.py` imports it defensively so a failure there
can never stop route prediction from starting.

```
GET  /ai/health                    public readiness
POST /ai/chat                      authenticated; role checks match the REST API
GET  /ai/session/{id}/history      own sessions only
GET  /ai/observability/*           admin
POST /ai/evaluation/run            admin
```

The search indices are build artifacts and are not committed. Build them once:

```bash
cd backend
python -m app.ai.ingestion.pipeline        # code index
python -m app.ai.ingestion.doc_pipeline    # documentation index
```

Without them the assistant still answers from the deterministic tools; it just
cannot cite source files. Optional `GEMINI_API_KEY` enables a hosted LLM —
without it the layer uses a grounded deterministic model that assembles answers
from retrieved evidence. Sections 40-42 of `docs/DBARS_Project_Defense_and_Codebase_Mastery.docx`
cover the architecture, the security model, the defects it exposed in the
routing engine, and -- in section 42 -- what was measured versus what was only
claimed.

## Testing
```bash
cd backend
pytest tests
python -m compileall app

cd ../frontend
npm run build
```

## Docker
```bash
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend: http://localhost:8000

## Deployment

Vercel can host the frontend with `vercel.json`; set `VITE_API_URL` to the deployed backend URL. Render can deploy both services with `deployment/render.yaml`. Railway, AWS, GCP, or Azure can use the Dockerfiles directly.

Recommended environment variables:

```
DATASET_PATH=/app/dataset/routes_cleaned.csv
STOP_COORDINATES_PATH=/app/dataset/stops_cleaned.csv
METRO_DATASET_PATH=/app/dataset/bengaluru_metro_network.csv
FARES_DATASET_PATH=/app/dataset/fares.json
ARTIFACT_DIR=/app/artifacts
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://localhost
RATE_LIMIT_PER_MINUTE=120
VITE_API_URL=https://your-backend-domain.com
JWT_SECRET_KEY=your-secure-jwt-secret
PASS_VERIFICATION_SECRET=your-pass-secret
```

`GOOGLE_MAPS_API_KEY` is optional. Without it, the app still trains the full stop-pair model and uses `dataset/stops_cleaned.csv` coordinates for free route-distance estimates.

Optional, for the operations features:

```
GTFS_BUILD_ON_STARTUP=true      set false on small dev machines
GTFS_RT_ALLOW_SIMULATED=false   local development only; never in a deployment
TRACKING_FEED=simulated         simulated | gtfs_rt | http_json | push
TRACKING_FEED_URL=              upstream feed, for gtfs_rt / http_json
TRACKING_FEED_FIELD_MAP=        JSON field map, for http_json
AVL_STALE_SECONDS=120           older positions are withheld, not shown
AVL_INGEST_KEY=                 required for POST /avl/ingest; unset refuses all
PASS_SIGNING_KEY=               signs travel passes; own domain, own key
DEMO_PASS_MODE=false            accept unsigned pass ids for a demonstration
```

## Database

Bus route prediction (`BMTCBusPredictor`) needs no database at all: the CSV is the training source and the trained model lives in memory. Account, voting, ticketing, and admin/depot features use MongoDB (`backend/app/db/database.py`), configured via the `MONGO_URI` environment variable (defaults to `mongodb://localhost:27017`; `docker-compose.yml` runs a local mongo service for this). If MongoDB isn't reachable, those features degrade gracefully and route prediction is unaffected.