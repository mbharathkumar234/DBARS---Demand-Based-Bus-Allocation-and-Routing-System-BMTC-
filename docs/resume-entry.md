# DBARS — resume material

Every number here is measured from the repo, and the file notes where. Nothing
is rounded up. If a bullet is on your resume, you should be able to open the
code and show it.

---

## Full entry (projects section, 5–6 bullets)

**DBARS — Demand Based Bus Allocation & Routing System**
*Full-stack transit platform for BMTC (Bengaluru) · Python, FastAPI, React, TypeScript, MongoDB*

- Built a route-planning engine over BMTC's published timetable (6,737 route-directions, 3,940 bus numbers, 4,883 stops), indexing 655,438 ordered stop pairs across 3.9M route segments to answer direct and one-transfer journey queries in ~0.9s median, 1.5s p90.
- Designed a **vehicle-blocking and crew-scheduling engine** that derives operational figures no consumer app produces: minimum fleet (6,849 buses interlined across 44 depots), dead kilometres, and 15,636 daily crew duties cut from those blocks at legal relief points — a 2.28 crew-to-bus ratio matching real transport-undertaking practice.
- Published the dataset as a **GTFS feed** (3,713 routes, 47,295 trips, 1.46M `stop_times`, built in 11s and streamed straight to a 14MB zip), plus GTFS-Realtime service alerts — making the data consumable by Google Maps and any journey planner.
- Implemented an **offline-first conductor ticketing workflow** — waybill sign-on/sign-off, cash reconciliation, and idempotent sync of onboard sales — using client-generated UUIDs and a unique DB index so a replayed offline batch cannot double-count revenue.
- Modelled the Karnataka **Shakti free-travel scheme** end to end, separating fare *value* from fare *collected* so revenue reports and state reimbursement claims are derived from the same tickets without misstating either.
- Shipped a 4-role application (commuter / conductor / depot manager / admin) with 82 REST endpoints, JWT auth with separate signing domains for sessions, tickets and travel passes, 4-language UI, and an SMS fallback channel for feature phones; 161 backend tests in CI.

---

## Short entry (1-page resume, 3 bullets)

**DBARS — Demand Based Bus Allocation & Routing System** · Python, FastAPI, React, TypeScript, MongoDB

- Route-planning engine over BMTC's real timetable — 6,737 route-directions, 655K indexed stop pairs — answering direct and one-transfer queries in ~0.9s median.
- Fleet and crew scheduling from the published timetable alone: minimum fleet across 44 depots, dead kilometres, and 15,636 daily crew duties at a 2.28 crew-to-bus ratio.
- GTFS + GTFS-Realtime export (1.46M `stop_times`, 11s build) and an offline-first conductor ticketing flow with idempotent sync that cannot double-count revenue.

---

## Tech stack line

`Python · FastAPI · MongoDB (Motor) · React · TypeScript · Vite · Leaflet · Docker · GitHub Actions · GTFS / GTFS-Realtime (protobuf) · Capacitor (Android)`

---

## Numbers you can defend

| Claim | Where it comes from |
|---|---|
| 6,737 route-directions, 3,940 buses, 4,883 stops | `artifacts/metrics.json` → `dataset_profile` |
| 655,438 ordered stop pairs, 3,946,744 route segments | `metrics.json` → `stop_pair_index` |
| ~0.9s median / 1.5s p90 predict latency | measured over 12 real city-crossing queries |
| GTFS: 3,713 routes, 47,295 trips, 1,459,066 stop_times, 14.4MB, 11s | `GET /gtfs/feed-info` build report |
| 6,849 buses interlined, 44 depots | `GET /depot/blocking-plan` |
| 21,453 duty pieces → 15,636 duties, 2.28 crew/bus | `GET /depot/crew-plan` |
| 82 REST endpoints | route table on the running app |
| 161 backend tests, CI on every push | `pytest tests`, `.github/workflows/ci.yml` |
| ~13.5K lines backend Python, ~8.5K lines frontend TS/TSX | line count over `backend/app`, `frontend/src` |
| 4 languages (English, Kannada, Hindi, Telugu) | `frontend/src/i18n/` |

---

## Do NOT put these on your resume

**Model accuracy.** Top-1 is 20%, top-5 is 33%, cross-validated top-5 43%, on 120
synthetic test journeys (`metrics.json`). Writing "achieved 20% accuracy" is
worse than writing nothing, and writing "high accuracy" is a claim an
interviewer can check in one question. The evaluation set is synthetic and
small, which is the honest reason the number is low — the engine is a graph
search over real route membership, not a classifier, and there is no labelled
ground truth of "which bus did this commuter actually take".

If asked about accuracy, the good answer is the one your own code already
gives: you benchmarked four candidate rankers (TF-IDF cosine, ordered-stop
fuzzy, distance-aware, live transfer search), reported them side by side, and
the shipped model reports the accuracy of *exactly what the API returns* rather
than of a proxy that scores better. That is a stronger signal of engineering
judgment than any single number.

**"Real-time bus tracking."** Vehicle positions come from a simulator unless a
live feed is configured. Say **"pluggable AVL layer with four feed adapters
(GTFS-RT, JSON, push-ingest, simulator), gated so simulated positions are never
published as real"** — which is both true and more interesting.

**"Payment integration."** Ticket purchase writes a transaction record; there
is no payment gateway. Say "e-ticketing with signed QR tokens".

**"Deployed for BMTC" / "used by N commuters."** It is not deployed with BMTC
and has no real users.

---

## Interview talking points

Pick two. These are the stories with a real decision in them.

**1. The map bug that was actually a routing bug.**
Route maps drew random straight lines across the city. The cause was stop-name
resolution without an anchor — Bengaluru has several "Kodihalli", and one route
drew a 69.4 km line for a 19.2 km journey. Fixing that exposed a worse bug: the
planner was offering transfers matched purely on stop *name*, so it told
commuters to change at "Avalahalli" where the two Avalahallis are 28.6 km
apart — a journey nobody can make. Added a geometric interchange check. Shows:
debugging past the symptom, and the difference between a rendering fault and a
correctness fault.

**2. Idempotency for offline ticket sales.**
Buses lose signal and a conductor cannot stop selling tickets. Sales are queued
on-device with a client-generated UUID and replayed until acknowledged; a
unique index on `(waybill_id, client_ticket_uuid)` makes replays safe, and the
sync response is per-item so the device only clears what the server confirmed.
Clearing on partial success is how offline revenue silently disappears. Shows:
distributed-systems reasoning about a real constraint.

**3. Fare value vs fare collected.**
A Shakti ticket is free to the passenger and not free to the operator — the
state reimburses it. One `fare_amount` field cannot express both, so revenue
reporting and reimbursement claims would misstate one or the other. Two fields,
one shared eligibility rule used by both the app and the conductor path, so a
passenger can't be told her journey is free and then charged on the bus. Shows:
domain modelling, and noticing where a schema quietly loses information.

**4. Optimising the crew scheduler.**
Pairing 21,453 duty pieces into split duties was quadratic — a 12-hour
spreadover window covers most of the day — and took 36s. Bounded the candidate
search and added a path-compressed skip list for already-paired pieces: 1.6s,
and marginally *fewer* duties. Shows: profiling before optimising, and knowing
when an approximation is acceptable (over-estimating crew is the safe direction).

---

## Repo presentation

Before linking it, make sure the README leads with what the project *is* and a
screenshot or two. The `docs/implementation-plan.md` file is worth leaving in —
it shows planning before building, and it is annotated with where reality
diverged from the plan, which reads well.
