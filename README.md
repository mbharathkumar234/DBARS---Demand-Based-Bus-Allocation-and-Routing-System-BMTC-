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

## Quick Start: Interview Demo Routine (3-Minute Setup)

Follow this exact sequence before starting your demo to ensure all services and database connections are ready:

### 1. Start MongoDB (via Docker Desktop)
> **Prerequisite:** Open **Docker Desktop** from your Windows Start Menu and ensure the engine status is green.

From the project root (`dbars/`):
```powershell
docker compose up -d mongo
```
*(Verify it prints `Container dbars-mongo-1 Started`)*

### 2. Seed Database & Accounts (Run once or after resetting Mongo)
```powershell
cd backend
.venv\Scripts\activate
python -m app.db.seed
```
*Creates the admin/depot demo users and indexes. Runs silently with code 0 on success.*

### 3. Start Backend & Frontend

You can start both simultaneously using the root helper script:
```powershell
.\start_all.ps1
```

Or run them in two separate PowerShell terminals:

- **Terminal 1 (Backend API):**
  ```powershell
  cd backend
  .venv\Scripts\activate
  python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
  *Live at: http://localhost:8000 (Swagger docs: http://localhost:8000/docs)*

- **Terminal 2 (Frontend UI):**
  ```powershell
  cd frontend
  npm run dev
  ```
  *Live at: http://localhost:5173*

---

### Demo Accounts for Presentation

| Role | Email | Password | Permissions & Features |
| :--- | :--- | :--- | :--- |
| **System Admin** | `admin@bmtc.ai` | `admin123` | Full dashboard, fleet analytics, Shakti scheme claims, audit logs, AI observability |
| **Depot Manager** | `depot@bmtc.ai` | `depot123` | Blocking scenarios, crew duty planning, waybills & depot rosters |
| **Commuter / Public** | Any new signup | *(User chosen)* | Route prediction, real-time tracking, voting, e-ticket booking, digital pass QR |

---

## Detailed Local Setup

### 1. Backend Setup

- **Python Version:** Python 3.11 or 3.12 is recommended (Python 3.14 lacks prebuilt wheels for FAISS and C-extensions).
- Run commands from `backend/`:

```powershell
cd backend

# Create virtual environment
py -3.11 -m venv .venv

# Activate environment on Windows
.venv\Scripts\activate

# Upgrade pip & install backend dependencies
# Note: Always use 'python -m pip' on Windows to avoid application execution alias blocks
python -m pip install -r requirements.txt
```

### 2. Database (MongoDB) Details

- **Standalone vs Database-backed features:**
  - **Core Bus Route Prediction (`BMTCBusPredictor`):** Works 100% standalone and in-memory from `dataset/routes_cleaned.csv`. It requires no database at all.
  - **Accounts, Login, Voting, E-Ticketing, and Depot/Admin:** Require MongoDB running on `mongodb://localhost:27017`.
- **Important Startup Order:** Always start MongoDB **before** launching `uvicorn`. If the backend starts while MongoDB is offline, it activates circuit-breaker fallback mode (503 for auth). If this happens, start MongoDB and restart `uvicorn`.

To start MongoDB with Docker:
```powershell
# In project root:
docker compose up -d mongo
```

To seed the initial database (admin/depot accounts, collections, and indexes):
```powershell
cd backend
.venv\Scripts\activate
python -m app.db.seed
```

### 3. Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```
Open **http://localhost:5173** in your browser.

---

## Model Training & Index Pre-building

### Route Prediction ML Training
The backend automatically initializes and trains the hybrid ranker model in memory upon startup. If you want to run the standalone benchmark training script to regenerate `backend/artifacts/metrics.json`:

```powershell
cd backend
.venv\Scripts\activate
python train.py
```

### AI Intelligence RAG Indices (Optional)
Build the local vector search indices for the AI Codebase and Operations assistants:

```powershell
cd backend
.venv\Scripts\activate
python -m app.ai.ingestion.pipeline        # Codebase index
python -m app.ai.ingestion.doc_pipeline    # Documentation index
```
*(Without these indices, the AI assistant still functions using deterministic transit tools; with them, it cites exact codebase files and documentation).*

---

## Testing & Code Quality

### Running the Full Test Suite
The project includes 757 unit and integration tests covering the ML models, scheduling algorithms, GTFS feed generator, and AI components:

```powershell
cd backend
.venv\Scripts\activate

# Use 'python -m pytest' to ensure the virtual environment's pytest is used
python -m pytest tests
```
> **Note:** The full test suite takes approximately **5 to 8 minutes** to run completely because it tests local vector embeddings, ML rankers, and scenario models.

### Fast Syntax & Compilation Check
To quickly verify all backend Python files are valid without waiting for tests:
```powershell
cd backend
.venv\Scripts\activate
python -m compileall app
```

### Frontend Build Test
To verify TypeScript types and production frontend bundling:
```powershell
cd frontend
npm run build
```

---

## Common Troubleshooting & FAQ (Interview Prep)

#### 1. "Failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine"
- **Cause:** Docker Desktop is closed.
- **Fix:** Launch **Docker Desktop** from the Windows Start menu, wait until its engine finishes starting (icon turns steady green in the system tray), then re-run `docker compose up -d mongo`.

#### 2. Red toast: "This feature requires a database connection, which is currently unavailable..."
- **Cause:** You tried to login, register, or access tickets while MongoDB was not running, or `uvicorn` was started before MongoDB was ready.
- **Fix:**
  1. Verify MongoDB is running: `docker compose up -d mongo`
  2. Seed data if not already done: `python -m app.db.seed` (from `backend/` with `.venv` active)
  3. Restart the `uvicorn` backend terminal so it establishes a fresh database connection.

#### 3. `ModuleNotFoundError: No module named 'app'` when seeding
- **Cause:** The command was executed from the root directory `dbars` instead of the `backend/` folder.
- **Fix:**
  ```powershell
  cd backend
  .venv\Scripts\activate
  python -m app.db.seed
  ```

#### 4. `ModuleNotFoundError: No module named 'langchain_core'` during pytest
- **Cause:** Running plain `pytest` used a global Python interpreter outside the virtual environment.
- **Fix:** Always invoke pytest through the virtual environment's python:
  ```powershell
  cd backend
  .venv\Scripts\activate
  python -m pytest tests
  ```

#### 5. Backend port 8000 already in use / zombie python processes
- If you restarted uvicorn and get `[WinError 10048] address already in use`, close existing python workers in PowerShell:
  ```powershell
  Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
  ```
  Then restart `uvicorn`.

---

## Docker Full-Stack Deployment

To run the entire system (Frontend, Backend, and MongoDB) inside Docker containers:

```bash
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend: http://localhost:8000
- MongoDB: localhost:27017

---

## Deployment & Environment Variables

The project is structured to deploy on platforms like Render, Railway, AWS, or GCP:
- Frontend on Vercel: set `VITE_API_URL` to your backend domain.
- Backend on Render: see `deployment/render.yaml`.

Key environment configuration:
```
DATASET_PATH=/app/dataset/routes_cleaned.csv
STOP_COORDINATES_PATH=/app/dataset/stops_cleaned.csv
METRO_DATASET_PATH=/app/dataset/bengaluru_metro_network.csv
FARES_DATASET_PATH=/app/dataset/fares.json
ARTIFACT_DIR=/app/artifacts
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://localhost
RATE_LIMIT_PER_MINUTE=120
MONGO_URI=mongodb://mongo:27017
JWT_SECRET_KEY=your-secure-jwt-secret
PASS_VERIFICATION_SECRET=your-pass-secret
```