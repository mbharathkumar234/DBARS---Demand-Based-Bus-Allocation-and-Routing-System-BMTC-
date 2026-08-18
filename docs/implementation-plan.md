# DBARS — Implementation Plan for Four High-Leverage Additions

> **Status: all four implemented.** 130 backend tests pass; the frontend builds.
> Where the build differed from this plan, the plan has been annotated inline —
> search for **BUILT:**. The three biggest divergences were:
>
> 1. The GTFS build takes **~11s, not minutes** (stop resolution is an exact
>    name match, not fuzzy), and the stop-name join resolved **100%** of stops.
> 2. Two exclusions the plan did not anticipate turned out to be mandatory:
>    depot pull-out schedules (325 route-directions a rider must never be routed
>    onto) and outstation coaches (timed at city speed they produced 30–40 hour
>    trips).
> 3. Crew pairing was quadratic and took 36s; bounding the candidate search
>    brought it to 1.6s **and** produced slightly fewer duties.

Scope: four features chosen because each one converts existing DBARS work into
something a transit operator can actually adopt, and none of the three
incumbents (Namma BMTC app, Google Maps, DBARS today) has it.

| # | Feature | Unblocks | Effort |
|---|---------|----------|--------|
| 1 | GTFS static + GTFS-RT export | Google Maps quality; BMTC office deliverable | ~5 days |
| 2 | Real AVL adapter | Honest live tracking, real ETAs, RT feeds | ~7 days |
| 3 | Crew duty scheduling | Depot's biggest daily pain; sequel to `blocking.py` | ~6 days |
| 4 | Conductor waybill + Shakti counting | Revenue/reimbursement — the adoption lever | ~8 days |

Estimates assume one developer familiar with this codebase.

Design principles carried over from the existing code, and applied throughout:

- **Assumptions are surfaced, never buried.** `BlockingParameters` sets the
  standard — every modelled value is configurable and echoed in the output.
- **Degrade honestly.** Features requiring MongoDB report themselves
  unavailable rather than returning zeros (see `database.py`, `votes.py`).
- **Never present simulated data as real.** `GET /tracking/source` exists
  precisely for this; Feature 2 makes it tell the truth by construction.

---

## Feature 1 — GTFS static + GTFS-RT export

### Why this first

It is the fastest path to visible external value: publishing a correct GTFS
feed improves BMTC data inside Google Maps without Google changing anything.
It is also the only deliverable here that the BMTC office can hand to a third
party, which makes it the easiest thing to get a meeting about.

### What the dataset already supports

Measured from `dataset/`:

```
route-direction rows      6,739
unique route numbers      3,940      -> routes.txt
distinct stop names       4,883      -> matches stops_cleaned.csv exactly
stop rows (platforms)     9,507      -> stops.txt
total trips               54,492     -> trips.txt
total stop_times rows     1,479,725  -> stop_times.txt (~90MB raw, ~10MB zipped)
```

The critical join is solved already: route `stop_list` names match
`stops_cleaned.csv` `stop_name` exactly (4,883 = 4,883). The only ambiguity is
which of the ~2 directional platforms a route uses, and
`GoogleMapsDistanceService._pick_candidate(candidates, near)` in
`backend/app/ml/distance.py` already picks the right one using the anchored
walk along the route. It just discards the `stop_id` and returns coordinates.

### Step 1.1 — Expose stop identity from the resolver

`backend/app/ml/distance.py`

Add alongside `resolve_coordinate` (do not change its signature — the predictor
and blocking engine both call it on hot paths):

```python
def resolve_stop_record(
    self, stop: str, *, near: tuple[float, float] | None = None
) -> StopRecord | None:
    """Same resolution as resolve_coordinate, but returns the chosen row's
    identity (stop_id, zone_id, name, point) rather than only its point.
    GTFS export needs the stop_id; nothing else does, which is why this is
    additive rather than a change to the existing hot-path method."""
```

Refactor `stop_coordinates` values to hold `StopRecord` (a slots dataclass:
`stop_id`, `stop_name`, `zone_id`, `lat`, `lon`) and have
`resolve_coordinate` return `record.point`. One internal change, two callers
unaffected.

### Step 1.2 — Static feed builder

New: `backend/app/gtfs/builder.py`

```python
@dataclass(frozen=True)
class GtfsParameters:
    agency_name: str = "Bangalore Metropolitan Transport Corporation"
    agency_timezone: str = "Asia/Kolkata"
    feed_prefix: str = "dbars"          # every id namespaced, so this feed can
                                        # never be mistaken for an official one
    service_id: str = "DAILY"
    average_speed_kmph: float = 16.0    # mirrors BlockingParameters
    dwell_minutes_per_stop: float = 0.3
    circuity_factor: float = 1.2
    include_shapes: bool = True
```

Files produced:

| File | Source | Notes |
|---|---|---|
| `agency.txt` | constants | one row |
| `stops.txt` | `stops_cleaned.csv` | 9,507 rows, `location_type=0` |
| `routes.txt` | grouped by `route_number` | `route_type=3`, `route_long_name` from `full_name` |
| `trips.txt` | one per `(route, direction, departure)` | `trip_id = "{prefix}:{route}:{dir}:{HHMM}"` |
| `stop_times.txt` | modelled timings | see below |
| `calendar.txt` | single `DAILY` service | **assumption — see caveat** |
| `shapes.txt` | `BlockingEngine.route_polyline` | optional, `include_shapes` |
| `feed_info.txt` | build metadata | carries the provenance statement |

`stop_times.txt` timing model — reuse, do not reinvent:
`BlockingEngine.route_length_km(route)` and `running_time_minutes(route, length)`
already produce the per-route running time from stop geometry, speed, and dwell.
Distribute that across stops proportionally to cumulative inter-stop distance,
adding `dwell_minutes_per_stop` at each intermediate stop. Set
`timepoint=0` on every stop_time — GTFS's own way of saying "interpolated, not
observed". This is the honest encoding and validators respect it.

Memory: 1.48M rows must be **streamed** straight into the zip
(`zipfile.ZipFile.open(..., 'w')` + `csv.writer` over a `TextIOWrapper`), never
accumulated in a list. Build to a temp file in `settings.artifact_dir`, then
atomically rename.

### Step 1.3 — Provenance (non-negotiable)

Publishing a feed whose times were modelled, without saying so, is worse than
publishing nothing. Three places carry the statement:

1. `feed_info.txt` → `feed_publisher_name = "DBARS (unofficial, derived)"`,
   `feed_version` = build timestamp + dataset hash.
2. Every id namespaced with `feed_prefix`, so a DBARS `route_id` can never
   collide with or impersonate an official BMTC id.
3. A `README.txt` inside the zip listing the four modelled quantities
   (running speed, dwell, circuity, daily service calendar) and stating that
   departure times come from BMTC's published `trip_list` and are exact, while
   intermediate stop times are interpolated.

**Calendar caveat:** the dataset has no day-of-week information. Emitting
`DAILY` (all seven days) is an assumption and will overstate Sunday service.
Flag it prominently; this is the single most likely correction BMTC would
supply, and the builder should accept a per-route calendar file the moment
they do.

### Step 1.4 — API surface

New: `backend/app/api/gtfs.py`, registered in `main.py`.

```
GET  /gtfs/static.zip          public; served from artifact cache; ETag + Last-Modified
GET  /gtfs/feed-info           JSON: build time, row counts, assumptions, dataset hash
POST /gtfs/rebuild             admin only; rebuilds in a thread, returns build id
```

Cache the built zip in `settings.artifact_dir/gtfs/`. Build takes minutes at
1.48M rows — never build inside a request. Warm it in `lifespan` the same
fire-and-forget way `_warm_blocking_plan` is warmed in `main.py:54`, held on
`app.state` to avoid the weak-reference GC problem the existing comment calls out.

### Step 1.5 — Realtime feeds

Add `gtfs-realtime-bindings` to `requirements.txt`.
New: `backend/app/gtfs/realtime.py`.

```
GET /gtfs-rt/service-alerts.pb      SHIP NOW  — real data today
GET /gtfs-rt/vehicle-positions.pb   BLOCKED   — needs Feature 2
GET /gtfs-rt/trip-updates.pb        BLOCKED   — needs Feature 2 + trip matching
```

**Service alerts can ship immediately.** The `service_alerts` collection
(`api/alerts.py`, `services/alerts_service.py`) holds genuine depot-published
disruptions with affected routes and stops — map straight onto GTFS-RT `Alert`
with `informed_entity` from `affected_routes` / `affected_stops`. No simulation
involved, no Feature 2 dependency.

**Vehicle positions must not be served from the simulator.** GTFS-RT has no
field for "this data is fabricated", and a consumer that ingests it cannot tell.
Gate it hard:

```python
if not active_feed.is_live and not settings.gtfs_rt_allow_simulated:
    raise HTTPException(503, detail=(
        "Vehicle positions are currently produced by a simulation, not a "
        "BMTC vehicle feed, and are therefore not published as GTFS-RT. "
        "See GET /tracking/source."
    ))
```

`GTFS_RT_ALLOW_SIMULATED=true` exists only for local development and demos, and
when set, the feed is served at `/gtfs-rt/vehicle-positions.sim.pb` — a
different path, so no consumer can be configured against it by accident.

### Step 1.6 — Tests

`backend/tests/test_gtfs_builder.py`

- every `trips.txt` row has ≥2 `stop_times` rows
- `stop_times` times are strictly non-decreasing within a trip
- every `stop_id` referenced exists in `stops.txt`; every `route_id` in `routes.txt`
- ids are all `feed_prefix`-namespaced
- builder streams: peak RSS on a full build stays under a set ceiling
- alerts feed: a fixture alert round-trips through protobuf with correct
  `informed_entity`

Optionally run MobilityData's `gtfs-validator` (Java) in CI against the built
zip and assert zero ERROR-severity notices; document WARNINGs that are expected
consequences of interpolated timings.

---

## Feature 2 — Real AVL adapter

### Goal

Make vehicle position data arrive from a real feed, with the existing simulator
demoted to one implementation behind an interface. Everything operational you
have built currently rests on `BusSimulator`; this is what makes it real.

### Step 2.1 — Define the interface

New package: `backend/app/tracking/`

```python
# base.py
@dataclass(slots=True)
class VehicleObservation:
    vehicle_id: str
    route_number: str | None
    direction_id: int | None
    lat: float
    lon: float
    bearing: float | None
    speed_kmph: float | None
    recorded_at: datetime          # from the source, NOT time of receipt
    occupancy_pct: float | None = None
    trip_id: str | None = None
    source: str = ""

class VehicleFeed(Protocol):
    name: str
    is_live: bool                  # False for anything synthetic
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def poll(self) -> list[VehicleObservation]: ...
```

`recorded_at` from the source rather than receipt time is what makes staleness
detection possible, and staleness is the difference between a trustworthy map
and a lying one.

### Step 2.2 — Adapters

| Adapter | File | Notes |
|---|---|---|
| `SimulatedFeed` | `adapters/simulated.py` | wraps existing `BusSimulator`, `is_live=False` |
| `GtfsRealtimeFeed` | `adapters/gtfs_rt.py` | polls an upstream RT URL — the standard shape most agencies expose |
| `HttpJsonFeed` | `adapters/http_json.py` | bespoke ITS/VTU JSON with a declarative field map in env/JSON, so a new operator API needs config not code |
| `PushIngestFeed` | `adapters/push.py` | backs `POST /avl/ingest` for feeds that push to you |

Selected by `TRACKING_FEED=simulated|gtfs_rt|http_json|push` in `core/config.py`.
Default stays `simulated` so nothing breaks.

`POST /avl/ingest` authenticates with a shared secret in an `X-AVL-Key` header
compared with `hmac.compare_digest`, and is exempted from `RateLimitMiddleware`
(a real fleet pushes hard). Same endpoint later serves a driver phone-as-GPS app.

### Step 2.3 — State store and staleness

`backend/app/tracking/store.py` — in-memory dict keyed by `vehicle_id`, plus
optional write-through to a MongoDB **time-series** collection
`vehicle_observations` (`timeField=recorded_at`, `metaField=vehicle_id`) with a
TTL of 30 days.

The history is not incidental — it is what lets you compute *observed* segment
speeds by time-of-day, which is (a) far better ETAs and (b) the empirical
replacement for `BlockingParameters.average_speed_kmph`, closing the loop on the
biggest assumption in `blocking.py`.

Staleness rule: an observation older than `AVL_STALE_SECONDS` (default 120) is
dropped from `get_all_buses()` entirely. Never render a last-known position as
current — that is the failure mode riders punish hardest.

### Step 2.4 — Trip matching

`backend/app/tracking/matcher.py`

Match each observation to a scheduled `Trip` from `BlockingEngine.all_trips()`:
candidates are trips of the same route/direction whose `[depart_minute,
arrive_minute]` window brackets `recorded_at` within a tolerance; score by
distance from the vehicle to the expected position along the route polyline;
keep the best, with hysteresis so a vehicle does not flap between trips.

This one component unlocks:
- **schedule adherence** — observed vs `Trip.depart_minute` → early/late minutes
- **missed trip detection** — a scheduled trip no vehicle ever matched
- **GTFS-RT `TripUpdate`** — needs the `trip_id` this produces
- **bunching detection** — two matched vehicles too close on one route

### Step 2.5 — Real ETAs

Replace the straight-line estimate in `services/tracking_service.py`
(`estimate_eta_minutes`, currently haversine × 1.4 ÷ current speed):

1. Project the vehicle onto `BlockingEngine.route_polyline(route)` — nearest
   point on the nearest segment.
2. Sum remaining segment distances to the target stop along the polyline.
3. Divide segment-by-segment by a blended speed: observed segment speed for
   this time band (from the time-series history) where available, falling back
   to the vehicle's recent speed, falling back to `average_speed_kmph`.
4. Add `dwell_minutes_per_stop` per intervening stop.
5. Return a **range with a confidence label**, derived from which fallback
   level was used — `high` (observed history), `medium` (vehicle speed only),
   `low` (parameter default). `GET /tracking/eta` returns the label.

A confidence-labelled range beats a false-precision single number, and it is
also honest about a real limitation rather than hiding it.

### Step 2.6 — `/tracking/source` becomes true by construction

The endpoint already exists and already reports honestly. Rewire it to report
`active_feed.name`, `active_feed.is_live`, last successful poll time, observation
count, and stale count — derived from the adapter rather than a constant. It
stops being a disclaimer and becomes a health check.

### Step 2.7 — Tests

`backend/tests/test_avl.py`

- replay a recorded fixture feed through `GtfsRealtimeFeed`, assert observations parse
- staleness: an observation with an old `recorded_at` is excluded
- projection: a vehicle placed at a known point on a known polyline yields the
  expected remaining distance
- matcher: a vehicle mid-route matches the correct scheduled trip; an
  off-schedule vehicle matches nothing rather than the nearest wrong trip
- the RT gate: with `SimulatedFeed` active, `/gtfs-rt/vehicle-positions.pb`
  returns 503

---

## Feature 3 — Crew duty scheduling

### Why it belongs here

`ml/blocking.py` already computes vehicle blocks and, at line 787,
`blocks_exceeding_duty()` — which explicitly names the gap:

> "A block is a vehicle's day; a duty is a person's. A re-block that saves buses
> by stretching each one across fourteen hours has not saved anything."

That counter is the placeholder this feature replaces. Crew is also the depot's
harder daily problem: buses do not call in sick.

### Step 3.1 — Parameters, in the established style

New: `backend/app/ml/crew.py`

```python
@dataclass(frozen=True)
class CrewParameters:
    """BMTC's real crew agreement is not in any published dataset. Every value
    here is therefore an assumption, surfaced in the output the same way
    BlockingParameters are, and replaceable with the agreement's real figures."""

    sign_on_minutes: int = 15            # pre-trip checks, waybill issue
    sign_off_minutes: int = 15           # cash remittance, waybill close
    max_continuous_driving_minutes: int = 240
    min_break_minutes: int = 30
    max_working_minutes: int = 480       # paid time, excludes split-duty gap
    max_spreadover_minutes: int = 720    # sign-on to sign-off, inclusive
    min_relief_gap_minutes: int = 10     # handover time at a relief point
    allow_split_duties: bool = True
    relief_points: frozenset[str] = frozenset()   # empty -> depots + terminals
```

### Step 3.2 — Algorithm

Operating on `BlockingEngine.block_by_route()` / `block_interlined()` output:

1. **Wrap** each `Block` with sign-on before its first trip and sign-off after
   its last. A block's crew cost starts before the wheels turn.
2. **Cut into pieces.** A cut is legal at a trip boundary where the terminal is
   a relief point and the idle gap is ≥ `min_relief_gap_minutes`.
3. **Straight duties, minimally.** DP over legal cut positions per block,
   minimising piece count subject to `max_continuous_driving_minutes` and
   `max_working_minutes`. Insert a break rather than a cut where a break alone
   satisfies the constraint — a break is cheaper than a second crew.
4. **Pair leftovers into split duties** (if `allow_split_duties`): short
   morning-peak and evening-peak pieces from the same depot, combined subject
   to `max_spreadover_minutes`. Greedy longest-first pairing is adequate for v1.
5. **Report infeasible pieces** explicitly rather than silently forcing them —
   an unstaffable piece is real information for a rostering officer.

**Lower bound**, mirroring `concurrency_lower_bound` at line 566: maximum number
of pieces simultaneously in progress is a hard floor on crew count. Reporting it
lets the output say *"provably minimal"* or *"heuristic result, N above the
bound"*, exactly as `RouteBlocking.is_provably_minimal` does. Keeping that
symmetry is what makes this feel like the same system.

Outputs per depot: duties required, **crew-to-bus ratio** (the number depot
managers actually quote), % split duties, mean paid vs spread hours, infeasible
piece count, and the assumption block echoed verbatim.

### Step 3.3 — Service and API

`backend/app/services/crew_service.py`, caching and warming exactly like
`blocking_plan_service`. Blocking already costs ~25s; crew builds on its output,
so cache both and warm together in `lifespan`.

```
GET  /depot/crew-plan?depot=       admin | depot_manager
POST /depot/crew-scenario          admin | depot_manager   (mirrors /depot/blocking-scenario)
```

Phase 1 is **pure schedule math with no database** — it works when MongoDB is
down, same as `/depot/blocking-plan`. That property is worth protecting.

### Step 3.4 — Phase 2: rostering (deliberately separate)

Assigning duties to named people needs real crew records, so it is DB-backed and
strictly later:

```
crew:            crew_id, name, depot, role (driver|conductor), grade, weekly_off
crew_assignments: date, duty_id, crew_id, status (assigned|absent|standby|swapped)
```

```
GET  /depot/roster?date=          duties with assigned crew, unassigned highlighted
POST /depot/roster/absence        mark absent; suggests standby replacements
```

This is where "the 6 a.m. absenteeism problem" gets solved, but it is a
different kind of feature — it needs an operator relationship, not just data.

### Step 3.5 — Frontend

`frontend/src/components/CrewPanel.tsx`, mounted in `DepotDashboard.tsx`
alongside `BlockingPanel.tsx`. Extend `ScenarioConsole.tsx` with the crew
parameters so one console drives both models — a scenario that saves three buses
but needs five more crew should show both numbers on the same screen. That
juxtaposition is the whole argument.

### Step 3.6 — Tests

`backend/tests/test_crew.py`, following `test_blocking.py`'s style:

- **coverage invariant**: every trip in every block is covered by exactly one duty
- **constraint invariants**: no duty exceeds working, spreadover, or continuous
  driving limits; every long duty contains a conforming break
- **relief validity**: every cut sits at a relief point with a sufficient gap
- **lower bound**: duty count ≥ max concurrent pieces, always
- a hand-computed fixture (one block, three trips, known cut) matches exactly

---

## Feature 4 — Conductor waybill + Shakti counting

### Current state

`ConductorScanner.tsx` hardcodes `conductor_id: "CND-402"` and
`route_id: "500-D"`; `POST /conductor/verify-pass` (`api/routes.py:312`) decides
validity from string suffixes and returns a hardcoded passenger name. Tickets
exist only as commuter self-purchase. None of the conductor's actual job — the
waybill — is modelled.

This is the feature that touches money, which is exactly why it is the one that
gets an operator to adopt the system.

### Step 4.1 — Conductor identity and duty sign-on

`UserRole.CONDUCTOR` already exists (`auth/auth.py:85`). Add `UserRole.DRIVER`
at the same time — drivers are currently invisible in the entire system.

```
conductor_duties:  duty_id, conductor_id, driver_id, date, depot,
                   route_number, direction_id, bus_reg, block_ref,
                   sign_on_at, sign_off_at
```

```
POST /conductor/sign-on    {duty_id | (route_number, bus_reg), opening_km,
                            opening_ticket_serial}  -> opens a waybill
```

Frontend takes conductor identity from `AuthContext`, deleting the hardcoded
`CND-402`.

### Step 4.2 — The waybill

```
waybills:
  waybill_id, conductor_id, driver_id, bus_reg, depot, route_number, duty_date,
  status: OPEN | CLOSED | RECONCILED,
  sign_on_at, sign_off_at,
  opening_km, closing_km, opening_ticket_serial, closing_ticket_serial,
  trips: [{trip_no, direction_id, start_at, end_at}],
  totals: {tickets_issued, cash_amount, digital_amount,
           pass_boardings, shakti_boardings, shakti_claim_value},
  reconciliation: {declared_cash, expected_cash, variance, remitted_at, remitted_to}
```

`totals` is derived, never client-supplied — recomputed from ticket rows on
close. A client-supplied total in a revenue document is a fraud vector.

### Step 4.3 — Onboard ticket issuance, offline-first

```
POST /conductor/tickets/issue   single ticket, online path
POST /conductor/tickets/sync    batch, idempotent, offline path
```

Pricing goes through the existing `core/fares.py::calculate_stage_fare` — it is
already authoritative, data-driven from `dataset/fares.json`, and carries
per-stage confidence notes. Do not duplicate fare logic; a second pricing path
that drifts from the first is the classic way this kind of system starts lying.

**Offline is the default assumption, not a fallback.** Buses lose signal
constantly, and a conductor cannot stop selling tickets. Client (`ConductorDuty`
page) writes each issued ticket to IndexedDB with a client-generated UUID and a
monotonic local serial, then drains the queue to `/sync` whenever connectivity
returns. Server dedupes on `(waybill_id, client_ticket_uuid)` with a unique
index, so retries and duplicate batches cannot double-count revenue. The sync
response returns per-item accepted/duplicate/rejected status; the client only
clears items the server acknowledged.

The `offlineMode` toggle already in `ConductorScanner.tsx` stops being a demo
prop and becomes the real operating mode.

### Step 4.4 — Shakti scheme counting

Free travel for women is zero-fare to the passenger but **not** zero-value to
BMTC — the state reimburses it, and the claim is only as good as the count.
Neither incumbent models this at all.

Ticket row shape:

```python
{
  "scheme": "shakti",
  "is_zero_fare": True,
  "fare_value_inr": 27.0,     # what it WOULD have cost -- this is the claim
  "fare_collected_inr": 0.0,
}
```

The distinction between `fare_value_inr` and `fare_collected_inr` is the whole
feature. Revenue reports must use `fare_collected_inr`; reimbursement claims use
`fare_value_inr`; conflating them misstates both.

```
GET /admin/shakti/claim?from=&to=&depot=
    -> per depot per day: boardings, claim value, breakdown by route
```

**Privacy:** count boardings, never store passenger identity or any attribute
beyond the scheme flag needed for the claim. State this in the module docstring,
consistent with the minimal-collection principle already written into
`services/analytics_service.py`.

### Step 4.5 — Real pass verification

Replace the stub with genuine cryptography, reusing the pattern the codebase
already established. `auth/auth.py` deliberately separates ticket signing from
session JWTs so a ticket can never be a credential; add a third domain key for
passes on the same reasoning (`PASS_SIGNING_KEY`).

- Passes are issued as signed tokens carrying pass id, type, validity window,
  and holder reference.
- The conductor device verifies **offline**: signature check + expiry check +
  lookup against a locally cached revocation list (small — only revoked ids),
  synced opportunistically. That is real offline verification, not simulated
  latency.
- Keep an explicit `DEMO_PASS_MODE` flag so pitch demos still work without
  issued passes, clearly labelled in the response as a demo result.

Delete `is_valid = not (pass_id.endswith("FAIL") ...)` and the hardcoded
`"Rohan Kumar"`.

### Step 4.6 — Sign-off, reconciliation, depot view

```
POST /conductor/sign-off      {closing_km, closing_ticket_serial, declared_cash}
                              -> computes expected vs declared, flags variance
GET  /depot/waybills?date=    depot_manager: open/closed, variances, missing sign-offs
GET  /admin/revenue/reconciliation
                              cash vs digital vs pass vs Shakti, per depot per day
```

Variance is reported, never auto-resolved. Add an admin audit log
(`audit_events`) for every waybill and reconciliation write — who, what, when.
The system currently gates writes by role but records nothing, which is not
acceptable once money is involved.

### Step 4.7 — Frontend

- New `frontend/src/pages/ConductorDuty.tsx` — sign-on, trip control, issue
  ticket (stop pair + passenger types + payment mode), sign-off with cash
  declaration.
- New `frontend/src/lib/offlineQueue.ts` — IndexedDB queue with a visible
  pending-count indicator and last-sync time. The conductor must always be able
  to see how many tickets are unsynced.
- Rework `ConductorScanner.tsx` to use real identity and the real verifier.

### Step 4.8 — Tests

`backend/tests/test_waybill.py`
- replaying the same sync batch twice issues each ticket exactly once
- waybill totals are recomputed server-side and ignore client-supplied totals
- variance math on sign-off
- a ticket cannot be issued against a CLOSED waybill

`backend/tests/test_shakti.py`
- a Shakti ticket has `fare_collected_inr == 0` and `fare_value_inr > 0`
- claim aggregation sums `fare_value_inr`; revenue aggregation excludes it
- no passenger-identifying field is persisted on a Shakti ticket

---

## Sequencing

```
Feature 1a (GTFS static + alerts RT)   independent   -> ship first
Feature 3  (crew duty scheduling)      independent   -> parallel track
Feature 2  (AVL adapter)               independent
Feature 1b (vehicle positions / trip updates RT)     -> requires Feature 2
Feature 4  (waybill + Shakti)          independent   -> largest, most valuable
```

Recommended order: **1a → 3 → 2 → 1b → 4**, which front-loads the two things
that need no external cooperation and produce an external artifact quickly.

If a real BMTC conversation is live, invert it: lead with **4**, because
revenue and Shakti reimbursement are what an operator actually feels, and a
working waybill is a far stronger meeting than a data feed.

## Cross-cutting prerequisites

- Add `UserRole.DRIVER` (Feature 4 step 4.1) — needed by anything driver-facing later.
- `audit_events` collection and a write-audit dependency for role-gated writes.
- New MongoDB indexes in `init_db()`: `waybills(conductor_id, duty_date)`,
  `conductor_tickets(waybill_id, client_ticket_uuid)` unique,
  `conductor_duties(date, depot)`, `vehicle_observations` time-series + TTL.
- `RateLimitMiddleware` exemption path for `/avl/ingest` and
  `/conductor/tickets/sync`.
- `requirements.txt`: `gtfs-realtime-bindings`, `protobuf`.
- `frontend`: `idb-keyval` for the offline queue.

## Risks

| Risk | Mitigation |
|---|---|
| GTFS timings are modelled, not observed; a wrong feed is worse than none | Namespaced ids, `timepoint=0`, provenance in `feed_info.txt` + in-zip README, "unofficial/derived" publisher |
| Daily calendar overstates Sunday service | Flagged as the top correction to request from BMTC; builder accepts a real calendar file when supplied |
| Crew agreement parameters are guesses | Same treatment as `BlockingParameters` — configurable, echoed in output, never quoted as fact |
| Real AVL needs a data-sharing agreement | Adapters make the swap a config change, so the rest of the work proceeds without it |
| Feature 4 touches money and state reimbursement | Build as a pilot; state plainly that it is not an accounting system of record until BMTC signs off; audit log from day one |
| GTFS-RT could leak simulated positions | Hard 503 gate + separate `.sim.pb` path + env opt-in, tested |
